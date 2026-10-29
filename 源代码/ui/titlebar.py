"""自绘标题栏：替换系统白色标题栏，让窗口顶部与深色界面连成一体。"""

from PySide6.QtCore import Qt, QPointF, QRect, QRectF, QEvent
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

import core.theme as theme

_CLOSE_HOVER = "#c42b1c"


class WindowGrip(QWidget):
    """无边框窗口边缘的缩放热区：只提供光标样式并发起系统缩放。

    无边框窗口没有系统边框，Qt 的 startSystemResize 必须由控件自己触发，
    所以在窗口四边与四角各放一条透明的窄条热区。
    """

    THICK = 6
    CORNER = 12

    def __init__(self, window, anchor, edges, cursor, parent=None):
        super().__init__(parent)
        self._window = window
        self.anchor = anchor
        self._edges = edges
        flags = edges[0]
        for edge in edges[1:]:
            flags |= edge
        self._edge_flags = flags
        self.setCursor(cursor)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)

    def place(self, width, height):
        t, c = self.THICK, self.CORNER
        rects = {
            "left": QRect(0, t, t, height - 2 * t),
            "right": QRect(width - t, t, t, height - 2 * t),
            "top": QRect(t, 0, width - 2 * t, t),
            "bottom": QRect(t, height - t, width - 2 * t, t),
            "top-left": QRect(0, 0, c, c),
            "top-right": QRect(width - c, 0, c, c),
            "bottom-left": QRect(0, height - c, c, c),
            "bottom-right": QRect(width - c, height - c, c, c),
        }
        self.setGeometry(rects[self.anchor])

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None:
                handle.startSystemResize(self._edge_flags)
            event.accept()
            return
        super().mousePressEvent(event)


class WindowButton(QWidget):
    """标题栏按钮：最小化 / 最大化（还原）/ 关闭，图标全部用线条绘制。"""

    WIDTH = 46

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self._hover = False
        self._maximized = False
        self.setFixedSize(self.WIDTH, TitleBar.HEIGHT)
        self.setToolTip({"min": "最小化", "max": "最大化", "close": "关闭"}[kind])

    def set_maximized(self, maximized):
        if self.kind != "max":
            return
        self._maximized = bool(maximized)
        self.setToolTip("还原" if maximized else "最大化")
        self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self._activate()
        super().mouseReleaseEvent(event)

    def _activate(self):
        window = self.window()
        if self.kind == "min":
            window.showMinimized()
        elif self.kind == "max":
            if window.isMaximized():
                window.showNormal()
            else:
                window.showMaximized()
        else:
            window.close()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        closing = self.kind == "close"
        if self._hover:
            hover_bg = QColor(_CLOSE_HOVER) if closing else QColor(theme.BG_SIDEBAR_HOVER)
            painter.fillRect(self.rect(), hover_bg)
        else:
            hover_bg = QColor(theme.BG_SIDEBAR)

        ink = QColor(theme.TEXT_WHITE if (closing and self._hover) else theme.TEXT_SECONDARY)
        pen = QPen(ink, 1.2)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)

        cx, cy = self.width() / 2.0, self.height() / 2.0
        if self.kind == "min":
            painter.drawLine(QPointF(cx - 5, cy + 0.5), QPointF(cx + 5, cy + 0.5))
        elif self.kind == "max" and not self._maximized:
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(cx - 5, cy - 5, 10, 10))
        elif self.kind == "max":
            # 还原图标：后面一层的方框先画，前景方框用底色遮住重叠线
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(cx - 3, cy - 5, 8, 8))
            painter.setBrush(QBrush(hover_bg))
            painter.drawRect(QRectF(cx - 5, cy - 3, 8, 8))
        else:
            painter.drawLine(QPointF(cx - 5, cy - 5), QPointF(cx + 5, cy + 5))
            painter.drawLine(QPointF(cx + 5, cy - 5), QPointF(cx - 5, cy + 5))
        painter.end()


class TitleBar(QWidget):
    """窗口自定义标题栏：拖动移动、双击最大化、右侧三个窗口按钮。"""

    HEIGHT = 38

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self._window = window
        self._press_global = None
        self.setFixedHeight(self.HEIGHT)
        self.setObjectName("appTitleBar")
        self.setStyleSheet(
            f"#appTitleBar {{ background-color: {theme.BG_SIDEBAR};"
            f" border-bottom: 1px solid {theme.BORDER}; }}")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 0, 0)
        layout.setSpacing(0)

        self.title_label = QLabel(window.windowTitle())
        self.title_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: 12px; background: transparent;")
        self.title_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.title_label)
        layout.addStretch()

        self.min_button = WindowButton("min", self)
        self.max_button = WindowButton("max", self)
        self.close_button = WindowButton("close", self)
        for button in (self.min_button, self.max_button, self.close_button):
            layout.addWidget(button)

        window.installEventFilter(self)

    # ---------------------------------------------------------------- 窗口交互
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_global is not None and event.buttons() & Qt.LeftButton:
            moved = event.globalPosition().toPoint() - self._press_global
            if moved.manhattanLength() >= 4:
                self._press_global = None
                self._start_move()
        event.accept()

    def mouseReleaseEvent(self, event):
        self._press_global = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._toggle_maximize()
        super().mouseDoubleClickEvent(event)

    def _start_move(self):
        if self._window.isMaximized():
            self._window.showNormal()
        handle = self._window.windowHandle()
        if handle is not None:
            handle.startSystemMove()

    def _toggle_maximize(self):
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def eventFilter(self, obj, event):
        if obj is self._window and event.type() == QEvent.WindowStateChange:
            self.max_button.set_maximized(self._window.isMaximized())
        return super().eventFilter(obj, event)
