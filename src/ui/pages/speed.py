"""网速测试页：仪表读数 + 本次结果 / 链路质量 / 最近 7 次，对应设计稿 screen-04。"""

import math
from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QProgressBar, QWidget

import core.theme as theme
from core.version import __version__
from ui.kit import (
    Bars, Card, Gauge, MiniGrid, Pill, Segmented, card_head, font, ghost_button,
    hbox, hline, ic, lbl, mono, page_head, primary_button, vbox,
)
from ui.responsive import ResponsiveColumns
from ui.workers import SpeedTestWorker


def _recolor(label, color):
    """只改颜色；字号由 kit/全局字体阶统一管理。"""
    label.setStyleSheet(f"color: {color}; background: transparent;")


class _SpeedGauge(Gauge):
    """复用 kit 仪表的弧线 / 刻度 / 指针绘制，中央读数改由真实数据标签显示。"""

    def __init__(self, parent=None):
        super().__init__(600, parent)
        self.center = QWidget(self)
        self.center.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        box = vbox(0, (0, 0, 0, 0), self.center)
        self.value_label = lbl("0.0", 62, theme.PAPER, 600, False, -3.7,
                               align=Qt.AlignHCenter | Qt.AlignBottom)
        self.value_label.setFixedHeight(64)
        box.addWidget(self.value_label)
        self.unit_label = lbl("MBPS · DOWNLOAD", 9, theme.TEXT_3, 400, True, 1.44,
                              align=Qt.AlignCenter)
        self.unit_label.setContentsMargins(0, 11, 0, 0)
        box.addWidget(self.unit_label)
        pill_row = hbox(0, (0, 12, 0, 0))
        pill_row.setAlignment(Qt.AlignHCenter)
        self.pill = Pill("等待测速", "ok", "ok")
        pill_row.addWidget(self.pill)
        box.addLayout(pill_row)
        self.center.setFixedSize(340, 128)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width, height = self.width(), self.height()
        self.center.move((width - self.center.width()) // 2,
                         int(height * 0.52) - self.center.height() // 2)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width, height = self.width(), self.height()
        scale = min(width / 460.0, height / 260.0)
        painter.translate((width - 460 * scale) / 2.0,
                          (height - 260 * scale) / 2.0)
        painter.scale(scale, scale)

        cx, cy = 230.0, 230.0
        arc_rect = QRectF(cx - 190, cy - 190, 380, 380)

        painter.setPen(QPen(QColor(255, 255, 255, 23), 2))
        painter.drawArc(arc_rect, 0, 180 * 16)

        ratio = min(1.0, self._value / self._max) if self._max else 0.0
        pen = QPen(QColor(theme.PAPER), 2)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawArc(arc_rect, 180 * 16, -int(ratio * 180 * 16))

        # 刻度：25 根，每 4 根加亮
        for index in range(25):
            angle = math.radians(-90 + index * 7.5)
            radius = 173 if index % 4 == 0 else 180
            painter.setPen(QPen(
                QColor(255, 255, 255, 82 if index % 4 == 0 else 33), 1))
            painter.drawLine(
                QPointF(cx + radius * math.sin(angle),
                        cy - radius * math.cos(angle)),
                QPointF(cx + 188 * math.sin(angle),
                        cy - 188 * math.cos(angle)))

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

        painter.setPen(QColor(theme.TEXT_3))
        painter.setFont(font(8, 400, True))
        for x, y, text in ((25, 247, "0"), (85, 92, "150"), (230, 31, "300"),
                           (375, 92, "450"), (435, 247, "600")):
            painter.drawText(QRectF(x - 24, y - 10, 48, 12),
                             Qt.AlignCenter, text)
        painter.end()


class SpeedPageMixin:
    """网速测试页：延迟 / 上下行测速、实时读数与取消。"""

    def _create_speed_page(self):
        """创建测速页面（设计稿 screen-04）"""
        page = QWidget()
        self.speed_page = page
        layout = vbox(14, (0, 0, 0, 0), page)

        self.speed_seg = Segmented(["下载", "上传", "延迟"], 0)
        self.speed_seg.currentChanged.connect(self._on_speed_mode_changed)

        self.speed_cancel_btn = ghost_button("取消")
        self.speed_cancel_btn.clicked.connect(self._cancel_speed_test)
        self.speed_cancel_btn.hide()

        self.speed_btn = primary_button("重新测试", None)
        self.speed_btn.clicked.connect(self._start_speed_test)

        self.speed_head = page_head(
            "SPEED TEST / LIVE",
            "此刻，你的网络有多快。",
            self._speed_desc(),
            [self.speed_seg, self.speed_cancel_btn, self.speed_btn])
        layout.addWidget(self.speed_head)

        body = ResponsiveColumns(left_stretch=16, right_stretch=10)
        layout.addWidget(body, 1)

        # ---------------- 左：大仪表 ----------------
        self.speed_gauge_card = Card(16, 0)
        head = hbox(12, (0, 0, 0, 0))
        self.speed_title_label = lbl("下载速度", 11, theme.TEXT_MAIN, 600)
        head.addWidget(self.speed_title_label)
        head.addStretch()
        self.speed_state_pill = Pill("待测试", "dim", None)
        head.addWidget(self.speed_state_pill)
        self.speed_gauge_card.body.addLayout(head)
        self.speed_gauge_card.body.addSpacing(14)

        self.speed_gauge = _SpeedGauge()
        self.speed_gauge_card.body.addWidget(self.speed_gauge, 1)

        self.speed_gauge_card.body.addSpacing(8)
        self.speed_gauge_card.body.addWidget(hline())

        foot = hbox(10, (0, 13, 0, 0))
        self.speed_foot_label = lbl("耗时 -- · 已用流量 --", 10,
                                    theme.TEXT_3)
        foot_meta = hbox(8, (0, 0, 0, 0))
        foot_meta.addWidget(ic("clock", 13, theme.TEXT_3))
        foot_meta.addWidget(self.speed_foot_label)
        self.net_dn_label = mono("↓ 0 B/s", 10, theme.TEXT_3)
        self.net_up_label = mono("↑ 0 B/s", 10, theme.TEXT_3)
        self.net_dn_label.hide()
        self.net_up_label.hide()
        foot_meta.addWidget(self.net_dn_label)
        foot_meta.addWidget(self.net_up_label)
        foot.addLayout(foot_meta)
        foot.addStretch()
        share = ghost_button("分享结果")
        share.clicked.connect(self._share_speed_result)
        self.speed_share_btn = share
        self.speed_report_btn = primary_button("保存报告", None)
        self.speed_report_btn.clicked.connect(self._save_speed_report)
        foot.addWidget(share)
        foot.addWidget(self.speed_report_btn)
        self.speed_gauge_card.body.addLayout(foot)

        self.speed_status_label = lbl("", 10, theme.TEXT_3)
        self.speed_status_label.hide()
        self.speed_gauge_card.body.addWidget(self.speed_status_label)

        self.speed_progress = QProgressBar()
        self.speed_progress.setFixedHeight(3)
        self.speed_progress.setTextVisible(False)
        self.speed_progress.setStyleSheet(
            "QProgressBar { background-color: #17171a; border: none;"
            " border-radius: 2px; }"
            f"QProgressBar::chunk {{ background-color: {theme.PAPER};"
            " border-radius: 2px; }")
        self.speed_progress.hide()
        self.speed_gauge_card.body.addWidget(self.speed_progress)
        body.add_left(self.speed_gauge_card, 16)

        # ---------------- 右：结果 / 质量 / 历史 ----------------
        right = body.right

        result_card = Card(16, 0)
        result_card.body.addWidget(card_head("本次结果", "REALTIME"))
        result_card.body.addSpacing(14)

        self.download_value = mono("--", 12, theme.TEXT_MAIN)
        self.upload_value = mono("--", 12, theme.TEXT_MAIN)
        self.ping_value = mono("--", 12, theme.TEXT_MAIN)
        for key, value_label, unit in (
                ("下载", self.download_value, "Mbps"),
                ("上传", self.upload_value, "Mbps"),
                ("延迟", self.ping_value, "ms")):
            result_card.body.addWidget(hline())
            result_card.body.addWidget(
                self._speed_result_row(key, value_label, unit))
        right.addWidget(result_card)

        quality_card = Card(16, 0)
        quality_card.body.addWidget(card_head("链路质量", "P95"))
        quality_card.body.addSpacing(14)
        quality_host = QWidget()
        self._quality_layout = vbox(0, (0, 0, 0, 0), quality_host)
        quality_card.body.addWidget(quality_host)
        right.addWidget(quality_card)
        self._speed_quality_grid = None
        self._refresh_speed_quality({})

        history_card = Card(16, 0)
        history_card.body.addStretch()
        history_card.body.addWidget(card_head("最近 7 次", "Mbps"))
        history_card.body.addSpacing(14)
        self.speed_hist_bars = Bars([], gap=7, radius=2)
        self.speed_hist_bars.setFixedHeight(54)
        history_card.body.addWidget(self.speed_hist_bars)
        self.speed_hist_hint = lbl("完成一次测速后，这里会显示历史趋势。",
                                   9, theme.TEXT_3)
        history_card.body.addWidget(self.speed_hist_hint)
        hist_foot = hbox(0, (0, 9, 0, 0))
        self.speed_hist_first = mono("--/--", 9, theme.TEXT_3)
        hist_foot.addWidget(self.speed_hist_first)
        hist_foot.addStretch()
        hist_foot.addWidget(mono("今天", 9, theme.TEXT_3))
        hist_foot.addStretch()
        self.speed_hist_best = mono("暂无记录", 9, theme.MINT)
        hist_foot.addWidget(self.speed_hist_best)
        history_card.body.addLayout(hist_foot)
        right.addWidget(history_card, 0)
        right.addStretch(1)

        self._speed_mode = 0
        self._speed_results = {}
        self._live_style_dl = False
        self._live_style_up = False
        self._refresh_speed_history()
        self._refresh_speed_readout()

    # ---------------------------------------------------------------- 组件
    @staticmethod
    def _speed_result_row(key, value_label, unit):
        row = QWidget()
        line = hbox(8, (0, 7, 0, 7), row)
        line.addWidget(lbl(key, 10, theme.TEXT_3))
        line.addStretch()
        line.addWidget(value_label)
        line.addWidget(lbl(unit, 9, theme.TEXT_3))
        return row

    @staticmethod
    def _style_value(label, color):
        _recolor(label, color)

    def _speed_desc(self):
        return f"自动选择测速节点 · {datetime.now():%H:%M} 更新"

    # ---------------------------------------------------------------- 数据
    def _previous_download(self):
        """上一次（不含本次）下载速度；没有返回 None。"""
        try:
            records = self.cache.get_history("speed") or []
        except Exception:
            records = []
        for record in reversed(records):
            download = (record.get("result") or {}).get("download") or {}
            value = download.get("speed_mbps")
            if isinstance(value, (int, float)):
                return float(value)
        return None

    def _compare_text(self, value):
        previous = self._previous_download()
        if previous is None or previous <= 0:
            return "本次测速完成"
        diff = (value - previous) / previous * 100
        if abs(diff) < 3:
            return "与上次基本持平"
        return f"比上次{'快' if diff > 0 else '慢'} {abs(diff):.0f}%"

    def _refresh_speed_quality(self, ping):
        ping = ping or {}

        def value_of(key, fmt):
            value = ping.get(key)
            return fmt.format(value) if isinstance(value, (int, float)) else "--"

        loss = ping.get("loss_rate")
        items = (
            ("P50 延迟", value_of("p50", "{:.0f}"), "ms", theme.TEXT_MAIN),
            ("P95 延迟", value_of("p95", "{:.0f}"), "ms", theme.TEXT_MAIN),
            ("抖动", value_of("jitter_ms", "{:.1f}"), "ms", theme.TEXT_MAIN),
            ("丢包", value_of("loss_rate", "{:.1f}"), "%",
             theme.TEXT_MAIN if not loss else theme.WARNING),
        )
        old = self._speed_quality_grid
        if old is not None:
            self._quality_layout.removeWidget(old)
            old.hide()
            old.setParent(None)
            old.deleteLater()
        grid = MiniGrid(items, 2)
        self._quality_layout.addWidget(grid)
        self._speed_quality_grid = grid

    def _refresh_speed_history(self):
        """最近 7 次测速：真实记录按 600 Mbps 满刻度换算柱高。"""
        try:
            records = self.cache.get_history("speed") or []
        except Exception:
            records = []
        speeds, dates = [], []
        for record in records[-7:]:
            result = record.get("result") or {}
            download = result.get("download") or {}
            speed = download.get("speed_mbps")
            if isinstance(speed, (int, float)):
                speeds.append(float(speed))
                stamp = str(record.get("timestamp", ""))
                dates.append(stamp[5:10].replace("-", "/") or "--/--")

        if speeds:
            best = max(speeds)
            values = []
            for index, speed in enumerate(speeds):
                if speed == best:
                    style = "best"
                elif index == len(speeds) - 1:
                    style = "cur"
                else:
                    style = ""
                values.append((min(1.0, speed / 600.0), style))
            first = dates[0] if dates else "--/--"
            best_text = f"最高 {best:.0f}"
            self.speed_hist_hint.hide()
        else:
            values = []
            first = "--/--"
            best_text = "暂无记录"
            self.speed_hist_hint.show()

        self.speed_hist_bars.set_values(values)
        self.speed_hist_first.setText(first)
        self.speed_hist_best.setText(best_text)

    def _refresh_speed_readout(self):
        """把当前模式的真实结果写进仪表读数、单位和状态胶囊。"""
        mode = self._speed_mode
        results = self._speed_results or {}
        titles = ("下载速度", "上传速度", "网络延迟")
        units = ("MBPS · DOWNLOAD", "MBPS · UPLOAD", "MS · LATENCY")
        self.speed_title_label.setText(titles[mode])
        self.speed_gauge.unit_label.setText(units[mode])

        value, max_value, pill_text = None, 600, "等待测速"
        if mode == 0:
            data = results.get("download") or {}
            if data.get("success"):
                value = float(data.get("speed_mbps") or 0)
                pill_text = self._compare_text(value)
            elif data:
                pill_text = "下载测速未完成"
        elif mode == 1:
            data = results.get("upload") or {}
            if data.get("success"):
                value = float(data.get("speed_mbps") or 0)
                pill_text = "本次上传测速完成"
            elif data:
                pill_text = "上传测速未完成"
        else:
            data = results.get("ping") or {}
            if data.get("success"):
                value = float(data.get("avg_latency") or 0)
                max_value = 200
                pill_text = "本次延迟测试完成"
            elif data:
                pill_text = "延迟测试未完成"

        self.speed_gauge.value_label.setText(
            f"{value:.1f}" if value is not None else "0.0")
        self.speed_gauge.set_value(value or 0.0, max_value)
        self.speed_gauge.pill.setText(pill_text)

    def _on_speed_mode_changed(self, index):
        self._speed_mode = index
        self._refresh_speed_readout()

    def _share_speed_result(self):
        results = self._speed_results or {}
        download = results.get("download") or {}
        upload = results.get("upload") or {}
        ping = results.get("ping") or {}
        if not download.get("success"):
            self._set_status("暂无测速结果可分享")
            self._notify("请先完成一次测速", "warn")
            return
        lines = ["网络优化助手 · 测速结果",
                 f"下载：{download.get('speed_mbps', '--')} Mbps"]
        if upload.get("success"):
            lines.append(f"上传：{upload.get('speed_mbps', '--')} Mbps")
        if ping.get("success"):
            lines.append(f"延迟：{ping.get('avg_latency', '--')} ms"
                         f"（P95 {ping.get('p95', '--')} ms）")
        lines.append(f"时间：{datetime.now():%Y-%m-%d %H:%M}")
        text = "\n".join(lines)
        try:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(text)
            self.speed_share_btn.setText("已复制")
            self._notify("测速结果已复制，可直接粘贴分享", "ok")
            QTimer.singleShot(2000,
                              lambda: self.speed_share_btn.setText("分享结果"))
        except Exception:
            self._set_status("复制测速结果失败")
            self._notify("复制测速结果失败", "error")

    def _save_speed_report(self):
        """把本次测速结果导出为报告文件。"""
        results = self._speed_results or {}
        download = results.get("download") or {}
        if not download.get("success"):
            self._set_status("暂无测速结果可保存")
            self._notify("请先完成一次测速", "warn")
            return
        from core.report import ReportDoc, ReportSection
        ping = results.get("ping") or {}
        upload = results.get("upload") or {}
        sections = [
            ReportSection("下载", [f"{download.get('speed_mbps', '--')} Mbps"]),
            ReportSection("上传", [f"{upload.get('speed_mbps', '--')} Mbps"]),
            ReportSection("延迟", [
                f"平均 {ping.get('avg_latency', '--')} ms · "
                f"P95 {ping.get('p95', '--')} ms · "
                f"抖动 {ping.get('jitter_ms', '--')} ms · "
                f"丢包 {ping.get('loss_rate', '--')}%"]),
        ]
        doc = ReportDoc(
            kind="speed",
            title="网速测试报告",
            summary=(f"下载 {download.get('speed_mbps', '--')} Mbps · "
                     f"上传 {upload.get('speed_mbps', '--')} Mbps"),
            sections=sections,
            meta={"版本": __version__},
        )
        if self._export_report_dialog(doc):
            self.speed_report_btn.setText("已保存")
            self._notify("测速报告已保存", "ok")
            QTimer.singleShot(
                2000, lambda: self.speed_report_btn.setText("保存报告"))

    @staticmethod
    def _fmt_traffic(kilobytes):
        megabytes = max(0.0, float(kilobytes or 0)) / 1024.0
        if megabytes >= 1024:
            return f"{megabytes / 1024:.1f} GB"
        return f"{megabytes:.1f} MB"

    # ---------------------------------------------------------------- 测速流程
    def _start_speed_test(self):
        """开始测速"""
        self.logger.info("开始网速测试")
        self.speed_btn.setEnabled(False)
        self.speed_btn.setText("测速中...")
        self.speed_cancel_btn.setEnabled(True)
        self.speed_cancel_btn.show()
        self.speed_progress.show()
        self.speed_progress.setValue(0)
        self.speed_state_pill.setText("测速中")
        self.speed_foot_label.setText("正在测速...")
        self.net_dn_label.show()
        self.net_up_label.show()

        self.speed_seg.set_current(0)
        self._speed_mode = 0
        self._speed_results = {}
        self.download_value.setText("--")
        self.upload_value.setText("--")
        self.ping_value.setText("--")
        for value_label in (self.download_value, self.upload_value,
                            self.ping_value):
            self._style_value(value_label, theme.TEXT_MAIN)
        self._refresh_speed_quality({})
        self._refresh_speed_readout()

        self._set_status("正在进行网速测试...")
        self._live_style_dl = False
        self._live_style_up = False

        self.worker = SpeedTestWorker()
        self._speed_worker = self.worker
        self.worker.progress.connect(self._on_speed_progress)
        self.worker.status.connect(self._on_speed_status)
        self.worker.live.connect(self._on_speed_live)
        self.worker.upline.connect(self._on_speed_uplive)
        self.worker.done.connect(self._on_speed_finished)
        self._start_worker(self.worker)

    def _cancel_speed_test(self):
        """用户主动取消测速：通知后台线程在下一个检查点退出。"""
        worker = getattr(self, "_speed_worker", None)
        if isinstance(worker, SpeedTestWorker) and worker.isRunning():
            worker.cancel()
            self.speed_cancel_btn.setEnabled(False)
            self.speed_btn.setText("正在取消...")
            self._set_status("正在取消测速...")

    def _on_speed_progress(self, percent):
        """测速进度更新"""
        self.speed_progress.setValue(percent)

    def _on_speed_status(self, text):
        """测速状态更新"""
        self.speed_status_label.setText(text)
        self.speed_foot_label.setText(text)

    def _on_speed_live(self, mbps):
        """实时显示当前瞬时下载速度"""
        self.download_value.setText(f"{mbps:.1f}")
        if not self._live_style_dl:
            self._live_style_dl = True
            self._style_value(self.download_value, theme.MINT)
        if self._speed_mode == 0:
            self.speed_gauge.value_label.setText(f"{mbps:.1f}")
            self.speed_gauge.set_value(mbps, 600)
            self.speed_gauge.pill.setText("实时采样中")

    def _on_speed_uplive(self, mbps):
        """实时显示当前瞬时上传速度"""
        self.upload_value.setText(f"{mbps:.1f}")
        if not self._live_style_up:
            self._live_style_up = True
            self._style_value(self.upload_value, theme.MINT)
        if self._speed_mode == 1:
            self.speed_gauge.value_label.setText(f"{mbps:.1f}")
            self.speed_gauge.set_value(mbps, 600)
            self.speed_gauge.pill.setText("实时上传采样中")

    def _fmt_rate(self, bps):
        """把字节/秒格式化为易读字符串"""
        if bps is None:
            return "--"
        if bps < 0:
            bps = 0.0
        if bps >= 1024 * 1024:
            return f"{bps / (1024 * 1024):.1f} MB/s"
        if bps >= 1024:
            return f"{bps / 1024:.0f} KB/s"
        return f"{bps:.0f} B/s"

    def _apply_net_rates(self, up, dn):
        """接收后台采样线程的速率并刷新底部实时网速（psutil 缺失时给一次性提示）"""
        if not self.traffic.enabled:
            if not getattr(self, "_psutil_warned", False):
                self._psutil_warned = True
                self._set_status("实时网速暂不可用（缺少 psutil 组件），其余功能正常")
            return
        up_l = getattr(self, "net_up_label", None)
        dn_l = getattr(self, "net_dn_label", None)
        if up_l is not None:
            up_l.setText(self._fmt_rate(up))
        if dn_l is not None:
            dn_l.setText(self._fmt_rate(dn))
        bup = getattr(self, "bottom_up_label", None)
        bdn = getattr(self, "bottom_down_label", None)
        if bup is not None:
            bup.setText("↑ " + self._fmt_rate(up))
        if bdn is not None:
            bdn.setText("↓ " + self._fmt_rate(dn))
        side_dn = getattr(self, "side_down_label", None)
        side_up = getattr(self, "side_up_label", None)
        dn_text = self._fmt_rate(dn)
        up_text = self._fmt_rate(up)
        if side_dn is not None:
            side_dn.setText(dn_text)
        if side_up is not None:
            side_up.setText(up_text)
        self._last_down_text = dn_text
        self._last_up_text = up_text
        try:
            self.state.push_traffic(up, dn)
        except Exception:
            pass
        self._refresh_home_metrics()

    def _on_speed_finished(self, results):
        """测速完成（结果为空表示任务失败）"""
        self.speed_btn.setEnabled(True)
        self.speed_btn.setText("重新测试")
        self.speed_cancel_btn.hide()
        self.speed_progress.hide()
        self.speed_status_label.hide()
        self.net_dn_label.hide()
        self.net_up_label.hide()

        self._speed_results = results or {}
        if not results:
            self.speed_state_pill.setText("测速失败")
            self.speed_foot_label.setText("测速未完成，请重试")
            self._refresh_speed_readout()
            self._set_status("测速未完成，请重试")
            return

        if results.get("cancelled"):
            self.speed_state_pill.setText("已取消")
            for value_label in (self.download_value, self.upload_value,
                                self.ping_value):
                value_label.setText("--")
                self._style_value(value_label, theme.TEXT_MAIN)
            self._refresh_speed_quality({})
            self.speed_foot_label.setText("测速已取消")
            self._refresh_speed_readout()
            self._set_status("测速已取消")
            self.logger.info("网速测试已取消")
            return

        # 延迟
        ping_result = results.get("ping", {})
        if ping_result.get("success"):
            latency = ping_result["avg_latency"]
            self.ping_value.setText(str(latency))
            self._style_value(self.ping_value, theme.TEXT_MAIN)
        else:
            self.ping_value.setText("失败")
            self._style_value(self.ping_value, theme.ERROR)

        # 下载
        download_result = results.get("download", {})
        if download_result.get("success"):
            speed = download_result["speed_mbps"]
            self.download_value.setText(str(speed))
            self._style_value(self.download_value, theme.TEXT_MAIN)
        else:
            self.download_value.setText("失败")
            self._style_value(self.download_value, theme.ERROR)

        # 上传
        upload_result = results.get("upload", {})
        if upload_result.get("success"):
            up_speed = upload_result["speed_mbps"]
            self.upload_value.setText(str(up_speed))
            self._style_value(self.upload_value, theme.TEXT_MAIN)
        else:
            self.upload_value.setText("不可测")
            self._style_value(self.upload_value, theme.WARNING)

        self._refresh_speed_quality(ping_result)
        self._refresh_speed_readout()

        duration = download_result.get("duration_s")
        traffic = download_result.get("downloaded_kb")
        parts = []
        if duration is not None:
            parts.append(f"耗时 {float(duration):.1f} s")
        if traffic is not None:
            parts.append(f"已用流量 {self._fmt_traffic(traffic)}")
        self.speed_foot_label.setText(" · ".join(parts) or "耗时 -- · 已用流量 --")

        self.speed_state_pill.setText("测试完成")
        self._set_status("测速完成")
        try:
            self._notify("测速完成", "ok")
        except Exception:
            pass
        try:
            self.state.publish("speed", results)
        except Exception:
            self.cache.save_result("speed", results)
        self._refresh_speed_history()
