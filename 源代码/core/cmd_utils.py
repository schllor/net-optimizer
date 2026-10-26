"""
命令执行工具 - 智能解码系统命令输出
解决不同 Windows 电脑上 netsh/ipconfig 输出编码不一致（GBK 或 UTF-8）导致的乱码与解析失败。

设计要点：
  - 不预设编码：先捕获原始字节，再逐条自动检测（UTF-8 严格优先，失败则回退 GBK/GB18030）。
  - 超时更宽松：netsh wlan 系列在部分机器上首次调用较慢，默认 12 秒。
  - 永不抛错：超时或异常都安全返回，方便上层做兜底判断。
  - 隐藏控制台窗口：GUI 程序调用命令行时不再闪出黑色 cmd 窗口。
"""

import platform
import subprocess
from types import SimpleNamespace

_IS_WINDOWS = platform.system() == "Windows"
_CREATE_NO_WINDOW = 0x08000000  # subprocess.CREATE_NO_WINDOW，仅 Windows 有效


def subprocess_kwargs():
    """返回创建子进程时隐藏控制台窗口的参数（非 Windows 返回空字典）。

    打包成窗口程序后，每次调用 ping/ipconfig 都会弹出一个黑色控制台窗口，
    对新手用户非常吓人。统一加上 CREATE_NO_WINDOW 可彻底消除该现象。
    """
    if _IS_WINDOWS:
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


def run_cmd(cmd, timeout=12):
    """安全执行命令并返回智能解码后的统一文本（含 stdout+stderr），永不抛错。"""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            **subprocess_kwargs(),
            # 不设 text/encoding，直接拿原始字节交给 smart_decode
        )
    except subprocess.TimeoutExpired as e:
        tail = _partial_bytes(e)
        prefix = f"(命令 {command_str(cmd)} 执行超时({timeout}s))"
        return prefix + ("\n" + smart_decode(tail) if tail else "")
    except Exception as e:
        return f"(命令 {command_str(cmd)} 执行失败：{e})"

    out = (proc.stdout or b"") + (proc.stderr or b"")
    return smart_decode(out)


def run_cmd_bytes(cmd, timeout=12):
    """安全执行命令，返回 (返回码, 原始字节)；超时/异常返回 (None, 已有输出/空)。"""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=timeout, **subprocess_kwargs())
        return proc.returncode, (proc.stdout or b"") + (proc.stderr or b"")
    except subprocess.TimeoutExpired as e:
        return None, _partial_bytes(e)
    except Exception:
        return None, b""


def smart_run(cmd, timeout=12):
    """运行命令并返回兼容 subprocess.run 结果的对象（.stdout 已智能解码，.returncode 可用）。

    用于把既有 `subprocess.run(..., encoding="gbk")` 统一替换为自动识别编码，
    同时在超时时也给出可读文本而非抛 TimeoutExpired，避免界面异常。
    """
    code, data = run_cmd_bytes(cmd, timeout)
    return SimpleNamespace(
        returncode=code if code is not None else 1,
        stdout=smart_decode(data),
        stderr="",
    )


def command_str(cmd):
    return " ".join(cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
