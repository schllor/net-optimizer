"""
网络信息模块（core/netinfo）单元测试。

覆盖默认网关的两条解析路径：
  - parse_route_table       ：route print 路由表（语言无关）
  - parse_gateway_from_ipconfig：ipconfig 文本（中英文标签 / 空值 / 同网段优先）
全部为纯文本解析，不联网、不依赖真实网卡。样例中的 IP 均为文档保留地址
（RFC 5737 TEST-NET）。
运行：pytest tests/  （在源代码根目录下）
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.netinfo import (
    parse_route_table, parse_route_table_info,
    parse_gateway_from_ipconfig, get_local_ip, _is_valid_ipv4, _same_subnet,
)


# ---------- 样例：route print -4 输出 ----------
ROUTE_SAMPLE = """===========================================================================
Interface List
 12...xx xx xx xx xx xx ......Intel(R) Wi-Fi 6 AX201 160MHz
===========================================================================

IPv4 Route Table
===========================================================================
Active Routes:
Network Destination        Netmask          Gateway       Interface  Metric
          0.0.0.0          0.0.0.0       192.0.2.1      192.0.2.208     45
        127.0.0.0        255.0.0.0         On-link         127.0.0.1    331
        127.0.0.1  255.255.255.255         On-link         127.0.0.1    331
===========================================================================
Persistent Routes:
  None
"""

# 两条默认路由（模拟有线 + 无线并存），metric 小者优先
ROUTE_MULTI = """Active Routes:
Network Destination        Netmask          Gateway       Interface  Metric
          0.0.0.0          0.0.0.0    198.51.100.1    198.51.100.107     55
          0.0.0.0          0.0.0.0       192.0.2.1      192.0.2.208     25
"""

# 仅有 On-link 默认路由（无真实网关）
ROUTE_ONLINK = """Active Routes:
Network Destination        Netmask          Gateway       Interface  Metric
          0.0.0.0          0.0.0.0         On-link      192.0.2.107    281
"""


# ---------- 样例：ipconfig 输出 ----------
IPCONFIG_CN = """以太网适配器 以太网:

   连接特定的 DNS 后缀 . . . . . . . :
   IPv4 地址 . . . . . . . . . . . . : 192.0.2.107
   子网掩码  . . . . . . . . . . . . : 255.255.255.0
   默认网关. . . . . . . . . . . . . : 192.0.2.1
"""

# 英文标签 + 中文适配器名，虚拟网卡网关为空且排在前
IPCONFIG_EN = """Ethernet adapter VMware Network Adapter VMnet1:

   Connection-specific DNS Suffix  . :
   IPv4 Address. . . . . . . . . . . : 203.0.113.1
   Subnet Mask . . . . . . . . . . . : 255.255.255.0
   Default Gateway . . . . . . . . . :

Ethernet adapter VMware Network Adapter VMnet8:

   IPv4 Address. . . . . . . . . . . : 198.51.100.1
   Default Gateway . . . . . . . . . :

Wireless LAN adapter WLAN:

   IPv4 Address. . . . . . . . . . . : 192.0.2.208
   Default Gateway . . . . . . . . . : 192.0.2.1
"""

# 两个非空网关：前者属虚拟网卡网段，后者与本机 IP 同网段
IPCONFIG_MULTI_GW = """Ethernet adapter VMware Network Adapter VMnet1:

   Default Gateway . . . . . . . . . : 203.0.113.1

Wireless LAN adapter WLAN:

   Default Gateway . . . . . . . . . : 192.0.2.1
"""

# 全为空网关
IPCONFIG_ALL_EMPTY = """Ethernet adapter VMware Network Adapter VMnet1:

   Default Gateway . . . . . . . . . :

Wireless LAN adapter WLAN:

   Default Gateway . . . . . . . . . :
"""


# ---------- route 路由表解析 ----------
def test_parse_route_table_single_default():
    assert parse_route_table(ROUTE_SAMPLE) == "192.0.2.1"


def test_parse_route_table_picks_lowest_metric():
    assert parse_route_table(ROUTE_MULTI) == "192.0.2.1"  # metric 25 < 55


def test_parse_route_table_skips_onlink():
    assert parse_route_table(ROUTE_ONLINK) is None  # On-link 不是真实网关


@pytest.mark.parametrize("text", ["", None, "IPv4 Route Table\nActive Routes:\n", "完全无关的文本"])
def test_parse_route_table_empty_or_irrelevant(text):
    assert parse_route_table(text) is None


def test_parse_route_table_info_fields():
    info = parse_route_table_info(ROUTE_SAMPLE)
    assert info["gateway"] == "192.0.2.1"
    assert info["interface"] == "192.0.2.208"
    assert info["metric"] == 45


# ---------- ipconfig 文本解析 ----------
def test_parse_gateway_ipconfig_chinese():
    assert parse_gateway_from_ipconfig(IPCONFIG_CN) == "192.0.2.1"


def test_parse_gateway_ipconfig_english():
    assert parse_gateway_from_ipconfig(IPCONFIG_EN) == "192.0.2.1"


def test_parse_gateway_ipconfig_skips_empty_vmware():
    """VMware 空网关行在前时不能被误取，应跳过并命中真实网关。"""
    assert parse_gateway_from_ipconfig(IPCONFIG_EN, "192.0.2.208") == "192.0.2.1"


def test_parse_gateway_ipconfig_prefers_same_subnet():
    """多个非空网关时，优先返回与本机 IP 同 /24 的候选。"""
    assert parse_gateway_from_ipconfig(IPCONFIG_MULTI_GW, "192.0.2.208") == "192.0.2.1"
    # 不给 local_ip 时退化为「第一个有效候选」
    assert parse_gateway_from_ipconfig(IPCONFIG_MULTI_GW) == "203.0.113.1"


def test_parse_gateway_ipconfig_all_empty():
    assert parse_gateway_from_ipconfig(IPCONFIG_ALL_EMPTY) is None


def test_parse_gateway_ipconfig_fullwidth_colon():
    """兼容使用全角冒号「：」分隔的输出。"""
    text = "   默认网关. . . . . . . . . . . . . ： 192.0.2.1\n"
    assert parse_gateway_from_ipconfig(text) == "192.0.2.1"


def test_parse_gateway_ipconfig_ignores_ipv6_only():
    """IPv6 网关（fe80::…）不应被当作 IPv4 网关。"""
    text = "   IPv6 默认网关 . . . . . . . . . : fe80::1%12\n"
    assert parse_gateway_from_ipconfig(text) is None


@pytest.mark.parametrize("text", ["", None, "Windows IP 配置\n\n"])
def test_parse_gateway_ipconfig_empty(text):
    assert parse_gateway_from_ipconfig(text) is None


# ---------- 辅助函数 ----------
@pytest.mark.parametrize("value,expected", [
    ("192.0.2.1", True),
    ("198.51.100.1", True),
    ("0.0.0.0", False),
    ("On-link", False),
    ("fe80::1", False),
    ("999.1.1.1", False),
    ("", False),
    (None, False),
])
def test_is_valid_ipv4(value, expected):
    assert _is_valid_ipv4(value) is expected


@pytest.mark.parametrize("a,b,expected", [
    ("192.0.2.1", "192.0.2.208", True),
    ("203.0.113.1", "192.0.2.208", False),
])
def test_same_subnet(a, b, expected):
    assert _same_subnet(a, b) is expected


# ---------- 本机 IP 探测（宽松断言：允许无网络环境返回 None）----------
def test_get_local_ip_returns_valid_or_none():
    ip = get_local_ip()
    assert ip is None or re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", ip)
