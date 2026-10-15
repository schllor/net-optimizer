"""
运行日志模块 - 记录程序关键操作和错误
日志保存在程序目录下的 data/logs 文件夹中（与 EXE 同目录，方便迁移和反馈 Bug）
"""
import logging
import os
from datetime import datetime

from core.paths import get_log_dir

_LOGGER = None


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

    # 每天一个日志文件
    log_file = os.path.join(get_log_dir(), "app_{}.log".format(
        datetime.now().strftime("%Y%m%d")))

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    _LOGGER = logger
    return _LOGGER


def log_exception(context):
    """记录异常堆栈，便于定位 Bug"""
    logger = get_logger()
    logger.exception("[异常] %s", context)
