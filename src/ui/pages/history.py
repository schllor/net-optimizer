"""历史记录页面：时间线 + 活跃度热图，对应设计稿 screen-09。"""

import json
import os
from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

import core.theme as theme
from ui.kit import (
    Card, Heatmap, MiniGrid, Segmented, ghost_button, hbox, hline, ic,
    lbl, mono, page_head, primary_button, vbox,
)
from ui.responsive import ResponsiveColumns

_CATEGORY_LABELS = {
    "diagnostic": "诊断记录",
    "repair": "修复记录",
    "speed": "测速记录",
    "dns": "DNS测试记录",
    "wifi": "Wi-Fi检测记录",
}

_CATEGORY_META = {
    "diagnostic": ("网络诊断", "pulse"),
    "repair": ("一键修复", "tool"),
    "speed": ("网速测试", "gauge"),
    "dns": ("DNS 优化", "globe"),
    "wifi": ("Wi-Fi 检测", "signal"),
}

_FILTER_KEYS = ("all", "diagnostic", "repair", "speed", "dns", "wifi")
_ROW_LIMIT = 9


class HistoryPageMixin:
    """历史记录页：诊断/修复/测速等历史查看与清理。"""

    def _create_history_page(self):
        """创建历史记录页面"""
        self.history_page = QWidget()
        self._history_show_all = False
        self._history_filter_key = "all"

        layout = vbox(14, (0, 0, 0, 0), self.history_page)

        self.history_filter = Segmented(
            ["全部", "诊断", "修复", "测速", "DNS", "Wi-Fi"])
        self.history_filter.currentChanged.connect(self._on_history_filter_changed)
        self.history_export_btn = primary_button("导出报告")
        self.history_export_btn.clicked.connect(self._export_history_report)

        self.history_toggle_btn = ghost_button("显示全部")
        self.history_toggle_btn.clicked.connect(self._toggle_history_all)
        self.history_toggle_btn.hide()

        head = page_head(
            "HISTORY / JOURNAL",
            "每一次优化，都有迹可循。",
            self._history_head_desc(),
            [self.history_filter, self.history_toggle_btn,
             self.history_export_btn])
        for label in head.findChildren(QLabel):
            if label.text().startswith("最近 30 天共"):
                self.history_desc_label = label
                break
        layout.addWidget(head)

        body = ResponsiveColumns(left_stretch=16, right_stretch=10)
        layout.addWidget(body, 1)
        left = body.left
        right = body.right

        # ================= 左列：操作时间线 =================
        timeline = Card(16, 0)
        timeline.head("操作时间线", "最近记录")
        self.history_widget = QWidget()
        self.history_layout = vbox(0, (0, 0, 0, 0), self.history_widget)
        timeline.body.addWidget(self.history_widget, 1)
        left.addWidget(timeline, 1)

        # ================= 右列：热图 + 累计效果 + 本地存储 =================

        heat_card = Card(16, 0)
        heat_card.head("近 30 天活跃度", "30 DAYS")
        heat_card.body.addSpacing(14)

        heat_data = self._history_heat_data()
        heat_wrap = hbox(6, (0, 0, 0, 0))
        days = vbox(0, (0, 0, 6, 0))
        days_widget = QWidget()
        days_widget.setFixedHeight(109)
        days_widget.setLayout(days)
        days.addWidget(lbl("一", 7, theme.TEXT_4, 400, True))
        days.addStretch()
        days.addWidget(lbl("三", 7, theme.TEXT_4, 400, True))
        days.addStretch()
        days.addWidget(lbl("五", 7, theme.TEXT_4, 400, True))
        days.addStretch()
        days.addWidget(lbl("日", 7, theme.TEXT_4, 400, True))
        heat_wrap.addWidget(days_widget)
        self.history_heat_holder = QWidget()
        self.history_heat_layout = vbox(0, (0, 0, 0, 0), self.history_heat_holder)
        heat_wrap.addWidget(self.history_heat_holder)

        self.history_stat_labels = {}
        stats = vbox(0, (8, 0, 0, 0))
        stats.addWidget(self._history_stat_row("活跃天数", "active"))
        stats.addStretch()
        stats.addWidget(self._history_stat_row("最长连续", "streak"))
        stats.addStretch()
        stats.addWidget(self._history_stat_row("日均操作", "average"))
        heat_wrap.addLayout(stats, 1)
        heat_card.body.addLayout(heat_wrap)

        legend = hbox(0, (0, 10, 0, 0))
        self.history_legend_start = mono(
            heat_data["start"].strftime("%m/%d"), 7, theme.TEXT_4)
        self.history_legend_end = mono(
            heat_data["end"].strftime("%m/%d"), 7, theme.TEXT_4)
        legend.addWidget(self.history_legend_start)
        legend.addStretch()
        scale = hbox(4, (0, 0, 0, 0))
        scale.addWidget(lbl("少", 7, theme.TEXT_4, 400, True))
        for color in ("#14ffffff", "#47ffffff", theme.MINT):
            square = QLabel()
            square.setFixedSize(8, 8)
            square.setStyleSheet(
                f"background-color: {color}; border-radius: 2px;")
            scale.addWidget(square)
        scale.addWidget(lbl("多", 7, theme.TEXT_4, 400, True))
        legend.addLayout(scale)
        legend.addStretch()
        legend.addWidget(self.history_legend_end)
        heat_card.body.addLayout(legend)
        right.addWidget(heat_card)

        effect = Card(16, 0)
        effect.head("累计效果", "ALL TIME")
        effect.body.addSpacing(14)
        self.history_effect_holder = QWidget()
        self.history_effect_layout = vbox(
            0, (0, 0, 0, 0), self.history_effect_holder)
        effect.body.addWidget(self.history_effect_holder)
        right.addWidget(effect)

        storage = Card(16, 0)
        storage.body.addWidget(self._history_storage_head())
        storage.body.addSpacing(14)
        storage.body.addWidget(self._history_setting_row(
            "导出格式", mono("导出时可选择 MD / TXT / JSON", 9,
                        theme.TEXT_MAIN), top_border=False))
        storage.body.addSpacing(10)
        self.history_clear_btn = ghost_button("清空本地记录")
        self.history_clear_btn.clicked.connect(self._clear_history)
        storage.body.addWidget(self.history_clear_btn)
        storage.body.addSpacing(8)
        self.history_open_btn = ghost_button("打开数据目录")
        self.history_open_btn.clicked.connect(self._open_log_dir)
        storage.body.addWidget(self.history_open_btn)
        storage.body.addStretch(1)
        right.addWidget(storage, 1)

        self._load_history()

    # ---------------------------------------------------------------- 组件
    def _history_stat_row(self, key, field):
        row = QWidget()
        layout = hbox(8, (0, 0, 0, 0), row)
        layout.addWidget(lbl(key, 8, theme.TEXT_3))
        layout.addStretch()
        value = mono("--", 8, theme.TEXT_4)
        layout.addWidget(value)
        self.history_stat_labels[field] = value
        return row

    def _history_storage_head(self):
        row = QWidget()
        layout = hbox(12, (0, 0, 0, 0), row)
        layout.addWidget(lbl("本地存储", 11, theme.TEXT_MAIN, 600))
        layout.addStretch()
        self.history_storage_size = mono(
            self._history_cache_size(), 8, theme.TEXT_4)
        layout.addWidget(self.history_storage_size)
        return row

    @staticmethod
    def _history_setting_row(key, control, top_border=False):
        row = QWidget()
        layout = vbox(0, (0, 0, 0, 0), row)
        if top_border:
            layout.addWidget(hline())
        inner = hbox(10, (0, 7, 0, 7))
        inner.addWidget(lbl(key, 9, theme.TEXT_3))
        inner.addStretch()
        inner.addWidget(control)
        layout.addLayout(inner)
        return row

    def _history_cache_size(self):
        path = getattr(self.cache, "cache_file", "")
        try:
            size = os.path.getsize(path)
        except OSError:
            return "--"
        if size >= 1024 ** 2:
            return f"{size / 1024 ** 2:.1f} MB"
        if size >= 1024:
            return f"{size / 1024:.0f} KB"
        return f"{size} B"

    # ---------------------------------------------------------------- 数据
    @staticmethod
    def _parse_ts(value):
        try:
            return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            return None

    def _history_all_rows(self):
        """全部历史记录，按时间倒序：[(时间, 分类, 记录)]。"""
        try:
            all_data = self.cache.get_all_history() or {}
        except Exception:
            all_data = {}
        rows = []
        for category in _CATEGORY_META:
            for record in all_data.get(category) or []:
                if isinstance(record, dict):
                    rows.append((str(record.get("timestamp", "")), category, record))
        rows.sort(key=lambda item: item[0], reverse=True)
        return rows

    def _history_records(self):
        rows = self._history_all_rows()
        key = getattr(self, "_history_filter_key", "all")
        if key in _CATEGORY_META:
            rows = [row for row in rows if row[1] == key]
        return rows

    def _history_heat_data(self):
        """近 5 周活跃度：按周一到周日排成 7 行，共 35 格。"""
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        start = monday - timedelta(days=28)
        days = [start + timedelta(days=offset) for offset in range(35)]

        counts = {}
        for stamp, _category, _record in self._history_all_rows():
            parsed = self._parse_ts(stamp)
            if parsed is None:
                continue
            counts[parsed.date()] = counts.get(parsed.date(), 0) + 1

        levels = []
        for day in days:
            count = counts.get(day, 0)
            levels.append(0 if count <= 0 else min(4, count))

        recent_30 = [day for day in days if day <= today][-30:]
        active_days = sum(1 for day in recent_30 if counts.get(day, 0) > 0)
        total_30 = sum(counts.get(day, 0) for day in recent_30)

        longest = current = 0
        for day in days:
            if day <= today and counts.get(day, 0) > 0:
                current += 1
                longest = max(longest, current)
            else:
                current = 0

        return {
            "levels": levels,
            "start": days[0],
            "end": today,
            "active": f"{active_days} 天",
            "streak": f"{longest} 天",
            "average": f"{total_30 / 30:.1f} 次",
        }

    def _history_head_desc(self):
        count = 0
        cutoff = date.today() - timedelta(days=30)
        try:
            rows = self._history_all_rows()
        except Exception:
            rows = []
        for stamp, _category, _record in rows:
            parsed = self._parse_ts(stamp)
            if parsed is not None and parsed.date() >= cutoff:
                count += 1
        return f"最近 30 天共 {count} 次操作，全部保存在本机。"

    def _refresh_history_desc(self):
        label = getattr(self, "history_desc_label", None)
        if label is not None:
            label.setText(self._history_head_desc())

    @staticmethod
    def _clear_widgets(layout):
        while layout.count() > 0:
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _history_refresh_summary(self):
        """刷新热图、统计、累计效果与存储占用。"""
        data = self._history_heat_data()
        self._clear_widgets(self.history_heat_layout)
        self.history_heat_layout.addWidget(
            Heatmap(data["levels"], rows=7, cell=13, gap=3))
        for field in ("active", "streak", "average"):
            label = self.history_stat_labels.get(field)
            if label is not None:
                label.setText(data[field])
        self.history_legend_start.setText(data["start"].strftime("%m/%d"))
        self.history_legend_end.setText(data["end"].strftime("%m/%d"))
        self.history_storage_size.setText(self._history_cache_size())

        self._clear_widgets(self.history_effect_layout)
        all_rows = self._history_all_rows()
        last_stamp = "--"
        if all_rows:
            parsed = self._parse_ts(all_rows[0][0])
            last_stamp = parsed.strftime("%m/%d %H:%M") if parsed else "--"
        self.history_effect_layout.addWidget(MiniGrid([
            ("记录总数", str(len(all_rows)), "条", theme.TEXT_MAIN),
            ("活跃天数", data["active"].replace(" 天", ""), "天",
             theme.TEXT_MAIN),
            ("最近记录", last_stamp, "", theme.TEXT_MAIN),
        ], columns=3))

    # ---------------------------------------------------------------- 渲染
    def _load_history(self):
        """加载历史记录"""
        while self.history_layout.count() > 0:
            item = self.history_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        self._refresh_history_desc()
        self._history_refresh_summary()
        rows = self._history_records()

        if not rows:
            self.history_layout.addWidget(self._history_date_label("暂无记录"))
            self._add_empty_history_item()
        else:
            show_all = bool(getattr(self, "_history_show_all", False))
            shown = rows if show_all else rows[:_ROW_LIMIT]
            last_date = None
            for stamp, category, record in shown:
                parsed = self._parse_ts(stamp)
                day = parsed.date() if parsed else None
                if day != last_date:
                    self.history_layout.addWidget(
                        self._history_date_label(self._history_day_text(day)))
                    last_date = day
                self._add_history_item(record, category)

        self.history_layout.addStretch()
        footer = hbox(8, (0, 10, 0, 0))
        footer.addWidget(lbl(
            f"显示 {len(rows) if self._history_show_all else min(len(rows), _ROW_LIMIT)}"
            f" / {len(rows)} 条", 9, theme.TEXT_3))
        footer.addStretch()
        footer.addWidget(mono(
            f"{len(self._history_all_rows())} RECORDS TOTAL", 9, theme.TEXT_3))
        footer_widget = QWidget()
        footer_widget.setLayout(footer)
        self.history_layout.addWidget(footer_widget)

        # 超过一屏时显示「显示全部 / 收起」
        self.history_toggle_btn.setVisible(len(rows) > _ROW_LIMIT)
        self.history_toggle_btn.setText(
            "收起" if self._history_show_all else "显示全部")

    def _history_day_text(self, day):
        if day is None:
            return "较早记录"
        today = date.today()
        if day == today:
            return f"今天 · {day:%m/%d}"
        if day == today - timedelta(days=1):
            return f"昨天 · {day:%m/%d}"
        return f"{day:%m/%d}"

    @staticmethod
    def _history_date_label(text):
        row = QWidget()
        layout = hbox(8, (0, 9, 0, 4), row)
        dot = QLabel()
        dot.setFixedSize(4, 4)
        dot.setStyleSheet(
            f"background-color: {theme.TEXT_4}; border-radius: 2px;")
        layout.addWidget(dot)
        layout.addWidget(lbl(text, 8, theme.TEXT_4, 400, True, 1.12))
        return row

    def _add_history_item(self, record, category):
        """添加一条时间线记录。"""
        parsed = self._parse_ts(record.get("timestamp", ""))
        stamp = parsed.strftime("%H:%M") if parsed else "--:--"
        title, icon_name = _CATEGORY_META.get(
            category, (_CATEGORY_LABELS.get(category, "操作"), "clock"))
        desc, value, tag = self._history_entry_meta(category, record.get("result"))

        item = QWidget()
        item_layout = vbox(0, (0, 0, 0, 0), item)
        item_layout.addWidget(hline())
        inner = hbox(11, (0, 9, 0, 9))

        time_label = mono(stamp, 8, theme.TEXT_4)
        time_label.setFixedWidth(38)
        inner.addWidget(time_label)

        box = QFrame()
        box.setFixedSize(25, 25)
        mint = category == "dns"
        box.setStyleSheet(
            "QFrame { background-color: "
            + ("#0d8bffd1" if mint else "#0c0c0f")
            + "; border: 1px solid "
            + ("#3d8bffd1" if mint else theme.LINE)
            + "; border-radius: 7px; }")
        box_layout = vbox(0, (0, 0, 0, 0), box)
        box_layout.setAlignment(Qt.AlignCenter)
        box_layout.addWidget(
            ic(icon_name, 12, theme.MINT if mint else theme.TEXT_2),
            0, Qt.AlignCenter)
        inner.addWidget(box, 0, Qt.AlignVCenter)

        text = vbox(0, (0, 0, 0, 0))
        title_label = lbl(title, 10, theme.TEXT_MAIN, 500)
        title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        text.addWidget(title_label)
        desc_label = mono(desc, 8, theme.TEXT_4)
        desc_label.setContentsMargins(0, 4, 0, 0)
        desc_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        text.addWidget(desc_label)
        inner.addLayout(text, 1)

        result = vbox(0, (0, 0, 0, 0))
        value_label = mono(value, 9, theme.TEXT_2)
        value_label.setAlignment(Qt.AlignRight)
        result.addWidget(value_label)
        tag_label = mono(tag, 7, theme.TEXT_4, 0.56)
        tag_label.setContentsMargins(0, 4, 0, 0)
        tag_label.setAlignment(Qt.AlignRight)
        result.addWidget(tag_label)
        inner.addLayout(result)

        item_layout.addLayout(inner)
        item.setCursor(Qt.PointingHandCursor)
        item.setToolTip("点击查看详情")
        item.mouseReleaseEvent = lambda event, r=record, c=category: (
            self._show_history_detail(r, c)
            if event.button() == Qt.LeftButton else None)
        self.history_layout.addWidget(item)

    def _add_empty_history_item(self):
        item = QWidget()
        item_layout = vbox(0, (0, 0, 0, 0), item)
        item_layout.addWidget(hline())
        inner = hbox(11, (0, 9, 0, 9))
        inner.addWidget(mono("--:--", 8, theme.TEXT_4))
        box = QFrame()
        box.setFixedSize(25, 25)
        box.setStyleSheet(
            f"QFrame {{ background-color: #0c0c0f; border: 1px solid {theme.LINE};"
            " border-radius: 7px; }")
        box_layout = vbox(0, (0, 0, 0, 0), box)
        box_layout.setAlignment(Qt.AlignCenter)
        box_layout.addWidget(ic("clock", 12, theme.TEXT_2), 0, Qt.AlignCenter)
        inner.addWidget(box)
        text = vbox(0, (0, 0, 0, 0))
        text.addWidget(lbl("暂无历史记录", 10, theme.TEXT_MAIN, 500))
        hint = mono("完成诊断 / 修复 / 测速后会自动记录", 8, theme.TEXT_4)
        hint.setContentsMargins(0, 4, 0, 0)
        text.addWidget(hint)
        inner.addLayout(text, 1)
        right = vbox(0, (0, 0, 0, 0))
        value = mono("--", 9, theme.TEXT_2)
        value.setAlignment(Qt.AlignRight)
        right.addWidget(value)
        tag = mono("EMPTY", 7, theme.TEXT_4, 0.56)
        tag.setContentsMargins(0, 4, 0, 0)
        tag.setAlignment(Qt.AlignRight)
        right.addWidget(tag)
        inner.addLayout(right)
        item_layout.addLayout(inner)
        self.history_layout.addWidget(item)

    def _history_entry_meta(self, category, result):
        """返回 (摘要, 右侧结果, 右侧标签)。"""
        result = result if result is not None else {}
        try:
            if category == "diagnostic":
                items = result if isinstance(result, list) else []
                total = len(items)
                ok = sum(1 for item in items if item.get("status") == "ok")
                bad = total - ok
                score = round(ok / total * 100) if total else 0
                return (f"{total} 项检查 · {bad} 项建议优化",
                        f"{score} 分", "GOOD" if score >= 80 else "CHECK")
            if category == "repair":
                items = result if isinstance(result, list) else []
                total = len(items)
                ok = sum(1 for item in items if item.get("success"))
                return (f"{total} 项修复 · 成功 {ok} 项",
                        f"{ok}/{total}" if total else "--",
                        "DONE" if total and ok == total else "PART")
            if category == "speed":
                dl = result.get("download", {}) if isinstance(result, dict) else {}
                up = result.get("upload", {}) if isinstance(result, dict) else {}
                down = dl.get("speed_mbps", "--")
                return (f"下载 {down} Mbps · 上传 {up.get('speed_mbps', '--')} Mbps",
                        str(down), "MBPS")
            if category == "dns":
                items = result if isinstance(result, list) else []
                best = next((item for item in items if item.get("success")), None)
                if best:
                    latency = best.get("p95") or best.get("latency") or "--"
                    return (f"{best.get('name', 'DNS')} · {best.get('ip', '')}",
                            f"{latency} ms", "DNS")
                return ("DNS 测试无可用结果", "--", "DNS")
            if category == "wifi":
                if isinstance(result, dict) and result.get("connected"):
                    signal = result.get("signal_strength", 0)
                    return (f"{result.get('ssid', '未知')} · 信号 {signal}%",
                            f"{signal}%", "SIGNAL")
                return ("Wi-Fi 未连接", "--", "WIFI")
        except Exception:
            pass
        return ("记录详情不可用", "--", "REC")

    # ---------------------------------------------------------------- 交互
    def _on_history_filter_changed(self, index):
        self._history_filter_key = _FILTER_KEYS[index] \
            if 0 <= index < len(_FILTER_KEYS) else "all"
        self._load_history()

    def _toggle_history_all(self):
        """在「最近 5 条」与「全部记录」之间切换。"""
        self._history_show_all = not getattr(self, "_history_show_all", False)
        self.history_toggle_btn.setText(
            "收起" if self._history_show_all else "显示全部")
        self._load_history()

    def _export_history_report(self):
        from core.report import ReportDoc, ReportSection

        rows = self._history_records()
        if not rows:
            self._set_status("暂无历史记录可导出")
            return
        sections = []
        for category, label in _CATEGORY_LABELS.items():
            lines = []
            for stamp, row_category, record in rows:
                if row_category != category:
                    continue
                lines.append(
                    f"{stamp} · {self._format_history_summary(category, record.get('result'))}")
            if lines:
                sections.append(ReportSection(label, lines))
        doc = ReportDoc(
            kind="history",
            title="历史记录报告",
            summary=f"共 {len(rows)} 条记录",
            sections=sections,
            meta={"导出格式": "Markdown"},
        )
        self._export_report_dialog(doc)

    def _show_history_detail(self, record, category):
        """弹出单条历史记录详情，并支持导出为报告。"""
        from core.report import from_history

        label = _CATEGORY_LABELS.get(category, category)
        result = record.get("result")
        if isinstance(result, (dict, list)):
            body = json.dumps(result, ensure_ascii=False, indent=2)
        else:
            body = str(result)

        dialog = QDialog(self)
        dialog.setWindowTitle(f"{label} · 详情")
        dialog.resize(720, 560)
        dlg_layout = QVBoxLayout(dialog)
        dlg_layout.setContentsMargins(16, 16, 16, 16)
        dlg_layout.setSpacing(10)

        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlainText(
            f"记录类型：{label}\n时间：{record.get('timestamp', '未知时间')}\n\n{body}")
        dlg_layout.addWidget(view, 1)

        row = hbox(10, (0, 0, 0, 0))
        row.addStretch()
        export_btn = QPushButton("导出报告")
        export_btn.setFixedHeight(34)
        export_btn.setCursor(Qt.PointingHandCursor)
        export_btn.setStyleSheet(
            f"QPushButton {{ background-color: {theme.ACCENT};"
            f" color: {theme.TEXT_ON_ACCENT}; border: none; border-radius: 6px;"
            " font-size: 11px; font-weight: bold; padding: 0 18px; }"
            f"QPushButton:hover {{ background-color: {theme.ACCENT_DARK}; }}")
        export_btn.clicked.connect(
            lambda: self._export_report_dialog(from_history(category, record)))
        row.addWidget(export_btn)

        close_btn = QPushButton("关闭")
        close_btn.setFixedHeight(34)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(
            f"QPushButton {{ background-color: {theme.BG_RAISED};"
            f" color: {theme.TEXT_MAIN}; border: 1px solid {theme.BORDER};"
            " border-radius: 6px; font-size: 11px; padding: 0 18px; }"
            f"QPushButton:hover {{ background-color: {theme.ACCENT_LIGHT}; }}")
        close_btn.clicked.connect(dialog.accept)
        row.addWidget(close_btn)
        dlg_layout.addLayout(row)

        dialog.exec()

    def _format_history_summary(self, category, result):
        """格式化历史记录摘要"""
        try:
            if category == "diagnostic":
                ok = sum(1 for r in result if r.get("status") == "ok")
                warn = sum(1 for r in result if r.get("status") == "warning")
                err = sum(1 for r in result if r.get("status") == "error")
                return f"正常{ok}项 | 警告{warn}项 | 异常{err}项"

            elif category == "repair":
                ok = sum(1 for r in result if r.get("success"))
                fail = sum(1 for r in result if not r.get("success"))
                return f"成功{ok}项 | 失败{fail}项"

            elif category == "speed":
                ping = result.get("ping", {})
                dl = result.get("download", {})
                ul = result.get("upload", {})
                latency = ping.get("avg_latency", "--")
                speed = dl.get("speed_mbps", "--")
                up = ul.get("speed_mbps", "--")
                return f"延迟: {latency}ms | 下载: {speed}Mbps | 上传: {up}Mbps"

            elif category == "dns":
                best = None
                for r in result:
                    if r.get("success"):
                        best = r
                        break
                if best:
                    return (f"最优DNS: {best.get('name', '')} "
                            f"({best.get('ip', '')}) 延迟{best.get('latency', '--')}ms")
                return "DNS测试无可用结果"

            elif category == "wifi":
                if result.get("connected"):
                    ssid = result.get("ssid", "未知")
                    signal = result.get("signal_strength", 0)
                    return f"Wi-Fi: {ssid} | 信号: {signal}%"
                return "Wi-Fi未连接"

        except Exception:
            pass

        return "记录详情不可用"

    def _open_log_dir(self):
        """打开数据文件夹（包含日志和历史记录），便于反馈Bug时提供"""
        self.logger.info("用户打开数据文件夹")
        from core.paths import get_data_dir
        data_dir = get_data_dir()
        try:
            if not os.path.exists(data_dir):
                os.makedirs(data_dir)
            os.startfile(data_dir)
        except Exception:
            QMessageBox.information(
                self, "数据位置", "数据文件夹位于：\n" + data_dir)

    def _clear_history(self):
        """清除所有历史记录"""
        reply = QMessageBox.question(
            self, "确认清除",
            "确定要清除所有历史记录吗？\n此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.cache.clear_history()
        self._load_history()
        self._set_status("历史记录已清除")
