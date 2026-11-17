"""设计稿组件库：把 ui-samples.html 的卡片、胶囊、环形分数、仪表与图表
映射成 PySide6 控件，页面只负责按设计稿的结构摆放。

所有颜色 / 字号 / 间距都取自 core.theme 里的 NOCTURNE 令牌与
design/ui-samples.html 的 CSS，像素值保持一致。
"""

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import (
    QBoxLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

import core.theme as theme
from ui import icons

SANS = theme.FONT_SANS
MONO = theme.FONT_MONO


# ---------------------------------------------------------------- 字体与文本
def font(size=12, weight=400, mono=False, ls=0.0, italic=False):
    f = QFont(MONO if mono else SANS)
    f.setPixelSize(theme.text_size(size))
    f.setWeight(QFont.Weight(weight))
    f.setItalic(italic)
    if ls:
        f.setLetterSpacing(QFont.AbsoluteSpacing, ls)
    return f


def apply_font(widget, size=12, weight=400, mono=False, ls=0.0):
    widget.setFont(font(size, weight, mono, ls))
    return widget


def lbl(text="", size=12, color=theme.TEXT_MAIN, weight=400, mono=False,
        ls=0.0, wrap=False, align=None):
    label = QLabel(text)
    apply_font(label, size, weight, mono, ls)
    label.setStyleSheet(f"color: {color}; background: transparent;")
    if wrap:
        label.setWordWrap(True)
    if align is not None:
        label.setAlignment(align)
    return label


def mono(text="", size=9, color=theme.TEXT_2, ls=0.0):
    return lbl(text, size, color, 400, True, ls)


def eyebrow(text, size=8, color=theme.TEXT_3):
    """全大写、字距很大的等宽小标签。"""
    return lbl(text, size, color, 500, True, size * 0.22)


def label_caps(text, color=theme.TEXT_4):
    return eyebrow(text, 8, color)


def dot(style="", size=5):
    return Dot(style, size)


# ---------------------------------------------------------------- 布局工具
def hbox(spacing=0, margins=(0, 0, 0, 0), parent=None):
    layout = QHBoxLayout(parent)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return layout


def vbox(spacing=0, margins=(0, 0, 0, 0), parent=None):
    layout = QVBoxLayout(parent)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return layout


def hline(color=theme.LINE):
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background-color: {color}; border: none;")
    return line


def vline(color=theme.LINE):
    line = QFrame()
    line.setFixedWidth(1)
    line.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
    line.setStyleSheet(f"background-color: {color}; border: none;")
    return line


# ---------------------------------------------------------------- 卡片
class Card(QFrame):
    """CSS .card：14px 圆角、1px 发丝描边、自上而下极淡的白色渐变。"""

    def __init__(self, padding=16, spacing=0, radius=14, bg=None,
                 border=theme.LINE, parent=None):
        super().__init__(parent)
        self.setObjectName("kitCard")
        if bg:
            background = bg
        else:
            background = (
                "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
                f"stop:0 {theme.CARD_TOP}, stop:1 {theme.CARD_BOTTOM})")
        self.setStyleSheet(
            f"QFrame#kitCard {{ background: {background};"
            f" border: 1px solid {border}; border-radius: {radius}px; }}")
        self.body = vbox(spacing, (padding, padding, padding, padding), self)

    def add(self, widget, stretch=0, align=None):
        if align is None:
            self.body.addWidget(widget, stretch)
        else:
            self.body.addWidget(widget, stretch, align)
        return widget

    def add_layout(self, layout, stretch=0):
        self.body.addLayout(layout, stretch)
        return layout

    def head(self, title, note=""):
        """卡片头：11px 标题 + 右侧 8px 等宽说明。"""
        row = QWidget()
        layout = hbox(12, (0, 0, 0, 0), row)
        layout.addWidget(lbl(title, 11, theme.TEXT_MAIN, 600))
        layout.addStretch()
        if note:
            layout.addWidget(lbl(note, 8, theme.TEXT_4, 400, True, 0.8))
        self.body.addWidget(row)
        return row


# ---------------------------------------------------------------- 基础元件
class Dot(QWidget):
    def __init__(self, style="", size=5, parent=None):
        super().__init__(parent)
        self._style = style
        self._size = size
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event):
        colors = {"ok": theme.MINT, "warn": theme.WARNING,
                  "error": theme.ERROR}
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(colors.get(self._style, theme.TEXT_3)))
        painter.drawEllipse(QRectF(0, 0, self._size, self._size))
        painter.end()

    def set_style(self, style):
        if style != self._style:
            self._style = style
            self.update()


