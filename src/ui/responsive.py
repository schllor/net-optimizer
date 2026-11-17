"""响应式布局基础：断点、两列 -> 单列切换、页面计数。

窗口尺寸变化时 MainWindow 会统一调用：

    page_head.set_compact(compact)          # 页头动作换行
    columns.set_compact(compact)            # 两列改单列
    sidebar.set_compact(compact)            # 图标侧栏

页面只负责把左右两列交给 ResponsiveColumns，不再自己判断窗口大小。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QBoxLayout, QHBoxLayout, QVBoxLayout, QWidget,
)

COMPACT_WIDTH = 1120
COMPACT_HEIGHT = 760
WIDE_WIDTH = 1440
WIDE_HEIGHT = 860


def mode_for(width, height):
    """返回 compact / regular / wide。"""
    try:
        width, height = int(width), int(height)
    except (TypeError, ValueError):
        return "regular"
    if width < COMPACT_WIDTH or height < COMPACT_HEIGHT:
        return "compact"
    if width >= WIDE_WIDTH and height >= WIDE_HEIGHT:
        return "wide"
    return "regular"


def is_compact(mode):
    return mode == "compact"


class ResponsiveColumns(QWidget):
    """左右两列容器；compact 时改为上下单列。

    页面使用方式：

        cols = ResponsiveColumns(left_stretch=16, right_stretch=10)
        layout.addWidget(cols, 1)
        cols.left.addWidget(card_a)
        cols.right.addWidget(card_b)

    ``left`` / ``right`` 都是 QVBoxLayout，页面代码与原来的 vbox 用法一致。
    """

    def __init__(self, left_stretch=1, right_stretch=1, spacing=14, parent=None):
        super().__init__(parent)
        self._left_stretch = left_stretch
        self._right_stretch = right_stretch
        self._compact = False

        self._outer = QBoxLayout(QBoxLayout.LeftToRight, self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(spacing)

        self._left_widget = QWidget()
        self.left = QVBoxLayout(self._left_widget)
        self.left.setContentsMargins(0, 0, 0, 0)
        self.left.setSpacing(spacing)

        self._right_widget = QWidget()
        self.right = QVBoxLayout(self._right_widget)
        self.right.setContentsMargins(0, 0, 0, 0)
        self.right.setSpacing(spacing)

        self._outer.addWidget(self._left_widget, left_stretch)
        self._outer.addWidget(self._right_widget, right_stretch)

    # ---------------------------------------------------------------- 兼容接口
    def add_left(self, widget, stretch=0, alignment=None):
        """把整块控件（如一张 Card）作为左列。"""
        if alignment is None:
            self.left.addWidget(widget, stretch)
        else:
            self.left.addWidget(widget, stretch, alignment)
        return widget

    def add_right(self, widget, stretch=0, alignment=None):
        if alignment is None:
            self.right.addWidget(widget, stretch)
        else:
            self.right.addWidget(widget, stretch, alignment)
        return widget

    def add_left_layout(self, layout):
        self.left.addLayout(layout)
        return layout

    def add_right_layout(self, layout):
        self.right.addLayout(layout)
        return layout

    # ---------------------------------------------------------------- 模式
    @property
    def compact(self):
        return self._compact

    def set_compact(self, compact):
        compact = bool(compact)
        if compact == self._compact:
            return
        self._compact = compact
        while self._outer.count():
            self._outer.takeAt(0)
        if compact:
            self._outer.setDirection(QBoxLayout.TopToBottom)
            self._outer.addWidget(self._left_widget, 1)
            self._outer.addWidget(self._right_widget, 1)
        else:
            self._outer.setDirection(QBoxLayout.LeftToRight)
            self._outer.addWidget(self._left_widget, self._left_stretch)
            self._outer.addWidget(self._right_widget, self._right_stretch)
        self.updateGeometry()


class PageScroll(QWidget):
    """页面外层：内容超出高度时纵向滚动，横屏不够时允许横向滚动。

    保持 ``page`` 自身的对象身份不变（测试与页面代码仍使用
    ``window.home_page``），只是把滚动容器放进 QStackedWidget。
    """

    def __init__(self, page, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QFrame, QScrollArea

        self.page = page
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }")
        self.scroll.setWidget(page)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)
        layout.addWidget(self.scroll)
