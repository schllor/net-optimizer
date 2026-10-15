"""
网络优化助手 v1.0 - 主程序入口
基于PySide6 (Qt) 构建，面向新手小白的网络优化工具
"""

import sys
import os

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontDatabase
from ui.main_window import MainWindow
from core.version import __version__, APP_NAME

# 打包后字体等资源被解压到临时目录（sys._MEIPASS）；源码运行时在本文件目录
_RESOURCE_BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))

# 常见中文系统字体，按优先级挑选可用的
_CJK_FONT_CANDIDATES = [
    "Microsoft YaHei UI", "Microsoft YaHei", "SimHei",
    "PingFang SC", "Noto Sans CJK SC", "Noto Sans SC",
    "Source Han Sans SC", "WenQuanYi Micro Hei",
]


def _setup_font(app):
    """设置中文字体。

    1) 优先注册随 EXE 打包的黑体（simhei.ttf），保证在没有任何中文字体的
       电脑上也能正常显示中文，而不是显示成"方块/框形文字"。
    2) 若系统里存在更美观的中文字体（如微软雅黑），则优先使用系统字体。
    """
    bundled = None
    try:
        font_path = os.path.join(_RESOURCE_BASE, "fonts", "simhei.ttf")
        if os.path.exists(font_path):
            fid = QFontDatabase.addApplicationFont(font_path)
            families = QFontDatabase.applicationFontFamilies(fid)
            if families:
                bundled = families[0]
    except Exception:
        bundled = None

    for family in _CJK_FONT_CANDIDATES:
        if family in QFontDatabase.families():
            app.setFont(QFont(family, 10))
            return
    if bundled:
        app.setFont(QFont(bundled, 10))


def main():
    """主函数"""
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)

    # 设置应用样式
    app.setStyle("Fusion")
    _setup_font(app)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