class Pill(QFrame):
    """CSS .pill：圆角胶囊，可选状态点。"""

    TONES = {
        "": (theme.TEXT_2, theme.LINE, None),
        "ok": (theme.MINT, theme.MINT_LINE, theme.MINT_DIM),
        "warn": (theme.WARNING, theme.WARNING_LINE, None),
        "dim": (theme.TEXT_3, theme.LINE, None),
        "on": (theme.TEXT_MAIN, theme.LINE_STRONG, None),
    }

    def __init__(self, text="", tone="", dot_style=None, small=False,
                 icon_name=None, parent=None):
        super().__init__(parent)
        color, border, bg = self.TONES.get(tone, self.TONES[""])
        pad_x, pad_y = (7, 4) if small else (11, 6)
        self.setStyleSheet(
            f"QFrame {{ background-color: {bg or 'transparent'};"
            f" border: 1px solid {border}; border-radius: 9px; }}")
        layout = hbox(7, (pad_x, pad_y, pad_x, pad_y), self)
        if dot_style is not None:
            layout.addWidget(Dot(dot_style))
        if icon_name:
            layout.addWidget(ic(icon_name, 11, color))
        self._label = lbl(text, 10 if not small else 9, color, 400, True, 0.8)
        layout.addWidget(self._label)

    def setText(self, text):
        self._label.setText(text)

    def text(self):
        return self._label.text()


class Switch(QWidget):
    """44×26 开关：开启为纸白底 + 深色圆钮，关闭为深灰底 + 灰钮。"""

    toggled = Signal(bool)

    def __init__(self, checked=True, parent=None):
        super().__init__(parent)
        self._checked = bool(checked)
        self.setFixedSize(44, 26)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("开关")

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        checked = bool(checked)
        if checked != self._checked:
            self._checked = checked
            self.update()
            self.toggled.emit(checked)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.setChecked(not self._checked)
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(
                event.position().toPoint()):
            self.setChecked(not self._checked)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.PAPER if self._checked else "#232329"))
        painter.drawRoundedRect(QRectF(0, 0, 44, 26), 13, 13)
        painter.setBrush(QColor("#08080a" if self._checked else theme.TEXT_3))
        x = 21 if self._checked else 3
        painter.drawEllipse(QRectF(x, 3, 20, 20))
        if self.hasFocus():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(theme.FOCUS), 1.5))
            painter.drawRoundedRect(QRectF(1, 1, 42, 24), 12, 12)
        painter.end()


class _SegLabel(QLabel):
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class Segmented(QFrame):
    """CSS .seg：分段选择器，选中段为纸白实心块。"""

    currentChanged = Signal(int)

    def __init__(self, options, current=0, parent=None):
        super().__init__(parent)
        self._labels = []
        self._current = current
        self.setStyleSheet(
            "QFrame { border: 1px solid " + theme.LINE +
            "; border-radius: 7px; background: transparent; }")
        layout = hbox(2, (2, 2, 2, 2), self)
        for index, text in enumerate(options):
            item = _SegLabel(text)
            item.setCursor(Qt.PointingHandCursor)
            item.setFocusPolicy(Qt.StrongFocus)
            item.setAccessibleName(text)
            item.setAlignment(Qt.AlignCenter)
            item.setFixedHeight(26)
            item.clicked.connect(lambda i=index: self.set_current(i, emit=True))
            layout.addWidget(item)
            self._labels.append(item)
        self._restyle()

    def _restyle(self):
        for index, item in enumerate(self._labels):
            active = index == self._current
            item.setStyleSheet(
                "QLabel { border-radius: 5px; padding: 0 10px;"
                f" font-size: {theme.text_size(9)}px;"
                f" font-weight: {600 if active else 400};"
                f" color: {'#050506' if active else theme.TEXT_3};"
                f" background-color: {theme.PAPER if active else 'transparent'}; }}"
            )

    def set_current(self, index, emit=False):
        if 0 <= index < len(self._labels) and index != self._current:
            self._current = index
            self._restyle()
            if emit:
                self.currentChanged.emit(index)

    def current(self):
        return self._current


