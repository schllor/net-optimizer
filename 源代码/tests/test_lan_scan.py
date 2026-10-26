"""
局域网扫描模块（core/lan_scan）单元测试 —— 组播/广播噪音过滤。

全部为纯文本解析，不联网、不依赖真实网卡（parse_arp_devices 传 resolve_names=False
可跳过主机名反查）。样例中的 IP/MAC 均为文档保留地址（RFC 5737 / RFC 7042）。
运行：pytest tests/  （在源代码根目录下）
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.lan_scan import is_noise_entry, parse_arp_devices


# ---------- 模拟 `arp -a` 输出（21 条，其中 18 条为噪音）----------
SAMPLE_ARP = """接口: 192.0.2.208 --- 0x9
  Internet 地址         物理地址              类型
  192.0.2.1             00-00-5e-00-53-01     动态
  192.0.2.255           ff-ff-ff-ff-ff-ff     静态
  224.0.0.22            01-00-5e-00-00-16     静态
  224.0.0.251           01-00-5e-00-00-fb     静态
  224.0.0.252           01-00-5e-00-00-fc     静态
  239.255.255.250       01-00-5e-7f-ff-fa     静态
  255.255.255.255       ff-ff-ff-ff-ff-ff     静态

接口: 198.51.100.1 --- 0xa
  Internet 地址         物理地址              类型
  198.51.100.254        00-00-5e-00-53-02     动态
  198.51.100.255        ff-ff-ff-ff-ff-ff     静态
  224.0.0.22            01-00-5e-00-00-16     静态
  224.0.0.251           01-00-5e-00-00-fb     静态
  224.0.0.252           01-00-5e-00-00-fc     静态
  239.255.255.250       01-00-5e-7f-ff-fa     静态
  255.255.255.255       ff-ff-ff-ff-ff-ff     静态

接口: 203.0.113.1 --- 0xb
  Internet 地址         物理地址              类型
  203.0.113.254         00-00-5e-00-53-03     动态
  203.0.113.255         ff-ff-ff-ff-ff-ff     静态
  224.0.0.22            01-00-5e-00-00-16     静态
  224.0.0.251           01-00-5e-00-00-fb     静态
  224.0.0.252           01-00-5e-00-00-fc     静态
  239.255.255.250       01-00-5e-7f-ff-fa     静态
  255.255.255.255       ff-ff-ff-ff-ff-ff     静态
"""

SAMPLE_DEVICE_IPS = {"192.0.2.1", "198.51.100.254", "203.0.113.254"}

ONLY_NOISE = """接口: 192.0.2.208 --- 0x9
  192.0.2.255           ff-ff-ff-ff-ff-ff     静态
  224.0.0.22            01-00-5e-00-00-16     静态
  224.0.0.251           01-00-5e-00-00-fb     静态
  239.255.255.250       01-00-5e-7f-ff-fa     静态
  255.255.255.255       ff-ff-ff-ff-ff-ff     静态
"""


# ---------- 样例数据：降噪后只剩真实设备 ----------
def test_sample_arp_keeps_only_real_devices():
    devices = parse_arp_devices(SAMPLE_ARP, resolve_names=False)
    assert len(devices) == 3
    assert {d["ip"] for d in devices} == SAMPLE_DEVICE_IPS


def test_noise_only_input_returns_empty():
    assert parse_arp_devices(ONLY_NOISE, resolve_names=False) == []


@pytest.mark.parametrize("text", ["", None, "接口: 192.0.2.208 --- 0x9\n  Internet 地址 物理地址 类型\n"])
def test_empty_or_header_only(text):
    assert parse_arp_devices(text, resolve_names=False) == []


# ---------- 噪音判据 ----------
@pytest.mark.parametrize("ip,mac,expected", [
    # 组播（MAC 前缀 01:00:5e）
    ("224.0.0.22", "01-00-5e-00-00-16", True),
    ("224.0.0.251", "01-00-5e-00-00-fb", True),
    ("239.255.255.250", "01-00-5e-7f-ff-fa", True),
    # 广播（各网段的 .255 与全局广播，MAC 全 F —— 无法靠 IP 字面量穷举）
    ("255.255.255.255", "ff-ff-ff-ff-ff-ff", True),
    ("192.0.2.255", "ff-ff-ff-ff-ff-ff", True),
    ("198.51.100.255", "ff-ff-ff-ff-ff-ff", True),
    ("203.0.113.255", "ff-ff-ff-ff-ff-ff", True),
    # IP 兜底
    ("0.0.0.0", "00-00-00-00-00-00", True),
    ("127.0.0.1", "00-00-00-00-00-00", True),
    # 真实设备（不应判为噪音）
    ("192.0.2.1", "00-00-5e-00-53-01", False),
    ("198.51.100.254", "00-00-5e-00-53-02", False),
    ("203.0.113.254", "00-00-5e-00-53-03", False),
    ("198.51.100.99", "00-00-5e-00-53-05", False),
])
def test_is_noise_entry(ip, mac, expected):
    assert is_noise_entry(ip, mac) is expected


def test_is_noise_entry_accepts_colon_mac():
    """冒号分隔的 MAC 同样能被识别（判据内部会归一化分隔符与大小写）。"""
    assert is_noise_entry("198.51.100.255", "FF:FF:FF:FF:FF:FF") is True
    assert is_noise_entry("224.0.0.1", "01:00:5e:00:00:01") is True


def test_multicast_ip_with_non_multicast_mac_is_filtered():
    """IP 落在组播段时，即使 MAC 不是 01:00:5e 也应被 IP 兜底判据过滤。"""
    assert is_noise_entry("239.1.2.3", "aa-bb-cc-dd-ee-ff") is True


# ---------- 去重与本机标记 ----------
def test_dedupes_same_ip_across_interfaces():
    text = """接口: 192.0.2.100 --- 0x9
  192.0.2.5             00-00-5e-00-53-04     动态
接口: 198.51.100.100 --- 0xa
  192.0.2.5             00-00-5e-00-53-04     动态
"""
    devices = parse_arp_devices(text, resolve_names=False)
    assert len(devices) == 1
    assert devices[0]["ip"] == "192.0.2.5"


def test_marks_local_device_as_self():
    devices = parse_arp_devices(SAMPLE_ARP, local_ip="192.0.2.1", resolve_names=False)
    by_ip = {d["ip"]: d for d in devices}
    assert by_ip["192.0.2.1"]["self"] is True
    assert by_ip["198.51.100.254"]["self"] is False


def test_device_record_shape():
    device = parse_arp_devices(SAMPLE_ARP, resolve_names=False)[0]
    assert set(device.keys()) == {"ip", "mac", "name", "online", "self"}
    assert device["mac"].count(":") == 5      # 已由 - 归一化为 :
    assert device["name"] == "未知设备"        # 未反查时回落默认名
    assert device["online"] is True
