"""管理员权限检测与提权（Windows）。

集中管理 UAC 相关逻辑，供网络修复与 DNS 设置共用，避免各模块各写一份。
"""

import subprocess
import sys

from .cmd_utils import IS_WINDOWS


def is_admin():
    """检测当前程序是否以管理员权限运行（非 Windows 视为 True）。"""
    if not IS_WINDOWS:
        return True
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin():
    """以管理员权限重新启动程序（Windows UAC 提权）。"""
    if not IS_WINDOWS:
        return False
    try:
        import ctypes
        exe_path = sys.executable if getattr(sys, "frozen", False) else sys.argv[0]
        # 透传命令行参数，避免提权重启后丢失运行参数
        params = subprocess.list2cmdline(sys.argv[1:]) if len(sys.argv) > 1 else ""
        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", exe_path, params, None, 1)
        # 返回值 > 32 表示提权启动成功
        return result > 32
    except Exception:
        return False


def require_admin(action="此操作"):
    """返回 (是否有权限, 给用户看的提示)。UI 在无权限时应直接展示该提示。"""
    if is_admin():
        return True, ""
    return False, f"{action}需要管理员权限，请右键选择「以管理员身份运行」后重试。"