class IconButton(QFrame):
    """32×32 发丝描边图标按钮。"""

    clicked = Signal()

    def __init__(self, icon_name, size=32, icon_size=14,
                 color=theme.TEXT_3, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(icon_name)
        self.setStyleSheet(
            f"QFrame {{ border: 1px solid {theme.LINE}; border-radius: 8px;"
            " background: transparent; }"
            f"QFrame:hover {{ border-color: {theme.LINE_STRONG}; }}")
        layout = vbox(0, (0, 0, 0, 0), self)
        layout.setAlignment(Qt.AlignCenter)
        layout.addWidget(ic(icon_name, icon_size, color), 0, Qt.AlignCenter)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(
                event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class Hint(QFrame):
    """浅绿提示条：图标 + 9px 说明。"""

    def __init__(self, text, icon_name="check", tone="mint", parent=None):
        super().__init__(parent)
        bg = theme.MINT_DIM if tone == "mint" else "transparent"
        border = theme.LINE
        color = theme.TEXT_2
        icon_color = theme.MINT if tone == "mint" else theme.TEXT_3
        self.setStyleSheet(
            f"QFrame {{ background-color: {bg}; border: 1px solid {border};"
            " border-radius: 8px; }")
        layout = hbox(8, (10, 9, 10, 9), self)
        layout.addWidget(ic(icon_name, 12, icon_color))
        self._label = lbl(text, 9, color, 400, False, 0, wrap=True)
        layout.addWidget(self._label, 1)

    def setText(self, text):
        self._label.setText(text)


class Avatar(QFrame):
    def __init__(self, icon_name, size=32, color=theme.TEXT_2,
                 border=theme.LINE_STRONG, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setStyleSheet(
            f"QFrame {{ border: 1px solid {border}; border-radius: 9px;"
            " background-color: #0e0e12; }")
        layout = vbox(0, (0, 0, 0, 0), self)
        layout.setAlignment(Qt.AlignCenter)
        layout.addWidget(ic(icon_name, int(size * 0.47), color), 0, Qt.AlignCenter)


def ic(name, size=15, color=theme.TEXT_2, stroke=1.6):
    """SVG 线条图标标签。"""
    label = QLabel()
    label.setPixmap(icons.pixmap(name, size, color, stroke))
    label.setFixedSize(size, size)
    label.setStyleSheet("background: transparent; border: none;")
    label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    return label


# ---------------------------------------------------------------- 按钮
def primary_button(text, icon_name=None, small=True):
    button = QPushButton(text)
    button.setCursor(Qt.PointingHandCursor)
    button.setFixedHeight(theme.HIT_PRIMARY if small else 44)
    button.setStyleSheet(
        "QPushButton { background-color: #f3f4f6; color: #050506; border: none;"
        f" border-radius: {8 if small else 10}px;"
        f" font-size: {theme.text_size(11 if small else 12)}px;"
        " font-weight: 600;"
        f" padding: 0 {14 if small else 20}px; }}"
        "QPushButton:hover { background-color: #ffffff; }"
        "QPushButton:pressed { background-color: #d7d9de; }"
        "QPushButton:focus { border: 2px solid #8bffd1; }"
        "QPushButton:disabled { background-color: #17171a; color: #7a7d85; }")
    if icon_name:
        button.setIcon(icons.pixmap(icon_name, 14 if small else 14, "#050506", 2))
        button.setIconSize(QSize(14, 14))
    return button


def ghost_button(text, small=True, icon_name=None):
    button = QPushButton(text)
    button.setCursor(Qt.PointingHandCursor)
    button.setFixedHeight(theme.HIT_SMALL if small else 44)
    button.setStyleSheet(
        "QPushButton { background-color: transparent; color: #f3f4f6;"
        f" border: 1px solid {theme.LINE_STRONG};"
        f" border-radius: {8 if small else 10}px;"
        f" font-size: {theme.text_size(11 if small else 12)}px;"
        " font-weight: 500;"
        f" padding: 0 {14 if small else 20}px; }}"
        "QPushButton:hover { background-color: #17171a; border-color: #33ffffff; }"
        "QPushButton:focus { border: 2px solid #8bffd1; }"
        "QPushButton:disabled { color: #7a7d85; border-color: #14ffffff; }")
    if icon_name:
        button.setIcon(icons.pixmap(icon_name, 13, theme.TEXT_MAIN, 1.8))
        button.setIconSize(QSize(13, 13))
    return button


# ---------------------------------------------------------------- 页头
class PageHead(QWidget):
    """CSS .page-head：左侧三行文字，右侧动作区顶对齐。

    compact 模式（窄窗口）时动作按钮移到描述下方并左对齐，避免把
    标题区挤成两行小字。MainWindow 会通过 findChildren 统一切换。
    """

    def __init__(self, eyebrow_text, title, desc, actions=(), parent=None):
        super().__init__(parent)
        self._compact = False
        self._title_text = title
        self._desc_text = desc
        self._actions = list(actions)

        self._outer = QHBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(20)

        self._text_wrap = QWidget()
        text = vbox(0, (0, 0, 0, 0), self._text_wrap)
        text.addWidget(eyebrow(eyebrow_text))
        self._title_label = lbl(title, 24, theme.TEXT_MAIN, 600, False, -0.7)
        self._title_label.setContentsMargins(0, 9, 0, 0)
        text.addWidget(self._title_label)
        self._desc_label = None
        if desc:
            self._desc_label = lbl(desc, 10, theme.TEXT_3, 400, False, 0,
                                   wrap=True)
            self._desc_label.setContentsMargins(0, 7, 0, 0)
            self._desc_label.setMaximumWidth(520)
            text.addWidget(self._desc_label)
        self._outer.addWidget(self._text_wrap, 1)

        self._action_row = hbox(8, (0, 0, 0, 0))
        self._action_row.setAlignment(Qt.AlignTop)
        for item in self._actions:
            self._action_row.addWidget(item)
        self._action_holder = QWidget()
        self._action_holder.setLayout(self._action_row)
        self._outer.addWidget(self._action_holder, 0, Qt.AlignTop)

    def set_compact(self, compact):
        compact = bool(compact)
        if compact == self._compact:
            return
        self._compact = compact
        self._outer.setDirection(
            QBoxLayout.TopToBottom if compact else QBoxLayout.LeftToRight)
        self._outer.setSpacing(12 if compact else 20)
        if compact:
            self._outer.setAlignment(self._action_holder, Qt.AlignLeft)
            self._title_label.setFont(font(22, 600, ls=-0.6))
            self._title_label.setContentsMargins(0, 7, 0, 0)
            if self._desc_label is not None:
                self._desc_label.setMaximumWidth(16777215)
        else:
            self._outer.setAlignment(self._action_holder, Qt.AlignTop)
            self._title_label.setFont(font(24, 600, ls=-0.7))
            self._title_label.setContentsMargins(0, 9, 0, 0)
            if self._desc_label is not None:
                self._desc_label.setMaximumWidth(520)

    def set_title(self, text):
        self._title_text = str(text)
        self._title_label.setText(self._title_text)

    def set_desc(self, text):
        self._desc_text = str(text or "")
        if self._desc_label is None:
            if not self._desc_text:
                return
            self._desc_label = lbl(self._desc_text, 10, theme.TEXT_3, 400,
                                   False, 0, wrap=True)
            self._desc_label.setContentsMargins(0, 7, 0, 0)
            self._desc_label.setMaximumWidth(
                16777215 if self._compact else 520)
            self._text_wrap.layout().addWidget(self._desc_label)
        else:
            self._desc_label.setText(self._desc_text)


def page_head(eyebrow_text, title, desc, actions=()):
    """保持旧调用点不变，返回可按 compact 重排的 PageHead。"""
    return PageHead(eyebrow_text, title, desc, actions)


def vspace(height):
    spacer = QWidget()
    spacer.setFixedHeight(height)
    return spacer


# ---------------------------------------------------------------- 卡片头 / 键值行
def card_head(title, note="", note_widget=None):
    widget = QWidget()
    layout = hbox(12, (0, 0, 0, 0), widget)
    layout.addWidget(lbl(title, 11, theme.TEXT_MAIN, 600))
    layout.addStretch()
    if note_widget is not None:
        layout.addWidget(note_widget)
    elif note:
        layout.addWidget(lbl(note, 8, theme.TEXT_4, 400, True, 0.8))
    return widget


def kv_row(key, value, value_color=theme.TEXT_MAIN, key_size=9,
           value_size=9):
    widget = QWidget()
    layout = hbox(10, (0, 9, 0, 9), widget)
    layout.addWidget(lbl(key, key_size, theme.TEXT_3))
    layout.addStretch()
    layout.addWidget(lbl(value, value_size, value_color, 400, True, 0.2))
    return widget


# ---------------------------------------------------------------- 统计块
class Metric(QWidget):
    """CSS .metric：9px 灰色标签 + 21px 数值 + 9px 单位。"""

    def __init__(self, key, value="--", unit="", value_size=21, parent=None):
        super().__init__(parent)
        layout = vbox(0, (0, 0, 0, 0), self)
        layout.addWidget(lbl(key, 9, theme.TEXT_3))
        row = hbox(3, (0, 5, 0, 0))
        self._value = lbl(value, value_size, theme.TEXT_MAIN, 600, False,
                          -value_size * 0.035)
        row.addWidget(self._value)
        if unit:
            unit_label = lbl(unit, 9, theme.TEXT_3)
            unit_label.setContentsMargins(0, 3, 0, 2)
            row.addWidget(unit_label, 0, Qt.AlignBottom)
        row.addStretch()
        layout.addLayout(row)

    def set_value(self, text):
        self._value.setText(text)


class MiniGrid(QFrame):
    """1px 分隔线的统计格子（mini-grid / stat-strip）。"""

    def __init__(self, items, columns=2, padding=(11, 12), parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ background-color: {theme.LINE};"
            " border-radius: 9px; }")
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(1)
        for index, (key, value, unit, color) in enumerate(items):
            cell = QFrame()
            cell.setStyleSheet(
                f"QFrame {{ background-color: {theme.SURFACE}; border: none; }}")
            box = vbox(0, (padding[0], padding[1], padding[0], padding[1]), cell)
            box.addWidget(lbl(key, 8, theme.TEXT_4, 400, False, 0.6))
            row = hbox(3, (0, 0, 0, 0))
            row.addWidget(lbl(value, 17, color, 600, False, -0.5))
            if unit:
                unit_label = lbl(unit, 8, theme.TEXT_3)
                unit_label.setContentsMargins(0, 6, 0, 0)
                row.addWidget(unit_label, 0, Qt.AlignBottom)
            row.addStretch()
            box.addLayout(row)
            grid.addWidget(cell, index // columns, index % columns)
        for index in range(columns):
            grid.setColumnStretch(index, 1)


# ---------------------------------------------------------------- 自绘可视化
class ScoreRing(QWidget):
    """环形分数：6px 环宽、纸白弧 + 极淡底环，中心分数 + 等宽小标题。"""

    def __init__(self, size=142, score=0, caption="HEALTH SCORE",
                 score_size=44, caption_size=8, parent=None):
        super().__init__(parent)
        self._score = max(0, min(100, int(score)))
        self._caption = caption
        self._score_size = score_size
        self._caption_size = caption_size
        self._unknown = False
        self.setFixedSize(size, size)

    def set_score(self, score, color=None, caption=None):
        self._score = max(0, min(100, int(score)))
        self._unknown = False
        if caption is not None:
            self._caption = caption
        self.update()

    def set_unknown(self, caption="HEALTH SCORE"):
        self._unknown = True
        self._caption = caption
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height())
        inset = 6.0
        rect = QRectF(inset / 2, inset / 2, side - inset, side - inset)

        pen = QPen(QColor(255, 255, 255, 19), inset)
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)
        painter.drawArc(rect, 0, 360 * 16)

        if not self._unknown and self._score > 0:
            pen = QPen(QColor(theme.PAPER), inset)
            pen.setCapStyle(Qt.FlatCap)
            painter.setPen(pen)
            painter.drawArc(rect, 90 * 16, -int(self._score * 3.6 * 16))

        painter.setPen(QColor(theme.PAPER))
        painter.setFont(font(self._score_size, 600, ls=-self._score_size * 0.06))
        value_rect = QRectF(0, side / 2 - self._score_size * 0.62,
                            side, self._score_size * 1.1)
        painter.drawText(value_rect, Qt.AlignCenter,
                         "—" if self._unknown else str(self._score))

        painter.setPen(QColor(theme.TEXT_4))
        painter.setFont(font(self._caption_size, 400, True,
                             self._caption_size * 0.18))
        cap_rect = QRectF(0, side / 2 + self._score_size * 0.42,
                          side, self._caption_size * 2)
        painter.drawText(cap_rect, Qt.AlignHCenter | Qt.AlignTop, self._caption)
        painter.end()


class Gauge(QWidget):
    """180° 速度仪表：刻度、弧、指针与中央读数，尺寸按 460×260 等比缩放。"""

    def __init__(self, max_value=600, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self._max = float(max_value)
        self.setMinimumHeight(210)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_value(self, value, max_value=None):
        self._value = max(0.0, float(value))
        if max_value:
            self._max = float(max_value)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        scale = min(w / 460.0, h / 260.0)
        painter.translate((w - 460 * scale) / 2.0, (h - 260 * scale) / 2.0)
        painter.scale(scale, scale)

        cx, cy = 230.0, 230.0
        arc_rect = QRectF(cx - 190, cy - 190, 380, 380)

        pen = QPen(QColor(255, 255, 255, 23), 2)
        painter.setPen(pen)
        painter.drawArc(arc_rect, 0, 180 * 16)

        ratio = min(1.0, self._value / self._max) if self._max else 0.0
        pen = QPen(QColor(theme.PAPER), 2)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawArc(arc_rect, 180 * 16, -int(ratio * 180 * 16))

        # 刻度：25 根，每 4 根加亮
        for i in range(25):
            angle = math.radians(-90 + i * 7.5)
            r1 = 173 if i % 4 == 0 else 180
            painter.setPen(QPen(
                QColor(255, 255, 255, 82 if i % 4 == 0 else 33), 1))
            painter.drawLine(
                QPointF(cx + r1 * math.sin(angle), cy - r1 * math.cos(angle)),
                QPointF(cx + 188 * math.sin(angle), cy - 188 * math.cos(angle)))

        # 指针
        needle = math.radians(-90 + ratio * 180)
        pen = QPen(QColor(theme.PAPER), 2.4)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawLine(QPointF(cx, cy), QPointF(
            cx + 132 * math.sin(needle), cy - 132 * math.cos(needle)))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.PAPER))
        painter.drawEllipse(QPointF(cx, cy), 6, 6)
        painter.setBrush(QColor("#050506"))
        painter.drawEllipse(QPointF(cx, cy), 2.2, 2.2)

        # 刻度文字
        painter.setPen(QColor(theme.TEXT_3))
        painter.setFont(font(8, 400, True))
        for x, y, text in ((25, 247, "0"), (85, 92, "150"), (230, 31, "300"),
                           (375, 92, "450"), (435, 247, "600")):
            painter.drawText(QRectF(x - 24, y - 10, 48, 12),
                             Qt.AlignCenter, text)

        # 中央读数
        painter.setPen(QColor(theme.PAPER))
        painter.setFont(font(62, 600, ls=-3.7))
        painter.drawText(QRectF(0, 40, 460, 70), Qt.AlignCenter,
                         f"{self._value:.1f}")
        painter.end()

    def pill_pos(self, pill):
        """把胶囊放到读数下方居中（供包含 Gauge 的页面定位子控件）。"""
        return (self.width() - pill.width()) // 2, int(self.height() * 0.52) + 48


class AreaChart(QWidget):
    """吞吐 / 速度折线图：极淡网格 + 白色面积线 + 薄荷绿副线。"""

    def __init__(self, down=None, up=None, parent=None):
        super().__init__(parent)
        self._down = list(down or [])
        self._up = list(up or [])
        self.setMinimumHeight(80)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_series(self, down=None, up=None):
        if down is not None:
            self._down = list(down)
        if up is not None:
            self._up = list(up)
        self.update()

    @staticmethod
    def _points(values, width, height):
        if not values:
            return []
        top, bottom = 4.0, height - 4.0
        step = width / max(1, len(values) - 1)
        return [(index * step, bottom - value * (bottom - top))
                for index, value in enumerate(values)]

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())

        painter.setPen(QPen(QColor(255, 255, 255, 15), 1))
        for i in range(1, 5):
            y = h * i / 5.0
            painter.drawLine(QPointF(0, y), QPointF(w, y))

        if self._down:
            points = self._points(self._down, w, h)
            path = QPainterPath(QPointF(0, h))
            for x, y in points:
                path.lineTo(x, y)
            path.lineTo(w, h)
            path.closeSubpath()
            gradient = QLinearGradient(0, 0, 0, h)
            gradient.setColorAt(0.0, QColor(255, 255, 255, 46))
            gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(gradient)
            painter.drawPath(path)

            line = QPainterPath()
            line.moveTo(*points[0])
            for x, y in points[1:]:
                line.lineTo(x, y)
            painter.setPen(QPen(QColor(theme.PAPER), 1.6))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(line)

            last_x, last_y = points[-1]
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255, 26))
            painter.drawEllipse(QPointF(last_x, last_y), 8, 8)
            painter.setBrush(QColor(theme.PAPER))
            painter.drawEllipse(QPointF(last_x, last_y), 3, 3)

        if self._up:
            points = self._points(self._up, w, h)
            line = QPainterPath()
            line.moveTo(*points[0])
            for x, y in points[1:]:
                line.lineTo(x, y)
            pen = QPen(QColor(139, 255, 209, 204), 1)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(line)
        painter.end()


