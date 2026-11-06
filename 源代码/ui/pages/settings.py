"""设置页面：测速时长、DNS 轮数、历史上限与探测方式。"""

import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFormLayout,
    QLineEdit, QSpinBox, QCheckBox, QFileDialog,
)
from PySide6.QtCore import Qt

import core.theme as theme
from core.settings import apply_runtime
from ui.common import Colors


class SettingsPageMixin:
    """设置页：读写 data/settings.json，保存后立即生效。"""

    def _create_settings_page(self):
        self.settings_page = QWidget()
        layout = QVBoxLayout(self.settings_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        card = self._create_card()
        form = QFormLayout(card)
        form.setContentsMargins(30, 24, 30, 24)
        form.setHorizontalSpacing(20)
        form.setVerticalSpacing(14)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.set_download_dir = QLineEdit()
        self.set_download_dir.setPlaceholderText("留空则使用系统默认下载目录")
        form.addRow("下载保存目录", self._settings_dir_row(self.set_download_dir))

        self.set_report_dir = QLineEdit()
        self.set_report_dir.setPlaceholderText("留空则保存到软件数据目录 reports 文件夹")
        form.addRow("报告导出目录", self._settings_dir_row(self.set_report_dir))

        self.set_speed_dl = QSpinBox()
        self.set_speed_dl.setRange(3, 30)
        self.set_speed_dl.setSuffix(" 秒")
        form.addRow("下载测速时长", self.set_speed_dl)

        self.set_speed_ul = QSpinBox()
        self.set_speed_ul.setRange(3, 20)
        self.set_speed_ul.setSuffix(" 秒")
        form.addRow("上传测速时长", self.set_speed_ul)

        self.set_dns_rounds = QSpinBox()
        self.set_dns_rounds.setRange(1, 6)
        self.set_dns_rounds.setSuffix(" 轮")
        form.addRow("DNS 测试轮数", self.set_dns_rounds)

        self.set_history_limit = QSpinBox()
        self.set_history_limit.setRange(5, 100)
        self.set_history_limit.setSuffix(" 条")
        form.addRow("历史记录保留", self.set_history_limit)

        self.set_dl_conn = QSpinBox()
        self.set_dl_conn.setRange(1, 16)
        self.set_dl_conn.setSuffix(" 路")
        self.set_dl_conn.setToolTip(
            "下载器最多同时使用的连接数；从 4 路起步，按网速自动增加。\n"
            "部分站点并发过高会限流（403/429），遇到时可调低。")
        form.addRow("下载并发连接", self.set_dl_conn)

        self.set_animations = QCheckBox("显示顶部流光进度条")
        form.addRow("界面动画", self.set_animations)

        self.set_native_api = QCheckBox("优先使用系统原生接口（WlanAPI / IP Helper）")
        self.set_native_api.setToolTip(
            "原生接口语言无关、不依赖 netsh 文本；失败时会自动回退 netsh/arp")
        form.addRow("探测方式", self.set_native_api)

        self.set_traffic_vpn = QCheckBox("实时网速统计包含 VPN 隧道接口")
        form.addRow("实时网速", self.set_traffic_vpn)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        save_btn = QPushButton("保存设置")
        save_btn.setFixedHeight(38)
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.setStyleSheet(theme.accent_button())
        save_btn.clicked.connect(self._save_settings)
        btn_row.addWidget(save_btn)

        reset_btn = QPushButton("恢复默认")
        reset_btn.setFixedHeight(38)
        reset_btn.setCursor(Qt.PointingHandCursor)
        reset_btn.setStyleSheet(theme.secondary_button())
        reset_btn.clicked.connect(self._reset_settings)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch()
        form.addRow("", btn_row)

        layout.addWidget(card)

        self.settings_hint = QLabel("")
        self.settings_hint.setWordWrap(True)
        self.settings_hint.setStyleSheet(
            f"font-size: 12px; color: {Colors.TEXT_SECONDARY}; line-height: 1.8;")
        layout.addWidget(self.settings_hint)
        layout.addStretch()

        self._load_settings_into_form()

    def _settings_dir_row(self, edit):
        """目录输入框 + 选择按钮。"""
        row = QWidget()
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        box.addWidget(edit, 1)
        btn = QPushButton("选择…")
        btn.setFixedHeight(34)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(theme.secondary_button())
        btn.clicked.connect(lambda: self._pick_settings_dir(edit))
        box.addWidget(btn)
        return row

    def _pick_settings_dir(self, edit):
        start = edit.text().strip() or os.path.expanduser("~")
        path = QFileDialog.getExistingDirectory(self, "选择文件夹", start)
        if path:
            edit.setText(path)

    def _load_settings_into_form(self):
        """把当前设置回填到控件。"""
        self.set_download_dir.setText(self.settings.get("download_dir", "") or "")
        self.set_report_dir.setText(self.settings.get("report_dir", "") or "")
        self.set_speed_dl.setValue(int(self.settings.get("speed_dl_seconds", 8)))
        self.set_speed_ul.setValue(int(self.settings.get("speed_ul_seconds", 6)))
        self.set_dns_rounds.setValue(int(self.settings.get("dns_rounds", 3)))
        self.set_history_limit.setValue(int(self.settings.get("history_limit", 20)))
        self.set_dl_conn.setValue(int(self.settings.get("download_connections", 8)))
        self.set_animations.setChecked(bool(self.settings.get("animations", True)))
        self.set_native_api.setChecked(bool(self.settings.get("native_api", True)))
        self.set_traffic_vpn.setChecked(
            bool(self.settings.get("traffic_include_vpn", False)))
        self._apply_animation_setting()

    def _collect_settings(self):
        return {
            "download_dir": self.set_download_dir.text().strip(),
            "report_dir": self.set_report_dir.text().strip(),
            "speed_dl_seconds": self.set_speed_dl.value(),
            "speed_ul_seconds": self.set_speed_ul.value(),
            "dns_rounds": self.set_dns_rounds.value(),
            "history_limit": self.set_history_limit.value(),
            "download_connections": self.set_dl_conn.value(),
            "animations": self.set_animations.isChecked(),
            "native_api": self.set_native_api.isChecked(),
            "traffic_include_vpn": self.set_traffic_vpn.isChecked(),
        }

    def _save_settings(self):
        values = self._collect_settings()
        if not self.settings.update(values):
            self.settings_hint.setText(f"保存失败：{self.settings.last_error}")
            self.settings_hint.setStyleSheet(
                f"font-size: 12px; color: {Colors.ERROR}; line-height: 1.8;")
            self._set_status("设置保存失败")
            return

        apply_runtime(self.settings)
        self._apply_history_limit()
        self.traffic.set_include_vpn(values["traffic_include_vpn"])
        self._apply_animation_setting()
        self.settings_hint.setText(
            "设置已保存并立即生效。测速时长与 DNS 轮数会在下次任务开始时使用。")
        self.settings_hint.setStyleSheet(
            f"font-size: 12px; color: {Colors.SUCCESS}; line-height: 1.8;")
        self._set_status("设置已保存")

    def _reset_settings(self):
        if self.settings.reset():
            self._load_settings_into_form()
            apply_runtime(self.settings)
            self._apply_history_limit()
            self.traffic.set_include_vpn(
                bool(self.settings.get("traffic_include_vpn", False)))
            self._apply_animation_setting()
            self.settings_hint.setText("已恢复默认设置。")
            self.settings_hint.setStyleSheet(
                f"font-size: 12px; color: {Colors.SUCCESS}; line-height: 1.8;")
        else:
            self.settings_hint.setText(f"恢复默认失败：{self.settings.last_error}")

    def _apply_animation_setting(self):
        bar = getattr(self, "comet_bar", None)
        if bar is not None:
            bar.set_animations_enabled(
                bool(self.settings.get("animations", True)))

    def _export_report_dialog(self, doc):
        """弹出保存对话框导出报告；成功返回路径，取消/失败返回空串。"""
        from core.report import default_filename, export

        default = default_filename(
            doc, directory=self.settings.get("report_dir") or None)
        path, _ = QFileDialog.getSaveFileName(
            self, "导出报告", default,
            "Markdown (*.md);;纯文本 (*.txt);;JSON (*.json)")
        if not path:
            return ""
        try:
            saved = export(doc, path)
        except OSError as e:
            self._set_status(f"导出失败：{e}")
            return ""
        self._set_status(f"报告已保存：{saved}")
        return saved
