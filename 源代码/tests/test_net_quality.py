"""测量方法学单元测试：分位数、RFC3550 抖动、稳定窗口吞吐、HTTP TTFB。

全部离线运行，网络连接用 Fake 对象替换。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.net_quality as nq


# ---------- ping 解析 / 统计 ----------
def test_parse_ping_times_mixed():
    text = (
        "来自 10.0.0.1 的回复: 字节=32 时间=12ms TTL=64\n"
        "Reply from 8.8.8.8: bytes=32 time<1ms TTL=117\n"
    )
    assert nq.parse_ping_times(text) == [12.0, 0.5]
    assert nq.parse_ping_times(None) == []


def test_summarize_percentiles_and_loss():
    stats = nq.summarize([10, 20, 30, 40], sent=5)
    assert stats.count == 4
    assert stats.mean == 25.0
    assert stats.p50 == 25.0
    assert stats.p95 == 38.5
    assert stats.min == 10.0
    assert stats.max == 40.0
    assert stats.loss == 20.0


def test_summarize_jitter_uses_rfc3550_smoothing():
    stats = nq.summarize([10, 20], sent=2)
    # 一次 |20-10| 的差值按 J += (D - J)/16 平滑
    assert stats.jitter == 0.6


def test_summarize_empty_marks_full_loss():
    stats = nq.summarize([], sent=5)
    assert stats.count == 0
    assert stats.loss == 100.0
    assert nq.summarize([]).loss == 0.0


# ---------- HTTP TTFB ----------
class _FakeResponse:
    status = 200
    will_close = False

    def __init__(self):
        self._calls = 0

    def read(self, n=1):
        self._calls += 1
        return b"x" if self._calls == 1 else b""

    def getresponse(self):
        return self


class _FakeConn:
    def __init__(self, timeout=None, context=None):
        self.requests = 0

    def connect(self):
        pass

    def request(self, method, path, headers=None):
        self.requests += 1

    def getresponse(self):
        return _FakeResponse()

    def close(self):
        pass


def test_http_latency_collects_samples(monkeypatch):
    monkeypatch.setattr(nq, "_http_connection", lambda parsed, timeout: _FakeConn())
    result = nq.http_latency("https://example.com/", samples=3)
    assert result["success"] is True
    assert len(result["samples"]) == 3
    assert result["stats"].count == 3


def test_http_latency_failure_is_graceful(monkeypatch):
    def broken(parsed, timeout):
        raise OSError("no route")

    monkeypatch.setattr(nq, "_http_connection", broken)
    result = nq.http_latency("https://example.com/", samples=2)
    assert result["success"] is False
    assert result["stats"].count == 0


# ---------- 稳定窗口吞吐 ----------
def test_stable_throughput_steady_stream():
    # 每 0.25s 收到 100KB，等价 3.2Mbps
    samples = [(i * 0.25, 100 * 1024, 1) for i in range(1, 33)]
    result = nq.stable_throughput(samples, window=3.0, ramp=0.6)
    assert result["success"] is True
    assert abs(result["mbps"] - 3.2) < 0.2
    assert result["window"] == 3.0


def test_stable_throughput_skips_ramp_and_picks_fast_window():
    samples = []
    for i in range(1, 33):
        rate = 50 * 1024 if i <= 8 else 200 * 1024
        samples.append((i * 0.25, rate, 1))
    result = nq.stable_throughput(samples, window=1.0, ramp=2.0)
    # 200KB / 0.25s = 6.4Mbps，应选中快窗口而不是把慢启动算进去
    assert abs(result["mbps"] - 6.4) < 0.3


def test_stable_throughput_empty():
    assert nq.stable_throughput([])["success"] is False


def test_throughput_meter_tracks_total_and_peak():
    meter = nq.ThroughputMeter()
    for i in range(1, 9):
        meter.add(i * 0.25, 64 * 1024, stream_id=1)
    assert meter.total_bytes == 8 * 64 * 1024
    assert meter.peak_mbps > 0
    result = meter.result(window=1.0, ramp=0.0)
    assert result["success"] is True
    assert result["total_bytes"] == meter.total_bytes
