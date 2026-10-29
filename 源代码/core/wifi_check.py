"""
Wi-Fi检测模块 - 检测Wi-Fi信号强度和质量
面向新手小白，提供简单易懂的Wi-Fi状态评估
"""

import subprocess
import re
import os

from .cmd_utils import IS_WINDOWS, run_cmd


class WiFiChecker:
    """Wi-Fi检测器 - 检测Wi-Fi信号强度和质量"""

    def __init__(self):
        self.is_windows = IS_WINDOWS

    def get_wifi_info(self):
        """获取当前Wi-Fi连接信息"""
        try:
            if self.is_windows:
                return self._get_wifi_windows()
            else:
                return self._get_wifi_linux()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _get_wifi_windows(self):
        """Windows系统获取Wi-Fi信息（智能编码 + 超时放宽 + ipconfig兜底）"""
        info = {"success": True, "connected": False}

        # netsh 输出可能是 GBK 也可能是 UTF-8，交给 run_cmd 自动检测；超时放宽到 12 秒
        output = run_cmd(["netsh", "wlan", "show", "interfaces"], timeout=12)

        if not output:
            # 命令超时/无任何输出：不直接报错，交给 ipconfig 兜底判定
            self._fallback_ipconfig(info)
            info.setdefault("_warn", "netsh 接口命令无响应，已改用系统信息判定")
            return info

        # WLAN 服务未运行 / 无无线网卡
        if ("没有运行" in output or "not running" in output.lower()
                or "无线自动配置服务未启动" in output
                or "没有无线接口" in output
                or "没有网络适配器" in output):
            return {
                "success": False,
                "error": "WLAN服务未运行或没有无线网卡",
                "connected": False
            }

        self._parse_interfaces(output, info)

        # 兜底：netsh 解析不出任何连接信息时，用 ipconfig 判定 WLAN 适配器是否已连上
        if not info.get("connected"):
            self._fallback_ipconfig(info)

        return info

    def _parse_interfaces(self, output, info):
        """从 netsh wlan show interfaces 输出中解析关键信息"""
        # 连接状态（权威判据：State/状态 是否有"已连接"）
        state_match = re.search(r"状态\s*[:：]\s*(.+)", output)
        if not state_match:
            state_match = re.search(r"State\s*[:：]\s*(.+)", output, re.IGNORECASE)
        if state_match:
            state_text = state_match.group(1).strip().lower()
            if state_text in ("connected", "已连接", "已关联", "associated"):
                info["connected"] = True

        # SSID
        ssid_match = re.search(r"SSID\s*[:：]\s*(.+)", output)
        if ssid_match:
            info["ssid"] = ssid_match.group(1).strip()

        # 信号强度
        signal_match = re.search(r"信号\s*[:：]\s*(\d+)\s*%", output)
        if not signal_match:
            signal_match = re.search(r"Signal\s*[:：]\s*(\d+)\s*%", output, re.IGNORECASE)

        if signal_match:
            info["signal_strength"] = int(signal_match.group(1))
            # 兜底：个别系统没有"State"行，但能解析到信号，同样视为已连接
            info["connected"] = True

        # 接收速率
        rx_match = re.search(r"接收速率\(MB/秒\)\s*[:：]\s*([\d.]+)", output)
        if not rx_match:
            rx_match = re.search(r"Receive rate.*?([\d.]+)", output, re.IGNORECASE)
        if rx_match:
            info["rx_rate"] = float(rx_match.group(1))

        # 发送速率
        tx_match = re.search(r"发送速率\(MB/秒\)\s*[:：]\s*([\d.]+)", output)
        if not tx_match:
            tx_match = re.search(r"Transmit rate.*?([\d.]+)", output, re.IGNORECASE)
        if tx_match:
            info["tx_rate"] = float(tx_match.group(1))

        # 频道
        channel_match = re.search(r"频道\s*[:：]\s*(\d+)", output)
        if not channel_match:
            channel_match = re.search(r"Channel\s*[:：]\s*(\d+)", output, re.IGNORECASE)
        if channel_match:
            info["channel"] = int(channel_match.group(1))

        # BSSID (支持冒号和连字符两种格式)
        bssid_match = re.search(r"BSSID\s*[:：]\s*([\da-fA-F:\-]+)", output, re.IGNORECASE)
        if bssid_match:
            info["bssid"] = bssid_match.group(1)

        # 无线类型
        radio_match = re.search(r"无线电类型\s*[:：]\s*(.+)", output)
        if not radio_match:
            radio_match = re.search(r"Radio type\s*[:：]\s*(.+)", output, re.IGNORECASE)
        if radio_match:
            info["radio_type"] = radio_match.group(1).strip()

    def _fallback_ipconfig(self, info):
        """netsh 不可用/超时/未解析出连接时，用 ipconfig 判定 WLAN 适配器是否已连接。

        依据：无线适配器区块若持有有效的 IPv4 地址（且非"媒体已断开"），即可认为已连接。
        """
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
            # 该适配器明确断开
            if ("媒体已断开" in block or "media disconnected" in block.lower()
                    or re.search(r"媒体状态[.:]*\s*媒体已断开", block)):
                continue
            if re.search(r"IPv4\s*地址|IPv4 Address", block, re.IGNORECASE):
                info["connected"] = True
                info.setdefault("_source", "ipconfig")
                return

    def _get_wifi_linux(self):
        """Linux系统获取Wi-Fi信息"""
        try:
            result = subprocess.run(
                ["iwconfig"],
                capture_output=True, text=True, timeout=5
            )
            output = result.stdout

            info = {"success": True, "connected": False}

            # SSID
            ssid_match = re.search(r'ESSID:"(.+?)"', output)
            if ssid_match:
                info["ssid"] = ssid_match.group(1)
                info["connected"] = True

            # 信号强度
            signal_match = re.search(r"Link Quality=(\d+)/(\d+)", output)
            if signal_match:
                quality = int(signal_match.group(1))
                max_quality = int(signal_match.group(2))
                info["signal_strength"] = int(quality / max_quality * 100)

            return info
        except:
            return {"success": False, "error": "无法获取Wi-Fi信息"}

    def scan_nearby_wifi(self):
        """扫描附近的Wi-Fi网络"""
        try:
            if self.is_windows:
                output = run_cmd(["netsh", "wlan", "show", "networks", "mode=bssid"],
                                 timeout=15) or ""

                networks = []
                current_network = {}

                for line in output.split("\n"):
                    line = line.strip()

                    # SSID
                    ssid_match = re.match(r"SSID\s*\d+\s*[:：]\s*(.+)", line)
                    if ssid_match:
                        if current_network.get("ssid"):
                            networks.append(current_network)
                        current_network = {"ssid": ssid_match.group(1).strip()}

                    # 信号强度
                    signal_match = re.search(r"信号\s*[:：]\s*(\d+)%", line)
                    if not signal_match:
                        signal_match = re.search(r"Signal\s*[:：]\s*(\d+)%", line, re.IGNORECASE)
                    if signal_match and current_network:
                        current_network["signal_strength"] = int(signal_match.group(1))

                    # 认证/加密
                    auth_match = re.search(r"身份验证\s*[:：]\s*(.+)", line)
                    if not auth_match:
                        auth_match = re.search(r"Authentication\s*[:：]\s*(.+)", line, re.IGNORECASE)
                    if auth_match and current_network:
                        current_network["authentication"] = auth_match.group(1).strip()

                    # 频道
                    channel_match = re.search(r"频道\s*[:：]\s*(\d+)", line)
                    if not channel_match:
                        channel_match = re.search(r"Channel\s*[:：]\s*(\d+)", line, re.IGNORECASE)
                    if channel_match and current_network:
                        current_network["channel"] = int(channel_match.group(1))

                if current_network.get("ssid"):
                    networks.append(current_network)

                # 按信号强度排序
                networks.sort(key=lambda x: x.get("signal_strength", 0), reverse=True)

                return {"success": True, "networks": networks}
            else:
                return {"success": False, "error": "暂不支持非Windows系统的Wi-Fi扫描"}
        except Exception as e:
            return {"success": False, "error": str(e)}

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
            # netsh 未返回信号量（如 ipconfig 兜底场景），无法给出基于信号的建议
            if not advice:
                advice.append("你已连接Wi-Fi，建议保持无线网卡驱动为最新以获得最佳体验")
            return advice

        if signal < 60:
            advice.append("靠近路由器：信号较弱时，靠近路由器可以显著提升速度")
            advice.append("清除障碍物：墙壁、金属物体会阻挡Wi-Fi信号，尽量让路由器和电脑之间无遮挡")

        channel = info.get("channel", 0)
        if 1 <= channel <= 14:
            # 2.4G频段
            if channel in [1, 6, 11]:
                advice.append("当前信道({})是2.4G频段的最优信道之一".format(channel))
            else:
                advice.append("建议将路由器信道改为1、6或11，减少信道干扰")

        # 检查是否在5G频段
        radio = info.get("radio_type") or ""
        channel = info.get("channel", 0)
        is_5g = "ac" in radio.lower() or "ax" in radio.lower() or (channel and channel > 14)
        if not is_5g and signal < 70:
            advice.append("如果路由器支持5G Wi-Fi，建议连接5G频段，速度更快干扰更少")

        if not advice:
            advice.append("当前Wi-Fi状态良好，无需特别优化")

        return advice

    def check_channel_interference(self, networks):
        """检查信道干扰情况"""
        if not networks:
            return []

        # 统计各信道的网络数量
        channel_count = {}
        for net in networks:
            ch = net.get("channel", 0)
            if ch:
                channel_count[ch] = channel_count.get(ch, 0) + 1

        advice = []
        # 2.4G信道建议
        channels_24g = [c for c in channel_count.keys() if 1 <= c <= 14]
        if len(channels_24g) > 3:
            advice.append(f"附近有 {len(channels_24g)} 个不同的2.4G信道，干扰可能较严重")
            advice.append("建议优先使用5G频段，或切换到使用人数最少的信道")

        return advice
