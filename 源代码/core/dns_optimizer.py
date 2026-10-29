"""
DNS优化模块 - 测试并推荐最优DNS服务器
面向新手小白，帮助选择最快的DNS

性能说明：10 个公共 DNS 串行测试时，弱网下最坏耗时约 10×2×2s=40s；
改为线程池并发后总耗时约等于单个 DNS 的测试时间（约 4s），提速近 10 倍。
"""

import re
import socket
import struct
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .cmd_utils import IS_WINDOWS, smart_run


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

    DNS_PORT = 53
    QUERY_TIMEOUT = 2.0        # 单个 DNS 查询超时
    MAX_WORKERS = 8            # 并发测试的 DNS 数量

    def __init__(self):
        self.is_windows = IS_WINDOWS
        self._cancel = threading.Event()

    def cancel(self):
        """请求停止正在进行的测试（已发出的查询会自行超时退出）。"""
        self._cancel.set()

    # ---------------- 当前系统 DNS ----------------
    def get_current_dns(self):
        """获取当前系统使用的DNS"""
        try:
            if self.is_windows:
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

        # 去重保序，过滤回环地址
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

    def _query_once(self, dns_ip, domain):
        """向指定 DNS 发送一次 A 查询，成功返回耗时(ms)，失败返回 None。"""
        sock = None
        try:
            query_data, txn_id = self._build_dns_query(domain)
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(self.QUERY_TIMEOUT)
            start = time.perf_counter()
            sock.sendto(query_data, (dns_ip, self.DNS_PORT))
            data, _ = sock.recvfrom(1024)
            elapsed = (time.perf_counter() - start) * 1000
            if len(data) < 12:
                return None
            resp_id = struct.unpack(">H", data[:2])[0]
            if resp_id != txn_id:
                return None
            # RCODE=0 才是有效应答（避免把 SERVFAIL/REFUSED 当作成功）
            rcode = data[3] & 0x0F
            return elapsed if rcode == 0 else None
        except (socket.timeout, socket.gaierror, OSError, struct.error):
            return None
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    def _ping_latency(self, dns_ip):
        """DNS 查询失败时的回退参考：用 ping 平均延迟估算可达性。"""
        if self.is_windows:
            result = smart_run(["ping", "-n", "2", "-w", "2000", dns_ip], timeout=6)
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
        """测试单个DNS的解析速度（直接向指定DNS服务器发送查询）。

        参数 test_domain 保留用于自定义首个测试域名；默认再补测 www.qq.com，
        取多次成功查询的平均值，降低单次抖动的影响。
        """
        if self._cancel.is_set():
            return {"ip": dns_ip, "latency": 999, "success": False, "cancelled": True}
        try:
            latencies = []
            test_domains = [test_domain, "www.qq.com"]
            for domain in test_domains:
                if self._cancel.is_set():
                    break
                elapsed = self._query_once(dns_ip, domain)
                if elapsed is not None:
                    latencies.append(elapsed)

            if not latencies and not self._cancel.is_set():
                fallback = self._ping_latency(dns_ip)
                if fallback is not None:
                    latencies.append(fallback)

            if latencies:
                avg_latency = sum(latencies) / len(latencies)
                return {"ip": dns_ip, "latency": round(avg_latency, 1), "success": True}
            return {"ip": dns_ip, "latency": 999, "success": False}
        except Exception as e:
            return {"ip": dns_ip, "latency": 999, "success": False, "error": str(e)}

    def test_all_dns(self, progress_callback=None):
        """并发测试所有常用DNS的速度，按延迟从快到慢排序。"""
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
                results.append(result)

                completed += 1
                if progress_callback:
                    progress_callback(int(completed / total * 100), dns["name"])

                if self._cancel.is_set():
                    for pending in future_map:
                        pending.cancel()
                    break

        # 按延迟排序（失败的排最后）
        results.sort(key=lambda x: x["latency"] if x.get("success") else 9999)
        return results

    def get_best_dns(self, results):
        """获取最优DNS推荐"""
        # 优先推荐国内的（不依赖调用方是否已排序，直接取延迟最小者）
        successful = [r for r in results if r.get("success")]
        domestic = [r for r in successful if r.get("region") == "国内"]
        pool = domestic or successful
        if pool:
            best = min(pool, key=lambda r: r.get("latency", 9999))
            return best, self._get_dns_advice(best["latency"])

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

    def _active_interfaces(self):
        """解析 `netsh interface show interface`，返回已连接且非回环的接口名。"""
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
        return interfaces

    def set_dns(self, primary_dns, secondary_dns=""):
        """设置系统DNS（需要管理员权限）"""
        try:
            if not self.is_windows:
                return False, "非Windows系统暂不支持自动设置DNS"

            interfaces = self._active_interfaces()
            if not interfaces:
                return False, "未找到活动的网络接口"

            # 对每个活动接口设置DNS
            success_count = 0
            last_output = ""
            for if_name in interfaces:
                # 设置主DNS
                set_result = smart_run(
                    ["netsh", "interface", "ip", "set", "dns",
                     if_name, "static", primary_dns, "primary"], timeout=6)
                last_output = (set_result.stdout or "").lower()
                if set_result.returncode == 0:
                    success_count += 1
                # 设置备用DNS
                if secondary_dns:
                    smart_run(
                        ["netsh", "interface", "ip", "add", "dns",
                         if_name, secondary_dns, "index=2"], timeout=6)

            if success_count > 0:
                return True, f"DNS设置成功（已应用到 {success_count} 个网络接口）"
            if "提升" in last_output or "denied" in last_output or "拒绝" in last_output:
                return False, "需要管理员权限才能设置DNS"
            return False, "DNS设置失败"
        except Exception as e:
            return False, f"DNS设置失败: {str(e)}"
