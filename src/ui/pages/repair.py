"""网络修复页：五步步骤列表与实时终端日志，对应设计稿 screen-03。"""

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QTextCursor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QProgressBar,
    QSizePolicy, QWidget,
)

import core.theme as theme
from ui.kit import (
    Card, Hint, Pill, font, ghost_button, hbox, hline, lbl, mono, page_head,
    primary_button, vbox,
)
from ui.responsive import ResponsiveColumns
from ui.workers import RepairWorker

# 真实修复项 -> 设计稿步骤文案
_REPAIR_STEPS = (
    ("刷新DNS缓存", "刷新 DNS 缓存", "清除过期的域名解析记录"),
    ("重置Winsock目录", "重置 Winsock", "修复套接字目录异常"),
    ("重置TCP/IP协议", "重置 TCP/IP 堆栈", "恢复默认网络协议配置"),
    ("释放并重新获取IP", "释放并重获 IP", "向路由器重新请求地址"),
    ("清除代理设置", "清除代理设置", "移除残留的系统代理"),
)

_STEP_STATE_STYLE = {
    "done": ("DONE", theme.TEXT_2, theme.MINT),
    "now": ("RUNNING", theme.TEXT_MAIN, theme.MINT),
    "wait": ("WAIT", theme.TEXT_MAIN, theme.TEXT_4),
    "fail": ("FAILED", theme.TEXT_MAIN, theme.ERROR),
    "error": ("ERROR", theme.TEXT_MAIN, theme.ERROR),
}


class _RepairStep(QFrame):
    """CSS .step：编号 + 标题/描述 + 右侧状态，当前步骤为高亮块。"""

    def __init__(self, number, title, desc, state="wait", first=False,
                 parent=None):
        super().__init__(parent)
        self._first = first
        self._state = state
        self.setFrameShape(QFrame.NoFrame)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._layout = hbox(12, (0, 11, 0, 11), self)

        self.n = lbl(f"{number:02d}", 9, theme.TEXT_4, 400, True)
        self.n.setFixedWidth(18)
        self.n.setContentsMargins(0, 2, 0, 0)
        self._layout.addWidget(self.n, 0, Qt.AlignTop)

        detail = vbox(0, (0, 0, 0, 0))
        self.t = lbl(title, 11, theme.TEXT_MAIN, 500)
        detail.addWidget(self.t)
        self.d = lbl(desc, 9, theme.TEXT_3, 400, False, 0, wrap=True)
        self.d.setContentsMargins(0, 4, 0, 0)
        detail.addWidget(self.d)
        self._layout.addLayout(detail, 1)

        self.s = lbl("", 8, theme.TEXT_4, 400, True, 0.5)
        self.s.setContentsMargins(0, 2, 0, 0)
        self._layout.addWidget(self.s, 0, Qt.AlignTop)

        self.set_state(state)

    def set_state(self, state):
        self._state = state
        text, title_color = _STEP_STATE_STYLE.get(
            state, _STEP_STATE_STYLE["wait"])[:2]
        status_color = _STEP_STATE_STYLE.get(
            state, _STEP_STATE_STYLE["wait"])[2]
        self._layout.setContentsMargins(
            *((10, 11, 10, 11) if state == "now" else (0, 11, 0, 11)))
        self.n.setStyleSheet(
            f"color: {theme.MINT if state == 'now' else theme.TEXT_4};"
            " background: transparent;")
        self.t.setStyleSheet(f"color: {title_color}; background: transparent;")
        self.d.setStyleSheet(f"color: {theme.TEXT_3}; background: transparent;")
        self.s.setText(text)
        self.s.setStyleSheet(f"color: {status_color}; background: transparent;")
        self.updateGeometry()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())
        if self._state == "now":
            painter.setPen(QPen(QColor(theme.LINE_STRONG), 1))
            painter.setBrush(QColor(theme.SURFACE_2))
            painter.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 9, 9)
        elif not self._first:
            painter.setPen(QPen(QColor(theme.LINE), 1))
            painter.drawLine(0, 0, int(w), 0)
        painter.end()


def _term_dot(color):
    dot = QFrame()
    dot.setFixedSize(6, 6)
    dot.setStyleSheet(
        f"QFrame {{ background-color: {color}; border: none;"
        " border-radius: 3px; }")
    return dot


