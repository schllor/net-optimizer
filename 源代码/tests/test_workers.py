"""后台任务基类测试：结果、异常、取消与窗口关闭收敛。"""

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from PySide6.QtWidgets import QApplication

from ui.workers import TaskWorker


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


class _BoomWorker(TaskWorker):
    def execute(self):
        raise RuntimeError("boom")


class _ValueWorker(TaskWorker):
    def execute(self):
        return {"ok": True}


class _LoopWorker(TaskWorker):
    """一直空转，直到收到取消请求。"""

    def execute(self):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.is_cancelled():
                return None
            time.sleep(0.02)
        return "timeout"


def _wait(app, predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return predicate()


def test_worker_emits_done_with_result(app):
    worker = _ValueWorker()
    seen = []
    worker.done.connect(seen.append)
    worker.start()
    assert worker.wait(2000)
    assert _wait(app, lambda: bool(seen))
    assert seen == [{"ok": True}]


def test_worker_exception_goes_to_failed_and_done_none(app):
    worker = _BoomWorker()
    failed, done = [], []
    worker.failed.connect(lambda msg, detail: failed.append((msg, detail)))
    worker.done.connect(done.append)
    worker.start()
    assert worker.wait(2000)
    assert _wait(app, lambda: bool(failed) and bool(done))
    assert "任务执行失败" in failed[0][0]
    assert "RuntimeError" in failed[0][1]
    assert done == [None]


def test_worker_cancel_stops_quickly(app):
    worker = _LoopWorker()
    cancelled, done = [], []
    worker.cancelled.connect(lambda: cancelled.append(True))
    worker.done.connect(done.append)
    worker.start()
    time.sleep(0.05)
    worker.cancel()
    started = time.monotonic()
    assert worker.wait(2000)
    assert time.monotonic() - started < 1.0
    assert _wait(app, lambda: bool(cancelled) and bool(done))
    assert done == [None]


def test_window_close_stops_running_worker_within_two_seconds(app):
    from ui.main_window import MainWindow

    window = MainWindow()
    worker = _LoopWorker()
    window._start_worker(worker)
    time.sleep(0.05)

    started = time.monotonic()
    window.close()
    elapsed = time.monotonic() - started

    assert elapsed < 2.5
    assert not worker.isRunning()
    assert window._workers == []
