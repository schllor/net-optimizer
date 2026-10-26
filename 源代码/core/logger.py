"""
运行日志模块 - 记录程序关键操作和错误
日志保存在程序目录下的 data/logs 文件夹中（与 EXE 同目录，方便迁移和反馈 Bug）

改进：
  - 启动时自动清理 14 天前的旧日志，避免长期使用后磁盘无限增长。
  - 打包为窗口程序（无控制台）时不再添加 stderr handler，避免无效输出。
  - 日志目录不可写时自动降级为仅控制台，不影响程序启动。
"""
import logging
import os
import sys
import time
from datetime import datetime

from core.paths import get_log_dir

_LOGGER = None
_LOG_KEEP_DAYS = 14


def _cleanup_old_logs(log_dir, keep_days=_LOG_KEEP_DAYS):
    """删除过期日志文件（失败静默，不影响主流程）。"""
    try:
        cutoff = time.time() - keep_days * 86400
        for name in os.listdir(log_dir):
            if not (name.startswith("app_") and name.endswith(".log")):
                continue
            path = os.path.join(log_dir, name)
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
            except OSError:
                continue
    except OSError:
        pass


def get_logger():
    """获取全局日志记录器（单例）"""
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER

    logger = logging.getLogger("network_optimizer")
    logger.setLevel(logging.INFO)
    if logger.handlers:  # 避免重复添加 handler
        _LOGGER = logger
        return _LOGGER

    log_dir = get_log_dir()
    _cleanup_old_logs(log_dir)

    # 每天一个日志文件
    log_file = os.path.join(log_dir, "app_{}.log".format(
        datetime.now().strftime("%Y%m%d")))

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    try:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        # 程序目录只读等场景：放弃文件日志，保持程序可用
        pass

    # 窗口程序（PyInstaller --noconsole）下 sys.stderr 可能为 None
    if sys.stderr is not None:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    _LOGGER = logger
    return _LOGGER


def log_exception(context):
    """记录异常堆栈，便于定位 Bug"""
    logger = get_logger()
    logger.exception("[异常] %s", context)
