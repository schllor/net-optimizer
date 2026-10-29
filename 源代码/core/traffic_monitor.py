"""
实时流量监控模块 - 采集所有网卡累计字节，计算实时上行/下行速率。
架构（借鉴 NetSpeedTray）：采集与 UI 刷新解耦，每秒调用一次几乎无 CPU 开销；
psutil 缺失或原生调用失败时自动降级：(None, None)，上层优雅显示 "--"。

性能说明：psutil.net_io_counters() 在 Windows 上实测约 8ms/次（要枚举全部网卡并逐条建对象），
每秒在 GUI 线程跑一次会挤压动画帧；改用 IP Helper API 的 GetIfTable2 实测约 0.8ms/次。
"""

import sys
import time

try:
    import psutil as _psutil
    _HAS_PSUTIL = True
except Exception:
    _psutil = None
    _HAS_PSUTIL = False


def _read_psutil():
    c = _psutil.net_io_counters()
    return c.bytes_sent, c.bytes_recv


IF_TYPE_PPP = 23
IF_TYPE_SOFTWARE_LOOPBACK = 24
IF_TYPE_TUNNEL = 131
OPER_STATUS_UP = 1


def select_interfaces(rows, include_vpn=False):
    """从网卡行中选出应计入实时流量的接口并求和。

    rows: [{alias, if_type, tunnel_type, oper_status, hardware, sent, recv}]
    VPN 场景下隧道接口与物理接口会重复计数，因此存在活动隧道时只汇总隧道；
    否则汇总已启用、非回环的物理网卡。
    """
    active = [r for r in rows if int(r.get("oper_status", 0)) == OPER_STATUS_UP]

    if include_vpn:
        tunnels = [r for r in active
                   if int(r.get("if_type", 0)) in (IF_TYPE_PPP, IF_TYPE_TUNNEL)
                   or int(r.get("tunnel_type", 0)) != 0]
        if tunnels:
            return (sum(int(r.get("sent", 0)) for r in tunnels),
                    sum(int(r.get("recv", 0)) for r in tunnels))

    physical = [r for r in active
                if r.get("hardware")
                and int(r.get("if_type", 0)) not in (
                    IF_TYPE_PPP, IF_TYPE_SOFTWARE_LOOPBACK, IF_TYPE_TUNNEL)
                and int(r.get("tunnel_type", 0)) == 0]
    return (sum(int(r.get("sent", 0)) for r in physical),
            sum(int(r.get("recv", 0)) for r in physical))


