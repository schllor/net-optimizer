"""DNS 优化页面。"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QProgressBar, QScrollArea, QMessageBox,
)
from PySide6.QtCore import Qt

import core.theme as theme
from ui.common import Colors
from ui.widgets import LatencyBarWidget
from ui.workers import DnsTestWorker


class DnsPageMixin:
    """DNS 优化页：并发测速、排名、推荐与一键应用。"""

    def _create_dns_page(self):
        """创建DNS优化页面"""
        self.dns_page = QWidget()
        layout = QVBoxLayout(self.dns_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        # 当前DNS信息
        info_card = self._create_card()
        info_layout = QHBoxLayout(info_card)
        info_layout.setContentsMargins(25, 15, 25, 15)

        info_icon = QLabel("●")
        info_icon.setStyleSheet("font-size: 24px;")
        info_icon.setFixedWidth(35)
        info_layout.addWidget(info_icon)

        info_text_layout = QVBoxLayout()
        info_text_layout.setSpacing(3)

        info_title = QLabel("当前DNS")
        info_title.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_SECONDARY};
        """)
        info_text_layout.addWidget(info_title)

        self.current_dns_label = QLabel("检测中...")
        self.current_dns_label.setStyleSheet(f"""
            font-size: 15px;
            font-weight: bold;
            color: {Colors.PRIMARY};
        """)
        info_text_layout.addWidget(self.current_dns_label)

        info_layout.addLayout(info_text_layout, 1)
        layout.addWidget(info_card)

        # 测试按钮
        btn_card = self._create_card()
        btn_layout = QVBoxLayout(btn_card)
        btn_layout.setContentsMargins(30, 20, 30, 20)
        btn_layout.setSpacing(15)

        self.dns_btn = QPushButton("测试所有DNS，推荐最优")
        self.dns_btn.setFixedHeight(50)
        self.dns_btn.setCursor(Qt.PointingHandCursor)
        self.dns_btn.setStyleSheet(theme.accent_button())
        self.dns_btn.clicked.connect(self._start_dns_test)
        btn_layout.addWidget(self.dns_btn)

        self.dns_progress = QProgressBar()
        self.dns_progress.setFixedHeight(20)
        self.dns_progress.setTextVisible(False)
        self.dns_progress.setStyleSheet(theme.progress_bar(chunk_color=Colors.PRIMARY))
        self.dns_progress.hide()
        btn_layout.addWidget(self.dns_progress)

        self.dns_progress_label = QLabel("")
        self.dns_progress_label.setAlignment(Qt.AlignCenter)
        self.dns_progress_label.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_SECONDARY};
        """)
        self.dns_progress_label.hide()
        btn_layout.addWidget(self.dns_progress_label)

        layout.addWidget(btn_card)

        # 推荐结果
        self.dns_recommend_card = self._create_card()
        rec_layout = QHBoxLayout(self.dns_recommend_card)
        rec_layout.setContentsMargins(25, 15, 25, 15)

        rec_icon = QLabel("★")
        rec_icon.setStyleSheet("font-size: 28px;")
        rec_icon.setFixedWidth(40)
        rec_layout.addWidget(rec_icon)

        self.dns_recommend_text = QLabel("点击上方按钮，测试并推荐最优DNS服务器")
        self.dns_recommend_text.setWordWrap(True)
        self.dns_recommend_text.setStyleSheet(f"""
            font-size: 14px;
            color: {Colors.TEXT_SECONDARY};
        """)
        rec_layout.addWidget(self.dns_recommend_text, 1)

        layout.addWidget(self.dns_recommend_card)

        # DNS列表 - 滚动区域
        list_card = self._create_card()
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(15, 15, 15, 15)

        list_title = QLabel("DNS服务器排名")
        list_title.setStyleSheet(f"""
            font-size: 14px;
            font-weight: bold;
            color: {Colors.TEXT_MAIN};
            padding-bottom: 10px;
        """)
        list_layout.addWidget(list_title)

        # 表头
        header_frame = QFrame()
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(10, 5, 10, 5)
        header_layout.setSpacing(0)

        headers = [("排名", 46), ("DNS名称", 96), ("DNS地址", 150), ("延迟", 70), ("地区", 52), ("延迟对比", 0)]
        for text, width in headers:
            label = QLabel(text)
            label.setStyleSheet(f"""
                font-size: 12px;
                font-weight: bold;
                color: {Colors.TEXT_LIGHT};
            """)
            if width:
                label.setFixedWidth(width)
            header_layout.addWidget(label, 1 if width == 0 else 0)

        list_layout.addWidget(header_frame)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"background-color: {Colors.BORDER}; max-height: 1px;")
        list_layout.addWidget(line)

        # 列表滚动区
        list_scroll = QScrollArea()
        list_scroll.setWidgetResizable(True)
        list_scroll.setMinimumHeight(200)
        list_scroll.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: {Colors.BG_INSET};
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

        self.dns_list_widget = QWidget()
        self.dns_list_layout = QVBoxLayout(self.dns_list_widget)
        self.dns_list_layout.setContentsMargins(10, 5, 10, 5)
        self.dns_list_layout.setSpacing(3)

        # 初始提示
        hint = QLabel("点击上方按钮开始测试...")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_LIGHT};
            padding: 20px 0;
        """)
        self.dns_list_layout.addWidget(hint)

        self.dns_list_layout.addStretch()
        list_scroll.setWidget(self.dns_list_widget)
        list_layout.addWidget(list_scroll, 1)

        layout.addWidget(list_card, 1)

        # 加载当前DNS
        self._load_current_dns()

    def _load_current_dns(self):
        """加载当前DNS"""
        dns_list = self.dns_optimizer.get_current_dns()
        dns_text = "、".join(dns_list)
        self.current_dns_label.setText(dns_text)

    def _start_dns_test(self):
        """开始DNS测试"""
        self.logger.info("开始DNS测试")
        self.dns_btn.setEnabled(False)
        self.dns_btn.setText("测试中...")
        self.dns_progress.show()
        self.dns_progress_label.show()
        self.dns_progress.setValue(0)

        self._clear_dns_list()

        self._set_status("正在测试DNS服务器...")

        self.worker = DnsTestWorker()
        self.worker.progress.connect(self._on_dns_progress)
        self.worker.finished.connect(self._on_dns_finished)
        self._start_worker(self.worker)

    def _on_dns_progress(self, percent, name):
        """DNS测试进度"""
        self.dns_progress.setValue(percent)
        self.dns_progress_label.setText(f"正在测试: {name} ({percent}%)")

    def _on_dns_finished(self, results):
        """DNS测试完成"""
        self.dns_btn.setEnabled(True)
        self.dns_btn.setText("重新测试")
        self.dns_progress.hide()
        self.dns_progress_label.hide()

        # 推荐最佳DNS
        best_dns, advice = self.dns_optimizer.get_best_dns(results)
        if best_dns:
            self.dns_recommend_text.setText(
                f"推荐使用: {best_dns['name']} ({best_dns['ip']})\n"
                f"延迟: {best_dns['latency']}ms | {advice}"
            )
            self.dns_recommend_text.setStyleSheet(f"""
                font-size: 14px;
                color: {Colors.SUCCESS};
                font-weight: bold;
                line-height: 1.6;
            """)
        else:
            self.dns_recommend_text.setText(f"{advice}")
            self.dns_recommend_text.setStyleSheet(f"""
                font-size: 14px;
                color: {Colors.ERROR};
                font-weight: bold;
            """)

        # 显示列表
        self._clear_dns_list()

        # 统一比例：以所有可用 DNS 中的最大延迟为满刻度，便于横向对比快慢
        latencies = [d.get("latency") for d in results if d.get("success")]
        max_latency = max(latencies) if latencies else 1

        for i, dns in enumerate(results):
            self._add_dns_list_item(i + 1, dns, max_latency)

        # 应用按钮必须加在 addStretch() 之前，否则会被挤压到底部不可见
        if best_dns:
            apply_btn = QPushButton("一键应用最优DNS")
            apply_btn.setFixedHeight(40)
            apply_btn.setCursor(Qt.PointingHandCursor)
            apply_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {Colors.PRIMARY};
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-size: 14px;
                    font-weight: bold;
                    margin-top: 8px;
                }}
                QPushButton:hover {{
                    background-color: {Colors.PRIMARY_DARK};
                }}
                QPushButton:disabled {{
                    background-color: {Colors.SHADOW_DARK};
                }}
            """)
            self._dns_best_ip = best_dns["ip"]
            apply_btn.clicked.connect(self._apply_best_dns)
            self.dns_list_layout.addWidget(apply_btn)

        self.dns_list_layout.addStretch()
        self._set_status("DNS测试完成")

        self.cache.save_result("dns", results)

    def _clear_dns_list(self):
        """清空DNS列表"""
        while self.dns_list_layout.count() > 0:
            item = self.dns_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _add_dns_list_item(self, rank, dns, max_latency=1):
        """添加DNS列表项"""
        item_frame = QFrame()
        is_best = rank == 1
        bg_color = Colors.SUCCESS_LIGHT if is_best else Colors.BG_RAISED
        item_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_color};
                border-radius: 4px;
            }}
        """)
        item_layout = QHBoxLayout(item_frame)
        item_layout.setContentsMargins(10, 8, 10, 8)
        item_layout.setSpacing(0)

        # 排名
        rank_text = f"★ {rank}" if is_best else f"   {rank}"
        rank_color = Colors.SUCCESS if is_best else Colors.TEXT_SECONDARY
        rank_label = QLabel(rank_text)
        rank_label.setStyleSheet(f"""
            font-size: 13px;
            color: {rank_color};
            font-weight: {'bold' if is_best else 'normal'};
        """)
        rank_label.setFixedWidth(46)
        item_layout.addWidget(rank_label)

        # 名称
        name_label = QLabel(dns.get("name", ""))
        name_label.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_MAIN};
            font-weight: {'bold' if is_best else 'normal'};
        """)
        name_label.setFixedWidth(96)
        item_layout.addWidget(name_label)

        # IP
        ip_label = QLabel(dns.get("ip", ""))
        ip_label.setStyleSheet(f"""
            font-size: 12px;
            color: {Colors.TEXT_SECONDARY};
            font-family: Consolas, Monaco, monospace;
        """)
        ip_label.setFixedWidth(150)
        item_layout.addWidget(ip_label)

        # 延迟
        if dns.get("success"):
            latency = dns["latency"]
            latency_text = f"{latency}ms"
            if latency < 30:
                latency_color = Colors.SUCCESS
            elif latency < 100:
                latency_color = Colors.WARNING
            else:
                latency_color = Colors.ERROR
        else:
            latency_text = "不可用"
            latency_color = Colors.ERROR

        latency_label = QLabel(latency_text)
        latency_label.setStyleSheet(f"""
            font-size: 13px;
            color: {latency_color};
            font-weight: bold;
        """)
        latency_label.setFixedWidth(70)
        item_layout.addWidget(latency_label)

        # 地区
        region = dns.get("region", "")
        region_color = Colors.PRIMARY if region == "国内" else Colors.TEXT_LIGHT
        region_label = QLabel(region)
        region_label.setStyleSheet(f"""
            font-size: 12px;
            color: {region_color};
        """)
        region_label.setFixedWidth(52)
        item_layout.addWidget(region_label)

        # 延迟对比条（占满剩余宽度，统一满刻度）
        bar = LatencyBarWidget()
        if dns.get("success"):
            bar.set_latency(dns["latency"], max_latency, latency_color)
        else:
            bar.set_unavailable()
        item_layout.addWidget(bar, 1)

        self.dns_list_layout.addWidget(item_frame)

    def _apply_best_dns(self):
        """一键应用最优DNS"""
        dns_ip = getattr(self, "_dns_best_ip", None)
        if not dns_ip:
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

        success, message = self.dns_optimizer.set_dns(dns_ip)
        if success:
            QMessageBox.information(self, "设置成功", message)
            self._load_current_dns()
        else:
            QMessageBox.warning(self, "设置失败", message)

        self._set_status("就绪")