class Bars(QWidget):
    """柱状图：频谱 / 历史测速 / 路由器负载共用。

    每项为 (比例 0-1, 样式)，样式：on / mid / cur / best / hot / mint / ''
    """

    STYLES = {
        "": QColor(255, 255, 255, 31),
        "mid": QColor(255, 255, 255, 77),
        "cur": QColor(theme.PAPER),
        "on": QColor(theme.PAPER),
        "best": QColor(theme.MINT),
        "hot": QColor(theme.MINT),
        "mint": QColor(theme.MINT),
    }

    def __init__(self, values=None, gap=2, radius=1, parent=None):
        super().__init__(parent)
        self._values = list(values or [])
        self._gap = gap
        self._radius = radius
        self.setMinimumHeight(12)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_values(self, values):
        self._values = list(values)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        count = len(self._values)
        if not count:
            painter.end()
            return
        w, h = float(self.width()), float(self.height())
        bar_w = max(1.0, (w - self._gap * (count - 1)) / count)
        for index, (ratio, style) in enumerate(self._values):
            bar_h = max(1.0, h * max(0.0, min(1.0, ratio)))
            color = self.STYLES.get(style, self.STYLES[""])
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(
                QRectF(index * (bar_w + self._gap), h - bar_h, bar_w, bar_h),
                self._radius, self._radius)
        painter.end()


