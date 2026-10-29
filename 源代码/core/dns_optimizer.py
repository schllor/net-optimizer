"""
DNS优化模块 - 测试并推荐最优DNS服务器
面向新手小白，帮助选择最快的DNS

方法学（v1.8）：
  - 每个 DNS 做多轮「热域名 + 随机冷域名」查询，冷域名走缓存穿透路径，
    更能反映日常首次访问网页的真实延迟；
  - 统计 P50/P95 与超时率，排名按 P95（比平均值更抗个别抖动）；
  - 查询可用但解析失败（SERVFAIL/REFUSED/超时）的服务器不推荐，
    ping 只用来标记「可连通但无法解析」，不参与排名；
  - 对前 3 名验证 RFC 8484 DoH（只做标记，不参与排名）。
"""

import json
import os
import re
import secrets
import socket
import struct
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from .admin import require_admin
from .cmd_utils import IS_WINDOWS, run_cmd_ex, smart_run
from .net_quality import summarize
from .paths import get_cache_dir


class DNSOptimizer:
    """DNS优化器 - 测试多个DNS，推荐最优"""

    # 常用公共DNS服务器列表
    POPULAR_DNS = [
        {"name": "阿里DNS", "ip": "223.5.5.5", "region": "国内"},
        {"name": "阿里DNS备", "ip": "223.6.6.6", "region": "国内"},
        {"name": "腾讯DNS", "ip": "119.29.29.29", "region": "国内"},
        {"name": "百度DNS", "ip": "180.76.76.76", "region": "国内"},
        {"name": "114DNS", "ip": "114.114.114.114", "region": "国内"},
        {"name": "114DNS备", "ip": "114.114.115.115", "region": "国内"},
        {"name": "CNNIC DNS", "ip": "1.2.4.8", "region": "国内"},
        {"name": "谷歌DNS", "ip": "8.8.8.8", "region": "国外"},
        {"name": "谷歌DNS备", "ip": "8.8.4.4", "region": "国外"},
        {"name": "Cloudflare", "ip": "1.1.1.1", "region": "国外"},
    ]

    # 已知的 DoH 端点（只用于标记，不参与排名；未列出的服务器不验证）
    DOH_ENDPOINTS = {
        "223.5.5.5": "https://dns.alidns.com/dns-query",
        "223.6.6.6": "https://dns.alidns.com/dns-query",
        "119.29.29.29": "https://doh.pub/dns-query",
        "1.1.1.1": "https://cloudflare-dns.com/dns-query",
        "1.0.0.1": "https://cloudflare-dns.com/dns-query",
        "8.8.8.8": "https://dns.google/dns-query",
        "8.8.4.4": "https://dns.google/dns-query",
    }

    DNS_PORT = 53
    QUERY_TIMEOUT = 2.0        # 单个 DNS 查询超时
    MAX_WORKERS = 8            # 并发测试的 DNS 数量
    ROUNDS = 3                 # 每个 DNS 的采样轮数（每轮热+冷各一次）
    HOT_DOMAINS = ("www.baidu.com", "www.qq.com")

    def __init__(self):
        self.is_windows = IS_WINDOWS
        self._cancel = threading.Event()

    def cancel(self):
        """请求停止正在进行的测试（已发出的查询会自行超时退出）。"""
        self._cancel.set()

    # ---------------- 当前系统 DNS ----------------
    def get_current_dns(self):
        """获取当前系统使用的DNS（原生 API 优先，ipconfig 兜底）。"""
        try:
            if self.is_windows:
                try:
                    from .winapi_net import get_dns_servers
                    servers = get_dns_servers()
                    if servers:
                        return servers
                except Exception:
                    pass
                return self._get_current_dns_windows()
            return self._get_current_dns_unix()
        except Exception as e:
            return [f"检测失败: {str(e)}"]

    def _get_current_dns_windows(self):
        output = smart_run(["ipconfig", "/all"], timeout=6).stdout or ""
        dns_servers = []
        in_dns_section = False

        for line in output.splitlines():
            if "DNS 服务器" in line or "DNS Servers" in line:
                in_dns_section = True
                tail = line.replace("：", ":").split(":", 1)[-1]
                dns_servers.extend(re.findall(r"\d+\.\d+\.\d+\.\d+", tail))
                continue
            if not in_dns_section:
                continue
            stripped = line.strip()
            if not stripped:
                in_dns_section = False
                continue
            # DNS 续行是缩进的纯 IP；遇到其它字段（如 NetBIOS）则结束本段
            match = re.fullmatch(r"(\d+\.\d+\.\d+\.\d+)", stripped)
            if match:
                dns_servers.append(match.group(1))
            else:
                in_dns_section = False

        unique = []
        for ip in dns_servers:
            if ip in unique or ip.startswith("127."):
                continue
            unique.append(ip)
        return unique or ["未检测到"]

    def _get_current_dns_unix(self):
        try:
            with open("/etc/resolv.conf", "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            dns_matches = re.findall(r"nameserver\s+(\d+\.\d+\.\d+\.\d+)", content)
            return dns_matches or ["未检测到"]
        except OSError:
            return ["未检测到"]

    # ---------------- DNS 查询测速 ----------------
    def _build_dns_query(self, domain):
        """构造DNS查询包（标准DNS over UDP协议）"""
        import random

        transaction_id = random.randint(0, 0xFFFF)
        flags = 0x0100  # 标准递归查询
        qdcount = 1

        header = struct.pack(">HHHHHH", transaction_id, flags, qdcount, 0, 0, 0)

        question = b""
        for part in domain.split("."):
            question += struct.pack("B", len(part)) + part.encode("ascii")
        question += b"\x00"
        question += struct.pack(">HH", 1, 1)  # QTYPE=A, QCLASS=IN

        return header + question, transaction_id

    def _query_once(self, dns_ip, domain, timeout=None):
        """向指定 DNS 发送一次 A 查询，成功返回耗时(ms)，失败返回 None。

        NOERROR(0) 与 NXDOMAIN(3) 都算解析服务正常；SERVFAIL/REFUSED 视为失败。
        """
        sock = None
        try:
            query_data, txn_id = self._build_dns_query(domain)
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout or self.QUERY_TIMEOUT)
            start = time.perf_counter()
            sock.sendto(query_data, (dns_ip, self.DNS_PORT))
            data, _ = sock.recvfrom(1024)
            elapsed = (time.perf_counter() - start) * 1000
            if len(data) < 12:
                return None
            resp_id = struct.unpack(">H", data[:2])[0]
            if resp_id != txn_id:
                return None
            rcode = data[3] & 0x0F
            return elapsed if rcode in (0, 3) else None
        except (socket.timeout, socket.gaierror, OSError, struct.error):
            return None
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    def query_stats(self, server, rounds=None, hot_domain=None, cancel=None):
        """多轮热/冷域名采样，返回 P50/P95、抖动、超时率与冷热延迟。"""
        cancel = cancel or self._cancel
        rounds = max(1, int(rounds or self.ROUNDS))
        hot_domain = hot_domain or self.HOT_DOMAINS[0]
        hot, cold = [], []
        sent = 0
        for _ in range(rounds):
            if cancel.is_set():
                break
            for domain, bucket in (
                    (hot_domain, hot),
                    (f"{secrets.token_hex(3)}.baidu.com", cold)):
                if cancel.is_set():
                    break
                sent += 1
                elapsed = self._query_once(server, domain)
                if elapsed is not None:
                    bucket.append(elapsed)
        samples = hot + cold
        stats = summarize(samples, sent=sent)
        timeouts = max(0, sent - len(samples))
        return {
            "ip": server,
            "latency": stats.p50,
            "p50": stats.p50,
            "p95": stats.p95,
            "jitter_ms": stats.jitter,
            "hot_ms": round(sum(hot) / len(hot), 1) if hot else None,
            "cold_ms": round(sum(cold) / len(cold), 1) if cold else None,
            "timeout_rate": round(timeouts / sent * 100, 1) if sent else 100.0,
            "samples": len(samples),
            "rounds": rounds,
            "success": bool(samples),
        }

    def _ping_latency(self, dns_ip):
        """仅用于标记「可连通但无法解析」的服务器，不参与排名。"""
        if self.is_windows:
            result = smart_run(["ping", "-n", "2", "-w", "1500", dns_ip], timeout=6)
            output = result.stdout or ""
            match = re.search(r"平均\s*[=＝]\s*([\d.]+)\s*ms", output)
            if not match:
                match = re.search(r"Average\s*[=＝]\s*([\d.]+)\s*ms", output, re.IGNORECASE)
        else:
            try:
                result = subprocess.run(
                    ["ping", "-c", "2", "-W", "2", dns_ip],
                    capture_output=True, text=True, timeout=5)
            except (OSError, subprocess.SubprocessError):
                return None
            output = result.stdout or ""
            match = re.search(r"rtt\s+min/avg/max.*?=\s*[\d.]+/([\d.]+)", output)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
        return None

    def test_dns_speed(self, dns_ip, test_domain="www.baidu.com"):
        """测试单个DNS的解析速度（保留旧方法名，内部走多轮冷热采样）。"""
        if self._cancel.is_set():
            return {"ip": dns_ip, "latency": 999, "success": False, "cancelled": True}
        try:
            result = self.query_stats(dns_ip, hot_domain=test_domain)
            if result["success"]:
                result["reachable"] = True
            else:
                result["reachable"] = self._ping_latency(dns_ip) is not None
            return result
        except Exception as e:
            return {"ip": dns_ip, "latency": 999, "success": False, "error": str(e)}

    def test_all_dns(self, progress_callback=None):
        """并发测试所有常用DNS，按 P95 从快到慢排序。"""
        self._cancel.clear()
        results = []
        total = len(self.POPULAR_DNS)
        completed = 0

        with ThreadPoolExecutor(
                max_workers=min(self.MAX_WORKERS, total),
                thread_name_prefix="dns-test") as executor:
            future_map = {
                executor.submit(self.test_dns_speed, dns["ip"]): dns
                for dns in self.POPULAR_DNS
            }
            for future in as_completed(future_map):
                dns = future_map[future]
                try:
                    result = future.result()
                except Exception as e:
                    result = {"ip": dns["ip"], "latency": 999,
                              "success": False, "error": str(e)}
                result["name"] = dns["name"]
                result["region"] = dns["region"]
                for key in ("p50", "p95", "jitter_ms"):
                    if key not in result:
                        result[key] = result.get("latency", 999)
                result.setdefault("timeout_rate", 0.0 if result.get("success") else 100.0)
                result.setdefault("reachable", bool(result.get("success")))
                results.append(result)

                completed += 1
                if progress_callback:
                    progress_callback(int(completed / total * 100), dns["name"])

                if self._cancel.is_set():
                    for pending in future_map:
                        pending.cancel()
                    break

        results.sort(key=lambda x: (
            0 if x.get("success") else 1, x.get("p95", x.get("latency", 9999))))
        if not self._cancel.is_set():
            # 只有真实采样结果才做 DoH 校验（离线测试注入的简化结果不含 samples）
            self._mark_doh([r for r in results[:3] if "samples" in r])
        return results

    # ---------------- DoH 校验（RFC 8484，仅标记） ----------------
    def verify_doh(self, url, domain="www.baidu.com", timeout=2.5):
        """按 RFC 8484 用 POST + wire-format 查询 DoH 端点。"""
        import http.client
        import urllib.parse

        parsed = urllib.parse.urlparse(url)
        conn = None
        try:
            query, txn_id = self._build_dns_query(domain)
            conn = http.client.HTTPSConnection(parsed.netloc, timeout=timeout)
            start = time.perf_counter()
            conn.request("POST", parsed.path or "/dns-query", body=query, headers={
                "Content-Type": "application/dns-message",
                "Accept": "application/dns-message",
                "User-Agent": "Mozilla/5.0 NetHelper/1.0",
            })
            resp = conn.getresponse()
            data = resp.read(4096)
            elapsed = round((time.perf_counter() - start) * 1000, 1)
            ok = (resp.status == 200 and len(data) >= 12
                  and struct.unpack(">H", data[:2])[0] == txn_id
                  and (data[3] & 0x0F) in (0, 3))
            return {"ok": ok, "latency": elapsed, "url": url}
        except (OSError, http.client.HTTPException, struct.error, ValueError) as e:
            return {"ok": False, "latency": None, "url": url, "error": str(e)}
        finally:
            if conn is not None:
                try:
                    conn.close()
                except OSError:
                    pass

    def _mark_doh(self, top_results):
        """对前 3 名中已知 DoH 端点的服务器做并发验证，结果写回 doh_ok。"""
        targets = [(r, self.DOH_ENDPOINTS.get(r.get("ip")))
                   for r in top_results if r.get("success")]
        targets = [(r, url) for r, url in targets if url]
        if not targets:
            return

        def one(item):
            result, url = item
            return result, self.verify_doh(url)

        with ThreadPoolExecutor(max_workers=len(targets)) as ex:
            for result, check in ex.map(one, targets):
                result["doh_ok"] = check.get("ok")

    def get_best_dns(self, results):
        """获取最优DNS推荐（国内优先，按 P95 比较）。"""
        successful = [r for r in results if r.get("success")]
        domestic = [r for r in successful if r.get("region") == "国内"]
        pool = domestic or successful
        if pool:
            best = min(pool, key=lambda r: r.get("p95", r.get("latency", 9999)))
            latency = best.get("p95", best.get("latency", 0))
            return best, self._get_dns_advice(latency)
        if any(r.get("reachable") for r in results):
            return None, "这些DNS可以连通但无法正常解析，建议检查网络或稍后重试"
        return None, "所有DNS服务器都无法连接，请检查网络"

    def _get_dns_advice(self, latency_ms):
        """根据DNS延迟给出建议"""
        if latency_ms <= 10:
            return "极速响应，解析网页会非常快"
        elif latency_ms <= 30:
            return "响应很快，网页打开速度良好"
        elif latency_ms <= 50:
            return "响应一般，可能会感觉到网页打开稍慢"
        elif latency_ms <= 100:
            return "响应较慢，建议更换更快的DNS"
        else:
            return "响应很慢，会明显影响网页打开速度"

    # ---------------- 设置 / 备份 / 回滚 ----------------
    def _active_interfaces(self):
        """返回已连接且非回环的接口名（netsh 解析失败时用原生名称兜底）。"""
        output = smart_run(["netsh", "interface", "show", "interface"], timeout=6).stdout or ""
        interfaces = []
        for line in output.splitlines():
            if "已连接" not in line and "Connected" not in line:
                continue
            if "Loopback" in line or "回送" in line:
                continue
            match = re.match(
                r"\s*\S+\s+(已连接|Connected|已禁用|Disabled)\s+\S+\s+(.+)",
                line, re.IGNORECASE)
            if not match:
                continue
            state = match.group(1)
            if state.lower() not in ("已连接", "connected"):
                continue
            if_name = match.group(2).strip()
            if if_name and if_name not in ("Loopback", "回送", "Loopback Pseudo-Interface"):
                interfaces.append(if_name)
        if not interfaces:
            try:
                from .winapi_net import get_dns_by_adapter
                interfaces = [row["name"] for row in (get_dns_by_adapter() or [])
                              if row.get("name")]
            except Exception:
                pass
        return interfaces

    @staticmethod
    def backup_path():
        return os.path.join(get_cache_dir(), "dns_backup.json")

    def _backup_current(self, interfaces):
        """把当前各接口 DNS 写入缓存文件（失败也不阻断设置流程）。"""
        try:
            from .winapi_net import get_dns_by_adapter
            adapters = get_dns_by_adapter() or []
        except Exception:
            adapters = []
        payload = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "interfaces": interfaces,
            "adapters": adapters,
            "dns": self.get_current_dns(),
        }
        path = self.backup_path()
        tmp = f"{path}.{os.getpid()}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except OSError:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
        return payload

    @staticmethod
    def build_dns_commands(alias, primary, secondary=""):
        """生成现代 netsh 命令（ipv4 子上下文 + name= 参数，兼容中文接口名）。"""
        quoted = f'name="{alias}"'
        commands = [[
            "netsh", "interface", "ipv4", "set", "dnsservers",
            quoted, "static", primary, "primary",
        ]]
        if secondary:
            commands.append([
                "netsh", "interface", "ipv4", "add", "dnsservers",
                quoted, secondary, "index=2",
            ])
        return commands

    @staticmethod
    def _powershell_set(alias, servers):
        safe = alias.replace("'", "''")
        joined = ",".join(f"'{s}'" for s in servers)
        return (f"Set-DnsClientServerAddress -InterfaceAlias '{safe}' "
                f"-ServerAddresses @({joined})")

    def _apply_dns(self, alias, servers):
        """把一个接口设为指定 DNS 列表；失败时尝试 PowerShell 兜底。"""
        servers = [s for s in servers if s]
        if not servers:
            return self._apply_dhcp(alias)
        commands = self.build_dns_commands(
            alias, servers[0], servers[1] if len(servers) > 1 else "")
        for cmd in commands:
            if not run_cmd_ex(cmd, timeout=8).ok:
                break
        else:
            return True
        res = run_cmd_ex(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             self._powershell_set(alias, servers)], timeout=12)
        return res.ok

    def _apply_dhcp(self, alias):
        res = run_cmd_ex([
            "netsh", "interface", "ipv4", "set", "dnsservers",
            f'name="{alias}"', "source=dhcp",
        ], timeout=8)
        if res.ok:
            return True
        safe = alias.replace("'", "''")
        res = run_cmd_ex(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f"Set-DnsClientServerAddress -InterfaceAlias '{safe}' -ResetServerAddresses"],
            timeout=12)
        return res.ok

    def set_dns(self, primary_dns, secondary_dns=""):
        """设置系统DNS（需要管理员权限；失败自动回滚到备份）。"""
        if not self.is_windows:
            return False, "非Windows系统暂不支持自动设置DNS"

        allowed, message = require_admin("修改 DNS ")
        if not allowed:
            return False, message

        interfaces = self._active_interfaces()
        if not interfaces:
            return False, "未找到活动的网络接口"

        backup = self._backup_current(interfaces)
        applied, failed = [], []
        for alias in interfaces:
            servers = [primary_dns] + ([secondary_dns] if secondary_dns else [])
            if self._apply_dns(alias, servers):
                applied.append(alias)
            else:
                failed.append(alias)

        if applied:
            if failed:
                return True, (f"DNS已应用到 {len(applied)} 个接口，"
                              f"{len(failed)} 个失败（可能被安全软件拦截）")
            return True, f"DNS设置成功（已应用到 {len(applied)} 个网络接口）"

        self._rollback(backup, interfaces)
        return False, "DNS设置失败（可能未以管理员身份运行，或 DNS 配置被策略锁定）"

    def _rollback(self, backup, interfaces):
        """把接口恢复到修改前的 DNS；没有备份时退回自动获取。"""
        rows = (backup or {}).get("adapters") or []
        restored = False
        for row in rows:
            name = row.get("name")
            if name:
                restored = self._apply_dns(name, row.get("dns") or []) or restored
        if restored:
            return
        for alias in interfaces:
            self._apply_dhcp(alias)

    def restore_dhcp(self, interfaces=None):
        """恢复为自动获取 DNS（DHCP）。"""
        if not self.is_windows:
            return False, "非Windows系统暂不支持自动设置DNS"
        allowed, message = require_admin("恢复 DNS ")
        if not allowed:
            return False, message
        interfaces = interfaces or self._active_interfaces()
        if not interfaces:
            return False, "未找到活动的网络接口"
        restored = [alias for alias in interfaces if self._apply_dhcp(alias)]
        if restored:
            return True, f"已恢复为自动获取DNS（{len(restored)} 个接口）"
        return False, "恢复失败，请检查管理员权限或手动在系统设置中修改"