class RepairPageMixin:
    """网络修复页：修复步骤、进度与实时日志。"""

    def _create_repair_page(self):
        """创建修复页面"""
        page = QWidget()
        self.repair_page = page
        self._repair_scope = None
        self._repair_auto_verify = False
        layout = vbox(14, (0, 0, 0, 0), page)

        self.repair_view_log_btn = ghost_button("查看日志")
        self.repair_view_log_btn.clicked.connect(self._show_repair_log)
        self.repair_cancel_btn = ghost_button("取消修复")
        self.repair_cancel_btn.clicked.connect(self._cancel_repair)
        self.repair_cancel_btn.hide()
        self.repair_btn = primary_button("开始修复", "play")
        self.repair_btn.clicked.connect(self._start_repair)
        self.repair_head = page_head(
            "REPAIR / READY",
            "修复前，先看清楚会发生什么。",
            "DNS 与代理修改前会自动备份；Winsock/TCP-IP 需重启生效，无法自动回滚。",
            [self.repair_view_log_btn, self.repair_cancel_btn,
             self.repair_btn])
        layout.addWidget(self.repair_head)

        body = ResponsiveColumns(left_stretch=100, right_stretch=145)
        layout.addWidget(body, 1)

        # ---------------- 左列：修复步骤 ----------------
        steps_card = Card(16, 0)
        self.repair_steps_card = steps_card
        body.add_left(steps_card, 100)

        head = hbox(12, (0, 0, 0, 14))
        head.addWidget(lbl("修复步骤", 11, theme.TEXT_MAIN, 600))
        head.addStretch()
        self.repair_step_note = lbl("0 / 5", 9, theme.TEXT_3, 400, True, 0.8)
        head.addWidget(self.repair_step_note)
        steps_card.add_layout(head)

        steps_wrap = QWidget()
        self._repair_steps_layout = vbox(0, (0, 0, 0, 0), steps_wrap)
        self._repair_step_rows = []
        self._repair_step_by_name = {}
        for index, (real_name, title, desc) in enumerate(_REPAIR_STEPS):
            row = _RepairStep(index + 1, title, desc, "wait",
                              first=index == 0)
            self._repair_steps_layout.addWidget(row)
            self._repair_step_rows.append(row)
            self._repair_step_by_name[real_name] = row
        self._repair_steps_layout.addStretch()
        steps_card.add(steps_wrap, 1)

        # 进度（默认隐藏，启动修复后显示）
        self.repair_progress = QProgressBar()
        self.repair_progress.setFixedHeight(4)
        self.repair_progress.setTextVisible(False)
        self.repair_progress.setRange(0, 100)
        self.repair_progress.setStyleSheet(
            "QProgressBar { background-color: #14ffffff; border: none;"
            " border-radius: 2px; }"
            "QProgressBar::chunk { background-color: #f3f4f6;"
            " border-radius: 2px; }")
        self.repair_progress.hide()
        steps_card.add(self.repair_progress)

        self.repair_progress_label = mono("", 8, theme.TEXT_4)
        self.repair_progress_label.setContentsMargins(0, 6, 0, 0)
        self.repair_progress_label.hide()
        steps_card.add(self.repair_progress_label)

        # 结果摘要（默认隐藏，完成后显示）
        self.repair_summary_card = QWidget()
        summary_layout = hbox(8, (0, 10, 0, 0))
        self.repair_summary_icon = lbl("·", 10, theme.TEXT_3)
        self.repair_summary_icon.setFixedWidth(12)
        summary_layout.addWidget(self.repair_summary_icon, 0, Qt.AlignTop)
        self.repair_summary_text = lbl(
            "点击上方按钮，开始修复网络问题", 10, theme.TEXT_3, 400, False, 0,
            wrap=True)
        summary_layout.addWidget(self.repair_summary_text, 1)
        self.repair_verify_btn = ghost_button("重新诊断")
        self.repair_verify_btn.clicked.connect(self._rediagnose_after_repair)
        self.repair_verify_btn.hide()
        summary_layout.addWidget(self.repair_verify_btn, 0, Qt.AlignTop)
        self.repair_summary_card.setLayout(summary_layout)
        self.repair_summary_card.hide()
        steps_card.add(self.repair_summary_card)

        steps_card.body.addStretch()
        steps_card.add(Hint("修复期间网络会短暂中断；需要重启的项会在完成后提示。",
                            "alert"))

        # ---------------- 右列：终端日志 ----------------
        log_card = Card(12, 0)
        self.repair_log_card = log_card
        body.add_right_layout(self._repair_log_column(log_card))

        # 详细结果容器保留给结果回填（界面由步骤列表与终端呈现）
        self.repair_results_widget = QWidget(page)
        self.repair_results_widget.hide()
        self.repair_results_layout = vbox(0, (0, 0, 0, 0),
                                          self.repair_results_widget)

    def _repair_log_column(self, card):
        column = vbox(0, (0, 0, 0, 0))
        column.addWidget(card, 1)

        term = QFrame()
        term.setObjectName("termBox")
        term.setStyleSheet(
            "QFrame#termBox { background-color: #060607;"
            f" border: 1px solid {theme.LINE}; border-radius: 12px; }}")
        term_layout = vbox(0, (15, 14, 15, 14), term)

        term_head = hbox(4, (0, 0, 0, 9))
        term_head.addWidget(_term_dot("#3a3a42"))
        term_head.addWidget(_term_dot("#2a2a30"))
        term_head.addWidget(_term_dot("#2a2a30"))
        title = mono("REPAIR LOG · ADMIN", 8, theme.TEXT_4, 1.0)
        title.setContentsMargins(8, 0, 0, 0)
        term_head.addWidget(title)
        term_head.addStretch()
        term_layout.addLayout(term_head)
        term_layout.addWidget(hline())

        self.repair_log_view = QPlainTextEdit()
        self.repair_log_view.setReadOnly(True)
        self.repair_log_view.setFrameShape(QFrame.NoFrame)
        self.repair_log_view.setFont(font(10, 400, True))
        self.repair_log_view.document().setDocumentMargin(0)
        self.repair_log_view.setStyleSheet(
            "QPlainTextEdit { background: transparent; border: none;"
            " color: #b9bdc4; padding: 9px 0 0 0;"
            " selection-background-color: #24ffffff;"
            " selection-color: #f3f4f6; }"
            "QScrollBar:vertical { width: 6px; background: transparent; }"
            "QScrollBar::handle:vertical { background: #24ffffff;"
            " border-radius: 3px; min-height: 20px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical"
            " { height: 0px; }")
        term_layout.addWidget(self.repair_log_view, 1)
        self.repair_log_view.setPlainText(
            "尚未执行修复。\n点击「开始修复」后，这里会实时显示每一步的真实结果。")
        card.add(term, 1)

        foot = hbox(0, (4, 12, 4, 2))
        foot.addWidget(lbl("预计剩余", 9, theme.TEXT_3))
        self.repair_eta_label = mono("--:--", 9, theme.TEXT_MAIN)
        self.repair_eta_label.setContentsMargins(4, 0, 0, 0)
        foot.addWidget(self.repair_eta_label)
        foot.addStretch()
        try:
            admin = self._is_admin_now()
        except Exception:
            admin = False
        self.repair_admin_pill = Pill(
            "管理员权限" if admin else "需要管理员权限", "", None, small=True)
        foot.addWidget(self.repair_admin_pill)
        column.addLayout(foot)
        return column

    # ---------------------------------------------------------------- 终端日志
    def _append_term(self, html):
        cursor = self.repair_log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if self.repair_log_view.toPlainText():
            cursor.insertBlock()
        cursor.insertHtml(html)
        self.repair_log_view.setTextCursor(cursor)
        bar = self.repair_log_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    # ---------------------------------------------------------------- 操作
    def _show_repair_log(self):
        self.repair_log_view.setFocus()
        self._set_status("修复日志会实时记录每一步操作")

    def _cancel_repair(self):
        worker = getattr(self, "worker", None)
        if worker is not None and worker.isRunning():
            worker.cancel()
            self.repair_cancel_btn.setEnabled(False)
            self.repair_progress_label.setText("正在取消…")
            self._set_status("正在取消修复…")

    def _start_repair(self):
        """开始修复：先如实列出权限/重启范围，再执行。"""
        self.logger.info("开始一键修复 (管理员: %s)", self._is_admin_now())
        preview = []
        try:
            preview = self.repair.preview()
        except Exception:
            preview = []
        scope = getattr(self, "_repair_scope", None)
        if scope:
            preview = [item for item in preview if item.get("name") in set(scope)]
        admin = self._is_admin_now()
        needs_admin = [item["title"] for item in preview
                       if item.get("requires_admin") and not admin]
        needs_reboot = [item["title"] for item in preview
                        if item.get("needs_reboot")]
        lines = [
            "即将执行网络修复操作，修复过程中网络可能会短暂断开。",
            "",
        ]
        if needs_admin:
            lines.append("以下操作需要管理员权限，当前可能失败："
                         + "、".join(needs_admin))
        if needs_reboot:
            lines.append("以下操作需重启电脑后完全生效："
                         + "、".join(needs_reboot))
        lines.append("DNS 与代理设置会在修改前自动备份。")
        lines.append("")
        lines.append("是否继续？")
        reply = QMessageBox.question(
            self, "确认修复", "\n".join(lines),
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            self._repair_auto_verify = False
            self._repair_scope = None
            return

        self.repair_btn.setEnabled(False)
        self.repair_btn.setText("修复中...")
        self.repair_cancel_btn.setEnabled(True)
        self.repair_cancel_btn.show()
        self.repair_progress.show()
        self.repair_progress_label.show()
        self.repair_progress.setValue(0)
        self.repair_progress_label.setText("准备修复…")
        self.repair_eta_label.setText("--:--")
        self._repair_total = len(scope) if scope else 5
        self._repair_done_count = 0
        self.repair_step_note.setText(f"0 / {self._repair_total}")
        self.repair_verify_btn.hide()
        self.repair_head.set_title("正在修复网络组件…")
        self.repair_head.set_desc("请勿关闭程序；需要重启的项会在完成后提示。")

        self._clear_repair_results()
        for row in self._repair_step_rows:
            row.set_state("wait")

        # 清空并重新显示实时日志
        self.repair_log_view.clear()
        self._append_term(
            f"<span style='color:{theme.TEXT_3}'>[开始]</span> 修复任务已启动")

        self.repair_summary_card.show()
        self.repair_summary_icon.setText("·")
        self.repair_summary_icon.setStyleSheet(
            f"color: {theme.TEXT_3}; background: transparent;")
        self.repair_summary_text.setText("正在修复网络问题，请稍候...")
        self.repair_summary_text.setStyleSheet(
            f"color: {theme.TEXT_3}; background: transparent;")

        self._set_status("正在进行网络修复...")

        self.worker = RepairWorker(only=scope)
        self.worker.progress.connect(self._on_repair_progress)
        self.worker.item_done.connect(self._on_repair_item_done)
        self.worker.done.connect(self._on_repair_finished)
        self._start_worker(self.worker)

    def _on_repair_item_done(self, result):
        """修复某项完成：更新步骤状态、实时追加日志并滚动到底部"""
        name = result.get("name", "")
        success = result.get("success", False)
        message = result.get("message", "")

        row = self._repair_step_by_name.get(name)
        if row is not None:
            row.set_state("done" if success else "fail")
            self._repair_done_count = getattr(self, "_repair_done_count", 0) + 1
            self.repair_step_note.setText(
                f"{self._repair_done_count} / "
                f"{getattr(self, '_repair_total', 5)}")
            index = self._repair_step_rows.index(row)
            if index + 1 < len(self._repair_step_rows):
                nxt = self._repair_step_rows[index + 1]
                if nxt._state == "wait":
                    nxt.set_state("now")

        prompt = f"<span style='color:{theme.TEXT_4}'>PS&gt;</span> "
        if success:
            flag = f"<span style='color:{theme.MINT}'>[OK]</span> "
        else:
            flag = f"<span style='color:{theme.ERROR}'>[!!]</span> "
        self._append_term(prompt + name)
        self._append_term(flag + message)

    def _on_repair_progress(self, percent, item_name):
        """修复进度更新"""
        self.repair_progress.setValue(percent)
        self.repair_progress_label.setText(
            f"正在修复: {item_name} ({percent}%)")
        remaining = max(0, int(round(20 * (100 - percent) / 100)))
        self.repair_eta_label.setText(f"00:{remaining:02d}")

    def _on_repair_finished(self, results):
        """修复完成（结果为空表示任务失败或被取消）"""
        self.repair_btn.setEnabled(True)
        self.repair_btn.setText("重新修复")
        self.repair_cancel_btn.hide()
        self.repair_progress_label.hide()
        self.repair_eta_label.setText("00:00")

        if not results:
            self.repair_progress.setValue(0)
            self._set_status("修复未完成，请重试")
            self._append_term(
                f"<span style='color:{theme.ERROR}'>[!!]</span> 修复已取消")
            return

        self.repair_progress.setValue(100)
        self.repair_step_note.setText(
            f"{len(results)} / {getattr(self, '_repair_total', 5)}")
        summary, status = self.repair.get_summary(results)
        status_colors = {
            "ok": theme.MINT,
            "warning": theme.AMBER,
            "error": theme.ERROR,
        }

        self.repair_summary_card.show()
        self.repair_summary_icon.setText(
            {"ok": "✓", "warning": "!", "error": "×"}.get(status, "·"))
        self.repair_summary_icon.setStyleSheet(
            "font-size: 10px;"
            f" color: {status_colors.get(status, theme.TEXT_3)};"
            " background: transparent;")
        self.repair_summary_text.setText(summary)
        self.repair_summary_text.setStyleSheet(
            f"color: {status_colors.get(status, theme.TEXT_3)};"
            " background: transparent;")
        self.repair_verify_btn.show()

        self._clear_repair_results()
        for result in results:
            self._add_repair_result_item(result)

        self._set_status("修复完成")
        self.repair_head.set_title("修复完成")
        needs_reboot = [item.get("name") for item in results
                        if item.get("needs_reboot") and item.get("success")]
        if needs_reboot:
            self.repair_head.set_desc(
                "部分设置需要重启电脑后完全生效：" + "、".join(needs_reboot))
        else:
            self.repair_head.set_desc(summary)

        # 实时日志补一行完成标记
        self._append_term(
            f"<span style='color:{theme.MINT}'>[完成]</span> {summary}")
        try:
            self._notify("修复完成", "ok" if status == "ok" else "warn")
        except Exception:
            pass

        try:
            self.state.publish("repair", results)
        except Exception:
            self.cache.save_result("repair", results)

        # 总结弹窗：只提示结果与下一步，不夸大
        icon = QMessageBox.Information if status == "ok" else (
            QMessageBox.Warning if status == "warning" else QMessageBox.Critical)
        msg_box = QMessageBox(self)
        msg_box.setIcon(icon)
        msg_box.setWindowTitle("修复完成")
        msg_box.setText(summary)
        msg_box.setInformativeText(
            "建议点击「重新诊断」验证效果；需要重启的项请重启电脑后再生效。")
        msg_box.setStandardButtons(QMessageBox.Ok)
        msg_box.exec()

        auto_verify = bool(getattr(self, "_repair_auto_verify", False))
        self._repair_scope = None
        self._repair_auto_verify = False
        self.repair_btn.setText("重新修复")
        if auto_verify and results:
            self._set_status("修复完成，正在自动复检…")
            QTimer.singleShot(200, self._rediagnose_after_repair)

    def _rediagnose_after_repair(self):
        """修复完成后跳转到诊断页并立即复检。"""
        self._switch_page("diagnose")
        self._start_diagnose()

    def _clear_repair_results(self):
        """清空修复结果"""
        while self.repair_results_layout.count() > 0:
            item = self.repair_results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _add_repair_result_item(self, result):
        """添加修复结果项（详细结果容器，界面由步骤列表与终端呈现）"""
        item_frame = QFrame()
        item_frame.setStyleSheet(
            f"QFrame {{ background-color: {theme.BG_RAISED};"
            " border-radius: 6px; padding: 10px; }")
        item_layout = QHBoxLayout(item_frame)
        item_layout.setContentsMargins(15, 10, 15, 10)
        item_layout.setSpacing(15)

        icon = "√" if result["success"] else "×"
        color = theme.SUCCESS if result["success"] else theme.ERROR

        icon_label = QLabel(icon)
        icon_label.setStyleSheet("font-size: 15px;")
        icon_label.setFixedWidth(30)
        item_layout.addWidget(icon_label)

        name_label = QLabel(result["name"])
        name_label.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {theme.TEXT_MAIN};")
        name_label.setFixedWidth(130)
        item_layout.addWidget(name_label)

        msg_label = QLabel(result["message"])
        msg_label.setStyleSheet(f"font-size: 11px; color: {color};")
        msg_label.setWordWrap(True)
        item_layout.addWidget(msg_label, 1)

        self.repair_results_layout.addWidget(item_frame)
