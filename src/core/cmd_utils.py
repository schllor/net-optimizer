"""
命令执行工具 - 智能解码系统命令输出
解决不同 Windows 电脑上 netsh/ipconfig 输出编码不一致（GBK 或 UTF-8）导致的乱码与解析失败。

设计要点：
  - 不预设编码：先捕获原始字节，再逐条自动检测（UTF-8 严格优先，失败则回退 GBK/GB18030）。
  - 结构化结果：超时/取消/无权限/命令不存在都有明确 status，调用方不用猜 returncode。
  - 可取消：长命令（ping/netsh）可传入 threading.Event，在 50ms 粒度内终止。
  - 永不抛错：超时或异常都安全返回，方便上层做兜底判断。
  - 隐藏控制台窗口：GUI 程序调用命令行时不再闪出黑色 cmd 窗口。
"""

import subprocess
import sys
import time
from dataclasses import dataclass
from types import SimpleNamespace

# 不用 platform.system()：它在 Windows 上首次调用会真的执行一次 `cmd /c ver`，
# 实测约 38ms，而本模块会在程序启动时被所有 core 模块导入。
IS_WINDOWS = sys.platform == "win32"
_CREATE_NO_WINDOW = 0x08000000  # subprocess.CREATE_NO_WINDOW，仅 Windows 有效

STATUS_OK = "ok"
STATUS_TIMEOUT = "timeout"
STATUS_CANCELLED = "cancelled"
STATUS_DENIED = "denied"
STATUS_NOT_FOUND = "not_found"
STATUS_ERROR = "error"

# 无权限时不同语言的提示（中文系统 / 英文系统 / netsh 原文）
_DENIED_HINTS = (
    "拒绝访问", "需要提升", "提升权限", "以管理员身份", "访问被拒绝",
    "access is denied", "requires elevation", "elevation required",
    "requested operation requires elevation",
)


@dataclass
class ExecResult:
    """一次命令执行的完整结果（stdout/stderr 已智能解码）。"""

    returncode: int
    stdout: str
    stderr: str
    status: str = STATUS_OK
    timed_out: bool = False
    duration_ms: float = 0.0

    @property
    def ok(self):
        return self.status == STATUS_OK and self.returncode == 0

    @property
    def output(self):
        return (self.stdout or "") + (self.stderr or "")


def subprocess_kwargs():
    """返回创建子进程时隐藏控制台窗口的参数（非 Windows 返回空字典）。

    打包成窗口程序后，每次调用 ping/ipconfig 都会弹出一个黑色控制台窗口，
    对新手用户非常吓人。统一加上 CREATE_NO_WINDOW 可彻底消除该现象。
    """
    if IS_WINDOWS:
        return {"creationflags": _CREATE_NO_WINDOW}
    return {}


def smart_decode(data, default="utf-8"):
    """对原始字节智能解码：优先 UTF-8，回退 GBK/GB18030，最终兜底不抛错。

    原理：GBK 的多字节中文字符基本不会是合法 UTF-8 序列，
    因此 UTF-8 严格解码失败时回退到 GBK，可覆盖两种主流输出。
    """
    if not data:
        return ""
    if isinstance(data, str):
        return data
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, ValueError):
            continue
    return data.decode(default, errors="replace")


def _partial_bytes(exc):
    """收集超时异常里已经产生的 stdout/stderr 字节。"""
    parts = []
    for stream in (getattr(exc, "stdout", None), getattr(exc, "stderr", None)):
        if isinstance(stream, bytes):
            parts.append(stream)
        elif isinstance(stream, str):
            parts.append(stream.encode("utf-8", "replace"))
    return b"".join(parts)


def _kill(proc):
    """结束子进程：先 terminate，1 秒内不退出再 kill。"""
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1.0)
    except (OSError, subprocess.SubprocessError):
        pass


def _classify(code, text):
    """按返回码与输出文本判定执行状态。"""
    if code == 0:
        return STATUS_OK
    lowered = (text or "").lower()
    if any(hint in lowered for hint in _DENIED_HINTS) or code == 5:
        return STATUS_DENIED
    return STATUS_ERROR


