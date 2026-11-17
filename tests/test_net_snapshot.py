"""网络快照采集的解析/缓存测试。"""

import core.net_snapshot as net_snapshot
from core.net_snapshot import Snapshot


def test_band_and_radio_labels():
    assert net_snapshot._band_from_channel(6) == "2.4G"
    assert net_snapshot._band_from_channel(149) == "5G"
    assert net_snapshot._radio_label("802.11ax") == "Wi-Fi 6"
    assert net_snapshot._radio_label("802.11be") == "Wi-Fi 7"
    assert net_snapshot._radio_label("") == ""


def test_collect_builds_snapshot_and_caches(monkeypatch):
    net_snapshot.clear_cache()
    monkeypatch.setattr(net_snapshot, "get_local_ip", lambda: "192.168.1.8")
    monkeypatch.setattr(net_snapshot, "get_default_gateway",
                        lambda local_ip=None: "192.168.1.1")
    monkeypatch.setattr(net_snapshot, "_dns_servers",
                        lambda: ["223.5.5.5", "119.29.29.29"])
    monkeypatch.setattr(net_snapshot, "_adapter_name", lambda: "WLAN")
    monkeypatch.setattr(net_snapshot, "_quick_online", lambda timeout=0.8: True)
    monkeypatch.setattr(net_snapshot.WiFiChecker, "get_wifi_info",
                        lambda self: {"connected": True, "ssid": "Home",
                                      "channel": 149, "signal_strength": 80,
                                      "rx_rate": 866, "tx_rate": 866,
                                      "radio_type": "802.11ax"})

    first = net_snapshot.collect(ttl=30)
    assert first.kind == "wifi"
    assert first.ssid == "Home"
    assert first.band == "5G"
    assert first.radio_label == "Wi-Fi 6"
    assert first.gateway == "192.168.1.1"
    assert first.online is True

    # TTL 内复用同一对象
    second = net_snapshot.collect(ttl=30)
    assert second is first
    net_snapshot.clear_cache()


def test_snapshot_defaults_are_unknown_not_fake():
    snap = Snapshot()
    assert snap.connected is False
    assert snap.ssid == ""
    assert snap.dns_servers == []
    assert snap.summary == "未连接"
