"""页面把真实结果写回界面的关键路径（不弹模态框）。"""


def _block_publish(window, monkeypatch):
    monkeypatch.setattr(window.state, "publish",
                        lambda *args, **kwargs: None)


def test_speed_results_update_labels_and_history(app, window, monkeypatch):
    saved = []

    def save(kind, data):
        saved.append({"timestamp": "2026-11-17 12:00:00", "result": data})
        return True

    monkeypatch.setattr(window.cache, "save_result", save)
    monkeypatch.setattr(window.cache, "get_history",
                        lambda kind: saved if kind == "speed" else [])
    results = {
        "download": {"success": True, "speed_mbps": 123.4},
        "upload": {"success": True, "speed_mbps": 42.0},
        "ping": {"success": True, "avg_latency": 18, "p95": 25,
                 "jitter_ms": 2.1, "loss_rate": 0.0},
    }
    window._on_speed_finished(results)
    app.processEvents()
    assert window.download_value.text() == "123.4"
    assert window.upload_value.text() == "42.0"
    assert window.ping_value.text() == "18"
    assert window.speed_hist_bars._values
    assert window.speed_state_pill.text() == "测试完成"


def test_dns_results_replace_placeholders(app, window, monkeypatch):
    _block_publish(window, monkeypatch)
    window._dns_current = ["192.168.1.1"]
    results = [
        {"name": "阿里DNS", "ip": "223.5.5.5", "success": True,
         "p50": 8, "p95": 9, "latency": 9, "doh_ok": True},
        {"name": "谷歌DNS", "ip": "8.8.8.8", "success": True,
         "p50": 50, "p95": 55, "latency": 55, "doh_ok": True},
    ]
    window._on_dns_finished(results)
    app.processEvents()
    assert window.dns_rec_ip_label.text() == "223.5.5.5"
    assert window.dns_apply_top_btn.isEnabled() is True
    assert window.dns_doh_value.text() == "支持 DoH"


def test_wifi_scan_updates_real_rows(app, window):
    result = {
        "success": True,
        "networks": [
            {"ssid": "Home", "signal": 82, "channel": 149,
             "connected": True, "auth": "WPA2"},
            {"ssid": "Neighbor", "signal": 55, "channel": 149,
             "connected": False, "auth": "WPA3"},
        ],
        "advice": ["5G 信道 149 有 1 个强干扰源"],
    }
    window._on_wifi_scan_finished(result)
    app.processEvents()
    assert window.wifi_nearby_note.text() == "2 FOUND"
    assert window.wifi_recommend_action.isEnabled() is True
    assert window._wifi_inter_labels["5 GHz 邻居"].text() == "2 个"


def test_devices_scan_updates_real_rows(app, window):
    devices = [
        {"name": "MyPC", "ip": "192.168.1.8", "mac": "aa:bb:cc:dd:ee:ff",
         "online": True, "self": True},
        {"name": "未知设备", "ip": "192.168.1.9", "mac": "11:22:33:44:55:66",
         "online": False, "unknown": True},
    ]
    window._on_devices_scanned(devices)
    app.processEvents()
    assert window.dev_stat_labels["online"].text() == "1"
    assert window.dev_stat_labels["unknown"].text() == "1"
    assert window.dev_unknown_title.text() == "发现 1 台未知设备"
    assert window.dev_last_scan.text().startswith("LAST SCAN ")