def _build_win_reader(include_vpn=False):
    """基于 GetIfTable2 的采样函数：只统计物理网卡，避免过滤驱动重复上报计数。"""
    import ctypes
    from ctypes import wintypes

    class _MibIfRow2(ctypes.Structure):
        _fields_ = [
            ("InterfaceLuid", ctypes.c_ulonglong),
            ("InterfaceIndex", wintypes.DWORD),
            ("InterfaceGuid", ctypes.c_ubyte * 16),
            ("Alias", wintypes.WCHAR * 257),
            ("Description", wintypes.WCHAR * 257),
            ("PhysicalAddressLength", wintypes.DWORD),
            ("PhysicalAddress", ctypes.c_ubyte * 32),
            ("PermanentPhysicalAddress", ctypes.c_ubyte * 32),
            ("Mtu", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TunnelType", wintypes.DWORD),
            ("MediaType", wintypes.DWORD),
            ("PhysicalMediumType", wintypes.DWORD),
            ("AccessType", wintypes.DWORD),
            ("DirectionType", wintypes.DWORD),
            ("InterfaceAndOperStatusFlags", ctypes.c_ubyte),
            ("OperStatus", wintypes.DWORD),
            ("AdminStatus", wintypes.DWORD),
            ("MediaConnectState", wintypes.DWORD),
            ("NetworkGuid", ctypes.c_ubyte * 16),
            ("ConnectionType", wintypes.DWORD),
            ("TransmitLinkSpeed", ctypes.c_ulonglong),
            ("ReceiveLinkSpeed", ctypes.c_ulonglong),
            ("InOctets", ctypes.c_ulonglong),
            ("InUcastPkts", ctypes.c_ulonglong),
            ("InNUcastPkts", ctypes.c_ulonglong),
            ("InDiscards", ctypes.c_ulonglong),
            ("InErrors", ctypes.c_ulonglong),
            ("InUnknownProtos", ctypes.c_ulonglong),
            ("InUcastOctets", ctypes.c_ulonglong),
            ("InMulticastOctets", ctypes.c_ulonglong),
            ("InBroadcastOctets", ctypes.c_ulonglong),
            ("OutOctets", ctypes.c_ulonglong),
            ("OutUcastPkts", ctypes.c_ulonglong),
            ("OutNUcastPkts", ctypes.c_ulonglong),
            ("OutDiscards", ctypes.c_ulonglong),
            ("OutErrors", ctypes.c_ulonglong),
            ("OutUcastOctets", ctypes.c_ulonglong),
            ("OutMulticastOctets", ctypes.c_ulonglong),
            ("OutBroadcastOctets", ctypes.c_ulonglong),
            ("OutQLen", ctypes.c_ulonglong),
        ]

    class _MibIfTable2(ctypes.Structure):
        _fields_ = [("NumEntries", ctypes.c_ulong), ("Table", _MibIfRow2 * 1)]

    iphlpapi = ctypes.WinDLL("iphlpapi")

    def read():
        table = ctypes.POINTER(_MibIfTable2)()
        if iphlpapi.GetIfTable2(ctypes.byref(table)) != 0:
            return None
        try:
            rows_ptr = ctypes.cast(
                ctypes.byref(table.contents.Table[0]),
                ctypes.POINTER(_MibIfRow2))
            rows = []
            for i in range(table.contents.NumEntries):
                row = rows_ptr[i]
                rows.append({
                    "alias": row.Alias,
                    "if_type": int(row.Type),
                    "tunnel_type": int(row.TunnelType),
                    "oper_status": int(row.OperStatus),
                    "hardware": bool(row.InterfaceAndOperStatusFlags & 1),
                    "sent": int(row.OutOctets),
                    "recv": int(row.InOctets),
                })
            return select_interfaces(rows, include_vpn)
        finally:
            iphlpapi.FreeMibTable(table)

    return read


if sys.platform == "win32":
    try:
        _READER_FACTORY = _build_win_reader
    except Exception:
        _READER_FACTORY = None
else:
    _READER_FACTORY = None

_READER = (_READER_FACTORY(False) if _READER_FACTORY
           else (_read_psutil if _HAS_PSUTIL else None))


class TrafficMonitor:
    """实时网速采样器：每次 sample() 返回 (上行bytes/s, 下行bytes/s)"""

    def __init__(self, reader=None, include_vpn=False):
        if reader is not None:
            self._reader = reader
        elif include_vpn and _READER_FACTORY is not None:
            self._reader = _READER_FACTORY(True)
        else:
            self._reader = _READER
        self.enabled = self._reader is not None
        self._prev_bytes = None   # (bytes_sent, bytes_recv)
        self._prev_time = None

    def sample(self):
        """返回 (upload_bps, download_bps)；首次调用或异常返回 (None, None)"""
        if not self.enabled:
            return None, None
        try:
            now = time.monotonic()   # 单调时钟：不受系统校时/夏令时影响
            cur = self._reader()     # 全部物理网卡累计
            if cur is None:
                return None, None
            if self._prev_bytes is None:
                self._prev_bytes = cur
                self._prev_time = now
                return None, None
            dt = now - self._prev_time
            # 网卡重置/驱动重载时计数器会回退，按 0 处理而不是产生负速度
            delta_up = max(0, cur[0] - self._prev_bytes[0])
            delta_dn = max(0, cur[1] - self._prev_bytes[1])
            up = delta_up / dt if dt > 0 else 0.0
            dn = delta_dn / dt if dt > 0 else 0.0
            self._prev_bytes = cur
            self._prev_time = now
            return up, dn
        except Exception:
            return None, None
