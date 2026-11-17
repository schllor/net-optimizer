"""结构化诊断结果与建议。"""

from core.diagnostic import NetworkDiagnostic


def _fake_checks(diag):
    diag.check_network_adapter = lambda: (
        "ok", "网卡正常", {"adapter_count": 2, "connected": True})
    diag.check_ip_address = lambda: ("ok", "IP 正常", {"ip": "192.168.1.8"})
    diag.check_gateway = lambda: (
        "ok", "网关正常", {"gateway": "192.168.1.1", "latency_ms": 2})
    diag.check_dns = lambda: (
        "warning", "DNS 偏慢", {"latency_ms": 120, "success": True})
    diag.check_internet = lambda: (
        "ok", "联网正常", {"latency_ms": 30, "loss_pct": 0})
    diag.check_multi_latency = lambda: (
        "warning", "延迟偏高", {"avg_ms": 80, "jitter_ms": 20})
    diag.check_proxy = lambda: ("ok", "未启用代理", {"enabled": False})


def test_results_keep_structured_data_and_recommendations():
    diag = NetworkDiagnostic()
    _fake_checks(diag)
    results = diag.run_all_tests()
    assert all("data" in item for item in results)
    dns = next(item for item in results if item["name"] == "DNS解析")
    assert dns["data"]["latency_ms"] == 120

    advice = diag.get_recommendations(results)
    assert advice
    assert any(item["page"] == "dns" for item in advice)


def test_repair_targets_only_for_failed_items():
    results = [
        {"name": "网卡状态", "status": "ok"},
        {"name": "DNS解析", "status": "warning"},
        {"name": "代理设置", "status": "error"},
        {"name": "多站点延迟", "status": "ok"},
    ]
    targets = NetworkDiagnostic.repair_targets(results)
    assert targets == ["刷新DNS缓存", "清除代理设置"]


def test_legacy_two_tuple_checks_still_work(monkeypatch):
    diag = NetworkDiagnostic()

    def legacy():
        return "ok", "旧格式"

    for name in ("check_network_adapter", "check_ip_address", "check_gateway",
                 "check_dns", "check_internet", "check_multi_latency",
                 "check_proxy"):
        monkeypatch.setattr(diag, name, legacy)
    results = diag.run_all_tests()
    assert len(results) == 7
    assert all(item["data"] == {} for item in results)
