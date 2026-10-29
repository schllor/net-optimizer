"""
netsh 文本解析与信道建议的离线测试（中英文样本，不依赖真实网卡）。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.wifi_check import (
    parse_netsh_interfaces, parse_netsh_networks, parse_rate_mbps,
    channel_advice, channel_band, network_band,
)


NETSH_INTERFACES_CN = """接口名称                   : WLAN
状态                       : 已连接
BSSID                      : 9e:2b:a6:8b:44:66
SSID                       : 吉胖网络
网络类型                   : 基础结构
无线电类型                 : 802.11ax
身份验证                   : WPA2 - 个人
密码                       : CCMP
接收速率(MB/秒)            : 866.7
发送速率(MB/秒)            : 780.0
信号                       : 80%
配置文件                   : 吉胖网络
频道                       : 36
"""

NETSH_INTERFACES_EN = """    Name                   : Wi-Fi
    Description            : Intel(R) Wi-Fi 6 AX201
    State                  : connected
    SSID                   : Office
    BSSID                  : 00:11:22:33:44:55
    Network type           : Infrastructure
    Radio type             : 802.11ac
    Authentication         : WPA2-Personal
    Receive rate (Mbps)    : 144.4
    Transmit rate (Mbps)   : 130.0
    Signal                 : 62%
    Channel                : 6
"""

NETSH_NETWORKS_CN = """接口名称 : WLAN
当前有 2 个网络可见。

SSID 1 : Home
    网络类型             : 基础结构
    身份验证             : WPA2 - 个人
    加密                 : CCMP
    BSSID 1              : 9e:2b:a6:8b:44:66
         信号            : 80%
         无线电类型      : 802.11ax
         频道            : 36

SSID 2 : Cafe
    身份验证             : 开放
    BSSID 1              : 00:11:22:33:44:55
         信号            : 40%
         频道            : 6
"""


def test_parse_interfaces_chinese():
    info = parse_netsh_interfaces(NETSH_INTERFACES_CN)
    assert info["connected"] is True
    assert info["ssid"] == "吉胖网络"       # 不被 BSSID 行误匹配
    assert info["signal_strength"] == 80
    assert info["channel"] == 36
    assert info["rx_rate"] == 866.7
    assert info["tx_rate"] == 780.0
    assert info["bssid"] == "9e:2b:a6:8b:44:66"
    assert info["radio_type"] == "802.11ax"


def test_parse_interfaces_english():
    info = parse_netsh_interfaces(NETSH_INTERFACES_EN)
    assert info["connected"] is True
    assert info["ssid"] == "Office"
    assert info["signal_strength"] == 62
    assert info["channel"] == 6
    assert info["rx_rate"] == 144.4
    assert info["tx_rate"] == 130.0


def test_parse_interfaces_disconnected():
    info = parse_netsh_interfaces("状态 : 已断开连接\nSSID : \n信号 : 0%\n")
    assert info["connected"] is False
    assert info.get("signal_strength") == 0


@pytest.mark.parametrize("text", ["", None])
def test_parse_interfaces_empty(text):
    assert parse_netsh_interfaces(text) == {"connected": False}


def test_parse_rate_mbps_units():
    assert parse_rate_mbps("接收速率(MB/秒) : 866.7")["rx_rate"] == 866.7
    rates = parse_rate_mbps("Receive rate (Mbps) : 144.4\nTransmit rate (Mbps): 130")
    assert rates == {"rx_rate": 144.4, "tx_rate": 130.0}
    assert parse_rate_mbps("无关文本") == {}


def test_parse_networks_chinese():
    nets = parse_netsh_networks(NETSH_NETWORKS_CN)
    assert len(nets) == 2
    assert nets[0]["ssid"] == "Home"
    assert nets[0]["signal"] == 80
    assert nets[0]["channel"] == 36
    assert nets[0]["auth"] == "WPA2 - 个人"
    assert nets[1]["ssid"] == "Cafe"
    assert nets[1]["channel"] == 6
    # 按信号从强到弱
    assert nets[0]["signal"] >= nets[1]["signal"]


def test_parse_networks_picks_strongest_bssid():
    text = """SSID 1 : Mesh
    BSSID 1 : aa:aa:aa:aa:aa:aa
         信号 : 30%
         频道 : 1
    BSSID 2 : bb:bb:bb:bb:bb:bb
         信号 : 70%
         频道 : 11
"""
    nets = parse_netsh_networks(text)
    assert len(nets) == 1
    assert nets[0]["signal"] == 70
    assert nets[0]["channel"] == 11


def test_parse_networks_empty():
    assert parse_netsh_networks("") == []
    assert parse_netsh_networks("接口名称 : WLAN\n当前有 0 个网络可见。") == []


# ---------- 频段与信道建议 ----------
@pytest.mark.parametrize("channel,band", [
    (1, "2.4G"), (6, "2.4G"), (14, "2.4G"),
    (36, "5G"), (149, "5G"), (177, "5G"),
    (0, ""), (None, ""), ("x", ""),
])
def test_channel_band(channel, band):
    assert channel_band(channel) == band


def test_network_band_prefers_frequency():
    assert network_band({"channel": 5, "freq": 5955}) == "6G"
    assert network_band({"channel": 36, "freq": 5180}) == "5G"
    assert network_band({"channel": 6, "freq": 2437}) == "2.4G"
    assert network_band({"channel": 149}) == "5G"


def test_channel_advice_avoids_congested_2g():
    networks = [
        {"ssid": "A", "signal": 80, "channel": 1, "connected": True},
        {"ssid": "B", "signal": 60, "channel": 2},
        {"ssid": "C", "signal": 40, "channel": 6},
        {"ssid": "D", "signal": 70, "channel": 149, "freq": 5745},
    ]
    advice = "\n".join(channel_advice(networks, current_channel=1))
    assert "切到 11" in advice
    assert "5G/6G" in advice


def test_channel_advice_current_channel_is_best():
    networks = [
        {"ssid": "A", "signal": 20, "channel": 11, "connected": True},
        {"ssid": "B", "signal": 70, "channel": 1},
        {"ssid": "C", "signal": 60, "channel": 2},
    ]
    advice = "\n".join(channel_advice(networks, current_channel=11))
    assert "已是推荐信道" in advice
    assert "切到" not in advice


def test_channel_advice_empty():
    assert channel_advice([]) == ["附近未检测到明显的信道拥堵"]