class Spark(QWidget):
    """设备行尾的迷你柱：2px 宽、白色高亮一根。"""

    def __init__(self, values, highlight=-1, parent=None):
        super().__init__(parent)
        self._values = list(values)
        self._highlight = highlight
        self.setFixedHeight(14)
        self.setMinimumWidth(len(values) * 3)

    def paintEvent(self, event):
        painter = QPainter(self)
        count = len(self._values)
        if not count:
            painter.end()
            return
        h = float(self.height())
        for index, ratio in enumerate(self._values):
            color = QColor(theme.PAPER) if index == self._highlight \
                else QColor(255, 255, 255, 41)
            painter.fillRect(QRectF(index * 3, h - h * ratio, 2, h * ratio),
                             color)
        painter.end()


class Heatmap(QWidget):
    """活跃度热图：13px 方格、3px 间距，7 行按列排布。"""

    LEVELS = ("#0effffff", "#24ffffff", "#47ffffff", "#85ffffff", theme.MINT)

    def __init__(self, levels, rows=7, cell=13, gap=3, parent=None):
        super().__init__(parent)
        self._levels = list(levels)
        self._rows = rows
        self._cell = cell
        self._gap = gap
        columns = max(1, math.ceil(len(self._levels) / rows))
        self.setFixedSize(columns * cell + (columns - 1) * gap,
                          rows * cell + (rows - 1) * gap)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(Qt.NoPen)
        for index, level in enumerate(self._levels):
            column, row = divmod(index, self._rows)
            color = self.LEVELS[max(0, min(4, int(level)))]
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(
                QRectF(column * (self._cell + self._gap),
                       row * (self._cell + self._gap), self._cell, self._cell),
                2, 2)
        painter.end()


