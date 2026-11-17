"""自绘标题栏：44px 面包屑 + 状态胶囊 + 窗口按钮，与设计稿一致。"""

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

import core.theme as theme
from ui.kit import Dot, hbox, lbl

_CLOSE_HOVER = "#c42b1c"


class WindowGrip(QWidget):
    """无边框窗口边缘的缩放热区：只提供光标样式并发起系统缩放。"""

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

    WIDTH = 30

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
        if event.button() == Qt.LeftButton and self.rect().contains(
                event.position().toPoint()):
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
        hover_bg = QColor(theme.SURFACE_2)
        if self._hover:
            hover_bg = QColor(_CLOSE_HOVER) if closing else QColor("#111114")
            painter.fillRect(self.rect(), hover_bg)

        ink = QColor(theme.TEXT_WHITE if (closing and self._hover)
                     else theme.TEXT_3)
        pen = QPen(ink, 1.1)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)

        cx, cy = self.width() / 2.0, self.height() / 2.0
        if self.kind == "min":
            painter.drawLine(QPointF(cx - 4.5, cy + 0.5), QPointF(cx + 4.5, cy + 0.5))
        elif self.kind == "max" and not self._maximized:
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(cx - 4.5, cy - 4.5, 9, 9))
        elif self.kind == "max":
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(cx - 2.5, cy - 4.5, 7, 7))
            painter.setBrush(hover_bg if self._hover else QColor(theme.VOID))
            painter.drawRect(QRectF(cx - 4.5, cy - 2.5, 7, 7))
        else:
            painter.drawLine(QPointF(cx - 4.5, cy - 4.5), QPointF(cx + 4.5, cy + 4.5))
            painter.drawLine(QPointF(cx + 4.5, cy - 4.5), QPointF(cx - 4.5, cy + 4.5))
        painter.end()


class TitleBar(QWidget):
    """窗口标题栏：左侧面包屑，右侧连接状态与三个窗口按钮。"""

    HEIGHT = 44

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self._window = window
        self._press_global = None
        self.setFixedHeight(self.HEIGHT)
        self.setObjectName("appTitleBar")
        self.setStyleSheet(
            f"#appTitleBar {{ background-color: {theme.VOID};"
            f" border-bottom: 1px solid {theme.LINE}; }}")

        layout = hbox(8, (18, 0, 0, 0), self)
        layout.setAlignment(Qt.AlignVCenter)
        app_name = lbl("网络优化助手", 10, theme.TEXT_2, 500)
        crumb_sep = lbl("/", 10, theme.TEXT_4)
        layout.addWidget(app_name)
        layout.addWidget(crumb_sep)
        self._crumb_prefix = (app_name, crumb_sep)
        self.crumb_label = lbl("首页", 10, theme.TEXT_3)
        self.crumb_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.crumb_label)
        layout.addStretch()

        # 兼容旧接口：title_label 始终等于窗口标题（不显示）
        self.title_label = lbl(window.windowTitle(), 10, theme.TEXT_3)
        self.title_label.hide()

        self.conn_pill = QWidget()
        self.conn_pill.setObjectName("connPill")
        self.conn_pill.setAttribute(Qt.WA_StyledBackground, True)
        pill_layout = hbox(7, (9, 5, 9, 5), self.conn_pill)
        self.conn_pill.setStyleSheet(
            f"#connPill {{ border: 1px solid {theme.LINE}; border-radius: 9px;"
            " background: transparent; }")
        self.conn_dot = Dot("warn")
        pill_layout.addWidget(self.conn_dot)
        self.conn_label = lbl("正在检测网络…", 8, theme.TEXT_3, 400, True, 0.8)
        self.conn_label.setMaximumWidth(280)
        pill_layout.addWidget(self.conn_label)
        layout.addWidget(self.conn_pill)
        layout.addSpacing(6)

        self.min_button = WindowButton("min", self)
        self.max_button = WindowButton("max", self)
        self.close_button = WindowButton("close", self)
        for button in (self.min_button, self.max_button, self.close_button):
            layout.addWidget(button)

        window.installEventFilter(self)

    def set_crumb(self, text):
        self.title_label.setText(text)

    def set_compact(self, compact):
        """窄窗口下隐藏面包屑前缀与连接胶囊，只保留页面名和窗口按钮。"""
        compact = bool(compact)
        if getattr(self, "_compact", None) == compact:
            return
        self._compact = compact
        for widget in getattr(self, "_crumb_prefix", ()):
            widget.setVisible(not compact)
        self.conn_pill.setVisible(not compact)

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
