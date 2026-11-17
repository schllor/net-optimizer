"""网络诊断页：扫描式检查列表、实时结果与诊断结论，对应设计稿 screen-02。"""

import datetime
import platform

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QProgressBar, QSizePolicy,
    QWidget,
)

import core.theme as theme
from core.version import __version__, APP_NAME
from ui import icons
from ui.kit import (
    Card, Pill, ScoreRing, ghost_button, hbox, hline, lbl, mono, page_head,
    primary_button, vbox,
)
from ui.responsive import ResponsiveColumns
from ui.workers import DiagnosticWorker

# 与 core.diagnostic.run_all_tests 的检测清单保持一致
_DIAG_NAMES = (
    "网卡状态", "IP地址", "网关连通性", "DNS解析",
    "互联网连通性", "多站点延迟", "代理设置",
)

_SHORT_NAMES = {
    "网卡状态": "网卡", "IP地址": "IP", "网关连通性": "网关",
    "DNS解析": "DNS", "互联网连通性": "联网",
    "多站点延迟": "延迟", "代理设置": "代理",
}

_STATUS_TEXT = {"ok": "正常", "warning": "注意", "error": "异常"}
_STATUS_CODE = {"ok": "OK", "warning": "WARN", "error": "ERROR"}
_VALUE_COLOR = {
    "ok": theme.TEXT_2,
    "warning": theme.AMBER,
    "error": theme.ERROR,
    "pending": theme.TEXT_4,
    "queued": theme.TEXT_4,
}


def _short(text, limit=34):
    text = str(text)
    return text if len(text) <= limit else text[:limit - 1] + "…"


