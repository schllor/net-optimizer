"""
优化项回归测试：并发执行、超时保护、取消、内存缓存与输出解析。
全部离线运行，不依赖真实网络与 GUI。
"""

import os
import sys
import time
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.lan_scan as lan_scan
import core.traffic_monitor as traffic_mod
from core.cache import CacheManager
from core.diagnostic import NetworkDiagnostic
from core.dns_optimizer import DNSOptimizer
from core.speed_test import parse_ping_times


# ---------- ping 输出解析 ----------
def test_parse_ping_times_chinese():
    text = (
        "来自 10.0.0.1 的回复: 字节=32 时间=12ms TTL=64\n"
        "来自 10.0.0.1 的回复: 字节=32 时间=13ms TTL=64\n"
    )
    assert parse_ping_times(text) == [12.0, 13.0]


def test_parse_ping_times_english_and_sub_ms():
    text = (
        "Reply from 8.8.8.8: bytes=32 time=25ms TTL=117\n"
        "Reply from 8.8.8.8: bytes=32 time<1ms TTL=117\n"
        "Minimum = 0ms, Maximum = 25ms, Average = 12ms\n"
    )
    # <1ms 按 0.5ms 计；汇总行不应被误认为样本
    assert parse_ping_times(text) == [25.0, 0.5]


def test_parse_ping_times_empty():
    assert parse_ping_times("") == []
    assert parse_ping_times(None) == []


# ---------- 诊断并发 ----------
def test_diagnostic_runs_checks_concurrently(monkeypatch):
    diag = NetworkDiagnostic()

    def slow_ok():
        time.sleep(0.2)
        return "ok", "正常"

    check_names = [
        "check_network_adapter", "check_ip_address", "check_gateway",
        "check_dns", "check_internet", "check_multi_latency", "check_proxy",
    ]
    for name in check_names:
        monkeypatch.setattr(diag, name, slow_ok)

    started = time.perf_counter()
    results = diag.run_all_tests()
    elapsed = time.perf_counter() - started

    # 串行需要 1.4s 以上，并发应接近单项耗时
    assert elapsed < 0.9
    assert [r["name"] for r in results] == [
        "网卡状态", "IP地址", "网关连通性", "DNS解析",
        "互联网连通性", "多站点延迟", "代理设置",
    ]
    assert all(r["status"] == "ok" for r in results)


def test_diagnostic_collects_progress(monkeypatch):
    diag = NetworkDiagnostic()

    def fast_ok():
        return "ok", "正常"

    for name in ("check_network_adapter", "check_ip_address", "check_gateway",
                 "check_dns", "check_internet", "check_multi_latency", "check_proxy"):
        monkeypatch.setattr(diag, name, fast_ok)

    progress, items = [], []
    diag.run_all_tests(
        progress_callback=lambda p, n: progress.append((p, n)),
        item_callback=items.append,
    )
    assert len(progress) == 7 and progress[-1][0] == 100
    assert len(items) == 7


# ---------- DNS 并发测速 ----------
def test_dns_test_all_is_concurrent(monkeypatch):
    optimizer = DNSOptimizer()

    def fake_speed(ip, test_domain="www.baidu.com"):
        time.sleep(0.1)
        # 让不同 IP 得到不同延迟，验证排序
        latency = 5.0 + int(ip.split(".")[-1]) % 20
        return {"ip": ip, "latency": latency, "success": True}

    monkeypatch.setattr(optimizer, "test_dns_speed", fake_speed)

    started = time.perf_counter()
    results = optimizer.test_all_dns()
    elapsed = time.perf_counter() - started

    assert elapsed < 0.8                       # 串行至少 1.0s
    assert len(results) == len(DNSOptimizer.POPULAR_DNS)
    latencies = [r["latency"] for r in results]
    assert latencies == sorted(latencies)
    assert {"name", "region", "ip", "latency", "success"} <= set(results[0])


# ---------- 局域网主机名并发反查 ----------
def test_resolve_hostnames_concurrent(monkeypatch):
    def slow_name(ip):
        time.sleep(0.4)
        return "host-" + ip

    monkeypatch.setattr(lan_scan, "_resolve_name", slow_name)
    ips = ["10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4"]

    started = time.perf_counter()
    names = lan_scan.resolve_hostnames(ips, timeout=1.0, workers=4)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.9                       # 串行需要 1.6s
    assert len(names) == 4
    assert names["10.0.0.1"] == "host-10.0.0.1"


def test_resolve_hostnames_respects_deadline(monkeypatch):
    monkeypatch.setattr(lan_scan, "_resolve_name", lambda ip: time.sleep(0.5) or "late")

    started = time.perf_counter()
    names = lan_scan.resolve_hostnames(["10.0.0.1", "10.0.0.2"], timeout=0.1, workers=2)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.4
    assert names == {}                         # 超时未返回的设备直接回落为未知


# ---------- 缓存：别名常驻内存 + 持久化 ----------
def test_cache_alias_is_cached_in_memory(tmp_path, monkeypatch):
    import core.cache as cache_mod
    monkeypatch.setattr(cache_mod, "get_cache_dir", lambda: str(tmp_path))

    cache = CacheManager()
    cache.save_device_alias("AA:BB:CC:DD:EE:FF", "客厅电视")
    assert cache.get_device_alias("aa:bb:cc:dd:ee:ff") == "客厅电视"

    # 删除磁盘文件后仍能命中内存缓存（证明不会每次刷新都读盘）
    os.remove(tmp_path / "device_aliases.json")
    assert cache.get_device_alias("AA:BB:CC:DD:EE:FF") == "客厅电视"

    # 新实例从磁盘读取（先恢复文件）
    cache.save_device_alias("AA:BB:CC:DD:EE:FF", "客厅电视")
    fresh = CacheManager()
    assert fresh.get_device_alias("aa:bb:cc:dd:ee:ff") == "客厅电视"
    fresh.save_device_alias("AA:BB:CC:DD:EE:FF", "")
    assert fresh.get_all_device_aliases() == {}


# ---------- 流量采样：计数器回退保护 ----------
def test_traffic_counter_reset_is_clamped():
    readings = [
        (10_000, 20_000),
        (100, 200),   # 网卡重置，计数回退
    ]
    monitor = traffic_mod.TrafficMonitor(reader=lambda: readings.pop(0))

    assert monitor.sample() == (None, None)     # 首次采样只建基线
    up, down = monitor.sample()
    assert up == 0.0 and down == 0.0
