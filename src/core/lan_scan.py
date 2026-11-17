"""
局域网设备扫描模块 - 基于 arp -a 解析当前局域网活跃设备（IP/MAC/主机名）。
只读扫描，不做任何路由配置；"限速/封禁"等操作仅定位设备供用户在路由器端处理。
面向新手，接口保持简单：scan_lan_devices() -> [ {ip,mac,name,online,self} ]

降噪说明：`arp -a` 会把组播与广播地址一并列出（实测本机 21 条里 18 条是噪音，
真实设备只有 3 台），这些条目并不是网络设备，需要过滤，详见 is_noise_entry()。
"""

import ipaddress
import re
import socket
import threading
import time

from .cmd_utils import smart_run
from .netinfo import get_local_ip

# 广播 MAC（ff:ff:ff:ff:ff:ff）与 IPv4 组播 MAC 前缀（01:00:5e，见 RFC 1112）
_BROADCAST_MAC = "ff:ff:ff:ff:ff:ff"
_MULTICAST_MAC_PREFIX = "01:00:5e"

_LINE_RE = re.compile(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]{17})")

# 主机名反查参数：并发 8 路、整体最多等待 2.5 秒
_RESOLVE_WORKERS = 8
_RESOLVE_TIMEOUT = 2.5


def is_noise_entry(ip, mac):
    """判断 arp 条目是否为「非设备」噪音（组播 / 广播）。

    判据与子网掩码、系统语言均无关：
      1) MAC 为主：广播地址的 MAC 恒为 ff:ff:ff:ff:ff:ff；IPv4 组播地址的 MAC
         恒以 01:00:5e 开头。这一条能覆盖「各网段的广播地址」（如 192.0.2.255、
         198.51.100.255），而这类地址无法用固定 IP 字面量穷举。
      2) IP 兜底：组播段(224-239)、未指定(0.x)、回环(127.x)、保留(240-255)。
    """
    normalized = (mac or "").lower().replace("-", ":")
    if normalized == _BROADCAST_MAC or normalized.startswith(_MULTICAST_MAC_PREFIX):
        return True
    try:
        addr = ipaddress.IPv4Address(ip)
    except ValueError:
        return True  # 非 IPv4 行（如 IPv6）一律视为噪音
    return (addr.is_multicast or addr.is_unspecified
            or addr.is_loopback or addr.is_reserved)


def _resolve_name(ip):
    """反查主机名，失败返回空串（不报错，避免卡顿）。"""
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return ""


def resolve_hostnames(ips, timeout=_RESOLVE_TIMEOUT, workers=_RESOLVE_WORKERS,
                      cancel=None):
    """并发反查多个 IP 的主机名，整体最多等待 timeout 秒。

    原实现逐个 `gethostbyaddr`，每台设备都可能触发系统解析超时（弱网下 3~5 秒），
    设备一多扫描就像“卡死”。改为守护线程并发反查并设总截止时间：
    超时未返回的设备直接显示「未知设备」，不阻塞界面与扫描结果。
    """
    unique = []
    for ip in ips or []:
        if ip and ip not in unique:
            unique.append(ip)
    if not unique:
        return {}

    names = {}
    lock = threading.Lock()
    cursor = {"index": 0}
    cursor_lock = threading.Lock()
    stopped = threading.Event()

    def worker():
        while not stopped.is_set():
            with cursor_lock:
                idx = cursor["index"]
                if idx >= len(unique):
                    return
                cursor["index"] = idx + 1
            ip = unique[idx]
            name = _resolve_name(ip)
            if name:
                with lock:
                    names[ip] = name

    threads = [
        threading.Thread(target=worker, daemon=True)
        for _ in range(min(workers, len(unique)))
    ]
    for t in threads:
        t.start()

    deadline = time.monotonic() + max(0.1, timeout)
    for t in threads:
        while t.is_alive():
            if cancel is not None and cancel.is_set():
                stopped.set()
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                stopped.set()
                break
            t.join(min(0.05, remaining))
        if stopped.is_set():
            break

    with lock:
        return dict(names)


