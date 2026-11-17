"""
路径统一模块 - 确保软件在任何位置都能正确找到数据目录
无论是直接运行源码还是打包成 EXE 后在别人电脑上运行，数据默认保存在程序所在目录下。

若程序安装在 Program Files 等只读目录，自动回退到 %LOCALAPPDATA%\\网络优化助手，
避免「看起来保存成功、实际写不进去」的假保存。
"""
import os
import sys

_APP_DIR_NAME = "网络优化助手"


def get_app_dir():
    """
    获取程序所在目录（EXE 或 main.py 所在目录）。
    - 打包运行（EXE）：返回 EXE 所在目录
    - 源码运行：返回 src 目录（main.py 所在目录）
    """
    if getattr(sys, "frozen", False):
        # PyInstaller 打包运行
        return os.path.dirname(os.path.abspath(sys.executable))
    else:
        # 源码运行：本文件在 core/ 下，上两级就是 src 目录
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _is_writable(path):
    """通过写一个临时探针文件判断目录是否可写。"""
    probe = os.path.join(path, f".write_probe_{os.getpid()}")
    try:
        with open(probe, "w", encoding="utf-8") as f:
            f.write("")
        os.remove(probe)
        return True
    except OSError:
        try:
            if os.path.exists(probe):
                os.remove(probe)
        except OSError:
            pass
        return False


def _fallback_data_dir():
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if not base:
        base = os.path.expanduser("~")
    return os.path.join(base, _APP_DIR_NAME, "data")


def get_data_dir():
    """获取数据目录（存放缓存、日志等）。

    优先使用程序目录下的 data/；不可写时回退到本地应用数据目录。
    """
    primary = os.path.join(get_app_dir(), "data")
    try:
        os.makedirs(primary, exist_ok=True)
    except OSError:
        primary = ""
    if primary and _is_writable(primary):
        return primary

    fallback = _fallback_data_dir()
    os.makedirs(fallback, exist_ok=True)
    return fallback


def get_cache_dir():
    """获取缓存目录"""
    cache_dir = os.path.join(get_data_dir(), "cache")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def get_log_dir():
    """获取日志目录"""
    log_dir = os.path.join(get_data_dir(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    return log_dir
