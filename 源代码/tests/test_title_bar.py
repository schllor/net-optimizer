"""自绘标题栏测试：无边框窗口、边缘缩放命中区与窗口按钮。

使用 Qt 离屏平台，无需真实显示器。
运行：pytest tests/ （在源代码根目录下）
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_window_uses_frameless_custom_title_bar(app):
    window = MainWindow()
    try:
        window.show()
        app.processEvents()
        assert window.windowFlags() & Qt.FramelessWindowHint
        bar = window.title_bar
        assert bar.isVisible()
        assert bar.title_label.text() == window.windowTitle()
        assert bar.width() == window.centralWidget().width()
        for button in (bar.min_button, bar.max_button, bar.close_button):
            assert button.isVisible()
    finally:
        window.close()


def test_hit_test_covers_window_edges(app):
    window = MainWindow()
    try:
        window.resize(1100, 720)
        window.show()
        app.processEvents()
        w, h = window.width(), window.height()
        grips = {grip.anchor: grip.geometry() for grip in window._grips}
        assert len(grips) == 8
        assert grips["left"] == QRect(0, 6, 6, h - 12)
        assert grips["right"] == QRect(w - 6, 6, 6, h - 12)
        assert grips["top"] == QRect(6, 0, w - 12, 6)
        assert grips["bottom"] == QRect(6, h - 6, w - 12, 6)
        assert grips["top-left"] == QRect(0, 0, 12, 12)
        assert grips["bottom-right"] == QRect(w - 12, h - 12, 12, 12)
        assert all(grip.isVisible() for grip in window._grips)
    finally:
        window.close()


def test_resize_grips_hide_when_maximized(app):
    window = MainWindow()
    try:
        window.show()
        app.processEvents()
        window.showMaximized()
        app.processEvents()
        assert all(not grip.isVisible() for grip in window._grips)
        window.showNormal()
        app.processEvents()
        assert all(grip.isVisible() for grip in window._grips)
    finally:
        window.close()


def test_maximize_button_toggles_window_state(app):
    window = MainWindow()
    try:
        window.show()
        app.processEvents()
        assert not window.isMaximized()
        window.title_bar.max_button._activate()
        app.processEvents()
        assert window.isMaximized()
        assert window.title_bar.max_button._maximized
        window.title_bar.max_button._activate()
        app.processEvents()
        assert not window.isMaximized()
        assert not window.title_bar.max_button._maximized
    finally:
        window.close()
