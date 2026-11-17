"""当前网络快照：标题栏、状态栏、首页共用的真实数据源。

设计原则：
  - 只读，不修改任何系统配置；
  - 原生 API 优先，失败再回退命令行；
  - 结果有 TTL 缓存，避免每次切页都执行 `route print` / `ipconfig`；
  - 采集全部在后台线程执行（见 ui.workers.NetSnapshotWorker）。
"""

import socket
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import List, Optional

from .netinfo import get_default_gateway, get_local_ip
from .wifi_check import WiFiChecker, network_band

RADIO_LABELS = {
    "802.11a": "Wi-Fi 1",
    "802.11b": "Wi-Fi 1",
    "802.11g": "Wi-Fi 3",
    "802.11n": "Wi-Fi 4",
    "802.11ac": "Wi-Fi 5",
    "802.11ax": "Wi-Fi 6",
    "802.11be": "Wi-Fi 7",
}


@dataclass
class Snapshot:
    """一次网络状态快照；缺省值表示“未知”，不要用假值填充。"""

    adapter: str = ""
    kind: str = "unknown"          # wifi / ethernet / none / unknown
    ssid: str = ""
    bssid: str = ""
    band: str = ""                 # 2.4G / 5G / 6G
    channel: Optional[int] = None
    signal_pct: Optional[int] = None
    rx_rate: Optional[float] = None
    tx_rate: Optional[float] = None
    radio: str = ""                # 802.11ax 等原始值
    radio_label: str = ""          # Wi-Fi 6 等用户可读标签
    ipv4: str = ""
    gateway: str = ""
    dns_servers: List[str] = field(default_factory=list)
    online: bool = False
    source: str = ""
    captured_at: float = 0.0
    error: str = ""

    def as_dict(self):
        return asdict(self)

    @property
    def connected(self):
        return self.online or bool(self.ipv4)

    @property
    def summary(self):
        """给标题栏/侧栏用的一句话状态。"""
        if self.kind == "wifi" and self.ssid:
            band = f" · {self.band}" if self.band else ""
            return f"已连接 · {self.ssid}{band}"
        if self.kind == "ethernet" and self.ipv4:
            return "有线连接"
        if self.ipv4:
            return "已连接"
        return "未连接"


_cache_lock = threading.RLock()
_cache_snapshot = None
_cache_at = 0.0


def _band_from_channel(channel, freq=None):
    net = {"channel": channel, "freq": freq}
    band = network_band(net)
    return {"2.4G": "2.4G", "5G": "5G", "6G": "6G"}.get(band, "")


def _radio_label(radio):
    radio = str(radio or "")
    return RADIO_LABELS.get(radio, radio)


def _quick_online(timeout=0.8):
    """TCP 连一下公共 DNS 的 53 端口，判断“能不能上网”。"""
    try:
        sock = socket.create_connection(("223.5.5.5", 53), timeout=timeout)
        sock.close()
        return True
    except OSError:
        return False


def _dns_servers():
    try:
        from .winapi_net import get_dns_servers
        servers = get_dns_servers() or []
        if servers:
            return list(servers)
    except Exception:
        pass
    try:
        from .dns_optimizer import DNSOptimizer
        return list(DNSOptimizer().get_current_dns() or [])
    except Exception:
        return []


def _adapter_name():
    try:
        from .winapi_net import get_dns_by_adapter
        rows = get_dns_by_adapter() or []
        for row in rows:
            if row.get("name"):
                return str(row["name"])
    except Exception:
        pass
    return ""


def collect(ttl=30.0, force=False, timeout=2.0):
    """采集当前网络快照；ttl 秒内复用缓存。

    该函数可能执行系统命令，调用方应放在后台线程。
    """
    global _cache_snapshot, _cache_at
    now = time.monotonic()
    with _cache_lock:
        if (not force and _cache_snapshot is not None
                and now - _cache_at < max(0.0, float(ttl))):
            return _cache_snapshot

    snapshot = Snapshot(captured_at=time.time())
    try:
        snapshot.ipv4 = get_local_ip() or ""
        try:
            snapshot.gateway = get_default_gateway(snapshot.ipv4 or None) or ""
        except Exception:
            snapshot.gateway = ""
        snapshot.dns_servers = _dns_servers()
        snapshot.adapter = _adapter_name()

        wifi = {}
        try:
            wifi = WiFiChecker().get_wifi_info() or {}
        except Exception:
            wifi = {}

        if wifi.get("connected"):
            snapshot.kind = "wifi"
            snapshot.source = str(wifi.get("_source") or "native")
            snapshot.ssid = str(wifi.get("ssid") or "")
            snapshot.bssid = str(wifi.get("bssid") or "")
            channel = wifi.get("channel")
            try:
                snapshot.channel = int(channel) if channel is not None else None
            except (TypeError, ValueError):
                snapshot.channel = None
            snapshot.band = _band_from_channel(
                snapshot.channel, wifi.get("freq"))
            try:
                snapshot.signal_pct = int(wifi.get("signal_strength"))
            except (TypeError, ValueError):
                snapshot.signal_pct = None
            for attr in ("rx_rate", "tx_rate"):
                try:
                    value = wifi.get(attr)
                    setattr(snapshot, attr,
                            float(value) if value is not None else None)
                except (TypeError, ValueError):
                    setattr(snapshot, attr, None)
            snapshot.radio = str(wifi.get("radio_type") or "")
            snapshot.radio_label = _radio_label(snapshot.radio)
        elif snapshot.ipv4:
            snapshot.kind = "ethernet"
            snapshot.source = "netinfo"
        else:
            snapshot.kind = "none"
            snapshot.source = "netinfo"

        snapshot.online = _quick_online(timeout=min(1.5, max(0.2, timeout)))
        if not snapshot.online and snapshot.kind == "none":
            snapshot.error = "未获取到网络连接"
    except Exception as exc:  # noqa: BLE001 - 快照失败不应影响界面
        snapshot.error = str(exc)
        snapshot.kind = snapshot.kind or "unknown"

    with _cache_lock:
        _cache_snapshot = snapshot
        _cache_at = time.monotonic()
    return snapshot


def clear_cache():
    """测试/网络切换时清缓存。"""
    global _cache_snapshot, _cache_at
    with _cache_lock:
        _cache_snapshot = None
        _cache_at = 0.0
