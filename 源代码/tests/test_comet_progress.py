"""顶部彗星进度条与任务接线测试（离屏运行）。"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QObject, Signal

from ui.main_window import MainWindow
from ui.widgets import CometProgressBar


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def bar(app):
    host = QWidget()
    widget = CometProgressBar(host)
    widget.resize(400, CometProgressBar.HEIGHT)
    yield widget
    widget.stop()


def _advance(widget, ms_total, step=16):
    for _ in range(max(1, int(ms_total / step))):
        widget.advance(step)


def test_starts_idle_and_hidden(bar):
    assert bar.state == "idle"
    assert bar.isHidden()


def test_start_switches_between_modes(bar):
    bar.start()
    assert bar.state == "indeterminate"
    bar.start(30)
    assert bar.state == "determinate"


def test_progress_converges_without_overshoot(bar):
    bar.start(0)
    bar.set_progress(40)
    _advance(bar, 2000)
    assert bar.value == pytest.approx(40.0, abs=0.6)
    assert bar.value <= 40.01


def test_progress_never_moves_backwards(bar):
    bar.start(0)
    bar.set_progress(60)
    _advance(bar, 1000)
    bar.set_progress(20)
    _advance(bar, 1000)
    assert bar.value >= 59.5


def test_finish_reaches_full_then_hides(bar):
    bar.start(45)
    _advance(bar, 1000)
    bar.finish()
    _advance(bar, 3000)
    assert bar.state == "idle"
    assert bar.isHidden()
    assert not bar._timer.isActive()


def test_pause_and_resume_keep_target(bar):
    bar.start(35)
    _advance(bar, 800)
    bar.pause()
    assert bar.state == "paused"
    _advance(bar, 2000)
    assert bar.isHidden()
    bar.resume()
    assert bar.state == "determinate"
    _advance(bar, 800)
    assert bar.value >= 34.0


def test_stop_is_idempotent(bar):
    bar.start()
    bar.stop()
    bar.stop()
    assert bar.state == "idle"
    assert bar.isHidden()


def test_paints_visible_pixels(app):
    host = QWidget()
    host.resize(420, 40)
    host.show()
    widget = CometProgressBar(host)
    widget.setGeometry(0, 0, 400, CometProgressBar.HEIGHT)
    widget.start(50)
    _advance(widget, 500)
    app.processEvents()
    image = widget.grab().toImage()
    assert image.width() == 400
    assert any(image.pixelColor(x, 1).alpha() > 0 for x in range(0, 400, 8))
    widget.stop()
    host.close()


@pytest.fixture
def window(app):
    win = MainWindow()
    yield win
    win.close()


def test_window_aggregates_tasks(window):
    bar = window.comet_bar
    assert bar.state == "idle"

    window._begin_task("a")
    assert bar.state == "indeterminate"

    window._update_task("a", 30)
    _advance(bar, 600)
    assert bar.state == "determinate"
    assert bar.value == pytest.approx(30.0, abs=1.0)

    window._begin_task("b")
    assert bar.state == "indeterminate"
    window._update_task("b", 70)
    assert bar.state == "determinate"

    window._end_task("b")
    assert bar.state == "determinate"

    window._end_task("a")
    assert bar.state == "finishing"
    _advance(bar, 4000)
    assert bar.state == "idle"


def test_window_pause_marks_task_paused(window):
    window._begin_task("download")
    window._update_task("download", 25)
    window._pause_task("download")
    assert window.comet_bar.state == "paused"
    window._resume_task("download")
    assert window.comet_bar.state == "determinate"
    window._end_task("download")


def test_close_stops_animation(window):
    window._begin_task("x")
    window._update_task("x", 50)
    assert window.comet_bar.state == "determinate"

    window.close()

    assert window.comet_bar.state == "idle"
    assert window.comet_bar.isHidden()
    assert not window.net_timer.isActive()


class _FakeScanWorker(QObject):
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.started = False

    def isRunning(self):
        return True

    def start(self):
        self.started = True

    def wait(self, ms=0):
        return True

    def cancel(self):
        pass


def test_devices_scan_registers_worker(window, monkeypatch):
    fake = _FakeScanWorker()
    monkeypatch.setattr("ui.pages.devices.DeviceScanWorker", lambda: fake)

    window._start_devices_scan()

    assert fake.started
    assert fake in window._workers
    window._workers.remove(fake)
    window._end_task(fake)
