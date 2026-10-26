"""网速测试页面。"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QProgressBar,
)
from PySide6.QtCore import Qt

import core.theme as theme
from ui.common import Colors, LEVEL_COLORS
from ui.workers import SpeedTestWorker


class SpeedPageMixin:
    """网速测试页：延迟/上下行测速、实时曲线与取消。"""

    def _create_speed_page(self):
        """创建测速页面"""
        self.speed_page = QWidget()
        layout = QVBoxLayout(self.speed_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        # 测速按钮
        btn_card = self._create_card()
        btn_layout = QVBoxLayout(btn_card)
        btn_layout.setContentsMargins(30, 20, 30, 20)
        btn_layout.setSpacing(15)

        self.speed_btn = QPushButton("开始测速")
        self.speed_btn.setFixedHeight(50)
        self.speed_btn.setCursor(Qt.PointingHandCursor)
        self.speed_btn.setStyleSheet(theme.accent_button())
        self.speed_btn.clicked.connect(self._start_speed_test)

        self.speed_cancel_btn = QPushButton("取消")
        self.speed_cancel_btn.setFixedHeight(50)
        self.speed_cancel_btn.setFixedWidth(96)
        self.speed_cancel_btn.setCursor(Qt.PointingHandCursor)
        self.speed_cancel_btn.setStyleSheet(theme.secondary_button())
        self.speed_cancel_btn.clicked.connect(self._cancel_speed_test)
        self.speed_cancel_btn.hide()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addWidget(self.speed_btn, 1)
        btn_row.addWidget(self.speed_cancel_btn)
        btn_layout.addLayout(btn_row)

        self.speed_progress = QProgressBar()
        self.speed_progress.setFixedHeight(20)
        self.speed_progress.setTextVisible(False)
        self.speed_progress.setStyleSheet(theme.progress_bar(chunk_color=Colors.PRIMARY))
        self.speed_progress.hide()
        btn_layout.addWidget(self.speed_progress)

        self.speed_status_label = QLabel("")
        self.speed_status_label.setAlignment(Qt.AlignCenter)
        self.speed_status_label.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_SECONDARY};
        """)
        self.speed_status_label.hide()
        btn_layout.addWidget(self.speed_status_label)

        layout.addWidget(btn_card)

        # 结果卡片区域
        results_layout = QHBoxLayout()
        results_layout.setSpacing(15)

        # 延迟卡片
        ping_card = self._create_card()
        ping_layout = QVBoxLayout(ping_card)
        ping_layout.setContentsMargins(20, 20, 20, 20)
        ping_layout.setSpacing(8)

        ping_title = QLabel("网络延迟")
        ping_title.setAlignment(Qt.AlignCenter)
        ping_title.setStyleSheet(f"""
            font-size: 14px;
            color: {Colors.TEXT_SECONDARY};
        """)
        ping_layout.addWidget(ping_title)

        self.ping_value = QLabel("--")
        self.ping_value.setAlignment(Qt.AlignCenter)
        self.ping_value.setStyleSheet(f"""
            font-size: 42px;
            font-weight: bold;
            color: {Colors.TEXT_LIGHT};
        """)
        ping_layout.addWidget(self.ping_value)

        ping_unit = QLabel("毫秒 (ms)")
        ping_unit.setAlignment(Qt.AlignCenter)
        ping_unit.setStyleSheet(f"""
            font-size: 12px;
            color: {Colors.TEXT_LIGHT};
        """)
        ping_layout.addWidget(ping_unit)

        self.ping_level = QLabel("等待测试")
        self.ping_level.setAlignment(Qt.AlignCenter)
        self.ping_level.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_LIGHT};
            padding-top: 5px;
        """)
        ping_layout.addWidget(self.ping_level)

        results_layout.addWidget(ping_card)

        # 下载速度卡片
        download_card = self._create_card()
        dl_layout = QVBoxLayout(download_card)
        dl_layout.setContentsMargins(20, 20, 20, 20)
        dl_layout.setSpacing(8)

        dl_title = QLabel("下载速度")
        dl_title.setAlignment(Qt.AlignCenter)
        dl_title.setStyleSheet(f"""
            font-size: 14px;
            color: {Colors.TEXT_SECONDARY};
        """)
        dl_layout.addWidget(dl_title)

        self.download_value = QLabel("--")
        self.download_value.setAlignment(Qt.AlignCenter)
        self.download_value.setStyleSheet(f"""
            font-size: 42px;
            font-weight: bold;
            color: {Colors.TEXT_LIGHT};
        """)
        dl_layout.addWidget(self.download_value)

        dl_unit = QLabel("Mbps")
        dl_unit.setAlignment(Qt.AlignCenter)
        dl_unit.setStyleSheet(f"""
            font-size: 12px;
            color: {Colors.TEXT_LIGHT};
        """)
        dl_layout.addWidget(dl_unit)

        self.download_level = QLabel("等待测试")
        self.download_level.setAlignment(Qt.AlignCenter)
        self.download_level.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_LIGHT};
            padding-top: 5px;
        """)
        dl_layout.addWidget(self.download_level)

        results_layout.addWidget(download_card)

        # 上传速度卡片
        upload_card = self._create_card()
        ul_layout = QVBoxLayout(upload_card)
        ul_layout.setContentsMargins(20, 20, 20, 20)
        ul_layout.setSpacing(8)

        ul_title = QLabel("上传速度")
        ul_title.setAlignment(Qt.AlignCenter)
        ul_title.setStyleSheet(f"""
            font-size: 14px;
            color: {Colors.TEXT_SECONDARY};
        """)
        ul_layout.addWidget(ul_title)

        self.upload_value = QLabel("--")
        self.upload_value.setAlignment(Qt.AlignCenter)
        self.upload_value.setStyleSheet(f"""
            font-size: 42px;
            font-weight: bold;
            color: {Colors.TEXT_LIGHT};
        """)
        ul_layout.addWidget(self.upload_value)

        ul_unit = QLabel("Mbps")
        ul_unit.setAlignment(Qt.AlignCenter)
        ul_unit.setStyleSheet(f"""
            font-size: 12px;
            color: {Colors.TEXT_LIGHT};
        """)
        ul_layout.addWidget(ul_unit)

        self.upload_level = QLabel("等待测试")
        self.upload_level.setAlignment(Qt.AlignCenter)
        self.upload_level.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_LIGHT};
            padding-top: 5px;
        """)
        ul_layout.addWidget(self.upload_level)

        results_layout.addWidget(upload_card)

        layout.addLayout(results_layout)

        # 实时网速卡片
        net_card = self._create_card()
        net_layout = QVBoxLayout(net_card)
        net_layout.setContentsMargins(20, 15, 20, 15)
        net_layout.setSpacing(10)

        net_title = QLabel("实时网速（每秒刷新，计算机当前全部网卡流量）")
        net_title.setStyleSheet(f"""
            font-size: 14px;
            font-weight: bold;
            color: {Colors.TEXT_MAIN};
        """)
        net_layout.addWidget(net_title)

        net_row = QHBoxLayout()
        net_row.setSpacing(20)

        up_box = QFrame()
        up_box.setStyleSheet(f"background-color: {Colors.PRIMARY_LIGHT}; border-radius: 10px;")
        up_l = QVBoxLayout(up_box)
        up_l.setContentsMargins(16, 12, 16, 12)
        up_tag = QLabel("▲ 上传")
        up_tag.setAlignment(Qt.AlignCenter)
        up_tag.setStyleSheet(f"font-size: 12px; color: {Colors.PRIMARY_DARK};")
        up_l.addWidget(up_tag)
        self.net_up_label = QLabel("--")
        self.net_up_label.setAlignment(Qt.AlignCenter)
        self.net_up_label.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {Colors.TEXT_MAIN};")
        up_l.addWidget(self.net_up_label)

        dn_box = QFrame()
        dn_box.setStyleSheet(f"background-color: {Colors.PRIMARY_LIGHT}; border-radius: 10px;")
        dn_l = QVBoxLayout(dn_box)
        dn_l.setContentsMargins(16, 12, 16, 12)
        dn_tag = QLabel("▼ 下载")
        dn_tag.setAlignment(Qt.AlignCenter)
        dn_tag.setStyleSheet(f"font-size: 12px; color: {Colors.PRIMARY_DARK};")
        dn_l.addWidget(dn_tag)
        self.net_dn_label = QLabel("--")
        self.net_dn_label.setAlignment(Qt.AlignCenter)
        self.net_dn_label.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {Colors.TEXT_MAIN};")
        dn_l.addWidget(self.net_dn_label)

        net_row.addWidget(up_box, 1)
        net_row.addWidget(dn_box, 1)
        net_layout.addLayout(net_row)

        if not self.traffic.enabled:
            hint = QLabel("提示：未安装 psutil，实时网速不可用（不影响测速）")
            hint.setStyleSheet(f"font-size: 12px; color: {Colors.WARNING};")
            net_layout.addWidget(hint)

        layout.addWidget(net_card)

        # 小知识
        tip_card = QFrame()
        tip_card.setStyleSheet(f"""
            background-color: {Colors.PRIMARY_LIGHT};
            border-radius: 8px;
        """)
        tip_layout = QHBoxLayout(tip_card)
        tip_layout.setContentsMargins(20, 12, 20, 12)

        tip_icon = QLabel("!")
        tip_icon.setStyleSheet("font-size: 20px;")
        tip_layout.addWidget(tip_icon)

        tip_text = QLabel("小知识：Mbps是网速单位，10Mbps ≈ 每秒下载1MB。网速越高，打开网页和下载文件越快。")
        tip_text.setStyleSheet(f"""
            font-size: 12px;
            color: {Colors.PRIMARY_DARK};
        """)
        tip_layout.addWidget(tip_text, 1)

        layout.addWidget(tip_card)
        layout.addStretch()

    def _start_speed_test(self):
        """开始测速"""
        self.logger.info("开始网速测试")
        self.speed_btn.setEnabled(False)
        self.speed_btn.setText("测速中...")
        self.speed_cancel_btn.setEnabled(True)
        self.speed_cancel_btn.show()
        self.speed_progress.show()
        self.speed_status_label.show()
        self.speed_progress.setValue(0)

        self.ping_value.setText("--")
        self.ping_value.setStyleSheet(f"font-size: 42px; font-weight: bold; color: {Colors.TEXT_LIGHT};")
        self.ping_level.setText("测试中...")
        self.ping_level.setStyleSheet(f"font-size: 13px; color: {Colors.TEXT_LIGHT}; padding-top: 5px;")

        self.download_value.setText("--")
        self.download_value.setStyleSheet(f"font-size: 42px; font-weight: bold; color: {Colors.TEXT_LIGHT};")
        self.download_level.setText("等待中（实时显示当前速度）...")
        self.download_level.setStyleSheet(f"font-size: 13px; color: {Colors.TEXT_LIGHT}; padding-top: 5px;")

        self.upload_value.setText("--")
        self.upload_value.setStyleSheet(f"font-size: 42px; font-weight: bold; color: {Colors.TEXT_LIGHT};")
        self.upload_level.setText("等待中...")
        self.upload_level.setStyleSheet(f"font-size: 13px; color: {Colors.TEXT_LIGHT}; padding-top: 5px;")

        self._set_status("正在进行网速测试...")
        self._live_style_dl = False
        self._live_style_up = False

        self.worker = SpeedTestWorker()
        self._speed_worker = self.worker
        self.worker.progress.connect(self._on_speed_progress)
        self.worker.status.connect(self._on_speed_status)
        self.worker.live.connect(self._on_speed_live)
        self.worker.upline.connect(self._on_speed_uplive)
        self.worker.finished.connect(self._on_speed_finished)
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

    def _on_speed_live(self, mbps):
        """实时显示当前瞬时下载速度"""
        self.download_value.setText(f"{mbps:.1f}")
        # 频繁回调中避免重复解析 QSS，只在首次切换颜色时设置
        if not getattr(self, "_live_style_dl", False):
            self._live_style_dl = True
            self.download_value.setStyleSheet(
                f"font-size: 42px; font-weight: bold; color: {Colors.PRIMARY};")
        self.download_level.setText("实时测速中...")

    def _on_speed_uplive(self, mbps):
        """实时显示当前瞬时上传速度"""
        self.upload_value.setText(f"{mbps:.1f}")
        if not getattr(self, "_live_style_up", False):
            self._live_style_up = True
            self.upload_value.setStyleSheet(
                f"font-size: 42px; font-weight: bold; color: {Colors.PRIMARY};")
        self.upload_level.setText("实时上传测速中...")

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

    def _update_net_rates(self):
        """每帧由定时器调用，更新底部实时网速显示（psutil 缺失时给一次性提示）"""
        up, dn = self.traffic.sample()
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

    def _on_speed_finished(self, results):
        """测速完成"""
        self.speed_btn.setEnabled(True)
        self.speed_btn.setText("重新测速")
        self.speed_cancel_btn.hide()
        self.speed_progress.hide()
        self.speed_status_label.hide()

        if results.get("cancelled"):
            for value_label in (self.ping_value, self.download_value, self.upload_value):
                value_label.setText("--")
                value_label.setStyleSheet(
                    f"font-size: 42px; font-weight: bold; color: {Colors.TEXT_LIGHT};")
            self.ping_level.setText("测速已取消")
            self.download_level.setText("测速已取消")
            self.upload_level.setText("测速已取消")
            self._set_status("测速已取消")
            self.logger.info("网速测试已取消")
            return
        ping_result = results.get("ping", {})
        if ping_result.get("success"):
            latency = ping_result["avg_latency"]
            self.ping_value.setText(str(latency))
            self.ping_value.setStyleSheet(f"font-size: 42px; font-weight: bold; color: {Colors.TEXT_MAIN};")

            level_text, level_key, _ = self.speed_test.get_latency_level(latency)
            level_color = LEVEL_COLORS.get(level_key, Colors.TEXT_MAIN)
            jitter = ping_result.get("jitter_ms")
            loss = ping_result.get("loss_rate", 0)
            detail = level_text
            if jitter is not None:
                detail += f"  ·  抖动{jitter}ms"
            if loss:
                detail += f"  ·  丢包{loss}%"
            self.ping_level.setText(detail)
            self.ping_level.setStyleSheet(f"font-size: 13px; color: {level_color}; padding-top: 5px; font-weight: bold;")
        else:
            self.ping_value.setText("失败")
            self.ping_value.setStyleSheet(f"font-size: 42px; font-weight: bold; color: {Colors.ERROR};")
            self.ping_level.setText("无法测试")
            self.ping_level.setStyleSheet(f"font-size: 13px; color: {Colors.ERROR}; padding-top: 5px;")

        # 下载速度结果
        download_result = results.get("download", {})
        if download_result.get("success"):
            speed = download_result["speed_mbps"]
            self.download_value.setText(str(speed))
            self.download_value.setStyleSheet(f"font-size: 42px; font-weight: bold; color: {Colors.TEXT_MAIN};")

            level_text, level_key, _ = self.speed_test.get_speed_level(speed)
            level_color = LEVEL_COLORS.get(level_key, Colors.TEXT_MAIN)
            sources = download_result.get("sources")
            peak = download_result.get("peak_mbps")
            detail = level_text
            if sources:
                detail += f"  ·  {sources} 个测速源"
            if peak is not None:
                detail += f"  ·  峰值 {peak}Mbps"
            self.download_level.setText(detail)
            self.download_level.setStyleSheet(f"font-size: 13px; color: {level_color}; padding-top: 5px; font-weight: bold;")
        else:
            self.download_value.setText("失败")
            self.download_value.setStyleSheet(f"font-size: 42px; font-weight: bold; color: {Colors.ERROR};")
            self.download_level.setText("无法测试")
            self.download_level.setStyleSheet(f"font-size: 13px; color: {Colors.ERROR}; padding-top: 5px;")

        # 上传速度结果
        upload_result = results.get("upload", {})
        if upload_result.get("success"):
            up_speed = upload_result["speed_mbps"]
            self.upload_value.setText(str(up_speed))
            self.upload_value.setStyleSheet(f"font-size: 42px; font-weight: bold; color: {Colors.TEXT_MAIN};")

            _, up_key, _ = self.speed_test.get_speed_level(up_speed)
            up_color = LEVEL_COLORS.get(up_key, Colors.TEXT_MAIN)
            peak = upload_result.get("peak_mbps")
            conns = upload_result.get("connections")
            detail = f"{conns} 路上传"
            if peak is not None:
                detail += f"  ·  峰值 {peak}Mbps"
            self.upload_level.setText(detail)
            self.upload_level.setStyleSheet(f"font-size: 13px; color: {up_color}; padding-top: 5px; font-weight: bold;")
        else:
            self.upload_value.setText("暂不可测")
            self.upload_value.setStyleSheet(f"font-size: 28px; font-weight: bold; color: {Colors.WARNING};")
            self.upload_level.setText("本次无法连接到上传服务器，不影响其它指标")
            self.upload_level.setStyleSheet(f"font-size: 12px; color: {Colors.WARNING}; padding-top: 5px;")

        self._set_status("测速完成")

        self.cache.save_result("speed", results)