class LaneChart(QWidget):
    """多线程下载泳道：8 行 × 40 格，已完成为白色/薄荷绿，头部高亮。"""

    def __init__(self, lanes=8, columns=40, progress=68, parent=None):
        super().__init__(parent)
        self._lanes = lanes
        self._columns = columns
        self._progress = max(0, min(100, progress))
        self.setFixedHeight(lanes * 8 + (lanes - 1) * 5)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_progress(self, progress):
        self._progress = max(0, min(100, int(progress)))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        w = float(self.width())
        gap = 2.0
        cell_w = max(1.0, (w - gap * (self._columns - 1)) / self._columns)

        if self._progress <= 0:
            # 空闲态：棋盘格交替深浅，暗示"空槽已就绪"而不是死黑
            for lane in range(self._lanes):
                y = lane * 13
                for column in range(self._columns):
                    base = QColor("#18181e") if (column + lane) % 2 == 0 \
                        else QColor("#121217")
                    painter.fillRect(
                        QRectF(column * (cell_w + gap), y, cell_w, 8), base)
            painter.end()
            return

        for lane in range(self._lanes):
            # 每条 lane 的填充有轻微错位，让并发感更明显
            ratio = min(98, self._progress + ((lane * 7) % 9) - 4)
            ratio = max(0, ratio)
            filled = round(self._columns * ratio / 100.0)
            y = lane * 13
            for column in range(self._columns):
                if column < filled - 1:
                    # 已完成：薄荷绿方块（稀疏点缀）或纸白
                    if (column + lane * 3) % 11 == 0:
                        color = QColor(theme.MINT)
                    else:
                        color = QColor(229, 229, 229, 255)
                elif column < filled:
                    # 正在写入：纯白（头部高亮）
                    color = QColor(theme.PAPER)
                else:
                    # 未分配：棋盘格交替深浅
                    color = QColor("#18181e") if (column + lane) % 2 == 0 \
                        else QColor("#121217")
                painter.fillRect(QRectF(column * (cell_w + gap), y, cell_w, 8),
                                 color)
        painter.end()