def parse_arp_devices(text, local_ip=None, resolve_names=True,
                      resolve_timeout=_RESOLVE_TIMEOUT, cancel=None):
    """纯解析：从 `arp -a` 输出提取真实设备列表（已过滤组播/广播噪音）。

    返回 list[dict]：ip / mac / name / online / self
    同一 IP 在多张网卡上重复出现时只保留一条。
    resolve_names=False 可跳过主机名反查，便于离线单测。
    """
    seen = set()
    devices = []
    for line in (text or "").splitlines():
        match = _LINE_RE.search(line)
        if not match:
            continue
        ip = match.group(1)
        mac = match.group(2).replace("-", ":")
        if ip in seen or is_noise_entry(ip, mac):
            continue
        seen.add(ip)
        devices.append({
            "ip": ip,
            "mac": mac,
            "name": "未知设备",
            "online": True,          # arp 表现在存在即视为最近活跃
            "self": ip == local_ip,
        })

    if resolve_names and devices:
        names = resolve_hostnames(
            [d["ip"] for d in devices], timeout=resolve_timeout, cancel=cancel)
        for device in devices:
            device["name"] = names.get(device["ip"]) or "未知设备"
    return devices


def parse_native_neighbors(rows, local_ip=None):
    """把 GetIpNetTable 结果转成设备列表（复用同一套噪音过滤）。"""
    seen = set()
    devices = []
    for row in rows or []:
        ip = row.get("ip") or ""
        mac = (row.get("mac") or "").lower()
        if not ip or ip in seen or is_noise_entry(ip, mac):
            continue
        seen.add(ip)
        devices.append({
            "ip": ip,
            "mac": mac,
            "name": "未知设备",
            "online": True,          # 原生路径会在扫描时用 SendARP 复核
            "self": ip == local_ip,
        })
    return devices


def _same_subnet(ip, local_ip):
    try:
        return ipaddress.IPv4Address(ip) in ipaddress.IPv4Network(
            f"{local_ip}/24", strict=False)
    except ValueError:
        return False


def scan_lan_devices(use_native=True, cancel=None):
    """扫描局域网设备列表。返回 list[dict]：ip / mac / name / online / self

    优先 GetIpNetTable + SendARP（语言无关、online 由 ARP 应答确认）；
    原生 API 不可用时回退 `arp -a` 文本解析。
    """
    local_ip = get_local_ip()
    devices = None
    if use_native:
        try:
            from .winapi_arp import get_neighbors
            rows = get_neighbors()
        except Exception:
            rows = None
        if rows is not None:
            devices = parse_native_neighbors(rows, local_ip)

    if devices is None:
        result = smart_run(["arp", "-a"], timeout=6)
        return parse_arp_devices(result.stdout or "", local_ip, cancel=cancel)

    if devices:
        # 主机名反查与 ARP 探测互不依赖，并行执行可把扫描耗时从 ~4.5s 压到 ~2.5s
        names_holder = {}

        def _resolve():
            names_holder["names"] = resolve_hostnames(
                [d["ip"] for d in devices], cancel=cancel)

        resolver = threading.Thread(target=_resolve, daemon=True)
        resolver.start()

        same_subnet = [d["ip"] for d in devices
                       if not d["self"] and _same_subnet(d["ip"], local_ip)]
        if same_subnet and (cancel is None or not cancel.is_set()):
            from .winapi_arp import probe_online
            online = probe_online(same_subnet, timeout=2.0, cancel=cancel)
            for device in devices:
                if device["ip"] in online:
                    device["online"] = True
                elif device["ip"] in same_subnet:
                    device["online"] = False   # 同网段但 ARP 无应答

        resolver.join(_RESOLVE_TIMEOUT + 0.1)
        names = names_holder.get("names", {})
        for device in devices:
            device["name"] = names.get(device["ip"]) or "未知设备"
    return devices
