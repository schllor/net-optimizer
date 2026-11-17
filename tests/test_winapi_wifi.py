"""
WlanAPI 原生探测的离线测试：结构体尺寸、频点/SSID 转换、列表合并。

不联网、不依赖真实无线网卡；真实 API 调用只做「不抛异常」冒烟。
"""

import ctypes
import os
import sys

import pytest
from core.winapi_wifi import (
    DOT11_SSID, WLAN_BSS_ENTRY, WLAN_CONNECTION_ATTRIBUTES,
    WLAN_AVAILABLE_NETWORK, WLAN_INTERFACE_INFO,
    channel_from_frequency, ssid_to_str, mac_to_str, _merge_networks,
    get_connection, scan_networks,
)


def _ssid(text):
    raw = text.encode("utf-8")
    s = DOT11_SSID()
    s.uSSIDLength = len(raw)
    s.ucSSID[:len(raw)] = raw
    return s


# ---------- 结构体布局 ----------
def test_struct_sizes_guard_alignment():
    assert ctypes.sizeof(WLAN_INTERFACE_INFO) == 532
    assert ctypes.sizeof(WLAN_CONNECTION_ATTRIBUTES) == 604
    assert ctypes.sizeof(WLAN_AVAILABLE_NETWORK) == 628
    assert ctypes.sizeof(WLAN_BSS_ENTRY) == 360


# ---------- 纯转换 ----------
@pytest.mark.parametrize("mhz,channel", [
    (2412, 1), (2437, 6), (2462, 11), (2484, 14),
    (5180, 36), (5320, 64), (5745, 149), (5955, 1),
    (0, None), (60000, None), (None, None),
])
def test_channel_from_frequency(mhz, channel):
    assert channel_from_frequency(mhz) == channel


def test_ssid_to_str_handles_utf8_and_empty():
    assert ssid_to_str(_ssid("HomeWiFi")) == "HomeWiFi"
    assert ssid_to_str(DOT11_SSID()) == ""
    hidden = DOT11_SSID()
    hidden.uSSIDLength = 3
    hidden.ucSSID[:3] = b"\x00\x00\x00"
    assert ssid_to_str(hidden) == ""


def test_mac_to_str():
    raw = (ctypes.c_ubyte * 6)(0x02, 0x00, 0x00, 0x00, 0x00, 0x01)
    assert mac_to_str(raw) == "02:00:00:00:00:01"


# ---------- 合并可用列表与 BSS 列表 ----------
def test_merge_uses_bss_signal_and_channel():
    available = [
        {"ssid": "Home", "signal": 0, "auth": "WPA2-PSK", "connected": True},
        {"ssid": "Guest", "signal": 71, "auth": "开放", "connected": False},
    ]
    bss = [
        {"ssid": "Home", "bssid": "aa:aa:aa:aa:aa:aa", "signal": 66,
         "freq": 5180, "channel": 36},
        {"ssid": "Hidden", "bssid": "bb:bb:bb:bb:bb:bb", "signal": 20,
         "freq": 2412, "channel": 1},
    ]
    merged = _merge_networks(available, bss)
    by_ssid = {n["ssid"]: n for n in merged}
    assert by_ssid["Home"]["signal"] == 66
    assert by_ssid["Home"]["channel"] == 36
    assert by_ssid["Home"]["freq"] == 5180
    assert by_ssid["Home"]["connected"] is True
    assert by_ssid["Guest"]["channel"] is None
    assert by_ssid["Hidden"]["auth"] == ""
    assert merged[0]["connected"] is True  # 已连接网络排最前


def test_merge_dedupes_same_ssid():
    available = [
        {"ssid": "A", "signal": 30, "auth": "", "connected": False},
        {"ssid": "A", "signal": 80, "auth": "WPA2-PSK", "connected": True},
    ]
    merged = _merge_networks(available, [])
    assert len(merged) == 1
    assert merged[0]["signal"] == 80
    assert merged[0]["connected"] is True
    assert merged[0]["auth"] == "WPA2-PSK"


# ---------- 真实 API 冒烟（只验证不抛异常、类型正确） ----------
@pytest.mark.skipif(sys.platform != "win32", reason="仅 Windows")
def test_real_api_returns_expected_type():
    conn = get_connection()
    assert conn is None or isinstance(conn, dict)
    nets = scan_networks()
    assert nets is None or isinstance(nets, list)

