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
