"""
IP Helper 邻居表与 SendARP 的离线测试（Fake 行数据，不发起真实网络请求）。
"""

import ctypes
import os
import sys
import threading

import pytest
import core.winapi_arp as arp
from core.lan_scan import parse_native_neighbors, _same_subnet


class FakeRow:
    def __init__(self, ip, mac, dw_type=3, index=13):
        raw = (ctypes.c_ubyte * 8)()
        for i, part in enumerate(mac.split(":")[:6]):
            raw[i] = int(part, 16)
        packed = bytes(int(p) for p in ip.split("."))
        self.dwIndex = index
        self.dwPhysAddrLen = 6
        self.bPhysAddr = raw
        self.dwAddr = int.from_bytes(packed, "little")
        self.dwType = dw_type


def test_ip_from_dword():
    assert arp.ip_from_dword(0x0101A8C0) == "192.168.1.1"


def test_mac_from_bytes():
    raw = (ctypes.c_ubyte * 8)(0x02, 0x00, 0x00, 0x00, 0x00, 0x01, 0, 0)
    assert arp.mac_from_bytes(raw, 6) == "02:00:00:00:00:01"
    assert arp.mac_from_bytes(raw, 0) == ""


def test_parse_neighbor_rows_filters_invalid_and_zero_mac():
    rows = [
        FakeRow("192.168.1.1", "02:00:00:00:00:01", dw_type=3),
        FakeRow("192.168.1.2", "aa:bb:cc:dd:ee:ff", dw_type=4),
        FakeRow("192.168.1.3", "aa:bb:cc:dd:ee:ff", dw_type=2),   # invalid
        FakeRow("192.168.1.4", "00:00:00:00:00:00", dw_type=3),
    ]
    parsed = arp.parse_neighbor_rows(rows)
    assert [d["ip"] for d in parsed] == ["192.168.1.1", "192.168.1.2"]
    assert parsed[0]["state"] == "dynamic"
    assert parsed[1]["state"] == "static"
    assert parsed[0]["ifindex"] == 13


def test_parse_native_neighbors_filters_noise_and_marks_self():
    rows = [
        {"ip": "224.0.0.22", "mac": "01:00:5e:00:00:16"},
        {"ip": "192.168.1.255", "mac": "ff:ff:ff:ff:ff:ff"},
        {"ip": "192.168.1.1", "mac": "02:00:00:00:00:01"},
        {"ip": "192.168.1.4", "mac": "02:00:00:00:00:03"},
        {"ip": "192.168.1.4", "mac": "02:00:00:00:00:03"},   # 去重
    ]
    devices = parse_native_neighbors(rows, local_ip="192.168.1.1")
    assert [d["ip"] for d in devices] == ["192.168.1.1", "192.168.1.4"]
    assert devices[0]["self"] is True
    assert devices[1]["self"] is False


def test_same_subnet():
    assert _same_subnet("192.168.1.4", "192.168.1.1") is True
    assert _same_subnet("192.168.2.4", "192.168.1.1") is False
    assert _same_subnet("bad-ip", "192.168.1.1") is False


def test_probe_online_returns_responders(monkeypatch):
    def fake_send(ip):
        return "aa:bb:cc:dd:ee:ff" if ip.endswith(".1") else None

    monkeypatch.setattr(arp, "send_arp", fake_send)
    result = arp.probe_online(
        ["192.168.1.1", "192.168.1.2", "192.168.1.1"], timeout=1.0)
    assert result == {"192.168.1.1": "aa:bb:cc:dd:ee:ff"}


def test_probe_online_respects_cancel(monkeypatch):
    cancel = threading.Event()
    cancel.set()

    def fake_send(ip):
        return "aa:bb:cc:dd:ee:ff"

    monkeypatch.setattr(arp, "send_arp", fake_send)
    result = arp.probe_online(["192.168.1.1"], timeout=5.0, cancel=cancel)
    assert result == {}


@pytest.mark.skipif(sys.platform != "win32", reason="仅 Windows")
def test_real_neighbor_table_type():
    rows = arp.get_neighbors()
    assert rows is None or isinstance(rows, list)

