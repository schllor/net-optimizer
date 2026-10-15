"""
局域网设备扫描模块 - 基于 arp -a 解析当前局域网活跃设备（IP/MAC/主机名）。
只读扫描，不做任何路由配置；"限速/禁用"等操作仅定位设备供用户在路由器端处理。
面向新手，接口保持简单：scan_lan_devices() -> [ {ip,mac,name,online,self} ]
"""

import socket
import re

from .cmd_utils import smart_run


def _get_own_ip():
    """通过 UDP 连接方式探测本机主 IP（不真正发包给外部）"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("223.5.5.5", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def _resolve_name(ip):
    """反查主机名，失败返回空串（不报错，避免卡顿）。"""
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return ""


def scan_lan_devices():
    """扫描局域网设备列表。返回 list[dict]：ip / mac / name / online / self"""
    result = smart_run(["arp", "-a"], timeout=6)
    out = result.stdout or ""
    line_re = re.compile(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]{17})")
    own = _get_own_ip()
    seen = set()
    devs = []
    for line in out.splitlines():
        m = line_re.search(line)
        if not m:
            continue
        ip, mac = m.group(1), m.group(2).replace("-", ":")
        if ip in seen or ip in ("224.0.0.0", "255.255.255.255"):
            continue
        seen.add(ip)
        name = _resolve_name(ip) if not ip.startswith("224.") else ""
        devs.append({
            "ip": ip,
            "mac": mac,
            "name": name or "未知设备",
            "online": True,          # arp 表现在存在即视为最近活跃
            "self": ip == own,
        })
    return devs