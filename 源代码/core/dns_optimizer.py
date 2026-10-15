"""
DNS优化模块 - 测试并推荐最优DNS服务器
面向新手小白，帮助选择最快的DNS
"""

import socket
import time
import subprocess
import platform

from .cmd_utils import smart_run


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

    def __init__(self):
        self.is_windows = platform.system() == "Windows"

    def get_current_dns(self):
        """获取当前系统使用的DNS"""
        try:
            if self.is_windows:
                result = smart_run(["ipconfig", "/all"], timeout=6)
                output = result.stdout

                import re
                # 查找DNS服务器行
                dns_section = False
                dns_servers = []
                for line in output.split("\n"):
                    if "DNS 服务器" in line or "DNS Servers" in line:
                        dns_section = True
                        # 当前行可能也带IP
                        ip_match = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
                        if ip_match:
                            dns_servers.append(ip_match.group(1))
                        continue
                    if dns_section:
                        ip_match = re.match(r"\s+(\d+\.\d+\.\d+\.\d+)", line)
                        if ip_match:
                            dns_servers.append(ip_match.group(1))
                        else:
                            if line.strip() and not line[0].isspace():
                                break
                            elif line.strip() == "":
                                if dns_servers:
                                    break

                if dns_servers:
                    return dns_servers
                return ["未检测到"]
            else:
                # 读取/etc/resolv.conf
                try:
                    with open("/etc/resolv.conf", "r") as f:
                        content = f.read()
                    import re
                    dns_matches = re.findall(r"nameserver\s+(\d+\.\d+\.\d+\.\d+)", content)
                    return dns_matches if dns_matches else ["未检测到"]
                except:
                    return ["未检测到"]
        except Exception as e:
            return [f"检测失败: {str(e)}"]

    def _build_dns_query(self, domain):
        """构造DNS查询包（标准DNS over UDP协议）"""
        import struct
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

    def test_dns_speed(self, dns_ip, test_domain="www.baidu.com"):
        """测试单个DNS的解析速度（直接向指定DNS服务器发送查询）"""
        try:
            import struct

            latencies = []
            test_domains = ["www.baidu.com", "www.qq.com"]

            for domain in test_domains:
                sock = None
                try:
                    query_data, txn_id = self._build_dns_query(domain)
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.settimeout(2)
                    start = time.time()
                    sock.sendto(query_data, (dns_ip, 53))
                    data, _ = sock.recvfrom(1024)
                    elapsed = (time.time() - start) * 1000  # ms

                    if len(data) >= 12:
                        resp_id = struct.unpack(">H", data[:2])[0]
                        if resp_id == txn_id:
                            latencies.append(elapsed)
                except (socket.timeout, socket.gaierror, OSError):
                    pass
                finally:
                    if sock is not None:
                        try:
                            sock.close()
                        except OSError:
                            pass

            # 如果DNS查询失败，用ping延迟作为回退参考
            if not latencies:
                import re
                if self.is_windows:
                    result = smart_run(["ping", "-n", "2", "-w", "2000", dns_ip], timeout=6)
                else:
                    result = subprocess.run(
                        ["ping", "-c", "2", "-W", "2", dns_ip],
                        capture_output=True, text=True, timeout=5
                    )
                avg_match = re.search(r"平均\s*=\s*(\d+)ms", result.stdout)
                if not avg_match:
                    avg_match = re.search(r"rtt\s+min/avg/max.*?=\s*[\d.]+/([\d.]+)", result.stdout)
                if avg_match:
                    latencies.append(float(avg_match.group(1)))

            if latencies:
                avg_latency = sum(latencies) / len(latencies)
                return {"ip": dns_ip, "latency": round(avg_latency, 1), "success": True}
            else:
                return {"ip": dns_ip, "latency": 999, "success": False}

        except Exception as e:
            return {"ip": dns_ip, "latency": 999, "success": False, "error": str(e)}

    def test_all_dns(self, progress_callback=None):
        """测试所有常用DNS的速度"""
        results = []
        total = len(self.POPULAR_DNS)

        for i, dns in enumerate(self.POPULAR_DNS):
            result = self.test_dns_speed(dns["ip"])
            result["name"] = dns["name"]
            result["region"] = dns["region"]
            results.append(result)

            if progress_callback:
                progress_callback(int((i + 1) / total * 100), dns["name"])

        # 按延迟排序
        results.sort(key=lambda x: x["latency"] if x["success"] else 9999)

        return results

    def get_best_dns(self, results):
        """获取最优DNS推荐"""
        # 优先推荐国内的
        domestic = [r for r in results if r.get("region") == "国内" and r["success"]]
        if domestic:
            best = domestic[0]
            return best, self._get_dns_advice(best["latency"])

        # 没有国内的就推荐最快的
        successful = [r for r in results if r["success"]]
        if successful:
            best = successful[0]
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

    def set_dns(self, primary_dns, secondary_dns=""):
        """设置系统DNS（需要管理员权限）"""
        try:
            if self.is_windows:
                # 获取活动的网络接口名称
                result = smart_run(["netsh", "interface", "show", "interface"], timeout=6)
                output = result.stdout

                import re
                interfaces = []
                for line in output.split("\n"):
                    line_stripped = line.strip()
                    if not line_stripped:
                        continue
                    # 匹配: 已连接 专用  ...  接口名（可能含空格）
                    # 或英文: Connected Dedicated ... Interface Name
                    if "已连接" in line or "Connected" in line:
                        if "Loopback" in line or "回送" in line or "Loopback Pseudo-Interface" in line:
                            continue
                        # netsh输出格式: Admin State State Type Interface Name
                        # 接口名从第4列开始，可能包含空格
                        # 用正则去掉前3个状态词，取剩余部分作为接口名
                        match = re.match(
                            r"\s*\S+\s+(已连接|Connected|已禁用|Disabled)\s+\S+\s+(.+)",
                            line, re.IGNORECASE
                        )
                        if match:
                            state = match.group(1)
                            if state in ("已连接", "Connected", "connected"):
                                if_name = match.group(2).strip()
                                if if_name and if_name not in ("Loopback", "回送", "Loopback Pseudo-Interface"):
                                    interfaces.append(if_name)

                if not interfaces:
                    return False, "未找到活动的网络接口"

                # 对每个活动接口设置DNS
                success_count = 0
                for if_name in interfaces:
                    # 设置主DNS
                    set_result = smart_run(
                        ["netsh", "interface", "ip", "set", "dns",
                         if_name, "static", primary_dns, "primary"], timeout=6
                    )
                    if set_result.returncode == 0:
                        success_count += 1
                    # 设置备用DNS
                    if secondary_dns:
                        smart_run(
                            ["netsh", "interface", "ip", "add", "dns",
                             if_name, secondary_dns, "index=2"], timeout=6
                        )

                if success_count > 0:
                    return True, f"DNS设置成功（已应用到 {success_count} 个网络接口）"
                else:
                    combined = ""
                    for if_name in interfaces[:1]:
                        r = smart_run(
                            ["netsh", "interface", "ip", "set", "dns",
                             if_name, "static", primary_dns, "primary"], timeout=6
                        )
                        combined = (r.stdout + r.stderr).lower()
                    if "提升" in combined or "denied" in combined:
                        return False, "需要管理员权限才能设置DNS"
                    return False, "DNS设置失败"
            else:
                return False, "非Windows系统暂不支持自动设置DNS"
        except Exception as e:
            return False, f"DNS设置失败: {str(e)}"
