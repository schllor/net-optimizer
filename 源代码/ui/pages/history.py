"""历史记录页面。"""

import json

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QMessageBox, QDialog, QPlainTextEdit,
)
from PySide6.QtCore import Qt

from ui.common import Colors

_CATEGORY_LABELS = {
    "diagnostic": "诊断记录",
    "repair": "修复记录",
    "speed": "测速记录",
    "dns": "DNS测试记录",
    "wifi": "Wi-Fi检测记录",
}


class HistoryPageMixin:
    """历史记录页：诊断/修复/测速等历史查看与清理。"""

    def _create_history_page(self):
        """创建历史记录页面"""
        self.history_page = QWidget()
        layout = QVBoxLayout(self.history_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        # 操作栏
        btn_card = self._create_card()
        btn_layout = QHBoxLayout(btn_card)
        btn_layout.setContentsMargins(25, 15, 25, 15)
        btn_layout.setSpacing(10)

        refresh_btn = QPushButton("刷新记录")
        refresh_btn.setFixedHeight(38)
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.PRIMARY};
                color: {Colors.TEXT_ON_ACCENT};
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-weight: bold;
                padding: 0 20px;
            }}
            QPushButton:hover {{
                background-color: {Colors.PRIMARY_DARK};
            }}
        """)
        refresh_btn.clicked.connect(self._load_history)
        btn_layout.addWidget(refresh_btn)

        clear_btn = QPushButton("清除所有记录")
        clear_btn.setFixedHeight(38)
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.ERROR};
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-weight: bold;
                padding: 0 20px;
            }}
            QPushButton:hover {{
                background-color: #cf6262;
            }}
        """)
        clear_btn.clicked.connect(self._clear_history)
        btn_layout.addWidget(clear_btn)

        log_btn = QPushButton("打开数据文件夹")
        log_btn.setFixedHeight(38)
        log_btn.setCursor(Qt.PointingHandCursor)
        log_btn.setToolTip("打开日志和历史记录所在的文件夹，反馈Bug时可一并提供")
        log_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.BG_RAISED};
                color: {Colors.TEXT_MAIN};
                border: 1px solid {Colors.BORDER};
                border-radius: 6px;
                font-size: 13px;
                padding: 0 20px;
            }}
            QPushButton:hover {{
                background-color: {Colors.PRIMARY_LIGHT};
            }}
        """)
        log_btn.clicked.connect(self._open_log_dir)
        btn_layout.addWidget(log_btn)

        self.history_toggle_btn = QPushButton("显示全部")
        self.history_toggle_btn.setFixedHeight(38)
        self.history_toggle_btn.setCursor(Qt.PointingHandCursor)
        self.history_toggle_btn.setToolTip("展开全部历史记录（条数上限见「设置」页）")
        self.history_toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.BG_RAISED};
                color: {Colors.TEXT_MAIN};
                border: 1px solid {Colors.BORDER};
                border-radius: 6px;
                font-size: 13px;
                padding: 0 20px;
            }}
            QPushButton:hover {{
                background-color: {Colors.PRIMARY_LIGHT};
            }}
        """)
        self.history_toggle_btn.clicked.connect(self._toggle_history_all)
        btn_layout.addWidget(self.history_toggle_btn)

        btn_layout.addStretch()
        layout.addWidget(btn_card)

        # 历史记录内容
        results_scroll = QScrollArea()
        results_scroll.setWidgetResizable(True)
        results_scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: {Colors.BG_CARD};
                border-radius: 8px;
                border: none;
            }}
            QScrollBar:vertical {{
                width: 8px;
                background: {Colors.BG_INSET};
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {Colors.SHADOW_DARK};
                border-radius: 4px;
            }}
        """)

        self.history_widget = QWidget()
        self.history_layout = QVBoxLayout(self.history_widget)
        self.history_layout.setContentsMargins(25, 15, 25, 15)
        self.history_layout.setSpacing(10)

        results_scroll.setWidget(self.history_widget)
        layout.addWidget(results_scroll, 1)

        self._history_show_all = False
        self._load_history()

    def _toggle_history_all(self):
        """在「最近 5 条」与「全部记录」之间切换。"""
        self._history_show_all = not getattr(self, "_history_show_all", False)
        self.history_toggle_btn.setText(
            "收起" if self._history_show_all else "显示全部")
        self._load_history()

    def _load_history(self):
        """加载历史记录"""
        while self.history_layout.count() > 0:
            item = self.history_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        all_data = self.cache.get_all_history()

        category_labels = {
            "diagnostic": ("诊断记录", Colors.PRIMARY),
            "repair": ("修复记录", Colors.SUCCESS),
            "speed": ("测速记录", Colors.PRIMARY),
            "dns": ("DNS测试记录", Colors.PRIMARY),
            "wifi": ("Wi-Fi检测记录", Colors.PRIMARY),
        }
        limit = (max(1, int(getattr(self.cache, "max_records", 20)))
                 if getattr(self, "_history_show_all", False) else 5)

        has_records = False

        for category, (label_text, color) in category_labels.items():
            records = all_data.get(category, [])
            if not records:
                continue

            has_records = True

            # 分类标题
            cat_label = QLabel(label_text)
            cat_label.setStyleSheet(f"""
                font-size: 15px;
                font-weight: bold;
                color: {color};
                padding: 10px 0 5px 0;
            """)
            self.history_layout.addWidget(cat_label)

            for record in records[-limit:]:
                self._add_history_item(record, category)

        if not has_records:
            hint = QLabel("暂无历史记录\n\n使用「一键诊断」「一键修复」「网速测试」等功能后，\n结果会自动保存在这里，方便您下次查看")
            hint.setAlignment(Qt.AlignCenter)
            hint.setStyleSheet(f"""
                font-size: 14px;
                color: {Colors.TEXT_LIGHT};
                padding: 60px 0;
            """)
            self.history_layout.addWidget(hint)

        self.history_layout.addStretch()

    def _add_history_item(self, record, category):
        """添加历史记录项"""
        item_frame = QFrame()
        item_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_RAISED};
                border-radius: 6px;
            }}
        """)
        item_layout = QVBoxLayout(item_frame)
        item_layout.setContentsMargins(15, 10, 15, 10)
        item_layout.setSpacing(5)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)

        # 时间戳
        time_label = QLabel(record.get("timestamp", "未知时间"))
        time_label.setStyleSheet(f"""
            font-size: 12px;
            color: {Colors.TEXT_LIGHT};
        """)
        head.addWidget(time_label)
        head.addStretch()

        detail_btn = QPushButton("查看详情")
        detail_btn.setCursor(Qt.PointingHandCursor)
        detail_btn.setFixedHeight(26)
        detail_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.BG_CARD};
                color: {Colors.TEXT_SECONDARY};
                border: 1px solid {Colors.BORDER};
                border-radius: 4px;
                font-size: 12px;
                padding: 0 10px;
            }}
            QPushButton:hover {{
                background-color: {Colors.PRIMARY_LIGHT};
                color: {Colors.TEXT_MAIN};
            }}
        """)
        detail_btn.clicked.connect(
            lambda checked=False, r=record, c=category: self._show_history_detail(r, c))
        head.addWidget(detail_btn)
        item_layout.addLayout(head)

        # 结果摘要
        result = record.get("result", {})
        summary_text = self._format_history_summary(category, result)

        summary_label = QLabel(summary_text)
        summary_label.setWordWrap(True)
        summary_label.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_SECONDARY};
        """)
        item_layout.addWidget(summary_label)

        self.history_layout.addWidget(item_frame)

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

        row = QHBoxLayout()
        row.addStretch()
        export_btn = QPushButton("导出报告")
        export_btn.setFixedHeight(34)
        export_btn.setCursor(Qt.PointingHandCursor)
        export_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.PRIMARY};
                color: {Colors.TEXT_ON_ACCENT};
                border: none; border-radius: 6px;
                font-size: 13px; font-weight: bold; padding: 0 18px;
            }}
            QPushButton:hover {{ background-color: {Colors.PRIMARY_DARK}; }}
        """)
        export_btn.clicked.connect(
            lambda: self._export_report_dialog(from_history(category, record)))
        row.addWidget(export_btn)

        close_btn = QPushButton("关闭")
        close_btn.setFixedHeight(34)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.BG_RAISED};
                color: {Colors.TEXT_MAIN};
                border: 1px solid {Colors.BORDER};
                border-radius: 6px;
                font-size: 13px; padding: 0 18px;
            }}
            QPushButton:hover {{ background-color: {Colors.PRIMARY_LIGHT}; }}
        """)
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
                    return f"最优DNS: {best.get('name', '')} ({best.get('ip', '')}) 延迟{best.get('latency', '--')}ms"
                return "DNS测试无可用结果"

            elif category == "wifi":
                if result.get("connected"):
                    ssid = result.get("ssid", "未知")
                    signal = result.get("signal_strength", 0)
                    return f"Wi-Fi: {ssid} | 信号: {signal}%"
                else:
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
            import os
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
