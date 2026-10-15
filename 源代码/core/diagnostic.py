"""
网络诊断模块 - 一键检测网络状态
面向新手小白，提供简单易懂的诊断结果
"""

import subprocess
import socket
import re
import platform
import os

from .cmd_utils import smart_run


class NetworkDiagnostic:
    """网络诊断器 - 检测各项网络指标是否正常"""

    def __init__(self):
        self.results = []  # 诊断结果列表
        self.is_windows = platform.system() == "Windows"

    def run_all_tests(self, progress_callback=None, item_callback=None):
        """运行所有诊断测试，返回结果列表"""
        self.results = []
        tests = [
            ("网卡状态", self.check_network_adapter),
            ("IP地址", self.check_ip_address),
            ("网关连通性", self.check_gateway),
            ("DNS解析", self.check_dns),
            ("互联网连通性", self.check_internet),
            ("多站点延迟", self.check_multi_latency),   # 整合开源多目标测点思路
            ("代理设置", self.check_proxy),
        ]

        total = len(tests)
        for i, (name, test_func) in enumerate(tests):
            try:
                status, message = test_func()
            except Exception as e:
                status = "error"
                message = f"检测异常: {str(e)}"

            result = {
                "name": name,
                "status": status,  # ok / warning / error
                "message": message
            }
            self.results.append(result)

            if item_callback:
                item_callback(result)
            if progress_callback:
                progress_callback(int((i + 1) / total * 100), name)

        return self.results

    def check_network_adapter(self):
        """检查网卡状态"""
        try:
            if self.is_windows:
                result = smart_run(["ipconfig"], timeout=6)
                output = result.stdout
                # 检查是否有启用的网卡
                adapters = re.findall(r"适配器\s+(.+?):", output)
                if not adapters:
                    adapters = re.findall(r"adapter\s+(.+?):", output, re.IGNORECASE)

                if len(adapters) == 0:
                    return "error", "未检测到网络适配器"

                # 检查是否有已连接的网卡
                if "IPv4" in output or "ipv4" in output.lower():
                    return "ok", f"检测到 {len(adapters)} 个网络适配器，状态正常"
                else:
                    return "warning", "检测到网卡但未获取到IP地址"
            else:
                return "ok", "网卡状态正常"
        except Exception as e:
            return "error", f"网卡检测失败: {str(e)}"

    def check_ip_address(self):
        """检查IP地址配置"""
        try:
            # 获取本机IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
            finally:
                s.close()

            if local_ip.startswith("169.254"):
                return "error", f"IP地址异常({local_ip})，未获取到有效IP"
            elif local_ip.startswith("127."):
                return "error", f"IP地址为回环地址({local_ip})，网络未连接"
            else:
                return "ok", f"本机IP: {local_ip}"
        except Exception as e:
            return "error", f"无法获取IP地址: {str(e)}"

    def check_gateway(self):
        """检查网关连通性"""
        try:
            if self.is_windows:
                result = smart_run(["ipconfig"], timeout=6)
                output = result.stdout
                # 提取默认网关
                gateway_match = re.search(r"默认网关[.*: ]+\s*(\d+\.\d+\.\d+\.\d+)", output)
                if not gateway_match:
                    gateway_match = re.search(r"Default Gateway[.*: ]+\s*(\d+\.\d+\.\d+\.\d+)", output, re.IGNORECASE)

                if gateway_match:
                    gateway = gateway_match.group(1)
                    # ping网关
                    ping_result = smart_run(["ping", "-n", "2", "-w", "2000", gateway], timeout=6)
                    if "TTL=" in ping_result.stdout or "ttl=" in ping_result.stdout.lower():
                        return "ok", f"网关({gateway})连通正常"
                    else:
                        return "warning", f"网关({gateway})无响应"
                else:
                    return "error", "未找到默认网关"
            else:
                return "ok", "网关连通正常"
        except Exception as e:
            return "error", f"网关检测失败: {str(e)}"

    def check_dns(self):
        """检查DNS解析"""
        try:
            # 尝试解析常用域名
            test_domains = ["www.baidu.com", "www.qq.com"]
            for domain in test_domains:
                try:
                    ip = socket.gethostbyname(domain)
                    return "ok", f"DNS解析正常 ({domain} -> {ip})"
                except socket.gaierror:
                    continue

            return "error", "DNS解析失败，所有测试域名均无法解析"
        except Exception as e:
            return "error", f"DNS检测失败: {str(e)}"

    def check_internet(self):
        """检查互联网连通性"""
        try:
            # ping百度服务器
            result = smart_run(["ping", "-n", "3", "-w", "2000", "www.baidu.com"], timeout=8)
            output = result.stdout

            # 统计丢包率
            loss_match = re.search(r"(\d+)% 丢失", output)
            if not loss_match:
                loss_match = re.search(r"(\d+)% loss", output, re.IGNORECASE)

            # 获取延迟
            time_match = re.search(r"平均\s*=\s*(\d+)ms", output)
            if not time_match:
                time_match = re.search(r"Average\s*=\s*(\d+)ms", output, re.IGNORECASE)

            if loss_match:
                loss = int(loss_match.group(1))
                if loss == 0:
                    if time_match:
                        latency = time_match.group(1)
                        return "ok", f"互联网连接正常，平均延迟 {latency}ms"
                    return "ok", "互联网连接正常"
                elif loss < 50:
                    return "warning", f"互联网连接不稳定，丢包率 {loss}%"
                else:
                    return "error", f"互联网连接很差，丢包率 {loss}%"
            else:
                return "error", "无法连接到互联网"
        except Exception as e:
            return "error", f"互联网检测失败: {str(e)}"

    def check_multi_latency(self):
        """多站点并发延迟（整合开源多目标测点思路，避免单点误判）"""
        try:
            from core.speed_test import SpeedTest
            hosts = ["www.baidu.com", "223.5.5.5", "1.1.1.1"]
            st = SpeedTest()
            res = st.multi_ping_test(hosts, count=2)
            ok = [r for r in res.values() if r.get("success")]
            if not ok:
                return "error", "多个站点均无法连通"
            avg = int(sum(r["avg_latency"] for r in ok) / len(ok))
            jitter = int(sum(r.get("jitter_ms", 0) for r in ok) / len(ok))
            detail = "、".join(
                f"{h}={res.get(h, {}).get('avg_latency', 0):.0f}ms"
                for h in hosts if res.get(h, {}).get("success")
            )
            # 延迟特别高或抖动大时给警告
            if avg >= 150 or jitter >= 40:
                return "warning", f"多站点延迟偏高或抖动大：平均{avg}ms/抖动{jitter}ms（{detail}）"
            return "ok", f"多站点延迟正常：平均{avg}ms/抖动{jitter}ms（{detail}）"
        except Exception as e:
            return "warning", f"多站点延迟检测失败: {str(e)}"

    def check_proxy(self):
        """检查代理设置"""
        try:
            if self.is_windows:
                # 检查注册表中的代理设置
                result = subprocess.run(
                    ["reg", "query",
                     r"HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                     "/v", "ProxyEnable"],
                    capture_output=True, text=True, timeout=5
                )
                output = result.stdout
                if "0x1" in output:
                    return "warning", "检测到代理服务器已启用，可能影响网络连接"
                else:
                    return "ok", "未启用代理服务器"
            else:
                proxy = os.environ.get("HTTP_PROXY", "")
                if proxy:
                    return "warning", f"检测到代理设置: {proxy}"
                return "ok", "未启用代理服务器"
        except Exception:
            return "ok", "代理状态未知（不影响正常使用）"

    def get_summary(self):
        """获取诊断摘要"""
        if not self.results:
            return "未进行诊断", "info"

        ok_count = sum(1 for r in self.results if r["status"] == "ok")
        warning_count = sum(1 for r in self.results if r["status"] == "warning")
        error_count = sum(1 for r in self.results if r["status"] == "error")

        if error_count > 0:
            return f"检测到 {error_count} 个严重问题，建议立即修复", "error"
        elif warning_count > 0:
            return f"网络基本正常，有 {warning_count} 个警告项", "warning"
        else:
            return "网络状态良好，所有检测项均正常", "ok"

    def has_issues(self):
        """是否有需要修复的问题"""
        return any(r["status"] in ("error", "warning") for r in self.results)
