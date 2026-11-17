"""轻量 Toast：底部居中的非阻塞反馈条。

不进入布局，直接作为内容区的子控件悬浮；3 秒后自动淡出。
"""

from PySide6.QtCore import QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

import core.theme as theme


class Toast(QFrame):
    """单例式反馈条；同一父控件下重复调用会复用同一个实例。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setObjectName("appToast")
        self.setStyleSheet(
            f"QFrame#appToast {{ background-color: #17171a;"
            f" border: 1px solid {theme.LINE_STRONG}; border-radius: 10px; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        self.label = QLabel("")
        self.label.setStyleSheet(
            f"color: {theme.TEXT_MAIN}; background: transparent;"
            f" font-size: {theme.text_size(11)}px;")
        layout.addWidget(self.label)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self._fade = None

    def show_message(self, text, tone="info", duration_ms=2800):
        self.label.setText(str(text))
        color = {
            "ok": theme.MINT,
            "warn": theme.WARNING,
            "error": theme.ERROR,
            "info": theme.TEXT_MAIN,
        }.get(tone, theme.TEXT_MAIN)
        self.label.setStyleSheet(
            f"color: {color}; background: transparent;"
            f" font-size: {theme.text_size(11)}px;")
        self.adjustSize()
        self.reposition()
        self.setWindowOpacity(1.0)
        self.show()
        self.raise_()
        self._timer.start(int(duration_ms))

    def reposition(self):
        parent = self.parentWidget()
        if parent is None:
            return
        width = min(max(self.sizeHint().width(), 140),
                    max(140, parent.width() - 48))
        self.setFixedWidth(width)
        self.adjustSize()
        x = (parent.width() - self.width()) // 2
        y = max(12, parent.height() - self.height() - 24)
        self.move(x, y)

    def _fade_out(self):
        self.hide()


def notify(parent_widget, text, tone="info", duration_ms=2800):
    """在给定内容区显示一条反馈；父控件不存在时安全返回。"""
    if parent_widget is None:
        return None
    toast = getattr(parent_widget, "_app_toast", None)
    if toast is None:
        toast = Toast(parent_widget)
        parent_widget._app_toast = toast
    toast.show_message(text, tone, duration_ms)
    return toast
