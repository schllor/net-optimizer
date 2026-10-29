"""主窗口结构测试：确认页面模块拆分后仍能完整组装与切换。

使用 Qt 离屏平台，无需真实显示器。
运行：pytest tests/ （在源代码根目录下）
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow
from ui.pages import (
    HomePageMixin, DiagnosePageMixin, RepairPageMixin, SpeedPageMixin,
    DnsPageMixin, DevicesPageMixin, WifiPageMixin, DownloaderPageMixin,
    HistoryPageMixin,
)

PAGE_KEYS = (
    "home", "wifi", "diagnose", "repair", "dns",
    "devices", "speed", "downloader", "history",
)

MIXINS = (
    HomePageMixin, DiagnosePageMixin, RepairPageMixin, SpeedPageMixin,
    DnsPageMixin, DevicesPageMixin, WifiPageMixin, DownloaderPageMixin,
    HistoryPageMixin,
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_main_window_composes_all_page_mixins():
    for mixin in MIXINS:
        assert issubclass(MainWindow, mixin)


def test_main_window_creates_and_switches_all_pages(app):
    window = MainWindow()
    try:
        assert window.pages.count() == len(PAGE_KEYS)
        for key in PAGE_KEYS:
            window._switch_page(key)
            assert window.current_page_key == key
    finally:
        window.close()


def test_dns_current_dns_is_loaded_lazily(app, monkeypatch):
    """当前 DNS 依赖 ipconfig，构建窗口时不应执行，首次进入 DNS 页才查一次。"""
    from core.dns_optimizer import DNSOptimizer

    calls = []
    monkeypatch.setattr(
        DNSOptimizer, "get_current_dns",
        lambda self: calls.append(1) or ["1.1.1.1"])

    window = MainWindow()
    try:
        assert calls == []
        window._switch_page("dns")
        assert calls == [1]
        assert window.current_dns_label.text() == "1.1.1.1"
        window._switch_page("home")
        window._switch_page("dns")
        assert calls == [1]
    finally:
        window.close()
