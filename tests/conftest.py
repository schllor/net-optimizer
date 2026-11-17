"""测试全局配置。

pytest 启动时自动执行：把 ``src`` 加入 ``sys.path``（pyproject.toml 已经配了
``pythonpath = ["src"]``，这里是双保险），固定 Qt 离屏平台避免弹窗。
同时提供三个 UI 测试共享的 fixture。
"""

import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# 离屏渲染：不需要真实显示器，打包后的 Qt 也能正常画像素
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ---------------------------------------------------------------- Qt 应用
@pytest.fixture(scope="session")
def qtapp():
    """进程级单例 QApplication。

    PySide6 限制全局只有一个 QApplication；session scope 保证所有测试
    共享同一个，避免模块级 fixture 被 pytest 并行/并发策略破坏。
    """
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(scope="session")
def app(qtapp):
    """兼容别名：历史上 UI 测试都叫 ``app``，不动调用点。"""
    return qtapp


# ---------------------------------------------------------------- 主窗口
@pytest.fixture
def window(app):
    """按需创建 MainWindow，yield 后 stop 后台线程并 close。"""
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        yield win
    finally:
        if getattr(win, "_dl_timer", None) is not None:
            try:
                win._dl_timer.stop()
            except RuntimeError:
                pass
        # 让 TrafficSampler 先停再关窗口，避免后台线程继续引用销毁的控件
        sampler = getattr(win, "net_sampler", None)
        if sampler is not None and sampler.isRunning():
            try:
                sampler.quit()
                sampler.wait(1500)
            except RuntimeError:
                pass
        win.close()
        app.processEvents()


# ---------------------------------------------------------------- 工具
def wait_until(app, predicate, timeout=2.0, interval=0.01):
    """推进事件循环直到 predicate() 为真或超时；超时返回假。

    离屏测试里后台线程（下载、测速、采样）的信号靠主线程事件循环送达。
    直接 ``time.sleep`` 会导致这些信号堆积、界面控件一直不更新。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(interval)
    app.processEvents()
    return predicate()
