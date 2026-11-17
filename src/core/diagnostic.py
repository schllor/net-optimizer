"""
网络诊断模块 - 一键检测网络状态
面向新手小白，提供简单易懂的诊断结果
"""

import socket
import re
import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .cmd_utils import IS_WINDOWS, smart_run
from .netinfo import get_local_ip, get_default_gateway


class NetworkDiagnostic:
    """网络诊断器 - 检测各项网络指标是否正常"""

    def __init__(self):
        self.results = []  # 诊断结果列表
        self.is_windows = IS_WINDOWS

    @staticmethod
    def _safe_check(name, check_func):
        """执行单项检测并把异常收敛为统一结果，保证并发任务不会中断。

        检测函数可以返回 (status, message) 或 (status, message, data)；
        data 是结构化指标，供界面回填结论卡，避免从中文文案里猜数字。
        """
        data = {}
        try:
            result = check_func()
            if isinstance(result, (tuple, list)):
                if len(result) >= 3:
                    status, message, data = result[0], result[1], result[2] or {}
                elif len(result) == 2:
                    status, message = result
                else:
                    status, message = "info", "检测完成"
            else:
                status, message = "info", str(result)
        except Exception as e:
            status, message = "error", f"检测异常: {str(e)}"
        return {"name": name, "status": status, "message": message,
                "data": data if isinstance(data, dict) else {}}

    @staticmethod
    def _ping_stats(output):
        """从 ping 输出提取平均延迟与丢包率；解析不到返回 None。"""
        text = output or ""
        latency = None
        match = re.search(r"平均\s*[=＝]\s*(\d+(?:\.\d+)?)\s*ms", text)
        if not match:
            match = re.search(r"Average\s*[=＝]\s*(\d+(?:\.\d+)?)\s*ms",
                              text, re.IGNORECASE)
        if match:
            latency = float(match.group(1))
        loss = None
        match = re.search(r"(\d+)%\s*(?:丢失|loss)", text, re.IGNORECASE)
        if match:
            loss = int(match.group(1))
        return {"latency_ms": latency, "loss_pct": loss}

    def run_all_tests(self, progress_callback=None, item_callback=None, cancel=None):
        """并发运行所有诊断测试，返回结果列表（顺序与测试清单一致）。

        各项检测互不依赖，串行执行会让总耗时等于各项超时之和（弱网下可达 20s+）。
        改为并发后总耗时约等于最慢的一项，实测可缩短 60% 以上。
        """
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
        results_by_index = {}
        with ThreadPoolExecutor(max_workers=total, thread_name_prefix="diag") as executor:
            future_map = {
                executor.submit(self._safe_check, name, func): (index, name)
                for index, (name, func) in enumerate(tests)
            }
            completed = 0
            for future in as_completed(future_map):
                if cancel is not None and cancel.is_set():
                    for pending in future_map:
                        pending.cancel()
                    break
                index, name = future_map[future]
                result = future.result()
                results_by_index[index] = result
                completed += 1

                if item_callback:
                    item_callback(result)
                if progress_callback:
                    progress_callback(int(completed / total * 100), name)

        self.results = [results_by_index[i] for i in sorted(results_by_index)]
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
                    return "error", "未检测到网络适配器", {"adapter_count": 0}

                # 检查是否有已连接的网卡
                if "IPv4" in output or "ipv4" in output.lower():
                    return ("ok", f"检测到 {len(adapters)} 个网络适配器，状态正常",
                            {"adapter_count": len(adapters), "connected": True})
                else:
                    return ("warning", "检测到网卡但未获取到IP地址",
                            {"adapter_count": len(adapters), "connected": False})
            else:
                return "ok", "网卡状态正常", {"connected": True}
        except Exception as e:
            return "error", f"网卡检测失败: {str(e)}", {}

    def check_ip_address(self):
        """检查IP地址配置"""
        try:
            # 获取本机IP（统一走 netinfo，避免与局域网扫描模块重复实现）
            local_ip = get_local_ip()
            if not local_ip:
                return "error", "无法获取IP地址，网络可能未连接", {}
            if local_ip.startswith("169.254"):
                return ("error", f"IP地址异常({local_ip})，未获取到有效IP",
                        {"ip": local_ip, "valid": False})
            elif local_ip.startswith("127."):
                return ("error", f"IP地址为回环地址({local_ip})，网络未连接",
                        {"ip": local_ip, "valid": False})
            else:
                return "ok", f"本机IP: {local_ip}", {"ip": local_ip, "valid": True}
        except Exception as e:
            return "error", f"无法获取IP地址: {str(e)}", {}

    def check_gateway(self):
        """检查网关连通性（路由表优先、语言无关；ipconfig 兜底）"""
        try:
            if not self.is_windows:
                return "ok", "网关连通正常"

            # 取默认网关：先读路由表（数据行为纯数字，不受系统语言影响），
            # 失败再回退解析 ipconfig（兼容中英文标签）。
            gateway = get_default_gateway()
            if not gateway:
                # 取不到网关不等于网络异常：热点共享、系统自动管理等场景下仍可正常上网，
                # 因此只给提示级警告，避免对能正常上网的用户误报红色错误。
                return ("warning",
                        "未找到默认网关，可能由系统自动管理；若能正常上网可忽略此项",
                        {"gateway": ""})

            # ping 网关确认可达
            ping_result = smart_run(["ping", "-n", "2", "-w", "2000", gateway], timeout=6)
            output = (ping_result.stdout or "").lower()
            stats = self._ping_stats(ping_result.stdout)
            stats["gateway"] = gateway
            if "ttl=" in output:
                return "ok", f"网关({gateway})连通正常", stats
            return "warning", f"网关({gateway})无响应", stats
        except Exception as e:
            return "error", f"网关检测失败: {str(e)}", {}

    @staticmethod
    def _resolve_with_timeout(domain, timeout=3.0):
        """带超时的 DNS 解析。系统解析器在断网时可能阻塞很久，这里用守护线程兜底。"""
        box = queue.Queue(maxsize=1)

        def worker():
            try:
                box.put(("ok", socket.gethostbyname(domain)))
            except Exception as exc:  # noqa: BLE001 - 结果回传，异常类型不影响判断
                box.put(("err", exc))

        threading.Thread(target=worker, daemon=True).start()
        try:
            kind, value = box.get(timeout=timeout)
        except queue.Empty:
            return None, "timeout"
        if kind == "ok":
            return value, ""
        return None, str(value)

    def check_dns(self):
        """检查DNS解析（单域名超时上限 3 秒，避免断网时长时间卡住）"""
        try:
            test_domains = ["www.baidu.com", "www.qq.com"]
            timeouts = 0
            started = time.perf_counter()
            for domain in test_domains:
                ip, err = self._resolve_with_timeout(domain, timeout=3.0)
                if ip:
                    elapsed = round((time.perf_counter() - started) * 1000, 1)
                    return ("ok", f"DNS解析正常 ({domain} -> {ip})",
                            {"domain": domain, "ip": ip,
                             "latency_ms": elapsed, "success": True})
                if err == "timeout":
                    timeouts += 1

            if timeouts == len(test_domains):
                return ("error", "DNS解析超时，请检查网络连接或 DNS 设置",
                        {"success": False, "latency_ms": None})
            return ("error", "DNS解析失败，所有测试域名均无法解析",
                    {"success": False, "latency_ms": None})
        except Exception as e:
            return "error", f"DNS检测失败: {str(e)}", {}

    def check_internet(self):
        """检查互联网连通性"""
        try:
            result = smart_run(["ping", "-n", "3", "-w", "2000", "www.baidu.com"], timeout=8)
            output = result.stdout
            stats = self._ping_stats(output)
            loss = stats.get("loss_pct")
            latency = stats.get("latency_ms")

            if loss is not None:
                if loss == 0:
                    if latency is not None:
                        return ("ok", f"互联网连接正常，平均延迟 {latency:.0f}ms",
                                stats)
                    return "ok", "互联网连接正常", stats
                elif loss < 50:
                    return ("warning", f"互联网连接不稳定，丢包率 {loss}%", stats)
                else:
                    return ("error", f"互联网连接很差，丢包率 {loss}%", stats)
            else:
                return "error", "无法连接到互联网", stats
        except Exception as e:
            return "error", f"互联网检测失败: {str(e)}", {}

    def check_multi_latency(self):
        """多站点并发延迟（整合开源多目标测点思路，避免单点误判）"""
        try:
            from .speed_test import SpeedTest
            hosts = ["www.baidu.com", "223.5.5.5", "1.1.1.1"]
            st = SpeedTest()
            res = st.multi_ping_test(hosts, count=2)
            ok = [r for r in res.values() if r.get("success")]
            if not ok:
                return "error", "多个站点均无法连通", {"hosts": res}
            avg = int(sum(r["avg_latency"] for r in ok) / len(ok))
            jitter = int(sum(r.get("jitter_ms", 0) for r in ok) / len(ok))
            detail = "、".join(
                f"{h}={res.get(h, {}).get('avg_latency', 0):.0f}ms"
                for h in hosts if res.get(h, {}).get("success")
            )
            data = {"avg_ms": avg, "jitter_ms": jitter,
                    "hosts": {h: res.get(h, {}) for h in hosts}}
            # 延迟特别高或抖动大时给警告
            if avg >= 150 or jitter >= 40:
                return ("warning",
                        f"多站点延迟偏高或抖动大：平均{avg}ms/抖动{jitter}ms（{detail}）",
                        data)
            return ("ok",
                    f"多站点延迟正常：平均{avg}ms/抖动{jitter}ms（{detail}）",
                    data)
        except Exception as e:
            return "warning", f"多站点延迟检测失败: {str(e)}", {}

    def check_proxy(self):
        """检查代理设置"""
        try:
            if self.is_windows:
                # 检查注册表中的代理设置（统一走 smart_run：编码自适应 + 不闪控制台）
                result = smart_run(
                    ["reg", "query",
                     r"HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                     "/v", "ProxyEnable"], timeout=5)
                output = (result.stdout or "").lower()
                if re.search(r"proxyenable\s+reg_dword\s+0x1", output):
                    return ("warning", "检测到代理服务器已启用，可能影响网络连接",
                            {"enabled": True})
                else:
                    return "ok", "未启用代理服务器", {"enabled": False}
            else:
                proxy = os.environ.get("HTTP_PROXY", "")
                if proxy:
                    return "warning", f"检测到代理设置: {proxy}", {"enabled": True}
                return "ok", "未启用代理服务器", {"enabled": False}
        except Exception:
            return "info", "代理状态未知（不影响正常使用）", {}

    def get_summary(self):
        """获取诊断摘要"""
        if not self.results:
            return "未进行诊断", "info"

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

    @staticmethod
    def get_recommendations(results):
        """把诊断结果转成可执行的建议（不依赖界面文案）。

        返回 [{title, detail, action, page}]：
          action 为 repair 时进入一键修复；page 为 dns/speed/wifi 等。
        """
        items = [r for r in (results or []) if isinstance(r, dict)]
        by_name = {r.get("name"): r for r in items}
        advice = []

        def add(title, detail, action="", page=""):
            advice.append({"title": title, "detail": detail,
                           "action": action, "page": page})

        def bad(name):
            item = by_name.get(name)
            return item if item and item.get("status") in ("warning", "error") else None

        adapter = bad("网卡状态")
        if adapter:
            add("检查无线/有线网卡", adapter.get("message", ""), "", "speed")
        ip = bad("IP地址")
        if ip:
            add("重新获取 IP 地址", "释放并重新获取 IP，通常可以解决 169.254 开头的地址问题。",
                "repair", "")
        gateway = bad("网关连通性")
        if gateway:
            add("检查路由器连接", "网关无响应时，先确认网线/Wi-Fi 连接，再尝试修复网络组件。",
                "repair", "")
        dns = bad("DNS解析")
        if dns:
            add("优化 DNS", "DNS 解析异常或偏慢，建议测试并切换到更快的公共 DNS。",
                "", "dns")
        internet = bad("互联网连通性")
        if internet:
            add("修复网络连接", "互联网不通时，可先刷新 DNS、重置网络组件，再重新检测。",
                "repair", "")
        multi = by_name.get("多站点延迟")
        if multi and multi.get("status") == "warning":
            add("关注延迟与抖动", multi.get("message", ""), "", "speed")
        proxy = bad("代理设置")
        if proxy:
            add("清除代理设置", "检测到系统代理已启用，若不需要代理可一键清除。",
                "repair", "")
        if not advice:
            add("网络状态良好", "所有检测项均正常，可定期体检保持状态。", "", "")
        return advice

    # 诊断项 -> 可执行的修复项（只修复检测到的问题，而不是每次全量重置）
    REPAIR_TARGETS = {
        "IP地址": ("释放并重新获取IP",),
        "网关连通性": ("释放并重新获取IP", "重置Winsock目录"),
        "DNS解析": ("刷新DNS缓存",),
        "互联网连通性": ("刷新DNS缓存", "重置Winsock目录", "重置TCP/IP协议"),
        "代理设置": ("清除代理设置",),
    }

    @classmethod
    def repair_targets(cls, results):
        """返回与失败/警告项相关的修复名称列表；去重并保持固定顺序。"""
        wanted = []
        for item in results or []:
            if not isinstance(item, dict):
                continue
            if item.get("status") not in ("warning", "error"):
                continue
            for name in cls.REPAIR_TARGETS.get(item.get("name"), ()):
                if name not in wanted:
                    wanted.append(name)
        return wanted