class Bar(QWidget):
    """4px 细进度条（CSS .bar）。"""

    def __init__(self, ratio=0.0, color=theme.PAPER, height=4, parent=None):
        super().__init__(parent)
        self._ratio = max(0.0, min(1.0, ratio))
        self._color = color
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_ratio(self, ratio):
        self._ratio = max(0.0, min(1.0, ratio))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        h = float(self.height())
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 18))
        painter.drawRoundedRect(QRectF(0, 0, self.width(), h), h / 2, h / 2)
        painter.setBrush(QColor(self._color))
        painter.drawRoundedRect(
            QRectF(0, 0, max(h, self.width() * self._ratio), h), h / 2, h / 2)
        painter.end()


class Spectrum(QWidget):
    """Wi-Fi 信道占用频谱：细柱贴底，当前信道薄荷绿。"""

    def __init__(self, values, height=88, parent=None):
        super().__init__(parent)
        self._values = list(values)
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_values(self, values):
        self._values = list(values or [])
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        count = len(self._values)
        if not count:
            painter.end()
            return
        w, h = float(self.width()), float(self.height())
        gap = 2.0
        bar_w = max(1.0, (w - gap * (count - 1)) / count)
        for index, (ratio, style) in enumerate(self._values):
            if style == "cur":
                color = QColor(theme.MINT)
            elif style == "mid":
                color = QColor(255, 255, 255, 77)
            else:
                color = QColor(255, 255, 255, 31)
            bar_h = max(1.0, h * ratio)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(
                QRectF(index * (bar_w + gap), h - bar_h, bar_w, bar_h), 1, 1)
        painter.end()


