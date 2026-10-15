"""
实时流量监控模块 - 基于 psutil 采集所有网卡累计字节，计算实时上行/下行速率。
架构（借鉴 NetSpeedTray）：采集与 UI 刷新解耦；采集极轻量，每秒调用一次 net_io_counters 几乎无 CPU 开销。
psutil 未安装时自动降级：(None, None)，上层优雅显示 "--"。
"""

import time

try:
    import psutil as _psutil
    _HAS_PSUTIL = True
except Exception:
    _psutil = None
    _HAS_PSUTIL = False


def available():
    return _HAS_PSUTIL


class TrafficMonitor:
    """实时网速采样器：每次 sample() 返回 (上行bytes/s, 下行bytes/s)"""

    def __init__(self):
        self._prev_bytes = None   # (bytes_sent, bytes_recv)
        self._prev_time = None
        self.enabled = _HAS_PSUTIL

    def sample(self):
        """返回 (upload_bps, download_bps)；首次调用或异常返回 (None, None)"""
        if not self.enabled:
            return None, None
        try:
            now = time.time()
            c = _psutil.net_io_counters()  # 全部网卡累计
            cur = (c.bytes_sent, c.bytes_recv)
            if self._prev_bytes is None:
                self._prev_bytes = cur
                self._prev_time = now
                return None, None
            dt = now - self._prev_time
            up = (cur[0] - self._prev_bytes[0]) / dt if dt > 0 else 0.0
            dn = (cur[1] - self._prev_bytes[1]) / dt if dt > 0 else 0.0
            self._prev_bytes = cur
            self._prev_time = now
            return up, dn
        except Exception:
            return None, None

    def reset(self):
        """重采样基线，避免长时间累计后溢出，或切换网卡"""
        self._prev_bytes = None
        self._prev_time = None