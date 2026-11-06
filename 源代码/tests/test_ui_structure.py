"""主窗口结构测试：确认页面模块拆分后仍能完整组装与切换。

使用 Qt 离屏平台，无需真实显示器。
运行：pytest tests/ （在源代码根目录下）
"""

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow
from ui.pages import (
    HomePageMixin, DiagnosePageMixin, RepairPageMixin, SpeedPageMixin,
    DnsPageMixin, DevicesPageMixin, WifiPageMixin, DownloaderPageMixin,
    HistoryPageMixin, SettingsPageMixin,
)

PAGE_KEYS = (
    "home", "wifi", "diagnose", "repair", "dns",
    "devices", "speed", "downloader", "history", "settings",
)

MIXINS = (
    HomePageMixin, DiagnosePageMixin, RepairPageMixin, SpeedPageMixin,
    DnsPageMixin, DevicesPageMixin, WifiPageMixin, DownloaderPageMixin,
    HistoryPageMixin, SettingsPageMixin,
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


def _wait_until(app, predicate, timeout=2.0):
    """离屏测试里推进事件循环，等待后台线程的信号送达主线程。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return predicate()


def test_downloader_gear_opens_settings_and_applies_connections(app, monkeypatch, tmp_path):
    """齿轮进设置、并发连接数可保存，并传给 Downloader。"""
    import core.settings as settings_mod
    import ui.pages.downloader as dl_page

    monkeypatch.setattr(
        settings_mod, "default_path", lambda: str(tmp_path / "settings.json"))

    captured = {}

    class FakeDownloader:
        def __init__(self, url, save_dir, max_workers=None, mirror=False):
            captured["max_workers"] = max_workers
            captured["mirror"] = mirror
            self.max_conn = max_workers
            self.max_workers = max_workers
            self.done_bytes = 0
            self.total_size = 0
            self.percent = 0.0
            self.completed = False
            self.error = None
            self.retries = 0
            self.is_paused = lambda: False
            self.is_cancelled = lambda: False
            self.cancel = lambda: None

    class _Signal:
        def connect(self, _fn):
            pass

    class FakeWorker:
        def __init__(self, _dl, _parent):
            self.done = _Signal()

        def isRunning(self):
            return False

        def start(self):
            pass

    monkeypatch.setattr(dl_page, "Downloader", FakeDownloader)
    monkeypatch.setattr(dl_page, "DownloadWorker", FakeWorker)

    window = MainWindow()
    try:
        assert window.dl_settings_btn.text() == "⚙"
        window._switch_page("downloader")
        window.dl_settings_btn.click()
        assert window.current_page_key == "settings"

        assert window.set_dl_conn.minimum() == 1
        assert window.set_dl_conn.maximum() == 16
        window.set_dl_conn.setValue(12)
        window._save_settings()
        assert window.settings.get("download_connections") == 12

        window._switch_page("downloader")
        window.dl_url_edit.setText("https://example.com/f.zip")
        window._start_download()
        assert captured["max_workers"] == 12
        assert window._dl.max_conn == 12
    finally:
        if window._dl_timer is not None:
            window._dl_timer.stop()
        window.close()


def test_sidebar_groups_keep_all_entries_and_pin_system_items(app):
    """分组导航只移动不删减；设置与升级入口固定在底部、不进入滚动区。"""
    from PySide6.QtWidgets import QLabel

    window = MainWindow()
    try:
        assert set(window.nav_buttons) == set(PAGE_KEYS)

        scroll_content = window.nav_scroll.widget()
        assert scroll_content.isAncestorOf(window.nav_buttons["history"])
        assert not scroll_content.isAncestorOf(window.nav_buttons["settings"])
        assert not scroll_content.isAncestorOf(window.upgrade_btn)

        titles = {label.text() for label in window.sidebar.findChildren(QLabel)}
        assert {"总览", "检测", "修复 · 优化", "工具", "记录"} <= titles

        window._switch_page("settings")
        assert (window.nav_buttons["settings"].styleSheet()
                != window.nav_buttons["home"].styleSheet())
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
        assert _wait_until(app, lambda: window.current_dns_label.text() == "1.1.1.1")
        assert calls == [1]
        window._switch_page("home")
        window._switch_page("dns")
        app.processEvents()
        assert calls == [1]
    finally:
        window.close()
