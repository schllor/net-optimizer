"""设置页面：按设计稿 screen-10 重构的偏好设置。"""

import os
import sys
from datetime import datetime

from PySide6.QtCore import QRectF, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QLabel, QLineEdit, QPushButton, QSpinBox, QWidget,
)

import core.theme as theme
from core.paths import get_data_dir, get_log_dir
from core.settings import apply_runtime
from core.version import __version__
from ui.kit import (
    Card, IconButton, Pill, Switch, dot, ghost_button, hbox, hline, ic, lbl,
    mono, page_head, primary_button, vbox,
)
from ui.responsive import ResponsiveColumns

_APP_NAME = "网络优化助手"
_RELEASES_URL = "https://github.com/schllor/net-optimizer/releases"


def _assets_base():
    """打包后资源解压到 sys._MEIPASS；源码运行时为 src 目录。"""
    return getattr(
        sys, "_MEIPASS",
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))))


def _human_size(size):
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024.0
    return "--"


class SettingsPageMixin:
    """设置页：读写 data/settings.json，保存后立即生效。"""

    def _create_settings_page(self):
        page = QWidget()
        self.settings_page = page
        layout = vbox(14, (0, 0, 0, 0), page)

        reset = ghost_button("恢复默认")
        reset.clicked.connect(self._reset_settings)
        save = primary_button("保存设置")
        save.clicked.connect(self._save_settings)
        layout.addWidget(page_head(
            "SETTINGS / PREFERENCES",
            "让工具按你的习惯工作。",
            "所有设置仅保存在本机，修改后立即生效。",
            [reset, save]))

        self._build_settings_controls()

        body = ResponsiveColumns(left_stretch=135, right_stretch=100)
        layout.addWidget(body, 1)
        body.add_left(self._settings_pref_card(), 135)

        right = body.right
        right.addWidget(self._settings_download_card())
        right.addWidget(self._settings_about_card())
        right.addWidget(self._settings_privacy_card(), 1)

        self._load_settings_into_form()

    # ---------------------------------------------------------------- 控件
    def _build_settings_controls(self):
        self.set_animations = Switch(True)
        self.set_native_api = Switch(True)
        self.set_traffic_vpn = Switch(False)

        self.set_speed_dl = self._spin(3, 30, 8)
        self.set_speed_ul = self._spin(3, 20, 6)
        self.set_dns_rounds = self._spin(1, 6, 3)
        self.set_history_limit = self._spin(5, 100, 20)
        self.set_dl_conn = self._spin(1, 16, 8)
        self.set_dl_conn.setToolTip(
            "下载器最多同时使用的连接数；从 4 路起步，按网速自动增加。\n"
            "部分站点并发过高会限流（403/429），遇到时可调低。")

        self.set_download_dir = QLineEdit()
        self.set_download_dir.setPlaceholderText("留空则使用系统默认下载目录")
        self.set_report_dir = QLineEdit()
        self.set_report_dir.setPlaceholderText("留空则保存到软件数据目录 reports 文件夹")

    @staticmethod
    def _spin(low, high, value):
        """数值来源：由外层的设计稿步进器调整并显示。"""
        spin = QSpinBox()
        spin.setRange(low, high)
        spin.setValue(value)
        spin.setButtonSymbols(QSpinBox.NoButtons)
        spin.setAccelerated(True)
        return spin

    def _stepper(self, spin):
        """CSS .stepper：- 数值 + 的紧凑步进器。"""
        frame = QFrame()
        frame.setObjectName("setStepper")
        frame.setFixedHeight(30)
        frame.setStyleSheet(
            f"QFrame#setStepper {{ border: 1px solid {theme.LINE};"
            " border-radius: 6px; background: transparent; }"
            "QPushButton { background: transparent; border: none;"
            f" color: {theme.TEXT_3}; font-family: \"{theme.FONT_MONO}\";"
            f" font-size: {theme.text_size(10)}px; padding: 0 7px; }}"
            "QPushButton:hover { color: " + theme.TEXT_2 + "; }"
            f"QPushButton#stepMinus {{ border-right: 1px solid {theme.LINE}; }}"
            f"QPushButton#stepPlus {{ border-left: 1px solid {theme.LINE}; }}")
        box = hbox(0, (0, 0, 0, 0), frame)
        minus = QPushButton("-")
        minus.setObjectName("stepMinus")
        plus = QPushButton("+")
        plus.setObjectName("stepPlus")
        for button in (minus, plus):
            button.setFixedSize(24, 28)
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.StrongFocus)
        minus.clicked.connect(lambda: spin.stepBy(-1))
        plus.clicked.connect(lambda: spin.stepBy(1))

        value = lbl(str(spin.value()), 11, theme.TEXT_2, 400, True)
        value.setAlignment(Qt.AlignCenter)
        value.setFixedSize(38, 28)
        spin.setParent(frame)
        spin.hide()
        spin.valueChanged.connect(lambda number: value.setText(str(number)))

        box.addWidget(minus)
        box.addWidget(value)
        box.addWidget(plus)
        return frame

    # ---------------------------------------------------------------- 分组
    @staticmethod
    def _set_head(number, title):
        head = QWidget()
        box = hbox(8, (0, 0, 0, 0), head)
        box.addWidget(mono(number, 8, theme.TEXT_4))
        box.addWidget(lbl(title, 10, theme.TEXT_2, 600))
        box.addStretch()
        return head

    @staticmethod
    def _set_row(title, desc=None, control=None, desc_widget=None):
        """CSS .set-row：左侧 10px 标题 + 8px 说明，右侧控件。"""
        row = QWidget()
        box = hbox(18, (0, 5, 0, 5), row)
        text = vbox(0, (0, 0, 0, 0))
        text.addWidget(lbl(title, 10, theme.TEXT_MAIN, 500))
        detail = desc_widget if desc_widget is not None else lbl(
            desc or "", 8, theme.TEXT_3)
        detail.setContentsMargins(0, 3, 0, 0)
        text.addWidget(detail)
        box.addLayout(text, 1)
        if control is not None:
            hold = QWidget()
            ctl = hbox(6, (0, 0, 0, 0), hold)
            ctl.addWidget(control)
            box.addWidget(hold, 0)
        return row

    def _section(self, number, title, rows, first=False):
        """CSS .set-section：分组标题 + 带细线分隔的若干设置行。"""
        section = QWidget()
        box = vbox(0, (0, 0, 0, 0), section)
        if not first:
            box.addSpacing(7)
            box.addWidget(hline())
            box.addSpacing(7)
        box.addWidget(self._set_head(number, title))
        for row in rows:
            box.addSpacing(1)
            box.addWidget(hline())
            box.addWidget(row)
        return section

    # ---------------------------------------------------------------- 左列
    def _settings_pref_card(self):
        card = Card(16, 0)

        head = hbox(12, (0, 0, 0, 14))
        head.addWidget(lbl("偏好设置", 11, theme.TEXT_MAIN, 600))
        head.addStretch()
        head.addWidget(mono("AUTO SAVE", 8, theme.TEXT_4, 0.8))
        card.add_layout(head)

        card.body.addWidget(self._section("01", "常规", [
            self._set_row("界面动效", "图表与状态切换的过渡动画",
                          self.set_animations),
            self._set_row("优先系统原生接口", "WlanAPI / IP Helper，失败自动回退",
                          self.set_native_api),
        ], first=True))
        card.body.addWidget(self._section("02", "网络", [
            self._set_row("DNS 测试轮数", "轮数越多，择优结果越稳定",
                          self._stepper(self.set_dns_rounds)),
            self._set_row("实时网速包含 VPN", "统计 VPN 隧道接口的流量",
                          self.set_traffic_vpn),
        ]))
        card.body.addWidget(self._section("03", "测速", [
            self._set_row("下载测速时长", "时间越长，结果越稳定",
                          self._stepper(self.set_speed_dl)),
            self._set_row("上传测速时长", "按上行带宽自动调整采样",
                          self._stepper(self.set_speed_ul)),
        ]))
        card.body.addWidget(self._section("05", "高级", [
            self._set_row("历史记录保留", "超出后自动清理最旧记录",
                          self._stepper(self.set_history_limit)),
            self._set_row("管理员权限", "修复网络组件时自动申请提权",
                          self._admin_pill()),
        ]))

        card.body.addStretch(1)
        footer = hbox(12, (0, 14, 0, 0))
        self.settings_footer = mono(self._config_footer(), 8, theme.TEXT_4, 0.8)
        footer.addWidget(self.settings_footer)
        footer.addStretch()
        self.settings_hint = mono("", 8, theme.TEXT_4, 0.4)
        footer.addWidget(self.settings_hint)
        card.body.addLayout(footer)
        return card

    def _admin_pill(self):
        enabled = bool(self._is_admin_now())
        return Pill("已启用" if enabled else "未启用",
                    "ok" if enabled else "dim",
                    "ok" if enabled else None, small=True)

    def _config_footer(self):
        stamp = datetime.now()
        try:
            stamp = datetime.fromtimestamp(os.path.getmtime(self.settings.path))
        except OSError:
            pass
        return (f"配置版本 {stamp.strftime('%Y.%m')}"
                f" · 最后修改 {stamp.strftime('%H:%M')}")

    # ---------------------------------------------------------------- 右列
    def _settings_download_card(self):
        card = Card(16, 0)
        card.body.addWidget(self._section("04", "下载", [
            self._set_row("默认线程数", "建议 8–16，过高可能被限速",
                          self._stepper(self.set_dl_conn)),
            self._path_row("保存位置", self.set_download_dir,
                           os.path.join(os.path.expanduser("~"), "Downloads")),
            self._path_row("报告导出位置", self.set_report_dir,
                           os.path.join(get_data_dir(), "reports")),
        ], first=True))
        return card

    def _path_row(self, title, edit, empty_text):
        label = lbl("", 8, theme.TEXT_3)
        label.setToolTip(edit.text().strip())
        button = self._inline_button("更改")
        button.clicked.connect(lambda: self._pick_settings_dir(edit, label, empty_text))
        row = self._set_row(title, control=button, desc_widget=label)
        edit.setParent(row)
        edit.hide()
        self._set_path_text(label, edit.text().strip(), empty_text)
        return row

    @staticmethod
    def _inline_button(text, on_click=None):
        """CSS .btn.ghost.sm 贴在设置行右侧的小按钮。"""
        button = QPushButton(text)
        button.setFixedHeight(28)
        button.setCursor(Qt.PointingHandCursor)
        button.setStyleSheet(
            "QPushButton { background: transparent; color: #f3f4f6;"
            f" border: 1px solid {theme.LINE_STRONG}; border-radius: 7px;"
            f" font-size: {theme.text_size(9)}px; padding: 0 10px; }}"
            "QPushButton:hover { background-color: #17171a;"
            " border-color: #33ffffff; }")
        if on_click is not None:
            button.clicked.connect(on_click)
        return button

    @staticmethod
    def _set_path_text(label, path, empty_text):
        text = path or empty_text
        if len(text) > 34:
            text = "…" + text[-33:]
        label.setText(text)
        label.setToolTip(path or empty_text)

    def _settings_about_card(self):
        card = Card(16, 0)
        row = hbox(13, (0, 0, 0, 0))
        row.addWidget(self._app_icon(58, 14))

        info = vbox(0, (0, 0, 0, 0))
        info.addWidget(lbl(_APP_NAME, 13, theme.TEXT_MAIN, 600))
        version = mono(f"VERSION {__version__}", 9, theme.TEXT_3)
        version.setContentsMargins(0, 5, 0, 0)
        info.addWidget(version)
        state = hbox(6, (0, 8, 0, 0))
        state.addWidget(dot("ok"))
        state.addWidget(lbl("本机版本", 9, theme.TEXT_2))
        state.addStretch()
        info.addLayout(state)
        row.addLayout(info, 1)

        refresh = IconButton("refresh", 32, 14, theme.TEXT_3)
        refresh.setToolTip("打开项目发布页")
        refresh.clicked.connect(self._check_updates)
        row.addWidget(refresh, 0, Qt.AlignTop)
        card.body.addLayout(row)

        buttons = hbox(8, (0, 14, 0, 0))
        check = ghost_button("打开发布页")
        check.clicked.connect(self._check_updates)
        changelog = ghost_button("更新日志")
        changelog.clicked.connect(self._show_changelog)
        buttons.addWidget(check, 1)
        buttons.addWidget(changelog, 1)
        card.body.addLayout(buttons)
        return card

    @staticmethod
    def _app_icon(size, radius):
        pixmap = QPixmap(os.path.join(
            _assets_base(), "assets", "icons", "app.png"))
        if pixmap.isNull():
            frame = QFrame()
            frame.setFixedSize(size, size)
            frame.setStyleSheet(
                f"QFrame {{ background: #000; border: 1px solid"
                f" {theme.LINE_STRONG}; border-radius: {radius}px; }}")
            box = vbox(0, (0, 0, 0, 0), frame)
            box.setAlignment(Qt.AlignCenter)
            box.addWidget(ic("wifi", 24, theme.TEXT_2), 0, Qt.AlignCenter)
            return frame

        pixmap = pixmap.scaled(size, size, Qt.KeepAspectRatioByExpanding,
                               Qt.SmoothTransformation)
        left = max(0, (pixmap.width() - size) // 2)
        top = max(0, (pixmap.height() - size) // 2)
        pixmap = pixmap.copy(left, top, size, size)

        rounded = QPixmap(size, size)
        rounded.fill(Qt.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
        painter.setClipPath(clip)
        painter.drawPixmap(0, 0, pixmap)
        painter.setClipping(False)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(theme.LINE_STRONG), 1))
        painter.drawRoundedRect(
            QRectF(0.5, 0.5, size - 1, size - 1), radius, radius)
        painter.end()

        label = QLabel()
        label.setFixedSize(size, size)
        label.setPixmap(rounded)
        return label

    def _settings_privacy_card(self):
        card = Card(16, 0)
        card.body.addStretch(1)

        head = hbox(12, (0, 0, 0, 0))
        head.addWidget(lbl("数据与隐私", 11, theme.TEXT_MAIN, 600))
        head.addStretch()
        head.addWidget(Pill("仅本地", "ok", "ok", small=True))
        card.body.addLayout(head)

        card.body.addWidget(hline())
        card.body.addWidget(self._privacy_row("网络记录", self._data_size_text()))
        card.body.addWidget(hline())
        card.body.addWidget(self._privacy_row("上传云端", "从不"))
        card.body.addWidget(hline())
        card.body.addWidget(self._privacy_row(
            "日志文件", widget=self._inline_button(
                "打开目录", self._open_log_dir)))

        note = lbl("SSID、MAC 地址与测速记录均只写入本机数据目录，不会上传。",
                   9, theme.TEXT_3, 400, False, 0, wrap=True)
        note.setContentsMargins(0, 10, 0, 0)
        card.body.addWidget(note)
        card.body.addStretch(1)
        return card

    @staticmethod
    def _privacy_row(key, value=None, widget=None):
        row = QWidget()
        box = hbox(10, (0, 7, 0, 7), row)
        box.addWidget(lbl(key, 9, theme.TEXT_3))
        box.addStretch()
        if widget is not None:
            box.addWidget(widget)
        else:
            box.addWidget(mono(value or "--", 9, theme.TEXT_MAIN))
        return row

    @staticmethod
    def _data_size_text():
        try:
            total = 0
            base = get_data_dir()
            for root, _dirs, files in os.walk(base):
                for name in files:
                    try:
                        total += os.path.getsize(os.path.join(root, name))
                    except OSError:
                        pass
            return _human_size(total)
        except Exception:
            return "--"

    # ---------------------------------------------------------------- 行为
    def _pick_settings_dir(self, edit, label=None, empty_text="系统默认目录"):
        start = edit.text().strip() or os.path.expanduser("~")
        path = QFileDialog.getExistingDirectory(self, "选择文件夹", start)
        if not path:
            return
        edit.setText(path)
        if label is not None:
            self._set_path_text(label, path, empty_text)
        self._set_status(f"已选择目录：{path}")

    def _check_updates(self):
        """打开项目发布页；不在本地伪造“已是最新版本”。"""
        try:
            opened = QDesktopServices.openUrl(QUrl(_RELEASES_URL))
            if opened:
                self._set_status("已打开项目发布页，可在页面查看最新版本")
            else:
                self._set_status(f"请手动访问：{_RELEASES_URL}")
        except Exception:
            self._set_status(f"请手动访问：{_RELEASES_URL}")

    def _show_changelog(self):
        try:
            opened = QDesktopServices.openUrl(QUrl(_RELEASES_URL))
            if opened:
                self._set_status("已打开更新日志（项目发布页）")
            else:
                self._set_status(f"请手动访问：{_RELEASES_URL}")
        except Exception:
            self._set_status(f"请手动访问：{_RELEASES_URL}")

    def _open_log_dir(self):
        try:
            path = get_log_dir()
            os.makedirs(path, exist_ok=True)
            os.startfile(path)  # type: ignore[attr-defined]
            self._set_status("已打开日志目录")
        except Exception as e:
            self._set_status(f"无法打开日志目录：{e}")

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
            self.settings_hint.setText("保存失败，请查看权限")
            self.settings_hint.setStyleSheet(
                f"color: {theme.ERROR}; background: transparent;")
            self._set_status(f"设置保存失败：{self.settings.last_error}")
            return

        apply_runtime(self.settings)
        self._apply_history_limit()
        self.traffic.set_include_vpn(values["traffic_include_vpn"])
        self._apply_animation_setting()
        self.settings_hint.setText("已保存，立即生效")
        self.settings_hint.setStyleSheet(
            f"color: {theme.SUCCESS}; background: transparent;")
        self.settings_footer.setText(self._config_footer())
        self._set_status("设置已保存")

    def _reset_settings(self):
        if self.settings.reset():
            self._load_settings_into_form()
            apply_runtime(self.settings)
            self._apply_history_limit()
            self.traffic.set_include_vpn(
                bool(self.settings.get("traffic_include_vpn", False)))
            self._apply_animation_setting()
            self.settings_hint.setText("已恢复默认设置")
            self.settings_hint.setStyleSheet(
                f"color: {theme.SUCCESS}; background: transparent;")
            self.settings_footer.setText(self._config_footer())
            self._set_status("已恢复默认设置")
        else:
            self.settings_hint.setText("恢复默认失败")
            self.settings_hint.setStyleSheet(
                f"color: {theme.ERROR}; background: transparent;")
            self._set_status(f"恢复默认失败：{self.settings.last_error}")

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
