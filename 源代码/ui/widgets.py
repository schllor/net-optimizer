"""
自绘可视化组件 - 信号弧 / 评分环
为 PySide6 提供 HTML 设计稿中的环形与弧段可视化，替代单调的进度条。
"""

from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from PySide6.QtCore import Qt, QRectF
import core.theme as theme


class SignalArcWidget(QWidget):
    """Wi-Fi 四段弧信号表：顶点朝上张开的拱形，亮几格一眼可辨弱/满。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._signal = 0          # 0 - 100
        self._color = theme.TEXT_MAIN
        self.setMinimumSize(120, 92)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_signal(self, signal, color=theme.TEXT_MAIN):
        self._signal = max(0, min(100, int(signal)))
        self._color = color
        self.update()

    def _bars(self):
        s = self._signal
        if s >= 80:
            return 4
        if s >= 60:
            return 3
        if s >= 40:
            return 2
        if s >= 20:
            return 1
        return 0

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        cx = w / 2.0
        cy = self.height() - 6.0            # 弧脚所在（底部中心）
        base_r = min(cx, cy) * 0.98
        pen_w = max(5, min(w, self.height()) // 14)

        on = QColor(self._color)
        off = QColor(theme.BG_RAISED)
        bars = self._bars()

        # 内圈序号 k=0（半径最小）到 k=3（半径最大）；信号越强点亮的 k 越多
        for k in range(4):
            r = base_r * (k + 1) / 4.0
            rect = QRectF(cx - r, cy - r, 2.0 * r, 2.0 * r)
            pen = QPen(on if k < bars else off, pen_w)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            # 圆心在底部，弧从约 200° 顺时针 220° 到右下，顶点在顶部
            painter.drawArc(rect, 200 * 16, -220 * 16)

        # 底部中心小圆点
        painter.setPen(Qt.NoPen)
        painter.setBrush(on if bars > 0 else off)
        d = pen_w + 2
        painter.drawEllipse(QRectF(cx - d / 2.0, cy - d / 2.0, d, d))
        painter.end()


class ScoreRingWidget(QWidget):
    """环形评分：背景环 + 按分数填充的前景弧，中心显示分数与说明。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._score = 0            # 0 - 100
        self._color = theme.TEXT_MAIN
        self._caption = "健康分"
        self._unknown = True       # 未知分数（无历史诊断）时显示占位
        self.setMinimumSize(120, 120)

    def set_score(self, score, color=theme.TEXT_MAIN, caption=None):
        self._unknown = False
        self._score = max(0, min(100, int(score)))
        self._color = color
        if caption:
            self._caption = caption
        self.update()

    def set_unknown(self, caption="健康分"):
        self._unknown = True
        self._caption = caption
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height())
        pen_w = max(8, side // 12)
        r = side / 2.0 - pen_w
        rect = QRectF(self.width() / 2.0 - r, self.height() / 2.0 - r, 2.0 * r, 2.0 * r)

        # 背景环
        bg_pen = QPen(QColor(theme.BG_RAISED), pen_w)
        bg_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(bg_pen)
        painter.drawArc(rect, 0, 360 * 16)

        if not self._unknown:
            fg = QColor(self._color)
            fg_pen = QPen(fg, pen_w)
            fg_pen.setCapStyle(Qt.RoundCap)
            painter.setPen(fg_pen)
            span = -int(self._score / 100.0 * 360 * 16)
            painter.drawArc(rect, 90 * 16, span)

        # 中心文字
        painter.setPen(QColor(theme.TEXT_MAIN))
        num_font = QFont()
        num_font.setPixelSize(max(18, side // 4))
        num_font.setBold(True)
        painter.setFont(num_font)
        num_rect = QRectF(self.width() / 2.0 - r, self.height() / 2.0 - r * 0.6, 2.0 * r, r)
        center_text = "--" if self._unknown else str(self._score)
        painter.drawText(num_rect, Qt.AlignCenter, center_text)

        cap_font = QFont()
        cap_font.setPixelSize(max(10, side // 12))
        cap_font.setBold(False)
        painter.setFont(cap_font)
        painter.setPen(QColor(theme.TEXT_LIGHT))
        cap_rect = QRectF(self.width() / 2.0 - r, self.height() / 2.0 + r * 0.05, 2.0 * r, r * 0.5)
        painter.drawText(cap_rect, Qt.AlignCenter, self._caption)
        painter.end()


class LatencyBarWidget(QWidget):
    """横向延迟对比条：按统一比例绘制各 DNS 解析耗时，长短一眼可辨快慢。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._latency = 0.0
        self._max_latency = 1.0
        self._color = theme.TEXT_MAIN
        self._available = True
        self.setMinimumSize(110, 18)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_latency(self, latency, max_latency, color=theme.TEXT_MAIN):
        self._available = True
        self._latency = max(0.0, float(latency))
        self._max_latency = max(1.0, float(max_latency))
        self._color = color
        self.update()

    def set_unavailable(self):
        self._available = False
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()
        track_h = 8.0
        y = (h - track_h) / 2.0

        # 底色槽
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.BG_RAISED))
        painter.drawRoundedRect(QRectF(0, y, w, track_h), track_h / 2.0, track_h / 2.0)

        if self._available:
            frac = min(1.0, self._latency / self._max_latency)
            bar_w = max(6.0, w * frac)
            painter.setBrush(QColor(self._color))
            painter.drawRoundedRect(QRectF(0, y, bar_w, track_h), track_h / 2.0, track_h / 2.0)

        painter.end()
