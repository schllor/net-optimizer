"""
路径统一模块 - 确保软件在任何位置都能正确找到数据目录
无论是直接运行源码还是打包成 EXE 后在别人电脑上运行，数据都保存在程序所在目录下。
"""
import os
import sys


def get_app_dir():
    """
    获取程序所在目录（EXE 或 main.py 所在目录）。
    - 打包运行（EXE）：返回 EXE 所在目录
    - 源码运行：返回源代码根目录（main.py 所在目录）
    """
    if getattr(sys, "frozen", False):
        # PyInstaller 打包运行
        return os.path.dirname(os.path.abspath(sys.executable))
    else:
        # 源码运行：本文件在 core/ 下，上级就是源代码根目录
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_data_dir():
    """获取数据目录（存放缓存、日志等），在程序目录下的 data/ 文件夹"""
    data_dir = os.path.join(get_app_dir(), "data")
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    return data_dir


def get_cache_dir():
    """获取缓存目录"""
    cache_dir = os.path.join(get_data_dir(), "cache")
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)
    return cache_dir


def get_log_dir():
    """获取日志目录"""
    log_dir = os.path.join(get_data_dir(), "logs")
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    return log_dir