def _execute(cmd, timeout=12, cancel=None):
    """执行命令，返回 (returncode, stdout_bytes, stderr_bytes, status, timed_out, duration_ms)。

    cancel 为 threading.Event；set 后在 50ms 内终止子进程。
    """
    started = time.perf_counter()
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **subprocess_kwargs(),
        )
    except FileNotFoundError:
        return (-1, b"", f"未找到命令: {command_str(cmd)}".encode("utf-8"),
                STATUS_NOT_FOUND, False, _elapsed_ms(started))
    except Exception as e:
        return (-1, b"", str(e).encode("utf-8"),
                STATUS_ERROR, False, _elapsed_ms(started))

    out_buf = b""
    err_buf = b""
    timed_out = False
    cancelled = False
    while True:
        budget = max(0.01, timeout - (time.perf_counter() - started))
        try:
            out_buf, err_buf = proc.communicate(timeout=min(0.05, budget))
            break
        except subprocess.TimeoutExpired as exc:
            # 每次超时都带回当前已产生的输出，保留下来供上层兜底
            if exc.stdout:
                out_buf = exc.stdout if isinstance(exc.stdout, bytes) else out_buf
            if exc.stderr:
                err_buf = exc.stderr if isinstance(exc.stderr, bytes) else err_buf
            if cancel is not None and cancel.is_set():
                cancelled = True
            elif time.perf_counter() - started >= timeout:
                timed_out = True
            if cancelled or timed_out:
                _kill(proc)
                try:
                    tail_out, tail_err = proc.communicate(timeout=1.0)
                    out_buf = tail_out or out_buf
                    err_buf = tail_err or err_buf
                except (subprocess.TimeoutExpired, OSError, ValueError):
                    pass
                break

    code = proc.returncode if proc.returncode is not None else -1
    duration = _elapsed_ms(started)
    if cancelled:
        status = STATUS_CANCELLED
    elif timed_out:
        status = STATUS_TIMEOUT
    else:
        status = _classify(code, smart_decode(out_buf + err_buf))
    return code, out_buf, err_buf, status, timed_out, duration


def _elapsed_ms(started):
    return round((time.perf_counter() - started) * 1000, 1)


def run_cmd_ex(cmd, timeout=12, cancel=None):
    """执行命令并返回 ExecResult；超时/取消/异常都不会抛出。"""
    code, out, err, status, timed_out, duration = _execute(cmd, timeout, cancel)
    return ExecResult(
        returncode=code,
        stdout=smart_decode(out),
        stderr=smart_decode(err),
        status=status,
        timed_out=timed_out,
        duration_ms=duration,
    )


def run_cmd(cmd, timeout=12, cancel=None):
    """安全执行命令并返回智能解码后的统一文本（含 stdout+stderr），永不抛错。

    超时或取消时只返回已产生的输出，不再把「执行超时」提示文字混入结果，
    避免被上层当成命令输出解析。
    """
    res = run_cmd_ex(cmd, timeout, cancel)
    if res.status in (STATUS_TIMEOUT, STATUS_CANCELLED):
        return res.output
    if res.status in (STATUS_NOT_FOUND, STATUS_ERROR):
        if not res.output:
            return f"(命令 {command_str(cmd)} 执行失败：{res.stderr or res.status})"
    return res.output


def run_cmd_bytes(cmd, timeout=12, cancel=None):
    """安全执行命令，返回 (返回码, 原始字节)；超时/取消/异常返回 (-1, 已有输出/空)。"""
    code, out, err, _status, _timed_out, _duration = _execute(cmd, timeout, cancel)
    return code, out + err


def smart_run(cmd, timeout=12, cancel=None):
    """运行命令并返回兼容 subprocess.run 结果的对象。

    .stdout 已智能解码，.returncode 可用；额外提供 .status/.timed_out/.duration_ms，
    让调用方可以区分「超时」与「命令失败」，而不是都看到一个 returncode=1。
    """
    res = run_cmd_ex(cmd, timeout, cancel)
    return SimpleNamespace(
        returncode=res.returncode,
        stdout=res.stdout,
        stderr=res.stderr,
        status=res.status,
        timed_out=res.timed_out,
        duration_ms=res.duration_ms,
    )


def command_str(cmd):
    return " ".join(cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
