"""测速流程测试：稳定窗口、取消、完整流程与 HTTP 延迟。

真实网络与线程池被替换为可控的 Fake，运行时间控制在 2 秒内。
"""

import os
import sys
import time
import core.speed_test as st_mod
from core.net_quality import summarize
from core.speed_test import SpeedTest


def _fake_stream(self, stream_id, deadline, meter, cancel):
    while time.time() < deadline and not cancel.is_set():
        meter.add(time.time(), 100 * 1024, stream_id)
        time.sleep(0.05)


def test_download_speed_uses_stable_window(monkeypatch):
    monkeypatch.setattr(SpeedTest, "_download_stream", _fake_stream)
    tester = SpeedTest()
    live = []
    result = tester.download_speed_test(
        live_callback=live.append, duration=1.2)

    assert result["success"] is True
    assert result["method"] == "stable-window"
    assert result["speed_mbps"] > 5
    assert result["streams"] >= 1
    assert result["window_s"] > 0
    assert result["downloaded_kb"] > 0
    assert live and max(live) > 0


def test_download_cancel_returns_early(monkeypatch):
    monkeypatch.setattr(SpeedTest, "_download_stream", _fake_stream)
    tester = SpeedTest()
    tester.cancel()
    result = tester.download_speed_test(duration=1.0)
    assert result == {"success": False, "cancelled": True}


def test_upload_speed_uses_meter(monkeypatch):
    def fake_upload(self, stream_id, deadline, meter, cancel):
        while time.time() < deadline and not cancel.is_set():
            meter.add(time.time(), 64 * 1024, stream_id)
            time.sleep(0.05)
        return 0

    monkeypatch.setattr(SpeedTest, "_upload_stream", fake_upload)
    tester = SpeedTest()
    result = tester.upload_speed_test(duration=1.0)
    assert result["success"] is True
    assert result["speed_mbps"] > 1
    assert result["connections"] >= 1


def test_latency_prefers_http_ttfb(monkeypatch):
    stats = summarize([12, 14, 13, 18, 15, 16], sent=6)

    def fake_http(url, samples=6, timeout=2.0, cancel=None):
        return {"url": url, "samples": [], "stats": stats, "success": True}

    monkeypatch.setattr(st_mod, "http_latency", fake_http)
    result = SpeedTest().latency_test()
    assert result["success"] is True
    assert result["method"] == "http"
    assert result["p50"] == stats.p50
    assert result["p95"] == stats.p95
    assert result["jitter_ms"] == stats.jitter


def test_run_full_test_keeps_legacy_keys(monkeypatch):
    tester = SpeedTest()

    def fake_latency():
        return {
            "host": "www.baidu.com", "method": "http", "avg_latency": 20.0,
            "p50": 18.0, "p95": 30.0, "jitter_ms": 2.0, "loss_rate": 0.0,
            "min_latency": 15.0, "max_latency": 35.0, "samples": 6,
            "success": True,
        }

    def fake_upload(progress_callback=None, live_callback=None,
                    duration=None, cancel=None):
        if progress_callback:
            progress_callback(100)
        return {"success": True, "speed_mbps": 10.0}

    def fake_download(progress_callback=None, live_callback=None,
                      duration=None, cancel=None):
        if progress_callback:
            progress_callback(100)
        if live_callback:
            live_callback(20.0)
        return {"success": True, "speed_mbps": 50.0}

    monkeypatch.setattr(tester, "latency_test", fake_latency)
    monkeypatch.setattr(tester, "upload_speed_test", fake_upload)
    monkeypatch.setattr(tester, "download_speed_test", fake_download)

    progress, status = [], []
    results = tester.run_full_test(progress.append, status.append)

    assert {"ping", "latency_stats", "upload", "download"} <= set(results)
    assert results["latency_stats"]["p95"] == 30.0
    assert progress[-1] == 100
    assert any("延迟" in text for text in status)


def test_run_full_test_stops_after_cancel(monkeypatch):
    tester = SpeedTest()

    def cancel_after_latency():
        tester.cancel()
        return {"success": True, "avg_latency": 10.0, "p50": 10.0,
                "p95": 12.0, "jitter_ms": 1.0, "loss_rate": 0.0,
                "samples": 5, "host": "x", "method": "http"}

    monkeypatch.setattr(tester, "latency_test", cancel_after_latency)
    results = tester.run_full_test()
    assert results.get("cancelled") is True
    assert "upload" not in results
