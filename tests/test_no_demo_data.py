"""默认首屏不得出现演示数据 / 不实承诺。"""

from PySide6.QtWidgets import QLabel

FORBIDDEN = (
    "MyHome_5G",
    "Intel Wi-Fi 6 AX201",
    "MacBook Pro",
    "已是最新版本",
    "一键回滚",
    "超过 96%",
    "上海电信",
    "最高 528",
    "12.4 MB/s",
    "3 个源已并发启用",
    "缓存命中率",
    "DoH 已启用",
    "已成功刷新 DNS 解析缓存",
    "SCREEN 01",
)


def _all_text(window):
    return "\n".join(label.text() for label in window.findChildren(QLabel)
                     if label.text())


def test_default_pages_have_no_demo_strings(window):
    text = _all_text(window)
    for forbidden in FORBIDDEN:
        assert forbidden not in text, forbidden


def test_pages_start_in_honest_empty_states(window):
    assert window.diag_score_ring._unknown is True
    assert window.diag_verdict.text() == "尚未检测"
    assert "尚未执行修复" in window.repair_log_view.toPlainText()

    assert window.dns_rec_ip_label.text() == "尚未测试"
    assert window.dns_apply_top_btn.isEnabled() is False

    assert window.speed_hist_best.text() == "暂无记录"
    assert window.speed_hist_bars._values == []

    assert window.dev_unknown_title.text() == "尚未扫描"
    assert window.wifi_ssid_value.text() == "尚未检测"
    assert window.wifi_signal_value.text() == "--"
    assert window.wifi_nearby_note.text() == "尚未扫描"


def test_repair_preview_is_structured(window):
    preview = window.repair.preview()
    names = {item["name"] for item in preview}
    assert "重置Winsock目录" in names
    assert any(item["needs_reboot"] for item in preview)
    assert any(item["requires_admin"] for item in preview)
