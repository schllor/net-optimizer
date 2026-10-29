"""
自绘可视化组件 - 信号弧 / 评分环 / 顶部彗星进度条
为 PySide6 提供 HTML 设计稿中的环形与弧段可视化，替代单调的进度条。
"""

import math

from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QBrush, QLinearGradient
from PySide6.QtCore import Qt, QRectF, QTimer, QElapsedTimer
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


class CometProgressBar(QWidget):
    """顶部细线彗星进度条。

    未知进度时循环扫过（indeterminate），收到真实百分比后平滑推进
    （determinate）；任务结束时冲到 100% 再淡出。控件本身不含布局，
    由父控件悬浮定位，避免出现/消失时挤动页面。
    """

    HEIGHT = 3
    HOLD_MS = 180.0      # 到达 100% 后的停顿
    FADE_TAU = 120.0     # 透明度与进度的缓动时间常数

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._state = "idle"                 # idle / indeterminate / determinate / finishing / paused
        self._resume_state = "indeterminate"
        self._target = 0.0                   # 目标百分比
        self._display = 0.0                  # 平滑后的显示百分比
        self._phase = 0.0                    # 不确定态相位 0..1
        self._opacity = 0.0
        self._hold_ms = 0.0
        self._fading_out = False

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._on_tick)
        self._clock = QElapsedTimer()
        self.hide()

    # ---------------------------------------------------------------- 公开接口
    @property
    def state(self):
        return self._state

    @property
    def value(self):
        return self._display

    def start(self, percent=None):
        """开始显示；percent 为 None 时进入不确定态。"""
        self._fading_out = False
        self._hold_ms = 0.0
        self._opacity = max(self._opacity, 0.02)
        if percent is None:
            self._state = "indeterminate"
        else:
            self._state = "determinate"
            self._target = self._clamp(percent)
        self.show()
        self._ensure_timer()
        self.update()

    def set_progress(self, percent):
        """更新真实百分比；目标值只增不减，避免多任务交错时回跳。"""
        value = self._clamp(percent)
        if self._state in ("idle", "paused", "finishing"):
            self.start(value)
            return
        self._state = "determinate"
        self._target = max(self._target, value)
        self._ensure_timer()
        self.update()

    def finish(self):
        """任务完成：确定态先补到 100% 再淡出，不确定态直接淡出。"""
        if self._state == "idle":
            return
        if self._state == "paused":
            self._reset_to_idle()
            return
        self._state = "finishing"
        self._hold_ms = 0.0
        if self._target <= 0.0:
            self._fading_out = True
        else:
            self._fading_out = False
            self._target = 100.0
        self._ensure_timer()

    def pause(self):
        """暂停显示（保留下载进度），淡出但不重置目标值。"""
        if self._state in ("idle", "paused"):
            return
        self._resume_state = "determinate" if self._state != "indeterminate" else "indeterminate"
        self._state = "paused"
        self._fading_out = False
        self._ensure_timer()

    def resume(self):
        if self._state != "paused":
            return
        self._state = self._resume_state
        self._fading_out = False
        self._hold_ms = 0.0
        self.show()
        self._ensure_timer()
        self.update()

    def stop(self):
        """立即复位并停表（窗口关闭时调用）。"""
        self._reset_to_idle()

    def advance(self, dt_ms):
        """推进动画；定时器槽与测试都走这里。"""
        dt = max(1.0, float(dt_ms))
        goal = 0.0 if (self._state in ("idle", "paused") or self._fading_out) else 1.0
        k = 1.0 - math.exp(-dt / self.FADE_TAU)
        self._opacity += (goal - self._opacity) * k
        if abs(goal - self._opacity) < 0.02:
            self._opacity = goal

        if self._state == "indeterminate":
            self._phase = (self._phase + dt / 1400.0) % 1.0
        elif self._state in ("determinate", "finishing"):
            self._display += (self._target - self._display) * k
            if abs(self._target - self._display) < 0.3:
                self._display = self._target

        if self._state == "finishing":
            if self._display >= 99.5:
                self._hold_ms += dt
                if self._hold_ms >= self.HOLD_MS:
                    self._fading_out = True
        elif self._state == "paused" and self._opacity <= 0.02:
            self._timer.stop()
            self.hide()
            return

        if self._fading_out and self._opacity <= 0.02:
            self._reset_to_idle()
            return

        self.update()

    # ---------------------------------------------------------------- 内部实现
    @staticmethod
    def _clamp(percent):
        try:
            value = float(percent)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(100.0, value))

    def _reset_to_idle(self):
        self._timer.stop()
        self._state = "idle"
        self._fading_out = False
        self._hold_ms = 0.0
        self._display = 0.0
        self._target = 0.0
        self._phase = 0.0
        self._opacity = 0.0
        self.hide()
        self.update()

    def _ensure_timer(self):
        if self._state == "idle" or not self.isVisible():
            return
        if not self._timer.isActive():
            self._clock.start()
            self._timer.start()

    def _on_tick(self):
        if not self._clock.isValid():
            dt = 16.0
            self._clock.start()
        else:
            dt = float(self._clock.restart())
        self.advance(dt)

    def showEvent(self, event):
        super().showEvent(event)
        self._ensure_timer()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        if self._opacity <= 0.02:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setOpacity(self._opacity)

        w = float(self.width())
        h = float(self.height())
        if w <= 2.0:
            painter.end()
            return

        head_color = QColor(theme.FOCUS)
        tail_color = QColor(theme.ACCENT)

        if self._state == "indeterminate":
            tail = max(48.0, min(w * 0.35, 180.0))
            eased = 0.5 - 0.5 * math.cos(math.pi * self._phase)
            head = -tail + (w + tail) * eased
        else:
            tail = min(160.0, max(36.0, w * 0.16))
            head = max(tail * 0.35, w * self._display / 100.0)

        self._draw_comet(painter, head, tail, w, h, head_color, tail_color)
        painter.end()

    def _draw_comet(self, painter, head, tail, w, h, head_color, tail_color):
        start = max(0.0, head - tail)
        length = head - start
        if length < 1.0:
            return

        gradient = QLinearGradient(start, 0.0, head, 0.0)
        faded = QColor(tail_color)
        faded.setAlpha(0)
        solid = QColor(tail_color)
        solid.setAlpha(235)
        gradient.setColorAt(0.0, faded)
        gradient.setColorAt(1.0, solid)

        radius = h / 2.0
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawRoundedRect(QRectF(start, 0.0, length, h), radius, radius)

        # 亮色头部：彗星的“核”
        painter.setBrush(head_color)
        dot = h + 1.0
        painter.drawEllipse(QRectF(max(0.0, head - dot / 2.0), (h - dot) / 2.0, dot, dot))
