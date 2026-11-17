"""DNS 方法学测试：冷热采样、P50/P95、DoH 校验、备份与回滚。

不访问真实网络：查询、命令执行与 HTTPS 全部替换为 Fake。
"""

import http.client
import os
import struct
import sys
import core.dns_optimizer as dns_mod
from core.dns_optimizer import DNSOptimizer


class _FakeSock:
    def __init__(self, *args, **kwargs):
        self.sent = None

    def settimeout(self, timeout):
        pass

    def sendto(self, data, addr):
        self.sent = data

    def recvfrom(self, size):
        rcode_header = struct.pack(">HHHHH", 0x8183, 1, 0, 0, 0)  # NXDOMAIN
        return self.sent[:2] + rcode_header, ("127.0.0.1", 53)

    def close(self):
        pass


def test_query_once_accepts_nxdomain(monkeypatch):
    monkeypatch.setattr(dns_mod.socket, "socket", _FakeSock)
    opt = DNSOptimizer()
    assert opt._query_once("1.1.1.1", "nonexistent.baidu.com") is not None


def test_query_stats_hot_and_cold(monkeypatch):
    opt = DNSOptimizer()
    values = iter([10.0, 20.0, 12.0, None])
    monkeypatch.setattr(
        opt, "_query_once",
        lambda ip, domain, timeout=None: next(values))

    result = opt.query_stats("1.1.1.1", rounds=2)
    assert result["samples"] == 3
    assert result["timeout_rate"] == 25.0
    assert result["p50"] == 12.0
    assert result["p95"] == 19.2
    assert result["hot_ms"] == 11.0
    assert result["cold_ms"] == 20.0
    assert result["success"] is True
    assert result["latency"] == result["p50"]


def test_build_dns_commands_uses_ipv4_context():
    commands = DNSOptimizer.build_dns_commands("以太网", "1.1.1.1", "8.8.8.8")
    assert commands == [
        ["netsh", "interface", "ipv4", "set", "dnsservers",
         'name="以太网"', "static", "1.1.1.1", "primary"],
        ["netsh", "interface", "ipv4", "add", "dnsservers",
         'name="以太网"', "8.8.8.8", "index=2"],
    ]
    assert len(DNSOptimizer.build_dns_commands("WLAN", "1.1.1.1")) == 1


def test_set_dns_requires_admin(monkeypatch):
    opt = DNSOptimizer()
    monkeypatch.setattr(opt, "is_windows", True)
    monkeypatch.setattr(dns_mod, "require_admin", lambda action="": (False, "需要管理员权限"))
    ok, message = opt.set_dns("1.1.1.1")
    assert ok is False
    assert "管理员" in message


def test_set_dns_backs_up_and_applies(monkeypatch):
    opt = DNSOptimizer()
    monkeypatch.setattr(opt, "is_windows", True)
    monkeypatch.setattr(dns_mod, "require_admin", lambda action="": (True, ""))
    monkeypatch.setattr(opt, "_active_interfaces", lambda: ["以太网", "WLAN"])
    backup = {"adapters": [{"name": "以太网", "dns": ["9.9.9.9"]}]}
    monkeypatch.setattr(opt, "_backup_current", lambda interfaces: backup)
    applied = []

    def fake_apply(alias, servers):
        applied.append((alias, list(servers)))
        return True

    monkeypatch.setattr(opt, "_apply_dns", fake_apply)
    ok, message = opt.set_dns("1.1.1.1", "8.8.8.8")
    assert ok is True
    assert "2 个网络接口" in message
    assert applied == [
        ("以太网", ["1.1.1.1", "8.8.8.8"]),
        ("WLAN", ["1.1.1.1", "8.8.8.8"]),
    ]


def test_set_dns_rolls_back_on_total_failure(monkeypatch):
    opt = DNSOptimizer()
    monkeypatch.setattr(opt, "is_windows", True)
    monkeypatch.setattr(dns_mod, "require_admin", lambda action="": (True, ""))
    monkeypatch.setattr(opt, "_active_interfaces", lambda: ["以太网"])
    backup = {"adapters": [{"name": "以太网", "dns": ["9.9.9.9"]}]}
    monkeypatch.setattr(opt, "_backup_current", lambda interfaces: backup)
    monkeypatch.setattr(opt, "_apply_dns", lambda alias, servers: False)
    rolled = []
    monkeypatch.setattr(opt, "_rollback",
                        lambda data, interfaces: rolled.append((data, interfaces)))

    ok, message = opt.set_dns("1.1.1.1")
    assert ok is False
    assert "失败" in message
    assert rolled and rolled[0][0] is backup


def test_restore_dhcp(monkeypatch):
    opt = DNSOptimizer()
    monkeypatch.setattr(opt, "is_windows", True)
    monkeypatch.setattr(dns_mod, "require_admin", lambda action="": (True, ""))
    monkeypatch.setattr(opt, "_active_interfaces", lambda: ["以太网"])
    monkeypatch.setattr(opt, "_apply_dhcp", lambda alias: True)
    ok, message = opt.restore_dhcp()
    assert ok is True
    assert "自动获取" in message


def test_verify_doh_uses_wire_format_post(monkeypatch):
    captured = {}

    class FakeResponse:
        status = 200

        def __init__(self, body):
            self.body = body

        def read(self, size):
            return self.body[:2] + struct.pack(">HHHHH", 0x8180, 1, 0, 0, 0)

    class FakeConn:
        def __init__(self, netloc, timeout=None):
            self.body = None

        def request(self, method, path, body=None, headers=None):
            captured["method"] = method
            captured["headers"] = headers
            self.body = body

        def getresponse(self):
            return FakeResponse(self.body)

        def close(self):
            pass

    monkeypatch.setattr(http.client, "HTTPSConnection", FakeConn)
    opt = DNSOptimizer()
    result = opt.verify_doh("https://dns.alidns.com/dns-query")
    assert result["ok"] is True
    assert captured["method"] == "POST"
    assert captured["headers"]["Content-Type"] == "application/dns-message"


def test_test_all_dns_sorts_by_p95_and_skips_doh_for_fakes(monkeypatch):
    opt = DNSOptimizer()
    latencies = {"223.5.5.5": 30.0, "223.6.6.6": 10.0}

    def fake_speed(ip, test_domain="www.baidu.com"):
        p95 = latencies.get(ip, 20.0)
        return {"ip": ip, "latency": p95, "p95": p95, "success": True}

    monkeypatch.setattr(opt, "test_dns_speed", fake_speed)
    doh_calls = []
    monkeypatch.setattr(opt, "_mark_doh", doh_calls.append)
    results = opt.test_all_dns()
    # 简化结果没有 samples 字段，不进入 DoH 校验（避免离线测试发起网络请求）
    assert doh_calls == [[]]
    assert [r["p95"] for r in results[:2]] == [10.0, 20.0]
    assert results[0]["ip"] == "223.6.6.6"


def test_get_best_dns_marks_reachable_but_unresolvable():
    opt = DNSOptimizer()
    results = [
        {"ip": "1.1.1.1", "success": False, "reachable": True, "latency": 999},
        {"ip": "8.8.8.8", "success": False, "reachable": False, "latency": 999},
    ]
    best, advice = opt.get_best_dns(results)
    assert best is None
    assert "无法正常解析" in advice
