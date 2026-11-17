"""DNS 优化页：解析链路对比 + 候选榜单 + 解析质量，对应设计稿 screen-05。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QLabel, QMessageBox, QProgressBar, QSizePolicy, QWidget,
)

import core.theme as theme
from ui.kit import (
    Bar, Card, Hint, IconButton, Pill, card_head, eyebrow, font, ghost_button,
    hbox, hline, ic, lbl, mono, page_head, primary_button, vbox,
)
from ui.responsive import ResponsiveColumns
from ui.workers import (
    DnsApplyWorker, DnsCurrentWorker, DnsRestoreWorker, DnsTestWorker)


def _recolor(label, color):
    """只改颜色；字号由统一字体阶管理。"""
    label.setStyleSheet(f"color: {color}; background: transparent;")


class _DnsAction(QLabel):
    """榜单行尾的「应用」文字按钮。"""

    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class DnsPageMixin:
    """DNS 优化页：并发测速、排名、推荐与一键应用。"""

    def _create_dns_page(self):
        """创建 DNS 优化页面（设计稿 screen-05）"""
        page = QWidget()
        self.dns_page = page
        layout = vbox(14, (0, 0, 0, 0), page)

        self.dns_restore_btn = ghost_button("恢复自动获取")
        self.dns_restore_btn.setToolTip("清除手动设置的 DNS，恢复为路由器自动下发")
        self.dns_restore_btn.clicked.connect(self._restore_dhcp)

        self.dns_apply_top_btn = primary_button("应用推荐", None)
        self.dns_apply_top_btn.setEnabled(False)
        self.dns_apply_top_btn.clicked.connect(self._apply_best_dns)
        self._dns_apply_btn = self.dns_apply_top_btn

        self.dns_head = page_head(
            "DNS / RESOLVER BENCHMARK",
            "把每一次解析，交给更近的节点。",
            "尚未测试。点击右上角刷新按钮，开始测试公共 DNS。",
            [self.dns_restore_btn, self.dns_apply_top_btn])
        layout.addWidget(self.dns_head)

        body = ResponsiveColumns(left_stretch=16, right_stretch=10)
        layout.addWidget(body, 1)

        # ---------------- 左列：链路对比 + 候选节点 ----------------
        left = body.left

        self.dns_compare_card = Card(16, 0)
        compare_head = hbox(12, (0, 0, 0, 0))
        compare_head.addWidget(lbl("解析链路对比", 11, theme.TEXT_MAIN, 600))
        compare_head.addStretch()
        self.dns_compare_pill = Pill("待测试", "dim", None)
        compare_head.addWidget(self.dns_compare_pill)
        self.dns_compare_card.body.addLayout(compare_head)
        self.dns_compare_card.body.addSpacing(14)

        compare = hbox(16, (0, 0, 0, 0))
        current_node = self._dns_node()
        current_box = vbox(0, (15, 12, 15, 12), current_node)
        current_box.addWidget(eyebrow("CURRENT / 当前", 8, theme.TEXT_3))
        self.current_dns_label = lbl("读取中…", 18, theme.PAPER, 600, True,
                                     -0.4)
        self.current_dns_label.setContentsMargins(0, 8, 0, 0)
        self.current_dns_label.setSizePolicy(QSizePolicy.Ignored,
                                             QSizePolicy.Preferred)
        current_box.addWidget(self.current_dns_label)
        self.dns_current_meta = lbl("正在读取系统 DNS", 9, theme.TEXT_3, 400,
                                    False, 0.32)
        self.dns_current_meta.setContentsMargins(0, 7, 0, 0)
        current_box.addWidget(self.dns_current_meta)
        compare.addWidget(current_node, 1)

        arrow_box = QWidget()
        arrow_box.setFixedWidth(64)
        arrow_layout = vbox(4, (0, 0, 0, 0), arrow_box)
        arrow_layout.setAlignment(Qt.AlignCenter)
        arrow_layout.addWidget(ic("arrow", 18, theme.TEXT_3), 0, Qt.AlignCenter)
        self.dns_delta_label = lbl("—", 9, theme.TEXT_3, 400, True, 0.18,
                                   align=Qt.AlignCenter)
        arrow_layout.addWidget(self.dns_delta_label)
        compare.addWidget(arrow_box)

        rec_node = self._dns_node(rec=True)
        rec_box = vbox(0, (15, 12, 15, 12), rec_node)
        rec_box.addWidget(eyebrow("RECOMMENDED / 推荐", 8, theme.MINT))
        self.dns_rec_ip_label = lbl("尚未测试", 18, theme.PAPER, 600, True,
                                    -0.4)
        self.dns_rec_ip_label.setContentsMargins(0, 8, 0, 0)
        self.dns_rec_ip_label.setSizePolicy(QSizePolicy.Ignored,
                                            QSizePolicy.Preferred)
        rec_box.addWidget(self.dns_rec_ip_label)
        self.dns_rec_meta = lbl("完成测速后显示推荐", 9,
                                theme.TEXT_3, 400, False, 0.32)
        self.dns_rec_meta.setContentsMargins(0, 7, 0, 0)
        rec_box.addWidget(self.dns_rec_meta)
        compare.addWidget(rec_node, 1)

        self.dns_compare_card.body.addLayout(compare)
        left.addWidget(self.dns_compare_card)

        self.dns_list_card = Card(16, 0)
        list_head = hbox(10, (0, 0, 0, 0))
        list_head.addWidget(lbl("候选节点", 11, theme.TEXT_MAIN, 600))
        list_head.addStretch()
        self.dns_btn = IconButton("refresh", 32, 14)
        self.dns_btn.setToolTip("重新测试所有候选 DNS")
        self.dns_btn.clicked.connect(self._start_dns_test)
        list_head.addWidget(self.dns_btn)
        self.dns_count_note = lbl("0 SERVERS · P95", 9, theme.TEXT_3, 400,
                                  True, 0.8)
        list_head.addWidget(self.dns_count_note)
        self.dns_list_card.body.addLayout(list_head)
        self.dns_list_card.body.addSpacing(14)

        self.dns_progress = QProgressBar()
        self.dns_progress.setFixedHeight(3)
        self.dns_progress.setTextVisible(False)
        self.dns_progress.setStyleSheet(
            "QProgressBar { background-color: #17171a; border: none;"
            " border-radius: 2px; }"
            f"QProgressBar::chunk {{ background-color: {theme.PAPER};"
            " border-radius: 2px; }")
        self.dns_progress.hide()
        self.dns_list_card.body.addWidget(self.dns_progress)

        self.dns_progress_label = lbl("", 9, theme.TEXT_3)
        self.dns_progress_label.hide()
        self.dns_list_card.body.addWidget(self.dns_progress_label)

        rank_head = QWidget()
        rank_grid = self._dns_grid(rank_head)
        rank_grid.setContentsMargins(0, 0, 0, 8)
        for column, text in enumerate(("#", "服务商", "地址", "延迟", "操作")):
            cell = lbl(text, 8, theme.TEXT_4, 400, True, 0.96)
            if column == 4:
                cell.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            rank_grid.addWidget(cell, 0, column)
        self.dns_list_card.body.addWidget(rank_head)
        self.dns_list_card.body.addWidget(hline())

        self.dns_list_widget = QWidget()
        self.dns_list_layout = vbox(0, (0, 0, 0, 0), self.dns_list_widget)
        self.dns_list_layout.addWidget(
            self._dns_list_hint("点击右上角刷新按钮开始测试..."))
        self.dns_list_layout.addStretch()
        self.dns_list_card.body.addWidget(self.dns_list_widget, 1)
        left.addWidget(self.dns_list_card, 1)

        # ---------------- 右列：解析质量 + 说明 ----------------
        right = body.right

        quality_card = Card(16, 0)
        quality_card.body.addWidget(card_head("解析质量", "LAST 20"))
        quality_card.body.addSpacing(14)
        big_row = hbox(0, (0, 0, 0, 0))
        self.dns_best_value = lbl("--", 40, theme.PAPER, 600, False, -2.2)
        big_row.addWidget(self.dns_best_value)
        best_unit = lbl(" ms", 12, theme.TEXT_3)
        best_unit.setContentsMargins(0, 0, 0, 4)
        big_row.addWidget(best_unit, 0, Qt.AlignBottom)
        big_row.addStretch()
        quality_card.body.addLayout(big_row)
        self.dns_quality_desc = lbl("完成测速后显示", 10, theme.TEXT_3)
        self.dns_quality_desc.setContentsMargins(0, 6, 0, 0)
        quality_card.body.addWidget(self.dns_quality_desc)

        self.dns_success_value = mono("—", 10, theme.TEXT_MAIN)
        self.dns_doh_value = mono("—", 10, theme.TEXT_MAIN)
        quality_card.body.addSpacing(12)
        for key, value_label in (
                ("解析成功率", self.dns_success_value),
                ("加密查询", self.dns_doh_value)):
            quality_card.body.addWidget(hline())
            quality_card.body.addWidget(self._dns_stat_row(key, value_label))
        right.addWidget(quality_card)

        note_card = Card(16, 0)
        note_card.body.addWidget(card_head("为什么是 DNS", "NOTE"))
        note_card.body.addSpacing(14)
        note_card.body.addWidget(lbl(
            "DNS 决定了「打开一个网址要先问谁」。解析慢，网页的首个字节"
            "就会跟着慢。", 10, theme.TEXT_3, 400, False, 0, wrap=True))
        note_card.body.addSpacing(12)
        note_card.body.addWidget(hline())
        note_card.body.addSpacing(12)
        gains = vbox(9, (0, 0, 0, 0))
        self._dns_gain_labels = {}
        for key in ("当前 P95", "推荐 P95", "预计差值"):
            row = hbox(10, (0, 0, 0, 0))
            row.addWidget(lbl(key, 10, theme.TEXT_2))
            row.addStretch()
            value = lbl("—", 10, theme.TEXT_3)
            row.addWidget(value)
            self._dns_gain_labels[key] = value
            gains.addLayout(row)
        note_card.body.addLayout(gains)
        note_card.body.addStretch()
        self.dns_backup_hint = Hint("应用前会自动备份当前 DNS", "alert")
        note_card.body.addWidget(self.dns_backup_hint)
        right.addWidget(note_card, 1)

        self._dns_loaded = False
        self._dns_results = []
        self._dns_current = []
        self._dns_best = None
        self._dns_best_ip = None

    # ---------------------------------------------------------------- 组件
    @staticmethod
    def _dns_node(rec=False):
        node = QFrame()
        node.setObjectName("dnsNode")
        if rec:
            node.setStyleSheet(
                f"QFrame#dnsNode {{ background-color: #098bffd1;"
                f" border: 1px solid {theme.MINT_LINE}; border-radius: 10px; }}")
        else:
            node.setStyleSheet(
                "QFrame#dnsNode { background-color: #09090b;"
                f" border: 1px solid {theme.LINE}; border-radius: 10px; }}")
        return node

    @staticmethod
    def _dns_grid(holder):
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 9, 0, 9)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(0)
        grid.setColumnMinimumWidth(0, 24)
        grid.setColumnMinimumWidth(4, 62)
        grid.setColumnStretch(1, 30)
        grid.setColumnStretch(2, 20)
        grid.setColumnStretch(3, 23)
        return grid

    @staticmethod
    def _dns_stat_row(key, value_label):
        row = QWidget()
        line = hbox(10, (0, 8, 0, 8), row)
        line.addWidget(lbl(key, 9, theme.TEXT_3))
        line.addStretch()
        line.addWidget(value_label)
        return row

    @staticmethod
    def _dns_list_hint(text):
        hint = lbl(text, 9, theme.TEXT_4, align=Qt.AlignCenter)
        hint.setContentsMargins(0, 18, 0, 18)
        return hint

    @staticmethod
    def _dns_badge(text, mint=False):
        badge = lbl(text, 7, theme.MINT if mint else theme.TEXT_3, 400, True,
                    0.56)
        border = theme.MINT_LINE if mint else theme.LINE
        background = "#098bffd1" if mint else "transparent"
        badge.setStyleSheet(
            f"color: {'#8bffd1' if mint else theme.TEXT_3};"
            f" border: 1px solid {border}; border-radius: 4px;"
            f" padding: 3px 4px; background-color: {background};")
        return badge

    # ---------------------------------------------------------------- 当前 DNS
    def _load_current_dns(self):
        """加载当前DNS（ipconfig / 原生查询在后台执行，避免切页卡顿）"""
        self._dns_loaded = True
        self.current_dns_label.setText("正在读取…")
        self._dns_current_worker = DnsCurrentWorker()
        self._dns_current_worker.done.connect(self._on_current_dns)
        self._start_worker(self._dns_current_worker)

    def _on_current_dns(self, dns_list):
        """当前DNS读取完成"""
        self._dns_current = list(dns_list or [])
        if not dns_list:
            self.current_dns_label.setText("未获取到 DNS")
            self.current_dns_label.setToolTip("")
        else:
            self.current_dns_label.setText("、".join(dns_list))
            self.current_dns_label.setToolTip("、".join(dns_list))
        self._refresh_dns_compare()

    def _refresh_dns_compare(self):
        """把当前 / 推荐节点与实测差值写回对比卡。"""
        current = self._dns_current[0] if self._dns_current else ""
        results = self._dns_results or []
        match = next((r for r in results
                      if r.get("ip") == current and r.get("success")), None)
        known = next((d for d in self.dns_optimizer.POPULAR_DNS
                      if d["ip"] == current), None)

        if match:
            self.dns_current_meta.setText(
                f"{match.get('name', '当前 DNS')} · 平均 "
                f"{match.get('p95') or match.get('latency') or '--'} ms · UDP")
        elif current:
            name = known["name"] if known else "当前 DNS"
            self.dns_current_meta.setText(f"{name} · 当前系统设置 · UDP")
        else:
            self.dns_current_meta.setText("正在读取系统 DNS")

        best = self._dns_best
        if best:
            latency = best.get("p95") or best.get("latency") or "--"
            doh = " · 支持 DoH" if best.get("doh_ok") else ""
            self.dns_rec_ip_label.setText(str(best.get("ip", "--")))
            self.dns_rec_meta.setText(
                f"{best.get('name', '推荐 DNS')} · P95 {latency} ms{doh}")
            self.dns_compare_pill.setText("可优化")
        else:
            self.dns_rec_ip_label.setText("尚未测试")
            self.dns_rec_meta.setText("完成测速后显示推荐")
            self.dns_compare_pill.setText("待测试")
        if getattr(self, "dns_apply_top_btn", None) is not None:
            self.dns_apply_top_btn.setEnabled(bool(best))

        if best and match:
            diff = float(match.get("p95") or match.get("latency") or 0) - float(
                best.get("p95") or best.get("latency") or 0)
            if diff >= 0:
                self.dns_delta_label.setText(f"-{diff:.0f} ms")
                _recolor(self.dns_delta_label, theme.MINT)
            else:
                self.dns_delta_label.setText(f"+{abs(diff):.0f} ms")
                _recolor(self.dns_delta_label, theme.TEXT_3)
        else:
            self.dns_delta_label.setText("—")
            _recolor(self.dns_delta_label, theme.TEXT_3)

        hint = getattr(self, "dns_backup_hint", None)
        if hint is not None:
            try:
                import os
                backup = self.dns_optimizer.backup_path()
                if os.path.exists(backup):
                    hint.setText("已备份当前 DNS，可在「恢复自动获取」中重置")
                else:
                    hint.setText("应用前会自动备份当前 DNS")
            except Exception:
                hint.setText("应用前会自动备份当前 DNS")

    # ---------------------------------------------------------------- 测速
    def _start_dns_test(self):
        """开始DNS测试"""
        self.logger.info("开始DNS测试")
        self._dns_best = None
        self._dns_best_ip = None
        self.dns_apply_top_btn.setEnabled(False)
        self.dns_rec_ip_label.setText("测试中…")
        self.dns_rec_meta.setText("正在测试候选节点")
        self.dns_delta_label.setText("—")
        self.dns_compare_pill.setText("测试中")
        self.dns_btn.setEnabled(False)
        self.dns_count_note.setText("测试中 · P95")
        self.dns_progress.show()
        self.dns_progress_label.show()
        self.dns_progress.setValue(0)
        self.dns_progress_label.setText("正在测试候选节点...")

        self._clear_dns_list()
        self.dns_list_layout.addWidget(self._dns_list_hint("正在测试候选节点..."))
        self.dns_list_layout.addStretch()

        self._set_status("正在测试DNS服务器...")

        self.worker = DnsTestWorker()
        self.worker.progress.connect(self._on_dns_progress)
        self.worker.done.connect(self._on_dns_finished)
        self._start_worker(self.worker)

    def _on_dns_progress(self, percent, name):
        """DNS测试进度"""
        self.dns_progress.setValue(percent)
        self.dns_progress_label.setText(f"正在测试: {name} ({percent}%)")

    def _on_dns_finished(self, results):
        """DNS测试完成（结果为空表示任务失败）"""
        self.dns_btn.setEnabled(True)
        self.dns_progress.hide()
        self.dns_progress_label.hide()

        if not results:
            self.dns_count_note.setText("0 SERVERS · P95")
            self._clear_dns_list()
            self.dns_list_layout.addWidget(
                self._dns_list_hint("测试未完成，请点击刷新重试"))
            self.dns_list_layout.addStretch()
            self._set_status("DNS 测试未完成，请重试")
            return

        self._dns_results = results
        best_dns, advice = self.dns_optimizer.get_best_dns(results)
        self._dns_best = best_dns
        self.dns_count_note.setText(f"{len(results)} SERVERS · P95")
        self.dns_head.set_title("找到更近的解析节点。")
        self.dns_head.set_desc(
            f"已测试 {len(results)} 个公共 DNS，基于多轮采样取 P95。")

        current = self._dns_current[0] if self._dns_current else ""
        match = next((r for r in results
                      if r.get("ip") == current and r.get("success")), None)
        if best_dns:
            p50 = best_dns.get("p50") or best_dns.get("latency") or 0
            p95 = best_dns.get("p95") or best_dns.get("latency") or 0
            self._dns_best_ip = best_dns.get("ip")
            self.dns_best_value.setText(f"{float(p95):.0f}")
            if match:
                current_p95 = float(match.get("p95", match.get("latency") or 0))
                gain = current_p95 - float(p95 or 0)
                self.dns_quality_desc.setText(
                    f"推荐节点 P95 · 比当前{'快' if gain >= 0 else '慢'} "
                    f"{abs(gain):.0f} ms")
                self._dns_gain_labels["当前 P95"].setText(
                    f"{current_p95:.0f} ms")
                self._dns_gain_labels["推荐 P95"].setText(f"{float(p95):.0f} ms")
                self._dns_gain_labels["预计差值"].setText(
                    f"{'-' if gain >= 0 else '+'}{abs(gain):.0f} ms")
            else:
                self.dns_quality_desc.setText(f"P50 {p50} ms · P95 {p95} ms")
                self._dns_gain_labels["当前 P95"].setText("—")
                self._dns_gain_labels["推荐 P95"].setText(f"{float(p95):.0f} ms")
                self._dns_gain_labels["预计差值"].setText("—")
            self.dns_doh_value.setText(
                "支持 DoH" if best_dns.get("doh_ok") else "未验证")
            _recolor(self.dns_doh_value,
                     theme.MINT if best_dns.get("doh_ok") else theme.TEXT_2)
        else:
            self._dns_best_ip = None
            self.dns_best_value.setText("--")
            self.dns_quality_desc.setText(advice)
            self.dns_doh_value.setText("—")
            for label in self._dns_gain_labels.values():
                label.setText("—")

        ok_count = sum(1 for item in results if item.get("success"))
        rate = round(ok_count / len(results) * 100)
        self.dns_success_value.setText(f"{rate}%")
        _recolor(self.dns_success_value,
                 theme.MINT if rate == 100 else theme.TEXT_MAIN)

        self._refresh_dns_compare()

        # 候选榜单
        self._clear_dns_list()
        latencies = [item.get("p95") or item.get("latency")
                     for item in results if item.get("success")]
        latencies = [float(value) for value in latencies if value is not None]
        max_latency = max(latencies) if latencies else 1
        for index, dns in enumerate(results):
            self._add_dns_list_item(
                index + 1, dns, max_latency, last=index == len(results) - 1)
        self.dns_list_layout.addStretch()

        self._set_status("DNS测试完成")
        self._notify("DNS 测试完成", "ok")
        try:
            self.state.publish("dns", results)
        except Exception:
            self.cache.save_result("dns", results)

    def _clear_dns_list(self):
        """清空DNS列表"""
        while self.dns_list_layout.count() > 0:
            item = self.dns_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _add_dns_list_item(self, rank, dns, max_latency=1, last=False):
        """添加 DNS 榜单行：排名 / 服务商 / 地址 / 延迟条 / 应用。"""
        is_best = rank == 1 and dns.get("success")
        is_current = dns.get("ip") in self._dns_current
        holder = QWidget()
        grid = self._dns_grid(holder)

        rank_label = lbl(f"{rank:02d}", 9, theme.TEXT_4, 400, True, 0.09)
        grid.addWidget(rank_label, 0, 0)

        name_box = QWidget()
        name_row = hbox(6, (0, 0, 0, 0), name_box)
        name_row.addWidget(lbl(dns.get("name", ""), 10, theme.TEXT_MAIN, 500))
        if is_best:
            name_row.addWidget(self._dns_badge("推荐", mint=True), 0,
                               Qt.AlignVCenter)
        elif is_current:
            name_row.addWidget(self._dns_badge("当前"), 0, Qt.AlignVCenter)
        if dns.get("doh_ok"):
            name_row.addWidget(self._dns_badge("DoH"), 0, Qt.AlignVCenter)
        name_row.addStretch()
        grid.addWidget(name_box, 0, 1)

        grid.addWidget(lbl(dns.get("ip", ""), 9, theme.TEXT_2, 400, True, 0.09),
                       0, 2)

        latency_box = QWidget()
        latency_row = hbox(8, (0, 0, 0, 0), latency_box)
        if dns.get("success"):
            latency = dns.get("p95") or dns.get("latency") or 0
            ratio = min(1.0, float(latency) / max(1.0, float(max_latency)))
            latency_row.addWidget(Bar(max(0.06, ratio), theme.PAPER), 1)
            value_color = (theme.WARNING if latency >= 40 else theme.TEXT_2)
            value_text = f"{float(latency):.0f} ms"
        else:
            latency_row.addWidget(Bar(0.0, theme.PAPER), 1)
            value_color = theme.TEXT_4
            value_text = "--"
        value_label = mono(value_text, 9, value_color)
        value_label.setFixedWidth(32)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        latency_row.addWidget(value_label)
        grid.addWidget(latency_box, 0, 3)

        if not dns.get("success"):
            action_text, action_color, clickable = "不可用", theme.TEXT_4, False
        elif is_current:
            action_text, action_color, clickable = "使用中", theme.TEXT_4, False
        elif is_best:
            action_text, action_color, clickable = "应用", theme.MINT, True
        else:
            action_text, action_color, clickable = "应用", theme.TEXT_3, True
        action = _DnsAction(action_text)
        action.setFont(font(8, 400, True, 0.64))
        action.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        action.setStyleSheet(f"color: {action_color}; background: transparent;")
        if clickable:
            action.setCursor(Qt.PointingHandCursor)
            action.clicked.connect(
                lambda ip=dns.get("ip"): self._apply_dns_ip(ip))
        grid.addWidget(action, 0, 4)

        self.dns_list_layout.addWidget(holder)
        if not last:
            self.dns_list_layout.addWidget(hline())

    def _apply_dns_ip(self, dns_ip):
        """榜单行「应用」：选中该 IP 并走与一键应用相同的确认流程。"""
        if not dns_ip:
            return
        self._dns_best_ip = dns_ip
        self._apply_best_dns()

    # ---------------------------------------------------------------- 应用 / 恢复
    def _apply_best_dns(self):
        """一键应用最优DNS（写入操作在后台线程执行）"""
        dns_ip = getattr(self, "_dns_best_ip", None)
        if not dns_ip:
            self._set_status("请先完成 DNS 测速，再应用推荐")
            return

        reply = QMessageBox.question(
            self, "确认设置DNS",
            f"即将将DNS设置为 {dns_ip}\n\n"
            "这会修改您电脑的网络设置，需要管理员权限。\n"
            "设置后可能需要重启浏览器才能生效。\n\n"
            "是否继续？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self._set_status("正在设置DNS...")
        if getattr(self, "_dns_apply_btn", None) is not None:
            self._dns_apply_btn.setEnabled(False)
        worker = DnsApplyWorker(dns_ip)
        worker.done.connect(self._on_dns_set_finished)
        self._dns_action_worker = worker
        self._start_worker(worker)

    def _on_dns_set_finished(self, result):
        """DNS 写入结束：提示结果并刷新当前 DNS"""
        if getattr(self, "_dns_apply_btn", None) is not None:
            self._dns_apply_btn.setEnabled(True)
        if not result:
            self._set_status("设置 DNS 未完成，请重试")
            return
        success, message = result
        if success:
            QMessageBox.information(self, "设置成功", message)
            self._load_current_dns()
            try:
                self._refresh_snapshot(force=True)
            except Exception:
                pass
            self._notify("DNS 已更新", "ok")
        else:
            QMessageBox.warning(self, "设置失败", message)
            self._notify("DNS 设置失败", "error")
        self._set_status("就绪")

    def _restore_dhcp(self):
        """恢复为自动获取 DNS（后台执行）"""
        reply = QMessageBox.question(
            self, "恢复自动获取DNS",
            "将把所有活动网卡的 DNS 恢复为「自动获取（DHCP）」，\n"
            "也就是由路由器重新下发 DNS。\n\n是否继续？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self._set_status("正在恢复自动获取DNS...")
        self.dns_restore_btn.setEnabled(False)
        worker = DnsRestoreWorker()
        worker.done.connect(self._on_dns_restore_finished)
        self._dns_action_worker = worker
        self._start_worker(worker)

    def _on_dns_restore_finished(self, result):
        """恢复 DHCP 结束"""
        self.dns_restore_btn.setEnabled(True)
        if not result:
            self._set_status("恢复自动获取 DNS 未完成，请重试")
            return
        success, message = result
        if success:
            QMessageBox.information(self, "恢复成功", message)
            self._load_current_dns()
        else:
            QMessageBox.warning(self, "恢复失败", message)
        self._set_status("就绪")
