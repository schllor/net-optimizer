"""网络修复页面。"""

import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QProgressBar, QScrollArea, QMessageBox, QPlainTextEdit,
)
from PySide6.QtCore import Qt

import core.theme as theme
from ui.common import Colors
from ui.workers import RepairWorker


class RepairPageMixin:
    """网络修复页：管理员提示、修复日志与结果汇总。"""

    def _create_repair_page(self):
        """创建修复页面"""
        self.repair_page = QWidget()
        layout = QVBoxLayout(self.repair_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        # 警告提示
        warn_card = QFrame()
        warn_card.setStyleSheet(f"""
            background-color: {Colors.WARNING_LIGHT};
            border-radius: 8px;
        """)
        warn_layout = QHBoxLayout(warn_card)
        warn_layout.setContentsMargins(20, 15, 20, 15)

        warn_icon = QLabel("!")
        warn_icon.setStyleSheet("font-size: 24px;")
        warn_icon.setFixedWidth(35)
        warn_layout.addWidget(warn_icon)

        warn_text = QLabel(
            "部分修复功能需要【管理员权限】。如果修复失败，请右键点击本软件，选择「以管理员身份运行」后再试。\n"
            "修复过程中网络可能会短暂断开，修复完成后建议重启电脑使设置完全生效。"
        )
        warn_text.setWordWrap(True)
        warn_text.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.WARNING};
            line-height: 1.6;
        """)
        warn_layout.addWidget(warn_text, 1)

        layout.addWidget(warn_card)

        # 管理员状态提示
        self.admin_status_card = QFrame()
        admin_bg, admin_color, admin_icon = (
            Colors.SUCCESS_LIGHT, Colors.SUCCESS, "√" if self._is_admin_now() else "!"
        )
        admin_msg = (
            "当前以【管理员身份】运行，可执行全部修复功能。"
            if self._is_admin_now()
            else "当前【未】以管理员身份运行，部分修复功能会失败。"
        )
        self.admin_status_card.setStyleSheet(f"background-color: {admin_bg}; border-radius: 8px;")
        admin_layout = QHBoxLayout(self.admin_status_card)
        admin_layout.setContentsMargins(20, 12, 20, 12)
        admin_icon_label = QLabel(admin_icon)
        admin_icon_label.setStyleSheet("font-size: 20px;")
        admin_icon_label.setFixedWidth(30)
        admin_layout.addWidget(admin_icon_label)
        self.admin_status_label = QLabel(admin_msg)
        self.admin_status_label.setWordWrap(True)
        self.admin_status_label.setStyleSheet(f"font-size: 13px; color: {admin_color}; line-height: 1.6;")
        admin_layout.addWidget(self.admin_status_label, 1)

        # 以管理员身份运行按钮（仅非管理员时显示）
        self.admin_btn = QPushButton("以管理员身份运行")
        self.admin_btn.setFixedHeight(32)
        self.admin_btn.setCursor(Qt.PointingHandCursor)
        self.admin_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.PRIMARY};
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 12px;
                font-weight: bold;
                padding: 0 12px;
            }}
            QPushButton:hover {{
                background-color: {Colors.PRIMARY_DARK};
            }}
        """)
        self.admin_btn.clicked.connect(self._request_admin_relaunch)
        if self._is_admin_now():
            self.admin_btn.hide()
        admin_layout.addWidget(self.admin_btn)
        layout.addWidget(self.admin_status_card)

        # 操作按钮
        btn_card = self._create_card()
        btn_layout = QVBoxLayout(btn_card)
        btn_layout.setContentsMargins(30, 20, 30, 20)
        btn_layout.setSpacing(15)

        self.repair_btn = QPushButton("开始修复")
        self.repair_btn.setFixedHeight(50)
        self.repair_btn.setCursor(Qt.PointingHandCursor)
        self.repair_btn.setStyleSheet(theme.accent_button())
        self.repair_btn.clicked.connect(self._start_repair)
        btn_layout.addWidget(self.repair_btn)

        self.repair_progress = QProgressBar()
        self.repair_progress.setFixedHeight(20)
        self.repair_progress.setTextVisible(False)
        self.repair_progress.setStyleSheet(theme.progress_bar(chunk_color=Colors.PRIMARY))
        self.repair_progress.hide()
        btn_layout.addWidget(self.repair_progress)

        self.repair_progress_label = QLabel("")
        self.repair_progress_label.setAlignment(Qt.AlignCenter)
        self.repair_progress_label.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_SECONDARY};
        """)
        self.repair_progress_label.hide()
        btn_layout.addWidget(self.repair_progress_label)

        layout.addWidget(btn_card)

        # 结果摘要
        self.repair_summary_card = self._create_card()
        summary_layout = QHBoxLayout(self.repair_summary_card)
        summary_layout.setContentsMargins(25, 20, 25, 20)

        self.repair_summary_icon = QLabel("·")
        self.repair_summary_icon.setStyleSheet("font-size: 36px;")
        self.repair_summary_icon.setFixedWidth(50)
        summary_layout.addWidget(self.repair_summary_icon)

        self.repair_summary_text = QLabel("点击上方按钮，开始修复网络问题")
        self.repair_summary_text.setWordWrap(True)
        self.repair_summary_text.setStyleSheet(f"""
            font-size: 15px;
            color: {Colors.TEXT_SECONDARY};
        """)
        summary_layout.addWidget(self.repair_summary_text, 1)

        layout.addWidget(self.repair_summary_card)

        # 实时修复日志
        self.repair_log_card = self._create_card()
        log_layout = QVBoxLayout(self.repair_log_card)
        log_layout.setContentsMargins(20, 15, 20, 15)
        log_layout.setSpacing(8)

        log_title = QLabel("实时修复日志")
        log_title.setStyleSheet(f"""
            font-size: 14px;
            font-weight: bold;
            color: {Colors.TEXT_MAIN};
        """)
        log_layout.addWidget(log_title)

        self.repair_log_view = QPlainTextEdit()
        self.repair_log_view.setReadOnly(True)
        self.repair_log_view.setFixedHeight(150)
        self.repair_log_view.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {Colors.BG_RAISED};
                border: none;
                border-radius: 6px;
                padding: 10px;
                font-family: Consolas, Monaco, monospace;
                font-size: 12px;
                color: {Colors.TEXT_SECONDARY};
            }}
        """)
        log_layout.addWidget(self.repair_log_view)

        self.repair_log_card.hide()
        layout.addWidget(self.repair_log_card)

        # 详细结果
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

        self.repair_results_widget = QWidget()
        self.repair_results_layout = QVBoxLayout(self.repair_results_widget)
        self.repair_results_layout.setContentsMargins(25, 15, 25, 15)
        self.repair_results_layout.setSpacing(10)

        hint = QLabel("修复结果将显示在这里...")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_LIGHT};
            padding: 30px 0;
        """)
        self.repair_results_layout.addWidget(hint)

        self.repair_results_layout.addStretch()
        results_scroll.setWidget(self.repair_results_widget)
        layout.addWidget(results_scroll, 1)

    def _start_repair(self):
        """开始修复"""
        self.logger.info("开始一键修复 (管理员: %s)", self._is_admin_now())
        reply = QMessageBox.question(
            self, "确认修复",
            "即将执行网络修复操作，修复过程中网络可能会短暂断开。\n\n是否继续？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.repair_btn.setEnabled(False)
        self.repair_btn.setText("修复中...")
        self.repair_progress.show()
        self.repair_progress_label.show()
        self.repair_progress.setValue(0)

        self._clear_repair_results()

        # 清空并显示实时日志
        self.repair_log_view.clear()
        self.repair_log_view.appendPlainText(
            f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 开始修复...")
        self.repair_log_card.show()

        self.repair_summary_icon.setText("·")
        self.repair_summary_text.setText("正在修复网络问题，请稍候...")
        self.repair_summary_text.setStyleSheet(f"font-size: 15px; color: {Colors.TEXT_SECONDARY};")

        self._set_status("正在进行网络修复...")

        self.worker = RepairWorker()
        self.worker.progress.connect(self._on_repair_progress)
        self.worker.item_done.connect(self._on_repair_item_done)
        self.worker.finished.connect(self._on_repair_finished)
        self._start_worker(self.worker)

    def _on_repair_item_done(self, result):
        """修复某项完成：实时追加日志行并自动滚动到底部"""
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        name = result.get("name", "")
        success = result.get("success", False)
        message = result.get("message", "")
        flag = "√" if success else "×"
        self.repair_log_view.appendPlainText(f"[{ts}] {flag} {name}：{message}")
        # 自动滚动到底部
        sb = self.repair_log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_repair_progress(self, percent, item_name):
        """修复进度更新"""
        self.repair_progress.setValue(percent)
        self.repair_progress_label.setText(f"正在修复: {item_name} ({percent}%)")

    def _on_repair_finished(self, results):
        """修复完成"""
        self.repair_btn.setEnabled(True)
        self.repair_btn.setText("重新修复")
        self.repair_progress.hide()
        self.repair_progress_label.hide()

        summary, status = self.repair.get_summary(results)
        status_icons = {"ok": "√", "warning": "!", "error": "×"}
        status_colors = {
            "ok": Colors.SUCCESS,
            "warning": Colors.WARNING,
            "error": Colors.ERROR
        }

        self.repair_summary_icon.setText(status_icons.get(status, "·"))
        self.repair_summary_text.setText(summary)
        self.repair_summary_text.setStyleSheet(f"font-size: 15px; color: {status_colors.get(status, Colors.TEXT_MAIN)}; font-weight: bold;")

        self._clear_repair_results()

        title = QLabel("修复详情")
        title.setStyleSheet(f"""
            font-size: 15px;
            font-weight: bold;
            color: {Colors.TEXT_MAIN};
            padding-bottom: 5px;
        """)
        self.repair_results_layout.addWidget(title)

        for result in results:
            self._add_repair_result_item(result)

        # 重启提示
        restart_hint = QLabel("修复完成后建议重启电脑，使所有设置完全生效")
        restart_hint.setAlignment(Qt.AlignCenter)
        restart_hint.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.PRIMARY};
            padding: 10px 0;
        """)
        self.repair_results_layout.addWidget(restart_hint)

        # 修复后一键重新诊断，形成「诊断 → 修复 → 复检」闭环
        redetect_btn = QPushButton("重新诊断网络状态")
        redetect_btn.setFixedHeight(38)
        redetect_btn.setCursor(Qt.PointingHandCursor)
        redetect_btn.setStyleSheet(theme.secondary_button())
        redetect_btn.clicked.connect(self._rediagnose_after_repair)
        self.repair_results_layout.addWidget(redetect_btn)

        self.repair_results_layout.addStretch()
        self._set_status("修复完成")

        # 实时日志补一行完成标记
        self.repair_log_view.appendPlainText(
            f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 修复完成：{summary}")

        self.cache.save_result("repair", results)

        # 总结弹窗
        icon = QMessageBox.Information if status == "ok" else (QMessageBox.Warning if status == "warning" else QMessageBox.Critical)
        msg_box = QMessageBox(self)
        msg_box.setIcon(icon)
        msg_box.setWindowTitle("修复完成")
        msg_box.setText(summary)
        msg_box.setInformativeText("修复完成后建议重启电脑，使所有设置完全生效。")
        msg_box.setStandardButtons(QMessageBox.Ok)
        msg_box.exec()

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
        """添加修复结果项"""
        item_frame = QFrame()
        item_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_RAISED};
                border-radius: 6px;
                padding: 10px;
            }}
        """)
        item_layout = QHBoxLayout(item_frame)
        item_layout.setContentsMargins(15, 10, 15, 10)
        item_layout.setSpacing(15)

        icon = "√" if result["success"] else "×"
        color = Colors.SUCCESS if result["success"] else Colors.ERROR

        icon_label = QLabel(icon)
        icon_label.setStyleSheet("font-size: 18px;")
        icon_label.setFixedWidth(30)
        item_layout.addWidget(icon_label)

        name_label = QLabel(result["name"])
        name_label.setStyleSheet(f"""
            font-size: 14px;
            font-weight: bold;
            color: {Colors.TEXT_MAIN};
        """)
        name_label.setFixedWidth(130)
        item_layout.addWidget(name_label)

        msg_label = QLabel(result["message"])
        msg_label.setStyleSheet(f"""
            font-size: 13px;
            color: {color};
        """)
        msg_label.setWordWrap(True)
        item_layout.addWidget(msg_label, 1)

        self.repair_results_layout.addWidget(item_frame)
