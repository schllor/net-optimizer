"""网络诊断页面。"""

import datetime
import platform

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QProgressBar, QScrollArea, QApplication,
)
from PySide6.QtCore import Qt, QTimer

import core.theme as theme
from core.version import __version__, APP_NAME
from ui.common import Colors
from ui.workers import DiagnosticWorker


class DiagnosePageMixin:
    """网络诊断页：并发检测、逐项结果与报告复制。"""

    def _create_diagnose_page(self):
        """创建诊断页面"""
        self.diagnose_page = QWidget()
        layout = QVBoxLayout(self.diagnose_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        # 操作按钮区
        btn_card = self._create_card()
        btn_layout = QVBoxLayout(btn_card)
        btn_layout.setContentsMargins(30, 20, 30, 20)
        btn_layout.setSpacing(15)

        self.diag_btn = QPushButton("开始诊断")
        self.diag_btn.setFixedHeight(50)
        self.diag_btn.setCursor(Qt.PointingHandCursor)
        self.diag_btn.setStyleSheet(theme.accent_button())
        self.diag_btn.clicked.connect(self._start_diagnose)
        btn_layout.addWidget(self.diag_btn)

        # 进度条
        self.diag_progress = QProgressBar()
        self.diag_progress.setFixedHeight(20)
        self.diag_progress.setTextVisible(False)
        self.diag_progress.setStyleSheet(theme.progress_bar(chunk_color=Colors.PRIMARY))
        self.diag_progress.hide()
        btn_layout.addWidget(self.diag_progress)

        self.diag_progress_label = QLabel("")
        self.diag_progress_label.setAlignment(Qt.AlignCenter)
        self.diag_progress_label.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_SECONDARY};
        """)
        self.diag_progress_label.hide()
        btn_layout.addWidget(self.diag_progress_label)

        layout.addWidget(btn_card)

        # 检测步骤清单（诊断时逐项点亮）
        self._diag_steps_card = self._create_card()
        steps_layout = QVBoxLayout(self._diag_steps_card)
        steps_layout.setContentsMargins(25, 18, 25, 18)
        steps_layout.setSpacing(8)

        steps_title = QLabel("检测进度")
        steps_title.setStyleSheet(f"""
            font-size: 14px;
            font-weight: bold;
            color: {Colors.TEXT_MAIN};
            padding-bottom: 4px;
        """)
        steps_layout.addWidget(steps_title)

        self._diag_steps_layout = QVBoxLayout()
        self._diag_steps_layout.setSpacing(6)
        steps_layout.addLayout(self._diag_steps_layout)

        self._diag_step_items = {}   # name -> (icon_label, name_label)
        self._diag_steps_card.hide()
        layout.addWidget(self._diag_steps_card)

        # 结果摘要
        self.diag_summary_card = self._create_card()
        summary_layout = QHBoxLayout(self.diag_summary_card)
        summary_layout.setContentsMargins(25, 20, 25, 20)

        self.diag_summary_icon = QLabel("·")
        self.diag_summary_icon.setStyleSheet("font-size: 36px;")
        self.diag_summary_icon.setFixedWidth(50)
        summary_layout.addWidget(self.diag_summary_icon)

        self.diag_summary_text = QLabel("点击上方按钮，开始检测您的网络状态")
        self.diag_summary_text.setWordWrap(True)
        self.diag_summary_text.setStyleSheet(f"""
            font-size: 15px;
            color: {Colors.TEXT_SECONDARY};
        """)
        summary_layout.addWidget(self.diag_summary_text, 1)

        # 一键复制完整诊断报告（方便新手把结果发给家人/客服排查）
        self.diag_copy_btn = QPushButton("复制报告")
        self.diag_copy_btn.setCursor(Qt.PointingHandCursor)
        self.diag_copy_btn.setStyleSheet(theme.secondary_button())
        self.diag_copy_btn.clicked.connect(self._copy_diagnostic_report)
        self.diag_copy_btn.hide()
        summary_layout.addWidget(self.diag_copy_btn)

        layout.addWidget(self.diag_summary_card)

        # 详细结果 - 滚动区域
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

        self.diag_results_widget = QWidget()
        self.diag_results_layout = QVBoxLayout(self.diag_results_widget)
        self.diag_results_layout.setContentsMargins(25, 15, 25, 15)
        self.diag_results_layout.setSpacing(10)

        # 初始提示
        hint = QLabel("诊断结果将显示在这里...")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_LIGHT};
            padding: 30px 0;
        """)
        self.diag_results_layout.addWidget(hint)

        self.diag_results_layout.addStretch()
        results_scroll.setWidget(self.diag_results_widget)
        layout.addWidget(results_scroll, 1)

    def _start_diagnose(self):
        """开始诊断"""
        self.logger.info("开始一键诊断")
        self.diag_btn.setEnabled(False)
        self.diag_btn.setText("诊断中...")
        self.diag_progress.show()
        self.diag_progress_label.show()
        self.diag_progress.setValue(0)

        self._clear_diag_results()
        self._build_diag_steps()

        self.diag_summary_icon.setText("·")
        self.diag_summary_text.setText("正在检测网络状态，请稍候...")
        self.diag_copy_btn.hide()

        self._set_status("正在进行网络诊断...")

        self.worker = DiagnosticWorker()
        self.worker.progress.connect(self._on_diag_progress)
        self.worker.item_done.connect(self._on_diag_item_done)
        self.worker.finished.connect(self._on_diag_finished)
        self._start_worker(self.worker)

    def _build_diag_steps(self):
        """构建诊断步骤清单（全部置为等待中）"""
        # 清空旧步骤
        while self._diag_steps_layout.count() > 0:
            item = self._diag_steps_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._diag_step_items = {}

        step_names = ["网卡状态", "IP地址", "网关连通性", "DNS解析", "互联网连通性", "多站点延迟", "代理设置"]
        for name in step_names:
            row = QHBoxLayout()
            row.setSpacing(10)
            icon_label = QLabel("○")
            icon_label.setStyleSheet("font-size: 14px;")
            icon_label.setFixedWidth(24)
            row.addWidget(icon_label)

            name_label = QLabel(name)
            name_label.setStyleSheet(f"""
                font-size: 13px;
                color: {Colors.TEXT_SECONDARY};
            """)
            row.addWidget(name_label)
            row.addStretch()

            holder = QWidget()
            holder.setLayout(row)
            self._diag_steps_layout.addWidget(holder)
            self._diag_step_items[name] = (icon_label, name_label)

        self._diag_steps_card.show()

    def _on_diag_item_done(self, result):
        """诊断某项完成：点亮对应步骤"""
        name = result.get("name", "")
        pair = self._diag_step_items.get(name)
        if not pair:
            return
        icon_label, name_label = pair
        status = result.get("status", "ok")
        status_map = {
            "ok": ("√", Colors.SUCCESS),
            "warning": ("!", Colors.WARNING),
            "error": ("×", Colors.ERROR),
        }
        icon, color = status_map.get(status, ("√", Colors.SUCCESS))
        icon_label.setText(icon)
        name_label.setStyleSheet(f"font-size: 13px; color: {color}; font-weight: bold;")

    def _on_diag_progress(self, percent, item_name):
        """诊断进度更新"""
        self.diag_progress.setValue(percent)
        self.diag_progress_label.setText(f"正在检测: {item_name} ({percent}%)")

    def _on_diag_finished(self, results):
        """诊断完成"""
        self.diag_btn.setEnabled(True)
        self.diag_btn.setText("重新诊断")
        self.diag_progress.hide()
        self.diag_progress_label.hide()
        self._diag_steps_card.hide()

        self.diagnostic.results = results

        summary, status = self.diagnostic.get_summary()
        status_icons = {"ok": "√", "warning": "!", "error": "×", "info": "·"}
        status_colors = {
            "ok": Colors.SUCCESS,
            "warning": Colors.WARNING,
            "error": Colors.ERROR,
            "info": Colors.TEXT_SECONDARY
        }

        self.diag_summary_icon.setText(status_icons.get(status, "·"))
        self.diag_summary_text.setText(summary)
        self.diag_summary_text.setStyleSheet(f"font-size: 15px; color: {status_colors.get(status, Colors.TEXT_MAIN)}; font-weight: bold;")

        # 显示详细结果
        self._clear_diag_results()

        title = QLabel("详细检测结果")
        title.setStyleSheet(f"""
            font-size: 15px;
            font-weight: bold;
            color: {Colors.TEXT_MAIN};
            padding-bottom: 5px;
        """)
        self.diag_results_layout.addWidget(title)

        for result in results:
            self._add_diag_result_item(result)

        # 如果有问题，添加修复按钮
        if self.diagnostic.has_issues():
            fix_btn = QPushButton("立即修复（前往一键修复）")
            fix_btn.setFixedHeight(40)
            fix_btn.setCursor(Qt.PointingHandCursor)
            fix_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {Colors.ERROR};
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-size: 14px;
                    font-weight: bold;
                    margin-top: 10px;
                }}
                QPushButton:hover {{
                    background-color: #cf6262;
                }}
            """)
            fix_btn.clicked.connect(lambda: self._switch_page("repair"))
            self.diag_results_layout.addWidget(fix_btn)

        self.diag_results_layout.addStretch()
        self._set_status("诊断完成")

        self.diag_copy_btn.show()
        self.cache.save_result("diagnostic", results)
        self._refresh_home_score()

    def _copy_diagnostic_report(self):
        """把当前诊断结果整理成文本并复制到剪贴板。"""
        results = self.diagnostic.results if self.diagnostic else []
        if not results:
            return
        icons = {"ok": "√", "warning": "!", "error": "×"}
        summary, _ = self.diagnostic.get_summary()
        lines = [
            f"{APP_NAME} v{__version__} 诊断报告",
            f"时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"系统：{platform.platform()}",
            f"结论：{summary}",
            "",
        ]
        for item in results:
            icon = icons.get(item.get("status"), "?")
            lines.append(f"[{icon}] {item.get('name', '')}：{item.get('message', '')}")
        try:
            QApplication.clipboard().setText("\n".join(lines))
            self.diag_copy_btn.setText("已复制")
            self._set_status("诊断报告已复制到剪贴板")
            QTimer.singleShot(
                2000, lambda: self.diag_copy_btn.setText("复制报告"))
        except Exception:
            self.logger.exception("复制诊断报告失败")

    def _clear_diag_results(self):
        """清空诊断结果"""
        while self.diag_results_layout.count() > 0:
            item = self.diag_results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _add_diag_result_item(self, result):
        """添加诊断结果项"""
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

        status_colors = {
            "ok": Colors.SUCCESS,
            "warning": Colors.WARNING,
            "error": Colors.ERROR
        }
        status_icons = {"ok": "√", "warning": "!", "error": "×"}

        icon_label = QLabel(status_icons.get(result["status"], "?"))
        icon_label.setStyleSheet("font-size: 18px;")
        icon_label.setFixedWidth(30)
        item_layout.addWidget(icon_label)

        name_label = QLabel(result["name"])
        name_label.setStyleSheet(f"""
            font-size: 14px;
            font-weight: bold;
            color: {Colors.TEXT_MAIN};
        """)
        name_label.setFixedWidth(100)
        item_layout.addWidget(name_label)

        msg_label = QLabel(result["message"])
        msg_label.setStyleSheet(f"""
            font-size: 13px;
            color: {status_colors.get(result['status'], Colors.TEXT_SECONDARY)};
        """)
        msg_label.setWordWrap(True)
        item_layout.addWidget(msg_label, 1)

        self.diag_results_layout.addWidget(item_frame)