class ProgressRing(QWidget):
    """小号百分比环（下载进度 104px / 诊断 112px）。"""

    def __init__(self, size=104, percent=0, caption="PERCENT",
                 score_size=28, caption_size=7, parent=None):
        super().__init__(parent)
        self._percent = max(0, min(100, int(percent)))
        self._caption = caption
        self._score_size = score_size
        self._caption_size = caption_size
        self.setFixedSize(size, size)

    def set_percent(self, percent):
        self._percent = max(0, min(100, int(percent)))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height())
        rect = QRectF(3, 3, side - 6, side - 6)
        pen = QPen(QColor(255, 255, 255, 19), 6)
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)
        painter.drawArc(rect, 0, 360 * 16)
        pen = QPen(QColor(theme.PAPER), 6)
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)
        painter.drawArc(rect, 90 * 16, -int(self._percent * 3.6 * 16))

        painter.setPen(QColor(theme.PAPER))
        painter.setFont(font(self._score_size, 600, ls=-1.4))
        painter.drawText(QRectF(0, side / 2 - self._score_size * 0.62, side,
                                self._score_size * 1.1),
                         Qt.AlignCenter, str(self._percent))
        painter.setPen(QColor(theme.TEXT_4))
        painter.setFont(font(self._caption_size, 400, True, 0.9))
        painter.drawText(QRectF(0, side / 2 + self._score_size * 0.42, side, 12),
                         Qt.AlignHCenter | Qt.AlignTop, self._caption)
        painter.end()
