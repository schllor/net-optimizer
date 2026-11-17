"""实时流量接口选择逻辑的离线测试（不读取真实网卡）。"""

import os
import sys
from core.traffic_monitor import select_interfaces


def _row(if_type, sent, recv, hardware=True, oper=1, tunnel=0, alias="x"):
    return {"alias": alias, "if_type": if_type, "tunnel_type": tunnel,
            "oper_status": oper, "hardware": hardware, "sent": sent, "recv": recv}


def test_sums_active_physical_interfaces_only():
    rows = [
        _row(6, 100, 200, alias="eth"),
        _row(71, 300, 400, alias="wifi"),
        _row(24, 999, 999, hardware=False, alias="loopback"),   # 回环
        _row(6, 500, 500, oper=2, alias="down"),                # 未启用
        _row(6, 700, 700, hardware=False, alias="filter"),      # 过滤驱动
    ]
    assert select_interfaces(rows) == (400, 600)


def test_vpn_tunnel_replaces_physical_when_enabled():
    rows = [
        _row(6, 100, 100, alias="eth"),
        _row(131, 40, 160, tunnel=1, alias="vpn"),
    ]
    # 默认不含 VPN：只统计物理网卡，避免隧道重复计数
    assert select_interfaces(rows) == (100, 100)
    # 开启含 VPN：优先隧道，避免物理 + 隧道重复
    assert select_interfaces(rows, include_vpn=True) == (40, 160)


def test_vpn_without_active_tunnel_falls_back_to_physical():
    rows = [
        _row(6, 100, 100, alias="eth"),
        _row(131, 40, 160, tunnel=1, oper=2, alias="vpn-down"),
    ]
    assert select_interfaces(rows, include_vpn=True) == (100, 100)


def test_empty_table():
    assert select_interfaces([]) == (0, 0)
