"""命令执行层测试：成功/失败/超时/取消/命令不存在/无权限归类。"""

import sys
import threading
import time

from core.cmd_utils import (
    STATUS_CANCELLED, STATUS_DENIED, STATUS_ERROR, STATUS_NOT_FOUND,
    STATUS_OK, STATUS_TIMEOUT, run_cmd, run_cmd_ex, smart_run,
)

PY = sys.executable


def test_success_returns_ok_and_stdout():
    res = run_cmd_ex([PY, "-c", "print('hello')"])
    assert res.ok
    assert res.status == STATUS_OK
    assert res.stdout.strip() == "hello"
    assert res.duration_ms >= 0


def test_nonzero_exit_is_error():
    res = run_cmd_ex([PY, "-c", "import sys; sys.exit(3)"])
    assert not res.ok
    assert res.returncode == 3
    assert res.status == STATUS_ERROR


def test_timeout_keeps_partial_output_without_hint_text():
    res = run_cmd_ex(
        [PY, "-c", "import time; print('start', flush=True); time.sleep(5)"],
        timeout=0.6)
    assert res.timed_out
    assert res.status == STATUS_TIMEOUT
    assert "start" in res.stdout
    # 超时提示不能再混入 stdout，避免被上层当成命令输出解析
    assert "超时" not in res.stdout


def test_cancel_returns_promptly():
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    started = time.monotonic()
    res = run_cmd_ex(
        [PY, "-c", "import time; time.sleep(5)"], timeout=10, cancel=cancel)
    assert res.status == STATUS_CANCELLED
    assert not res.timed_out
    assert time.monotonic() - started < 3


def test_missing_command_is_not_found():
    res = run_cmd_ex(["nethelper-command-does-not-exist-xyz"])
    assert res.status == STATUS_NOT_FOUND
    assert res.returncode == -1
    assert "未找到命令" in res.stderr


def test_denied_text_is_classified():
    res = run_cmd_ex(
        [PY, "-c", "print('Access is denied.'); raise SystemExit(1)"])
    assert res.status == STATUS_DENIED
    assert not res.ok


def test_run_cmd_never_raises_and_hides_timeout_hint():
    out = run_cmd([PY, "-c", "import time; time.sleep(5)"], timeout=0.4)
    assert "超时" not in out


def test_smart_run_exposes_status_fields():
    res = smart_run([PY, "-c", "print('x')"])
    assert res.returncode == 0
    assert res.status == STATUS_OK
    assert res.timed_out is False
    assert res.stdout.strip() == "x"
