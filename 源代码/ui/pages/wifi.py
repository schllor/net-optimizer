"""Wi-Fi 检测页面。"""

import datetime
import os
import platform

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QApplication,
)
from PySide6.QtCore import Qt, QTimer

import core.theme as theme
from core.paths import get_data_dir
from core.theme import RADIUS_SMALL
from core.version import __version__
from ui.common import Colors, LEVEL_COLORS
from ui.widgets import SignalArcWidget
from ui.workers import WifiCheckWorker


class WifiPageMixin:
    """Wi-Fi 检测页：信号弧、质量评估与诊断信息导出。"""

    def _create_wifi_page(self):
        """创建Wi-Fi检测页面"""
        self.wifi_page = QWidget()
        layout = QVBoxLayout(self.wifi_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        # 检测按钮
        btn_card = self._create_card()
        btn_layout = QVBoxLayout(btn_card)
        btn_layout.setContentsMargins(30, 20, 30, 20)

        self.wifi_btn = QPushButton("检测Wi-Fi状态")
        self.wifi_btn.setFixedHeight(50)
        self.wifi_btn.setCursor(Qt.PointingHandCursor)
        self.wifi_btn.setStyleSheet(theme.accent_button())
        self.wifi_btn.clicked.connect(self._start_wifi_check)
        btn_layout.addWidget(self.wifi_btn)

        layout.addWidget(btn_card)

        # Wi-Fi信息卡片
        info_layout = QHBoxLayout()
        info_layout.setSpacing(15)

        # 信号强度卡片
        signal_card = self._create_card()
        signal_layout = QVBoxLayout(signal_card)
        signal_layout.setContentsMargins(20, 20, 20, 20)
        signal_layout.setSpacing(8)

        signal_title = QLabel("信号强度")
        signal_title.setAlignment(Qt.AlignCenter)
        signal_title.setStyleSheet(f"""
            font-size: 14px;
            color: {Colors.TEXT_SECONDARY};
        """)
        signal_layout.addWidget(signal_title)

        self.wifi_signal_value = QLabel("--%")
        self.wifi_signal_value.setAlignment(Qt.AlignCenter)
        self.wifi_signal_value.setStyleSheet(f"""
            font-size: 42px;
            font-weight: bold;
            color: {Colors.TEXT_LIGHT};
        """)
        signal_layout.addWidget(self.wifi_signal_value)

        self.wifi_signal_level = QLabel("等待检测")
        self.wifi_signal_level.setAlignment(Qt.AlignCenter)
        self.wifi_signal_level.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_LIGHT};
            padding-top: 5px;
        """)
        signal_layout.addWidget(self.wifi_signal_level)

        # Wi-Fi 四段弧信号表（替换单调进度条，弱/满一眼可辨）
        self.wifi_signal_arc = SignalArcWidget()
        self.wifi_signal_arc.setFixedHeight(96)
        self.wifi_signal_arc.set_signal(0, Colors.TEXT_LIGHT)
        signal_layout.addWidget(self.wifi_signal_arc)

        info_layout.addWidget(signal_card)

        # Wi-Fi名称卡片
        name_card = self._create_card()
        name_layout = QVBoxLayout(name_card)
        name_layout.setContentsMargins(20, 20, 20, 20)
        name_layout.setSpacing(8)

        name_title = QLabel("Wi-Fi名称")
        name_title.setAlignment(Qt.AlignCenter)
        name_title.setStyleSheet(f"""
            font-size: 14px;
            color: {Colors.TEXT_SECONDARY};
        """)
        name_layout.addWidget(name_title)

        self.wifi_ssid_value = QLabel("--")
        self.wifi_ssid_value.setAlignment(Qt.AlignCenter)
        self.wifi_ssid_value.setWordWrap(True)
        self.wifi_ssid_value.setStyleSheet(f"""
            font-size: 22px;
            font-weight: bold;
            color: {Colors.TEXT_LIGHT};
        """)
        name_layout.addWidget(self.wifi_ssid_value, 1)

        self.wifi_channel_label = QLabel("")
        self.wifi_channel_label.setAlignment(Qt.AlignCenter)
        self.wifi_channel_label.setStyleSheet(f"""
            font-size: 12px;
            color: {Colors.TEXT_LIGHT};
        """)
        name_layout.addWidget(self.wifi_channel_label)

        info_layout.addWidget(name_card)

        layout.addLayout(info_layout)

        # 弱信号 / 冲突信道 橙色预警条（点击跳转一键优化）
        self.wifi_warn_bar = QFrame()
        self.wifi_warn_bar.setCursor(Qt.PointingHandCursor)
        self.wifi_warn_bar.mousePressEvent = self._on_wifi_warn_click
        self.wifi_warn_bar.setStyleSheet(f"""
            background-color: {Colors.WARNING_LIGHT};
            border-radius: {RADIUS_SMALL};
        """)
        _wl = QHBoxLayout(self.wifi_warn_bar)
        _wl.setContentsMargins(14, 10, 14, 10)
        self.wifi_warn_label = QLabel("")
        self.wifi_warn_label.setStyleSheet(
            f"color: {Colors.WARNING}; font-size: 13px; font-weight: bold;")
        _wl.addWidget(self.wifi_warn_label)
        _wl.addStretch()
        _warn_go = QLabel("去一键优化  →")
        _warn_go.setStyleSheet(f"color: {Colors.PRIMARY}; font-size: 13px; font-weight: bold;")
        _wl.addWidget(_warn_go)
        self.wifi_warn_bar.hide()
        layout.addWidget(self.wifi_warn_bar)

        # 优化建议
        advice_card = QFrame()
        advice_card.setStyleSheet(f"""
            background-color: {Colors.SUCCESS_LIGHT};
            border-radius: 8px;
        """)
        advice_layout = QVBoxLayout(advice_card)
        advice_layout.setContentsMargins(20, 15, 20, 15)
        advice_layout.setSpacing(8)

        advice_title = QLabel("Wi-Fi优化建议")
        advice_title.setStyleSheet(f"""
            font-size: 14px;
            font-weight: bold;
            color: {Colors.SUCCESS};
        """)
        advice_layout.addWidget(advice_title)

        self.wifi_advice_label = QLabel("点击上方按钮检测Wi-Fi状态，获取个性化优化建议")
        self.wifi_advice_label.setWordWrap(True)
        self.wifi_advice_label.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.SUCCESS};
            line-height: 1.8;
        """)
        advice_layout.addWidget(self.wifi_advice_label)

        # 复制诊断信息按钮（未连接/异常时显示，便于跨电脑排查）
        self.wifi_diag_btn = QPushButton("复制诊断信息")
        self.wifi_diag_btn.setCursor(Qt.PointingHandCursor)
        self.wifi_diag_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.BG_RAISED}; color: {Colors.TEXT_MAIN};
                border: 1px solid {Colors.BORDER}; border-radius: 6px;
                padding: 9px; font-size: 13px; font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {Colors.PRIMARY_LIGHT};
            }}
        """)
        self.wifi_diag_btn.clicked.connect(self._copy_diag_info)
        self.wifi_diag_btn.hide()
        advice_layout.addWidget(self.wifi_diag_btn)

        layout.addWidget(advice_card)
        layout.addStretch()

    def _start_wifi_check(self):
        """开始Wi-Fi检测"""
        self.logger.info("开始Wi-Fi检测")
        self.wifi_btn.setEnabled(False)
        self.wifi_btn.setText("检测中...")
        self._set_status("正在检测Wi-Fi...")

        self.worker = WifiCheckWorker()
        self.worker.finished.connect(self._on_wifi_finished)
        self._start_worker(self.worker)

    def _on_wifi_finished(self, info):
        """Wi-Fi检测完成（安全包装：任何异常都不会以报错形式外泄到界面）"""
        try:
            self._on_wifi_finished_impl(info)
        except Exception:
            self.logger.exception("Wi-Fi检测结果处理出现异常")
            self.wifi_btn.setEnabled(True)
            self.wifi_btn.setText("重新检测")
            self.wifi_signal_value.setText("--")
            self.wifi_ssid_value.setText("未连接Wi-Fi")
            self.wifi_advice_label.setText("检测遇到问题，请点击重新检测；若持续异常，请检查网络适配器是否正常")
            self.wifi_advice_label.setStyleSheet(
                f"font-size: 13px; color: {Colors.ERROR}; line-height: 1.8;")
            self._set_status("Wi-Fi检测完成（出现异常）")

    def _on_wifi_finished_impl(self, info):
        """Wi-Fi检测完成（内部实现）"""
        self.wifi_btn.setEnabled(True)
        self.wifi_btn.setText("重新检测")

        if info is None or not isinstance(info, dict):
            info = {"success": False, "connected": False,
                    "error": "未获取到Wi-Fi信息，请确认已安装无线网卡"}

        if not info.get("success") or not info.get("connected"):
            self.wifi_signal_value.setText("--")
            self.wifi_signal_value.setStyleSheet(f"font-size: 42px; font-weight: bold; color: {Colors.ERROR};")
            self.wifi_signal_level.setText("未连接")
            self.wifi_signal_level.setStyleSheet(f"font-size: 13px; color: {Colors.ERROR}; padding-top: 5px;")
            self.wifi_signal_arc.set_signal(0, Colors.ERROR)

            self.wifi_ssid_value.setText("未连接Wi-Fi")
            self.wifi_ssid_value.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {Colors.ERROR};")
            self.wifi_channel_label.setText("")

            error_msg = info.get("error") or "未连接到Wi-Fi网络：请连接Wi-Fi后重新检测"
            self.wifi_advice_label.setText(error_msg)
            self.wifi_advice_label.setStyleSheet(f"font-size: 13px; color: {Colors.ERROR}; line-height: 1.8;")
            self.wifi_diag_btn.show()
            self.wifi_warn_bar.hide()

            self._set_status("Wi-Fi检测完成（未连接）")
            return

        # 信号强度（netsh 不可用时由 ipconfig 兜底判定为已连接，无信号量则显示占位）
        fallback = info.get("_source") == "ipconfig" or "signal_strength" not in info
        if fallback:
            self.wifi_signal_value.setText("--")
            self.wifi_signal_value.setStyleSheet(f"font-size: 42px; font-weight: bold; color: {Colors.TEXT_MAIN};")
            self.wifi_signal_level.setText("已连接")
            self.wifi_signal_level.setStyleSheet(f"font-size: 13px; color: {Colors.SUCCESS}; padding-top: 5px; font-weight: bold;")
            self.wifi_signal_arc.set_signal(0, Colors.SUCCESS)
        else:
            signal = info.get("signal_strength", 0)
            self.wifi_signal_value.setText(f"{signal}%")
            self.wifi_signal_value.setStyleSheet(f"font-size: 42px; font-weight: bold; color: {Colors.TEXT_MAIN};")

            level_text, level_key, _ = self.wifi_checker.get_signal_level(signal)
            level_color = LEVEL_COLORS.get(level_key, Colors.TEXT_MAIN)
            self.wifi_signal_level.setText(level_text)
            self.wifi_signal_level.setStyleSheet(f"font-size: 13px; color: {level_color}; padding-top: 5px; font-weight: bold;")

            # 按信号强度点亮四段弧信号表
            self.wifi_signal_arc.set_signal(signal, level_color)

        # SSID
        if info.get("ssid"):
            ssid = info["ssid"]
        else:
            ssid = "已有网络连接（名称暂未获取）" if fallback else "未知"
        self.wifi_ssid_value.setText(ssid)
        self.wifi_ssid_value.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {Colors.TEXT_MAIN};")

        # 频道
        channel = info.get("channel", "")
        if channel:
            self.wifi_channel_label.setText(f"频道: {channel}")
            self.wifi_channel_label.setStyleSheet(f"font-size: 12px; color: {Colors.TEXT_SECONDARY};")
        elif fallback:
            self.wifi_channel_label.setText("信号强度与频道详情需升级驱动后获取")
            self.wifi_channel_label.setStyleSheet(f"font-size: 12px; color: {Colors.WARNING};")

        # 优化建议
        advice_list = self.wifi_checker.get_wifi_advice(info) or []
        if fallback:
            advice_list.insert(0, "已确认电脑连接了Wi-Fi网络。当前系统未返回信号强度等详情，可能与无线网卡驱动有关，可尝试重装/更新Wi-Fi驱动后重新检测。")
        advice_text = "\n".join(advice_list)
        self.wifi_advice_label.setText(advice_text)
        self.wifi_advice_label.setStyleSheet(f"font-size: 13px; color: {Colors.SUCCESS}; line-height: 1.8;")
        self._update_wifi_warning(info, fallback, advice_list)
        self.wifi_diag_btn.hide()
        self.wifi_diag_btn.setText("复制诊断信息")

        self._set_status("Wi-Fi检测完成")

        self.cache.save_result("wifi", info)

    def _on_wifi_warn_click(self, event):
        """点击预警条时跳转到一键修复页"""
        self._switch_page("repair")

    def _update_wifi_warning(self, info, fallback, advice_list):
        """根据检测结果显示弱信号/信道冲突的橙色预警条"""
        msg = ""
        if not fallback:
            signal = info.get("signal_strength", 100)
            if signal < 50:
                msg = "信号偏弱，可能影响网速，建议靠近路由器"
        if not msg:
            for a in advice_list:
                if any(k in a for k in ("信道", "拥堵", "干扰", "拥挤")):
                    msg = "检测到Wi-Fi信道可能拥挤或受干扰"
                    break
        if msg:
            self.wifi_warn_label.setText("!  " + msg)
            self.wifi_warn_bar.show()
        else:
            self.wifi_warn_bar.hide()

    def _run_diag_cmd(self, cmd):
        """安全运行命令并返回解码后的文本（逐条自动识别 GBK/UTF-8，禁止抛错）"""
        from core.cmd_utils import run_cmd
        return run_cmd(cmd, timeout=12)

    def _gather_wifi_diag(self):
        """汇总网络环境诊断文本（便于复制后跨电脑排查）"""
        parts = [
            "【网络优化助手 诊断信息】",
            f"版本: v{__version__}",
            f"系统: {platform.platform()}",
            f"Python/PyInstaller 目标: {platform.machine()}",
            f"生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "==== netsh wlan show interfaces ====",
            self._run_diag_cmd(["netsh", "wlan", "show", "interfaces"]),
            "",
            "==== netsh wlan show drivers ====",
            self._run_diag_cmd(["netsh", "wlan", "show", "drivers"]),
            "",
            "==== 无线本地信息 (ipconfig /all) ====",
            self._run_diag_cmd(["ipconfig", "/all"]),
        ]
        return "\n".join(parts)

    def _copy_diag_info(self):
        """一键复制诊断信息到剪贴板，并另存一份到软件同目录(便于迁移)"""
        diag = self._gather_wifi_diag()
        try:
            QApplication.clipboard().setText(diag)
            copied = True
        except Exception:
            copied = False

        saved = None
        try:
            save_path = os.path.join(get_data_dir(), "wifi_diag.txt")
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(diag)
            saved = save_path
        except Exception:
            saved = None

        if copied:
            self.wifi_diag_btn.setText("已复制诊断信息")
            tip = "诊断信息已复制，可直接粘贴发给我"
            if saved:
                tip += f"；并已保存到软件目录 {os.path.basename(saved)}"
            self._set_status(tip)
        else:
            self.wifi_diag_btn.setText("复制失败")
            self._set_status("复制诊断信息失败，请重试")
        QTimer.singleShot(2500, lambda: self.wifi_diag_btn.setText("复制诊断信息"))