class _CheckIcon(QWidget):
    """24px 圆形检查图标：完成/警告/异常/检测中/排队。"""

    def __init__(self, state="queued", parent=None):
        super().__init__(parent)
        self._state = state
        self.setFixedSize(24, 24)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def set_state(self, state):
        self._state = state
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        styles = {
            "ok": (theme.MINT, theme.MINT_LINE, "#0f8bffd1", "check"),
            "warning": (theme.AMBER, theme.AMBER_LINE, "#0dffc46b", "alert"),
            "error": (theme.ERROR, "#3fff8f8f", "#0fff8f8f", "x"),
        }
        rect = QRectF(0.5, 0.5, 23, 23)
        if self._state in styles:
            color, border, bg, name = styles[self._state]
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(bg))
            painter.drawEllipse(rect)
            painter.setPen(QPen(QColor(border), 1))
            painter.drawEllipse(rect)
            pixmap = icons.pixmap(name, 11, color, 2)
            painter.drawPixmap(7, 7, pixmap)
        elif self._state == "pending":
            pen = QPen(QColor(theme.LINE_STRONG), 1)
            pen.setStyle(Qt.DashLine)
            pen.setDashPattern([2, 2])
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(rect)
        else:
            painter.setPen(QPen(QColor(theme.LINE_STRONG), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(rect)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(theme.TEXT_3))
            painter.drawEllipse(QRectF(10, 10, 4, 4))
        painter.end()


class _ScanLine(QWidget):
    """卡片内的 1px 薄荷绿扫描线（对应 CSS .scanbox 的 scanline 动画）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._phase = 0.0
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    def _tick(self):
        self._phase = (self._phase + 40 / 2800.0) % 1.0
        self.update()

    def showEvent(self, event):
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        if self.height() <= 0:
            return
        fade = min(1.0, self._phase / 0.08, (1.0 - self._phase) / 0.08)
        if fade <= 0:
            return
        y = 6 + self._phase * (self.height() - 12)
        gradient = QLinearGradient(0, 0, self.width(), 0)
        gradient.setColorAt(0.0, QColor(139, 255, 209, 0))
        gradient.setColorAt(0.5, QColor(139, 255, 209, int(216 * fade)))
        gradient.setColorAt(1.0, QColor(139, 255, 209, 0))
        painter = QPainter(self)
        painter.setPen(QPen(gradient, 1))
        painter.drawLine(0, int(y), self.width(), int(y))
        painter.end()


class _ScanCard(Card):
    """带扫描线的检查卡。"""

    def __init__(self, padding=16, spacing=0, parent=None):
        super().__init__(padding, spacing, parent=parent)
        self._scan = _ScanLine(self)
        self._scan.resize(self.width(), self.height())
        self._scan.show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scan.setGeometry(0, 0, self.width(), self.height())
        self._scan.raise_()


class _DiagRow(QWidget):
    """CSS .check-row：圆形图标 + 名称/描述 + 右侧结果。"""

    def __init__(self, name, desc, value, sub, state, parent=None):
        super().__init__(parent)
        layout = hbox(11, (0, 10, 0, 10), self)
        self.icon = _CheckIcon(state)
        layout.addWidget(self.icon, 0, Qt.AlignTop)

        detail = vbox(0, (0, 0, 0, 0))
        self.name_label = lbl(name, 11, theme.TEXT_MAIN, 500)
        detail.addWidget(self.name_label)
        self.desc_label = lbl(desc, 9, theme.TEXT_3, 400, True, 0.2)
        self.desc_label.setContentsMargins(0, 3, 0, 0)
        detail.addWidget(self.desc_label)
        layout.addLayout(detail, 1)

        value_box = vbox(0, (0, 1, 0, 0))
        self.value_label = lbl(value, 9, _VALUE_COLOR.get(state, theme.TEXT_2),
                               400, True, 0.2, align=Qt.AlignRight)
        self.sub_label = lbl(sub, 8, theme.TEXT_4, 400, False, 0,
                             align=Qt.AlignRight)
        self.sub_label.setContentsMargins(0, 4, 0, 0)
        value_box.addWidget(self.value_label)
        value_box.addWidget(self.sub_label)
        layout.addLayout(value_box)

    def set_result(self, state, value, sub, desc=None, value_color=None):
        self.icon.set_state(state)
        self.value_label.setText(value)
        self.value_label.setStyleSheet(
            f"color: {value_color or _VALUE_COLOR.get(state, theme.TEXT_2)};"
            " background: transparent;")
        self.sub_label.setText(sub)
        if desc is not None:
            self.desc_label.setText(desc)

    def set_pending(self, desc="等待检测…"):
        self.icon.set_state("queued")
        self.value_label.setText("—")
        self.value_label.setStyleSheet(
            f"color: {theme.TEXT_4}; background: transparent;")
        self.sub_label.setText("QUEUED")
        self.desc_label.setText(desc)


class DiagnosePageMixin:
    """网络诊断页：并发检测、逐项结果与报告复制。"""

    def _create_diagnose_page(self):
        """创建诊断页面"""
        page = QWidget()
        self.diagnose_page = page
        layout = vbox(14, (0, 0, 0, 0), page)

        self.diag_stop_btn = ghost_button("停止扫描")
        self.diag_stop_btn.setEnabled(False)
        self.diag_stop_btn.clicked.connect(self._stop_diagnose)
        self.diag_btn = primary_button("开始诊断", "play")
        self.diag_btn.clicked.connect(self._start_diagnose)
        self.diag_head = page_head(
            "DIAGNOSE / READY",
            "先给网络做一次体检。",
            "7 项检查，约 3–8 秒。开始后请保持当前网络连接。",
            [self.diag_stop_btn, self.diag_btn])
        layout.addWidget(self.diag_head)

        body = ResponsiveColumns(left_stretch=135, right_stretch=100)
        layout.addWidget(body, 1)

        # ---------------- 左列：检查项 ----------------
        check_card = _ScanCard(16, 0)
        self.diag_check_card = check_card
        body.add_left(check_card, 135)

        head = hbox(12, (0, 0, 0, 12))
        head.addWidget(lbl("检查项", 11, theme.TEXT_MAIN, 600))
        head.addStretch()
        self.diag_note = lbl("0 / 7", 9, theme.TEXT_3, 400, True, 0.8)
        head.addWidget(self.diag_note)
        check_card.add_layout(head)

        self.diag_progress = QProgressBar()
        self.diag_progress.setFixedHeight(4)
        self.diag_progress.setTextVisible(False)
        self.diag_progress.setRange(0, 100)
        self.diag_progress.setValue(0)
        self.diag_progress.setStyleSheet(
            "QProgressBar { background-color: #14ffffff; border: none;"
            " border-radius: 2px; }"
            "QProgressBar::chunk { background-color: #f3f4f6;"
            " border-radius: 2px; }")
        check_card.add(self.diag_progress)

        self.diag_progress_label = mono("", 9, theme.TEXT_3)
        self.diag_progress_label.setContentsMargins(0, 4, 0, 0)
        self.diag_progress_label.setFixedHeight(18)
        check_card.add(self.diag_progress_label)

        rows_wrap = QWidget()
        self._diag_steps_layout = vbox(0, (0, 6, 0, 0), rows_wrap)
        check_card.add(rows_wrap, 1)

        foot = QWidget()
        foot_layout = vbox(0, (0, 11, 0, 0), foot)
        log_head = hbox(8, (0, 0, 0, 7))
        log_head.addWidget(lbl("检测日志", 9, theme.TEXT_3, 400, True, 1.0))
        log_head.addStretch()
        self.diag_scan_time = mono("--:--:--", 9, theme.TEXT_3)
        log_head.addWidget(self.diag_scan_time)
        foot_layout.addLayout(log_head)
        self._diag_log_layout = vbox(0, (0, 0, 0, 0))
        self.diag_log_hint = lbl("开始诊断后，这里会显示每一项的真实结果。",
                                 9, theme.TEXT_3, wrap=True)
        self._diag_log_layout.addWidget(self.diag_log_hint)
        foot_layout.addLayout(self._diag_log_layout)
        check_card.body.addWidget(hline())
        check_card.add(foot)

        # ---------------- 右列：得分 + 结论 ----------------
        right = body.right

        score_card = Card(16, 0)
        self.diag_summary_card = score_card
        score_row = hbox(18, (0, 0, 0, 0))
        self.diag_score_ring = ScoreRing(112, 0, "SCORE", score_size=34,
                                         caption_size=8)
        self.diag_score_ring.set_unknown("SCORE")
        score_row.addWidget(self.diag_score_ring, 0, Qt.AlignVCenter)

        summary = vbox(0, (0, 0, 0, 0))
        top = hbox(8, (0, 0, 0, 0))
        top.addWidget(lbl("诊断结果", 9, theme.TEXT_3, 400, True, 1.0))
        self.diag_summary_icon = lbl("", 9, theme.TEXT_2)
        self.diag_summary_icon.hide()
        top.addWidget(self.diag_summary_icon)
        top.addStretch()
        self.diag_result_pill = Pill("待检测", "dim", None, small=True)
        top.addWidget(self.diag_result_pill)
        summary.addLayout(top)

        self.diag_verdict = lbl("尚未检测", 16, theme.TEXT_MAIN, 600, False, -0.2)
        self.diag_verdict.setContentsMargins(0, 9, 0, 0)
        summary.addWidget(self.diag_verdict)

        self.diag_summary_text = lbl(
            "点击「开始诊断」，结果显示在这里。",
            10, theme.TEXT_3, 400, False, 0, wrap=True)
        self.diag_summary_text.setContentsMargins(0, 5, 0, 0)
        summary.addWidget(self.diag_summary_text)

        score_row.addLayout(summary, 1)
        score_card.body.addLayout(score_row)
        right.addWidget(score_card)

        concl = Card(16, 0)
        concl_head = hbox(12, (0, 0, 0, 14))
        concl_head.addWidget(lbl("诊断结论", 11, theme.TEXT_MAIN, 600))
        concl_head.addStretch()
        concl_head.addWidget(lbl("AUTO", 9, theme.TEXT_3, 400, True, 0.8))
        concl.body.addLayout(concl_head)

        self.diag_pills_layout = hbox(6, (0, 0, 0, 0))
        self.diag_pills_layout.addWidget(
            lbl("尚未检测", 10, theme.TEXT_3))
        self.diag_pills_layout.addStretch()
        concl.body.addLayout(self.diag_pills_layout)

        concl.body.addSpacing(14)
        concl.body.addWidget(hline())
        concl.body.addSpacing(14)
        self._diag_metric_labels = {}
        for key in ("平均延迟", "DNS 响应", "丢包率", "扫描耗时"):
            row = hbox(10, (0, 9, 0, 9))
            row.addWidget(lbl(key, 10, theme.TEXT_3))
            row.addStretch()
            value = mono("—", 10, theme.TEXT_MAIN)
            row.addWidget(value)
            self._diag_metric_labels[key] = value
            concl.body.addLayout(row)

        concl.body.addSpacing(14)
        concl.body.addWidget(hline())
        concl.body.addSpacing(14)
        self.diag_recommend_label = lbl(
            "完成诊断后，这里会给出可执行的下一步建议。",
            10, theme.TEXT_2, wrap=True)
        concl.body.addWidget(self.diag_recommend_label)
        concl.body.addStretch()

        actions = hbox(8, (0, 14, 0, 0))
        self.diag_copy_btn = ghost_button("复制报告")
        self.diag_copy_btn.setSizePolicy(QSizePolicy.Expanding,
                                         QSizePolicy.Fixed)
        self.diag_copy_btn.clicked.connect(self._copy_diagnostic_report)
        self.diag_copy_btn.hide()
        actions.addWidget(self.diag_copy_btn, 1)

        self.diag_export_btn = ghost_button("导出报告")
        self.diag_export_btn.setSizePolicy(QSizePolicy.Expanding,
                                           QSizePolicy.Fixed)
        self.diag_export_btn.clicked.connect(self._export_diagnostic_report)
        actions.addWidget(self.diag_export_btn, 1)

        self.diag_fix_btn = primary_button("一键修复")
        self.diag_fix_btn.setSizePolicy(QSizePolicy.Expanding,
                                        QSizePolicy.Fixed)
        self.diag_fix_btn.clicked.connect(self._start_scoped_repair)
        self.diag_fix_btn.setEnabled(False)
        actions.addWidget(self.diag_fix_btn, 1)
        concl.body.addLayout(actions)
        right.addWidget(concl, 1)

        # 详细结果容器保留给报告回填（界面上的结果由检查行与结论卡呈现）
        self.diag_results_widget = QWidget(page)
        self.diag_results_widget.hide()
        self.diag_results_layout = vbox(0, (0, 0, 0, 0),
                                        self.diag_results_widget)

        self._diag_step_items = {}
        self._diag_step_detail = {}
        self._build_diag_steps()

    # ---------------------------------------------------------------- 检查列表
    def _build_diag_steps(self):
        """构建检查清单：默认全部等待检测。"""
        while self._diag_steps_layout.count() > 0:
            item = self._diag_steps_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._diag_step_items = {}
        self._diag_step_detail = {}

        rows = [(name, "等待检测…", "—", "QUEUED", "queued")
                for name in _DIAG_NAMES]

        for index, (name, desc, value, sub, state) in enumerate(rows):
            if index:
                self._diag_steps_layout.addWidget(hline())
            row = _DiagRow(name, desc, value, sub, state)
            self._diag_steps_layout.addWidget(row)
            self._diag_step_items[name] = (row.icon, row.name_label)
            self._diag_step_detail[name] = row

        self._diag_steps_layout.addStretch()
        self._diag_done_count = 0

    def _start_diagnose(self):
        """开始诊断"""
        self.logger.info("开始一键诊断")
        self.diag_btn.setEnabled(False)
        self.diag_btn.setText("诊断中...")
        self.diag_stop_btn.setEnabled(True)
        self.diag_progress.show()
        self.diag_progress.setValue(0)
        self.diag_progress_label.show()
        self.diag_progress_label.setText("准备扫描…")
        self.diag_note.setText(f"0 / {len(_DIAG_NAMES)}")
        self._diag_started_at = datetime.datetime.now()
        self._diag_log_lines = 0
        self._clear_diag_log()
        self.diag_log_hint.setText("正在收集每一项的真实结果…")

        self._clear_diag_results()
        self._build_diag_steps()

        self.diag_score_ring.set_unknown("SCORE")
        self.diag_verdict.setText("正在评估…")
        self.diag_summary_text.setText("正在检测网络状态，请稍候…")
        self.diag_summary_text.setStyleSheet(
            f"color: {theme.TEXT_3}; background: transparent;")
        self.diag_result_pill.setText("扫描中")
        self.diag_result_pill.setStyleSheet("")
        self.diag_fix_btn.setEnabled(False)
        self.diag_fix_btn.setText("一键修复")
        self.diag_copy_btn.hide()
        self.diag_export_btn.show()
        self.diag_scan_time.setText(
            datetime.datetime.now().strftime("%H:%M:%S"))
        self._clear_diag_pills()
        for label in self._diag_metric_labels.values():
            label.setText("—")
        self.diag_recommend_label.setText("正在根据检测结果生成建议…")
        self.diag_head.set_title("正在扫描你的网络…")
        self.diag_head.set_desc("请保持当前网络连接，检测完成后会自动给出结论。")

        self._set_status("正在进行网络诊断...")

        self.worker = DiagnosticWorker()
        self.worker.progress.connect(self._on_diag_progress)
        self.worker.item_done.connect(self._on_diag_item_done)
        self.worker.done.connect(self._on_diag_finished)
        self._start_worker(self.worker)

    # ---------------------------------------------------------------- 日志 / 结论
    def _clear_diag_log(self):
        layout = getattr(self, "_diag_log_layout", None)
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _append_diag_log(self, name, message, status):
        layout = getattr(self, "_diag_log_layout", None)
        if layout is None:
            return
        color = {"ok": theme.MINT, "warning": theme.WARNING,
                 "error": theme.ERROR}.get(status, theme.TEXT_3)
        line = hbox(8, (0, 1, 0, 1))
        line.addWidget(mono(name, 9, theme.TEXT_3))
        text = lbl(_short(message, 46), 9, color, wrap=True)
        line.addWidget(text, 1)
        holder = QWidget()
        holder.setLayout(line)
        layout.addWidget(holder)

    def _clear_diag_pills(self):
        layout = getattr(self, "diag_pills_layout", None)
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _build_diag_pills(self, results):
        self._clear_diag_pills()
        layout = self.diag_pills_layout
        for item in results:
            status = item.get("status")
            tone = {"ok": "ok", "warning": "warn", "error": "warn"}.get(
                status, "dim")
            label = _SHORT_NAMES.get(item.get("name"), item.get("name", ""))
            layout.addWidget(Pill(label, tone, None, small=True))
        layout.addStretch()

    def _fill_diag_metrics(self, results):
        def data_of(name):
            for item in results:
                if item.get("name") == name:
                    return item.get("data") or {}
            return {}

        multi = data_of("多站点延迟")
        internet = data_of("互联网连通性")
        gateway = data_of("网关连通性")
        dns = data_of("DNS解析")
        latency = multi.get("avg_ms")
        if latency is None:
            latency = internet.get("latency_ms")
        if latency is None:
            latency = gateway.get("latency_ms")
        loss = internet.get("loss_pct")
        if loss is None:
            loss = gateway.get("loss_pct")
        self._diag_metric_labels["平均延迟"].setText(
            f"{float(latency):.0f} ms" if isinstance(latency, (int, float))
            else "—")
        dns_ms = dns.get("latency_ms")
        self._diag_metric_labels["DNS 响应"].setText(
            f"{float(dns_ms):.0f} ms" if isinstance(dns_ms, (int, float))
            else "—")
        self._diag_metric_labels["丢包率"].setText(
            f"{float(loss):.1f}%" if isinstance(loss, (int, float)) else "—")
        started = getattr(self, "_diag_started_at", None)
        if started is not None:
            elapsed = (datetime.datetime.now() - started).total_seconds()
            self._diag_metric_labels["扫描耗时"].setText(f"{elapsed:.1f} s")

    def _fill_diag_recommendation(self, results):
        try:
            advice = self.diagnostic.get_recommendations(results)
        except Exception:
            advice = []
        if not advice:
            self.diag_recommend_label.setText("无额外建议。")
            return
        first = advice[0]
        text = f"建议：{first.get('title', '')}"
        detail = first.get("detail")
        if detail:
            text += f" · {detail}"
        if len(advice) > 1:
            text += f"（另有 {len(advice) - 1} 条建议）"
        self.diag_recommend_label.setText(text)

    def _start_scoped_repair(self):
        """只修复本次诊断发现的问题，修复后自动复检。"""
        targets = list(getattr(self, "_diag_repair_targets", []) or [])
        if not targets:
            self._set_status("本次诊断没有需要修复的项目")
            return
        self._repair_scope = targets
        self._repair_auto_verify = True
        self._switch_page("repair")
        self.repair_btn.setText(f"修复 {len(targets)} 项")
        self.repair_head.set_desc(
            "将只执行与本次诊断问题相关的修复项；完成后会自动重新诊断。")
        self._start_repair()

    def _stop_diagnose(self):
        """请求停止当前诊断。"""
        worker = getattr(self, "worker", None)
        if worker is not None and worker.isRunning():
            worker.cancel()
            self.diag_stop_btn.setEnabled(False)
            self.diag_progress_label.setText("正在停止…")
            self._set_status("正在停止诊断…")

    def _on_diag_item_done(self, result):
        """诊断某项完成：点亮对应检查行并回填结果。"""
        name = result.get("name", "")
        row = self._diag_step_detail.get(name)
        if row is None:
            return
        status = result.get("status", "ok")
        state = {"ok": "ok", "warning": "warning",
                 "error": "error"}.get(status, "pending")
        row.set_result(
            state,
            _STATUS_TEXT.get(status, "未知"),
            _STATUS_CODE.get(status, "—"),
            _short(result.get("message", "")))
        self._diag_done_count = getattr(self, "_diag_done_count", 0) + 1
        self.diag_note.setText(
            f"{self._diag_done_count} / {len(_DIAG_NAMES)}")
        self.diag_scan_time.setText(
            datetime.datetime.now().strftime("%H:%M:%S"))
        self._append_diag_log(name, result.get("message", ""), status)

    def _on_diag_progress(self, percent, item_name):
        """诊断进度更新"""
        self.diag_progress.setValue(percent)
        self.diag_progress_label.setText(
            f"正在检测: {item_name} ({percent}%)")

    def _on_diag_finished(self, results):
        """诊断完成（结果为空表示任务失败或被取消）"""
        self.diag_btn.setEnabled(True)
        self.diag_btn.setText("重新诊断")
        self.diag_stop_btn.setEnabled(False)
        self.diag_progress_label.hide()

        if not results:
            self.diag_progress.setValue(0)
            self.diag_note.setText(f"0 / {len(_DIAG_NAMES)}")
            self.diag_verdict.setText("诊断未完成")
            self.diag_summary_text.setText("诊断未完成，请重新开始扫描。")
            self.diag_head.set_title("这次没有完成体检。")
            self.diag_head.set_desc("可能是网络波动或任务被取消，可以再试一次。")
            self._set_status("诊断未完成，请重试")
            return

        self.diag_progress.setValue(100)
        self.diag_note.setText(
            f"{len(results)} / {len(_DIAG_NAMES)}")
        self.diagnostic.results = results

        summary, status = self.diagnostic.get_summary()
        status_colors = {
            "ok": theme.MINT,
            "warning": theme.AMBER,
            "error": theme.ERROR,
            "info": theme.TEXT_2,
        }
        verdicts = {"ok": "整体良好", "warning": "存在可优化项",
                    "error": "发现网络异常", "info": "扫描完成"}

        self.diag_summary_icon.setText(
            {"ok": "✓", "warning": "!", "error": "×"}.get(status, "·"))
        self.diag_verdict.setText(verdicts.get(status, "扫描完成"))
        self.diag_summary_text.setText(summary)
        self.diag_summary_text.setStyleSheet(
            f"color: {status_colors.get(status, theme.TEXT_3)};"
            " background: transparent;")

        ok_count = sum(1 for item in results if item.get("status") == "ok")
        issues = len(results) - ok_count
        self.diag_score_ring.set_score(round(ok_count / len(results) * 100))
        self.diag_result_pill.setText(
            f"{issues} 项可优化" if issues else "全部通过")
        try:
            targets = self.diagnostic.repair_targets(results)
        except Exception:
            targets = []
        self._diag_repair_targets = targets
        self.diag_fix_btn.setEnabled(bool(targets))
        self.diag_fix_btn.setText(
            f"修复 {len(targets)} 项" if targets else "无需修复")
        self._build_diag_pills(results)
        self._fill_diag_metrics(results)
        self._fill_diag_recommendation(results)
        self.diag_head.set_title(verdicts.get(status, "扫描完成"))
        self.diag_head.set_desc(summary)

        # 详细结果回填（供报告与后续扩展使用，界面由检查行呈现）
        self._clear_diag_results()
        for result in results:
            self._add_diag_result_item(result)

        self._set_status("诊断完成")
        try:
            self._notify("诊断完成", "ok" if status == "ok" else "warn")
        except Exception:
            pass

        self.diag_copy_btn.show()
        self.diag_export_btn.show()
        try:
            self.state.publish("diagnostic", results)
        except Exception:
            self.cache.save_result("diagnostic", results)
        self._refresh_home_score()

    # ---------------------------------------------------------------- 报告
    def _copy_diagnostic_report(self):
        """把当前诊断结果整理成文本并复制到剪贴板。"""
        results = self.diagnostic.results if self.diagnostic else []
        if not results:
            return
        icons_map = {"ok": "√", "warning": "!", "error": "×"}
        summary, _ = self.diagnostic.get_summary()
        lines = [
            f"{APP_NAME} v{__version__} 诊断报告",
            f"时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"系统：{platform.platform()}",
            f"结论：{summary}",
            "",
        ]
        for item in results:
            icon = icons_map.get(item.get("status"), "?")
            lines.append(f"[{icon}] {item.get('name', '')}：{item.get('message', '')}")
        try:
            QApplication.clipboard().setText("\n".join(lines))
            self.diag_copy_btn.setText("已复制")
            self._set_status("诊断报告已复制到剪贴板")
            QTimer.singleShot(
                2000, lambda: self.diag_copy_btn.setText("复制报告"))
        except Exception:
            self.logger.exception("复制诊断报告失败")

    def _export_diagnostic_report(self):
        """把当前诊断结果导出为 Markdown/JSON/TXT 报告。"""
        results = self.diagnostic.results if self.diagnostic else []
        if not results:
            return
        from core.report import ReportDoc, ReportSection

        summary, _ = self.diagnostic.get_summary()
        sections = [
            ReportSection(item.get("name", ""), [item.get("message", "")])
            for item in results
        ]
        doc = ReportDoc(
            kind="diagnostic",
            title="网络诊断报告",
            summary=summary,
            sections=sections,
            meta={"版本": f"v{__version__}", "系统": platform.platform()},
        )
        if self._export_report_dialog(doc):
            self.diag_export_btn.setText("已导出")
            QTimer.singleShot(2000, lambda: self.diag_export_btn.setText("导出报告"))

    def _clear_diag_results(self):
        """清空诊断结果"""
        while self.diag_results_layout.count() > 0:
            item = self.diag_results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _add_diag_result_item(self, result):
        """添加诊断结果项（详细结果容器，界面由检查行呈现）"""
        item_frame = QFrame()
        item_frame.setStyleSheet(
            f"QFrame {{ background-color: {theme.BG_RAISED};"
            " border-radius: 6px; padding: 10px; }")
        item_layout = QHBoxLayout(item_frame)
        item_layout.setContentsMargins(15, 10, 15, 10)
        item_layout.setSpacing(15)

        status_colors = {
            "ok": theme.SUCCESS,
            "warning": theme.WARNING,
            "error": theme.ERROR,
        }
        status_icons = {"ok": "√", "warning": "!", "error": "×"}

        icon_label = QLabel(status_icons.get(result["status"], "?"))
        icon_label.setStyleSheet("font-size: 15px;")
        icon_label.setFixedWidth(30)
        item_layout.addWidget(icon_label)

        name_label = QLabel(result["name"])
        name_label.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {theme.TEXT_MAIN};")
        name_label.setFixedWidth(100)
        item_layout.addWidget(name_label)

        msg_label = QLabel(result["message"])
        msg_label.setStyleSheet(
            "font-size: 11px;"
            f" color: {status_colors.get(result['status'], theme.TEXT_SECONDARY)};")
        msg_label.setWordWrap(True)
        item_layout.addWidget(msg_label, 1)

        self.diag_results_layout.addWidget(item_frame)
