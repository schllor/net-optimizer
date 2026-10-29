"""
Wi-Fi检测模块 - 检测Wi-Fi信号强度和质量
面向新手小白，提供简单易懂的Wi-Fi状态评估

探测顺序：WlanAPI 原生接口（语言无关）→ netsh 文本解析 → ipconfig 判定。
原生接口失败时自动回退，也可用环境变量 NETHELPER_NATIVE=0 强制走旧路径。
"""

import re
import subprocess

from .cmd_utils import IS_WINDOWS, run_cmd


def _search_label(text, labels, pattern=r"(.+)"):
    """按中英文标签查找字段值，返回第一处匹配。"""
    for label in labels:
        match = re.search(label + r"\s*[:：]\s*" + pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def parse_rate_mbps(text):
    """从 netsh 文本取接收/发送速率（netsh 数值单位即为 Mbps）。"""
    rates = {}
    for key, label in (("rx_rate", "接收速率|Receive rate"),
                       ("tx_rate", "发送速率|Transmit rate")):
        match = re.search(
            r"(?:" + label + r")[^:：\n]*[:：]?\s*([\d.]+)", text, re.IGNORECASE)
        if match:
            try:
                rates[key] = float(match.group(1))
            except ValueError:
                pass
    return rates


def parse_netsh_interfaces(text):
    """解析 `netsh wlan show interfaces`（中英文标签兼容，纯函数）。"""
    info = {"connected": False}
    if not text:
        return info

    state = _search_label(text, ("状态", "State"))
    if state and state.lower() in ("connected", "已连接", "已关联", "associated"):
        info["connected"] = True

    ssid = _search_label(text, (r"(?<!B)SSID",), r"(.+)")
    if ssid:
        info["ssid"] = ssid.strip()

    signal = _search_label(text, ("信号", "Signal"), r"(\d+)\s*%")
    if signal:
        info["signal_strength"] = int(signal)
        # 个别系统没有 State 行，但有信号值时同样视为已连接
        if state is None and info["signal_strength"] > 0:
            info["connected"] = True

    info.update(parse_rate_mbps(text))

    channel = _search_label(text, ("频道", "Channel"), r"(\d+)")
    if channel:
        info["channel"] = int(channel)

    bssid = _search_label(text, ("BSSID",), r"([\da-fA-F:\-]+)")
    if bssid:
        info["bssid"] = bssid

    radio = _search_label(text, ("无线电类型", "Radio type"))
    if radio:
        info["radio_type"] = radio
    return info


def parse_netsh_networks(text):
    """解析 `netsh wlan show networks mode=bssid`，返回 [{ssid,signal,channel,auth}]。"""
    if not text:
        return []
    blocks = re.split(r"^\s*SSID\s+\d+\s*[:：]", text, flags=re.MULTILINE)
    networks = []
    for block in blocks[1:]:
        lines = block.splitlines()
        ssid = lines[0].strip() if lines else ""
        if not ssid:
            continue
        signals = [int(v) for v in re.findall(
            r"(?:信号|Signal)\s*[:：]\s*(\d+)\s*%", block, re.IGNORECASE)]
        channels = [int(v) for v in re.findall(
            r"(?:频道|Channel)\s*[:：]\s*(\d+)", block, re.IGNORECASE)]
        auth = _search_label(block, ("身份验证", "Authentication"))
        best = max(range(len(signals)), key=lambda i: signals[i]) if signals else -1
        networks.append({
            "ssid": ssid,
            "signal": signals[best] if best >= 0 else 0,
            "channel": channels[best] if 0 <= best < len(channels) else (
                channels[0] if channels else None),
            "auth": auth or "",
            "connected": False,
        })
    networks.sort(key=lambda n: -n["signal"])
    return networks


def channel_band(channel):
    """信道号 → 频段标签（netsh 文本没有频率，只能按信道号粗分）。"""
    try:
        channel = int(channel)
    except (TypeError, ValueError):
        return ""
    if 1 <= channel <= 14:
        return "2.4G"
    if 32 <= channel <= 177:
        return "5G"
    return ""


def network_band(net):
    """优先用原生接口返回的频点判断频段，避免 6G 信道号与 2.4G 冲突。"""
    freq = net.get("freq")
    if freq:
        if freq < 2500:
            return "2.4G"
        if freq < 5925:
            return "5G"
        return "6G"
    return channel_band(net.get("channel"))


def channel_advice(networks, current_channel=None):
    """基于附近网络的信道占用给出建议（2.4G 只看 1/6/11，5G/6G 直接推荐）。"""
    nets = [n for n in (networks or []) if n.get("channel")]
    advice = []
    # 自己正在连接的网络不是干扰源，计入会永远把当前信道判为最差
    g24 = [n for n in nets
           if network_band(n) == "2.4G" and not n.get("connected")]

    def overlap_score(channel):
        return sum(int(n.get("signal") or 0) for n in g24
                   if abs(int(n["channel"]) - channel) <= 4)

    if g24:
        scores = {ch: overlap_score(ch) for ch in (1, 6, 11)}
        best = min(scores, key=scores.get)
        current = int(current_channel) if current_channel else None
        if current in (1, 6, 11) and scores[current] <= scores[best]:
            advice.append(f"当前 2.4G 信道 {current} 已是推荐信道")
        elif current and 1 <= current <= 14:
            advice.append(
                f"2.4G 建议从信道 {current} 切到 {best}（1/6/11 互不重叠，邻近干扰更少）")
        else:
            advice.append(f"2.4G 建议使用信道 {best}（1/6/11 互不重叠）")

    g5 = [n for n in nets
          if network_band(n) in ("5G", "6G") and not n.get("connected")]
    if g5:
        advice.append(
            f"检测到 {len(g5)} 个 5G/6G 网络：优先连接高频段，干扰更少、速率更高")

    if not advice:
        advice.append("附近未检测到明显的信道拥堵")
    return advice


class WiFiChecker:
    """Wi-Fi检测器 - 检测Wi-Fi信号强度和质量"""

    def __init__(self):
        self.is_windows = IS_WINDOWS

    def get_wifi_info(self):
        """获取当前Wi-Fi连接信息"""
        try:
            if self.is_windows:
                return self._get_wifi_windows()
            return self._get_wifi_linux()
        except Exception as e:
            return {"success": False, "connected": False,
                    "error": f"Wi-Fi 检测失败: {e}"}

    # ---------- Windows ----------
    def _get_wifi_windows(self):
        native = self._native_info()
        if native is not None:
            if native.get("no_interface"):
                return {"success": False, "connected": False,
                        "error": "没有无线网卡，或 WLAN 服务未运行"}
            infos = {"success": True, "connected": False, "_source": "native"}
            infos.update({k: v for k, v in native.items() if k != "no_interface"})
            if not infos.get("connected"):
                infos["error"] = "未连接到Wi-Fi网络：请连接Wi-Fi后重新检测"
            return infos
        return self._get_wifi_netsh()

    def _native_info(self):
        try:
            from .winapi_wifi import get_connection
            return get_connection()
        except Exception:
            return None

    def _get_wifi_netsh(self):
        """netsh 文本解析（原生 API 不可用时的回退路径）"""
        info = {"success": True, "connected": False, "_source": "netsh"}
        output = run_cmd(["netsh", "wlan", "show", "interfaces"], timeout=12)

        if not output:
            self._fallback_ipconfig(info)
            info.setdefault("_warn", "netsh 接口命令无响应，已改用系统信息判定")
            return info

        lowered = output.lower()
        if ("没有运行" in output or "not running" in lowered
                or "无线自动配置服务未启动" in output
                or "没有无线接口" in output
                or "没有网络适配器" in output):
            return {"success": False, "connected": False,
                    "error": "WLAN服务未运行或没有无线网卡"}

        info.update(parse_netsh_interfaces(output))
        if not info.get("connected"):
            self._fallback_ipconfig(info)
        return info

    def _fallback_ipconfig(self, info):
        """netsh 不可用/超时/未解析出连接时，用 ipconfig 判定 WLAN 适配器是否已连接。"""
        try:
            ip = run_cmd(["ipconfig"], timeout=8)
        except Exception:
            return
        wifi_names = ("WLAN", "Wi-Fi", "Wifi", "Wireless", "802.11", "无线网络",
                      "无线局域网适配器", "无线")
        blocks = re.split(r"\n\s*\n", ip)
        for block in blocks:
            if not any(n in block for n in wifi_names):
                continue
            if ("媒体已断开" in block or "media disconnected" in block.lower()
                    or re.search(r"媒体状态[.:]*\s*媒体已断开", block)):
                continue
            if re.search(r"IPv4\s*地址|IPv4 Address", block, re.IGNORECASE):
                info["connected"] = True
                info.setdefault("_source", "ipconfig")
                return

    # ---------- Linux ----------
    def _get_wifi_linux(self):
        try:
            result = subprocess.run(
                ["iwconfig"], capture_output=True, text=True, timeout=5)
            output = result.stdout
            info = {"success": True, "connected": False}
            ssid_match = re.search(r'ESSID:"(.+?)"', output)
            if ssid_match:
                info["ssid"] = ssid_match.group(1)
                info["connected"] = True
            signal_match = re.search(r"Link Quality=(\d+)/(\d+)", output)
            if signal_match:
                quality = int(signal_match.group(1))
                max_quality = int(signal_match.group(2))
                info["signal_strength"] = int(quality / max_quality * 100)
            return info
        except Exception:
            return {"success": False, "connected": False,
                    "error": "无法获取Wi-Fi信息"}

    # ---------- 附近网络 ----------
    def scan_nearby_wifi(self):
        """扫描附近 Wi-Fi 与信道建议；返回 dict（networks/advice/error）。"""
        if not self.is_windows:
            return {"success": False, "networks": [], "advice": [],
                    "error": "当前系统暂不支持附近网络扫描"}

        native = None
        try:
            from .winapi_wifi import scan_networks
            native = scan_networks()
        except Exception:
            native = None
        if native is not None:
            current = next((n.get("channel") for n in native if n.get("connected")), None)
            return {"success": True, "networks": native,
                    "advice": channel_advice(native, current), "source": "native"}

        output = run_cmd(["netsh", "wlan", "show", "networks", "mode=bssid"], timeout=12)
        if not output:
            return {"success": False, "networks": [], "advice": [],
                    "error": "扫描附近网络失败：WLAN 服务未运行或没有无线网卡"}
        networks = parse_netsh_networks(output)
        current_ssid = self.get_wifi_info().get("ssid")
        for net in networks:
            net["connected"] = bool(current_ssid and net["ssid"] == current_ssid)
        networks.sort(key=lambda n: (not n["connected"], -n["signal"]))
        current = next((n.get("channel") for n in networks if n["connected"]), None)
        return {"success": True, "networks": networks,
                "advice": channel_advice(networks, current), "source": "netsh"}

    # ---------- 评估 ----------
    def get_signal_level(self, signal_strength):
        """根据信号强度给出评级"""
        if signal_strength >= 80:
            return "非常好", "ok", "信号非常强，上网速度会很快"
        elif signal_strength >= 60:
            return "良好", "ok", "信号良好，日常使用没问题"
        elif signal_strength >= 40:
            return "一般", "warning", "信号一般，距离路由器较远或有障碍物"
        elif signal_strength >= 20:
            return "较弱", "warning", "信号较弱，可能会导致网速慢或断连"
        else:
            return "很差", "error", "信号很差，严重影响网络体验"

    def get_wifi_advice(self, info):
        """根据Wi-Fi信息给出优化建议"""
        advice = []

        if not info.get("connected"):
            advice.append("您的电脑没有连接Wi-Fi，请先连接Wi-Fi网络")
            return advice

        signal = info.get("signal_strength", 0)
        if "signal_strength" not in info:
            advice.append("你已连接Wi-Fi，建议保持无线网卡驱动为最新以获得最佳体验")
            return advice

        if signal < 60:
            advice.append("靠近路由器：信号较弱时，靠近路由器可以显著提升速度")
            advice.append("清除障碍物：墙壁、金属物体会阻挡Wi-Fi信号，尽量让路由器和电脑之间无遮挡")

        channel = info.get("channel", 0)
        if 1 <= channel <= 14:
            if channel in (1, 6, 11):
                advice.append(f"当前信道({channel})是2.4G频段的最优信道之一")
            else:
                advice.append("建议将路由器信道改为1、6或11，减少信道干扰")

        radio = (info.get("radio_type") or "").lower()
        is_5g = any(tag in radio for tag in ("ac", "ax", "be")) or (channel and channel > 14)
        if not is_5g and signal < 70:
            advice.append("如果路由器支持5G Wi-Fi，建议连接5G频段，速度更快干扰更少")

        if not advice:
            advice.append("当前Wi-Fi状态良好，无需特别优化")
        return advice


def collect_wifi_diagnostics():
    """汇总网络环境诊断文本，供复制或导出排查。

    内部会执行 netsh/ipconfig（约 1~3 秒），调用方应放到后台线程。
    """
    import datetime
    import platform

    from .version import __version__

    parts = [
        "【网络优化助手 诊断信息】",
        f"版本: v{__version__}",
        f"系统: {platform.platform()}",
        f"生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "==== netsh wlan show interfaces ====",
        run_cmd(["netsh", "wlan", "show", "interfaces"], timeout=12),
        "",
        "==== netsh wlan show drivers ====",
        run_cmd(["netsh", "wlan", "show", "drivers"], timeout=12),
        "",
        "==== 网络配置 (ipconfig /all) ====",
        run_cmd(["ipconfig", "/all"], timeout=12),
    ]
    return "\n".join(parts)
