"""Wi-Fi 检测页：信号、信道频谱、邻近网络与建议。

所有数字都来自 WlanAPI/netsh 的实时扫描；没有扫描结果时显示空态，
不再用设计稿里的 MyHome_5G / Wi-Fi 6 / 干扰数量等示例数据。
"""

import os

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QWidget

import core.theme as theme
from core.paths import get_data_dir
from core.version import __version__
from core.wifi_check import network_band
from ui.kit import (
    Avatar, Card, MiniGrid, Pill, Spectrum, ghost_button, hbox, hline, lbl,
    mono, page_head, primary_button, vbox,
)
from ui.responsive import ResponsiveColumns
from ui.workers import WifiCheckWorker, WifiDiagWorker, WifiScanWorker

_RADIO_LABELS = {
    "802.11ax": "Wi-Fi 6",
    "802.11be": "Wi-Fi 7",
    "802.11ac": "Wi-Fi 5",
    "802.11n": "Wi-Fi 4",
    "802.11a": "Wi-Fi 1",
    "802.11b": "Wi-Fi 1",
    "802.11g": "Wi-Fi 3",
}


class _SignalArcs(QWidget):
    """128px 三弧信号图标：白弧逐层加深，底部薄荷绿圆点。"""

    def __init__(self, size=128, parent=None):
        super().__init__(parent)
        self._signal = 0
        self._color = theme.MINT
        self.setFixedSize(size, size)

    def set_signal(self, signal, color=theme.MINT):
        self._signal = max(0, min(100, int(signal or 0)))
        self._color = color
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        scale = min(self.width(), self.height()) / 120.0
        painter.scale(scale, scale)
        painter.setBrush(Qt.NoBrush)
        for radius, center_y, opacity in ((58.0, 90.0, 0.28),
                                          (38.0, 91.7, 0.55),
                                          (19.0, 94.9, 0.90)):
            color = QColor(theme.PAPER)
            color.setAlphaF(opacity)
            pen = QPen(color, 6)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            rect = QRectF(60 - radius, center_y - radius, radius * 2, radius * 2)
            painter.drawArc(rect, int(137 * 16), int(-94 * 16))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self._color))
        painter.drawEllipse(QRectF(55.5, 93.5, 9, 9))
        painter.end()


class _SignalBars(QWidget):
    """4 根信号格：20×12，点亮与否按信号等级决定。"""

    HEIGHTS = (4, 7, 10, 12)

    def __init__(self, level=4, mint=False, parent=None):
        super().__init__(parent)
        self._level = max(0, min(4, int(level)))
        self._mint = bool(mint)
        self.setFixedSize(20, 12)

    def paintEvent(self, event):
        painter = QPainter(self)
        for index, height in enumerate(self.HEIGHTS):
            if index < self._level:
                color = QColor(theme.MINT if self._mint else theme.PAPER)
            else:
                color = QColor(255, 255, 255, 33)
            painter.fillRect(QRectF(index * 5, 12 - height, 3, height), color)
        painter.end()


def _badge(text, color=theme.TEXT_3, border=theme.LINE, bg=None):
    badge = QFrame()
    badge.setStyleSheet(
        f"QFrame {{ border: 1px solid {border}; border-radius: 4px;"
        f" background-color: {bg or 'transparent'}; }}")
    layout = hbox(0, (5, 3, 5, 3), badge)
    layout.addWidget(lbl(text, 9, color, 400, True, 0.5))
    return badge


def _band_text(net):
    band = network_band(net)
    return {"2.4G": "2.4 GHz", "5G": "5 GHz", "6G": "6 GHz"}.get(band, "—")


def _signal_level(signal):
    if signal >= 80:
        return 4
    if signal >= 60:
        return 3
    if signal >= 40:
        return 2
    if signal >= 20:
        return 1
    return 0


def _short_auth(auth):
    auth = str(auth or "")
    if "WPA3" in auth:
        return "WPA3"
    if "WPA2" in auth:
        return "WPA2"
    if "WPA" in auth:
        return "WPA"
    if not auth or "开放" in auth or "open" in auth.lower():
        return "开放"
    return auth[:10]


class WifiPageMixin:
    """Wi-Fi 检测页：真实信号、扫描结果与基于扫描的建议。"""

    def _create_wifi_page(self):
        page = QWidget()
        self.wifi_page = page
        layout = vbox(14, (0, 0, 0, 0), page)

        self.wifi_scan_btn = ghost_button("扫描附近网络")
        self.wifi_scan_btn.clicked.connect(self._start_wifi_scan)
        self.wifi_btn = primary_button("检测 Wi-Fi")
        self.wifi_btn.clicked.connect(self._start_wifi_check)
        self.wifi_head = page_head(
            "WI-FI / SPECTRUM ANALYSIS",
            "信号、信道与干扰，一次看清。",
            "尚未扫描。点击「扫描附近网络」查看真实信道占用。",
            [self.wifi_scan_btn, self.wifi_btn])
        layout.addWidget(self.wifi_head)

        body = ResponsiveColumns(left_stretch=135, right_stretch=100)
        layout.addWidget(body, 1)

        # ---------------- 左列：信号英雄卡 + 邻近网络 ----------------
        left = body.left

        hero = Card(16, 0)
        hero_row = hbox(20, (0, 0, 0, 0))
        self.wifi_signal_arc = _SignalArcs(128)
        hero_row.addWidget(self.wifi_signal_arc, 0, Qt.AlignVCenter)

        detail = vbox(0, (0, 0, 0, 0))
        detail.addStretch()
        top = hbox(10, (0, 0, 0, 0))
        top.addWidget(lbl("SIGNAL STRENGTH", 8, theme.TEXT_3, 400, True, 1.3))
        top.addStretch()
        self.wifi_signal_level = Pill("未检测", "dim", None)
        top.addWidget(self.wifi_signal_level)
        detail.addLayout(top)

        score = hbox(3, (0, 8, 0, 0))
        self.wifi_signal_value = lbl("--", 44, theme.TEXT_MAIN, 600, False, -2.4)
        score.addWidget(self.wifi_signal_value)
        unit = lbl("%", 14, theme.TEXT_3)
        unit.setContentsMargins(0, 0, 0, 7)
        score.addWidget(unit, 0, Qt.AlignBottom)
        score.addStretch()
        detail.addLayout(score)

        link = hbox(0, (0, 6, 0, 0))
        self.wifi_ssid_value = lbl("尚未检测", 10, theme.TEXT_3)
        link.addWidget(self.wifi_ssid_value)
        link.addWidget(lbl(" · ", 10, theme.TEXT_3))
        self.wifi_link_meta = lbl("点击「检测 Wi-Fi」", 10, theme.TEXT_3)
        link.addWidget(self.wifi_link_meta)
        link.addStretch()
        detail.addLayout(link)

        meta = hbox(12, (0, 12, 0, 0))
        self.wifi_band_label = mono("频段 —", 9, theme.TEXT_3, 0.2)
        self.wifi_channel_label = mono("信道 —", 9, theme.TEXT_3, 0.2)
        self.wifi_radio_label = mono("—", 9, theme.TEXT_3, 0.2)
        self.wifi_auth_label = mono("加密 —", 9, theme.TEXT_3, 0.2)
        for widget in (self.wifi_band_label, self.wifi_channel_label,
                       self.wifi_radio_label, self.wifi_auth_label):
            meta.addWidget(widget)
        meta.addStretch()
        detail.addLayout(meta)
        detail.addStretch()

        hero_row.addLayout(detail, 1)
        hero.body.addLayout(hero_row)
        hero.body.addSpacing(14)
        self.wifi_grid_host = QWidget()
        self._wifi_grid_layout = vbox(0, (0, 0, 0, 0), self.wifi_grid_host)
        self._refresh_wifi_grid(None)
        hero.body.addWidget(self.wifi_grid_host)
        left.addWidget(hero)

        # 弱信号 / 信道冲突预警条（点击跳转一键修复）
        self.wifi_warn_bar = QFrame()
        self.wifi_warn_bar.setCursor(Qt.PointingHandCursor)
        self.wifi_warn_bar.mousePressEvent = self._on_wifi_warn_click
        self.wifi_warn_bar.setStyleSheet(
            f"QFrame {{ background-color: {theme.WARNING_LIGHT};"
            f" border: 1px solid {theme.AMBER_LINE}; border-radius: 8px; }}")
        warn_layout = hbox(8, (12, 8, 12, 8), self.wifi_warn_bar)
        self.wifi_warn_label = lbl("", 10, theme.WARNING, 500)
        warn_layout.addWidget(self.wifi_warn_label)
        warn_layout.addStretch()
        warn_layout.addWidget(lbl("去一键修复  →", 10, theme.MINT, 500))
        self.wifi_warn_bar.hide()
        left.addWidget(self.wifi_warn_bar)

        nearby = Card(16, 0)
        nearby_head = hbox(12, (0, 0, 0, 14))
        nearby_head.addWidget(lbl("邻近网络", 11, theme.TEXT_MAIN, 600))
        nearby_head.addStretch()
        self.wifi_nearby_note = lbl("尚未扫描", 9, theme.TEXT_3, 400, True, 0.8)
        nearby_head.addWidget(self.wifi_nearby_note)
        nearby.body.addLayout(nearby_head)

        self.wifi_rows_box = QWidget()
        self.wifi_rows_layout = vbox(0, (0, 0, 0, 0), self.wifi_rows_box)
        nearby.body.addWidget(self.wifi_rows_box, 1)

        self.wifi_nearby_label = lbl("", 10, theme.TEXT_3, wrap=True)
        self.wifi_nearby_label.hide()
        nearby.body.addWidget(self.wifi_nearby_label)

        self.wifi_advice_label = lbl("", 10, theme.TEXT_3, wrap=True)
        self.wifi_advice_label.hide()
        nearby.body.addWidget(self.wifi_advice_label)

        self.wifi_diag_btn = ghost_button("复制诊断信息")
        self.wifi_diag_btn.clicked.connect(lambda: self._start_wifi_diag(False))
        self.wifi_export_btn = ghost_button("导出诊断报告")
        self.wifi_export_btn.clicked.connect(lambda: self._start_wifi_diag(True))
        self.wifi_diag_row = QWidget()
        diag_layout = hbox(10, (0, 6, 0, 0), self.wifi_diag_row)
        diag_layout.addWidget(self.wifi_diag_btn, 1)
        diag_layout.addWidget(self.wifi_export_btn, 1)
        self.wifi_diag_row.hide()
        nearby.body.addWidget(self.wifi_diag_row)
        left.addWidget(nearby, 1)

        # ---------------- 右列：频谱 + 干扰分析 + 建议 ----------------
        right = body.right

        spec = Card(16, 0)
        spec_head = hbox(12, (0, 0, 0, 0))
        spec_head.addWidget(lbl("5 GHz 信道占用", 11, theme.TEXT_MAIN, 600))
        spec_head.addStretch()
        spec_head.addWidget(lbl("CH 36–165", 9, theme.TEXT_3, 400, True, 0.8))
        spec.body.addLayout(spec_head)
        spec.body.addSpacing(14)
        self.wifi_spec_hint = lbl("尚未扫描，点击「扫描附近网络」查看真实占用。",
                                  10, theme.TEXT_3, align=Qt.AlignCenter)
        spec.body.addWidget(self.wifi_spec_hint)
        self.wifi_spec_5g = Spectrum([], 84)
        spec.body.addWidget(self.wifi_spec_5g)
        chan = hbox(0, (0, 7, 0, 0))
        for index, (text, color) in enumerate((
                ("36", theme.TEXT_3), ("64", theme.TEXT_3),
                ("149", theme.MINT), ("165", theme.TEXT_3))):
            chan.addWidget(mono(text, 9, color, 0.2))
            if index < 3:
                chan.addStretch()
        spec.body.addLayout(chan)

        spec.body.addSpacing(13)
        spec.body.addWidget(hline())
        spec.body.addSpacing(13)

        sub_head = hbox(12, (0, 0, 0, 6))
        sub_head.addWidget(lbl("2.4 GHz 信道占用", 10, theme.TEXT_3, 500))
        sub_head.addStretch()
        sub_head.addWidget(lbl("CH 1–13", 9, theme.TEXT_3, 400, True, 0.8))
        spec.body.addLayout(sub_head)
        spec.body.addSpacing(4)
        self.wifi_spec_24 = Spectrum([], 44)
        spec.body.addWidget(self.wifi_spec_24)
        right.addWidget(spec)

        interference = Card(16, 0)
        inter_head = hbox(10, (0, 0, 0, 0))
        inter_head.addWidget(lbl("干扰分析", 10, theme.TEXT_3, 400, True, 1.0))
        inter_head.addStretch()
        inter_head.addWidget(_badge("来自扫描"))
        interference.body.addLayout(inter_head)
        interference.body.addSpacing(10)
        self._wifi_inter_labels = {}
        for key in ("2.4 GHz 邻居", "5 GHz 邻居", "同信道强干扰"):
            interference.body.addWidget(hline())
            row = hbox(10, (0, 8, 0, 8))
            row.addWidget(lbl(key, 10, theme.TEXT_3))
            row.addStretch()
            value = mono("—", 10, theme.TEXT_MAIN)
            row.addWidget(value)
            self._wifi_inter_labels[key] = value
            interference.body.addLayout(row)
        right.addWidget(interference)

        self.wifi_recommend_card = Card(16, 0)
        self.wifi_recommend_card.body.addStretch()
        rec_head = hbox(10, (0, 0, 0, 0))
        rec_head.addWidget(lbl("RECOMMENDATION", 8, theme.MINT, 400, True, 1.3))
        rec_head.addStretch()
        self.wifi_recommend_pill = Pill("待扫描", "dim", None)
        rec_head.addWidget(self.wifi_recommend_pill)
        self.wifi_recommend_card.body.addLayout(rec_head)

        self.wifi_recommend_title = lbl("扫描后给出建议", 15,
                                        theme.TEXT_MAIN, 600, False, -0.2,
                                        wrap=True)
        self.wifi_recommend_title.setContentsMargins(0, 9, 0, 0)
        self.wifi_recommend_card.body.addWidget(self.wifi_recommend_title)

        self.wifi_recommend_desc = lbl(
            "系统会根据邻近网络的信道占用情况给出建议。", 10,
            theme.TEXT_3, 400, False, 0, wrap=True)
        self.wifi_recommend_desc.setContentsMargins(0, 6, 0, 0)
        self.wifi_recommend_card.body.addWidget(self.wifi_recommend_desc)

        self.wifi_channel_advice_label = lbl("", 10, theme.TEXT_3, wrap=True)
        self.wifi_channel_advice_label.hide()
        self.wifi_recommend_card.body.addWidget(self.wifi_channel_advice_label)

        actions = hbox(8, (0, 13, 0, 0))
        switch_btn = primary_button("查看修复建议")
        switch_btn.setEnabled(False)
        switch_btn.clicked.connect(lambda: self._switch_page("repair"))
        self.wifi_recommend_action = switch_btn
        later_btn = ghost_button("稍后")
        later_btn.clicked.connect(lambda: self._set_status("已保留当前信道"))
        actions.addWidget(switch_btn, 1)
        actions.addWidget(later_btn)
        self.wifi_recommend_card.body.addLayout(actions)
        self.wifi_recommend_card.body.addStretch()
        right.addWidget(self.wifi_recommend_card, 1)

        self._render_wifi_rows(())
        self._set_wifi_empty_state()

    # ---------------------------------------------------------------- 视图
    def _refresh_wifi_grid(self, info):
        while self._wifi_grid_layout.count():
            item = self._wifi_grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        if not info:
            items = (("信号", "—", "%", theme.TEXT_3),
                     ("协商下行", "—", "Mbps", theme.TEXT_3),
                     ("协商上行", "—", "Mbps", theme.TEXT_3))
        else:
            signal = info.get("signal_strength")
            rx = info.get("rx_rate")
            tx = info.get("tx_rate")
            items = (
                ("信号", f"{signal}" if signal is not None else "—", "%",
                 theme.TEXT_MAIN),
                ("协商下行", f"{rx:.0f}" if isinstance(rx, (int, float)) else "—",
                 "Mbps", theme.TEXT_MAIN),
                ("协商上行", f"{tx:.0f}" if isinstance(tx, (int, float)) else "—",
                 "Mbps", theme.TEXT_MAIN),
            )
        self._wifi_grid_layout.addWidget(MiniGrid(items, 3, (12, 11)))

    def _wifi_row(self, name, meta, level, value, icon, current, first=False):
        row = QWidget()
        layout = hbox(10, (0, 2 if first else 9, 0, 9), row)
        layout.addWidget(Avatar(icon, 28))
        text = vbox(4, (0, 0, 0, 0))
        name_row = hbox(6, (0, 0, 0, 0))
        name_row.addWidget(lbl(name, 11, theme.TEXT_MAIN, 500))
        if current:
            name_row.addWidget(_badge(
                "当前", theme.MINT, theme.MINT_LINE, "#0f8bffd1"))
        name_row.addStretch()
        text.addLayout(name_row)
        text.addWidget(mono(meta, 9, theme.TEXT_3, 0.2))
        layout.addLayout(text, 1)
        layout.addWidget(_SignalBars(level, mint=current))
        value_label = mono(value, 10, theme.TEXT_MAIN)
        value_label.setFixedWidth(42)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(value_label)
        return row

    def _render_wifi_rows(self, rows):
        while self.wifi_rows_layout.count():
            item = self.wifi_rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not rows:
            hint = lbl("尚未扫描。点击「扫描附近网络」查看邻近 Wi-Fi。",
                       10, theme.TEXT_3, wrap=True, align=Qt.AlignCenter)
            hint.setContentsMargins(0, 24, 0, 24)
            self.wifi_rows_layout.addWidget(hint)
            self.wifi_rows_layout.addStretch()
            return
        for index, (name, meta, level, value, icon, current) in enumerate(rows):
            if index:
                self.wifi_rows_layout.addWidget(hline())
            self.wifi_rows_layout.addWidget(
                self._wifi_row(name, meta, level, value, icon, current,
                               first=index == 0))
        self.wifi_rows_layout.addStretch()

    def _set_wifi_empty_state(self):
        self.wifi_signal_value.setText("--")
        self.wifi_signal_level.setText("未检测")
        self.wifi_ssid_value.setText("尚未检测")
        self.wifi_link_meta.setText("点击「检测 Wi-Fi」")
        self.wifi_band_label.setText("频段 —")
        self.wifi_channel_label.setText("信道 —")
        self.wifi_radio_label.setText("—")
        self.wifi_auth_label.setText("加密 —")
        self.wifi_signal_arc.set_signal(0, theme.TEXT_3)
        self._refresh_wifi_grid(None)
        for label in self._wifi_inter_labels.values():
            label.setText("—")
        self.wifi_recommend_pill.setText("待扫描")
        self.wifi_recommend_title.setText("扫描后给出建议")
        self.wifi_recommend_desc.setText(
            "系统会根据邻近网络的信道占用情况给出建议。")
        self.wifi_channel_advice_label.hide()
        self.wifi_warn_bar.hide()
        self.wifi_diag_row.hide()
        if getattr(self, "wifi_spec_hint", None) is not None:
            self.wifi_spec_hint.show()
        if getattr(self, "wifi_recommend_action", None) is not None:
            self.wifi_recommend_action.setEnabled(False)

    # ---------------------------------------------------------------- 扫描
    def _start_wifi_scan(self):
        """扫描附近 Wi-Fi（后台线程，避免 netsh 阻塞界面）"""
        self.wifi_scan_btn.setEnabled(False)
        self.wifi_scan_btn.setText("扫描中…")
        self._set_status("正在扫描附近 Wi-Fi...")
        self._wifi_scan_worker = WifiScanWorker()
        self._wifi_scan_worker.done.connect(self._on_wifi_scan_finished)
        self._start_worker(self._wifi_scan_worker)

    def _on_wifi_scan_finished(self, result):
        self.wifi_scan_btn.setEnabled(True)
        self.wifi_scan_btn.setText("扫描附近网络")
        if not isinstance(result, dict) or not result.get("success"):
            error = result.get("error") if isinstance(result, dict) else "扫描失败"
            self._render_wifi_rows(())
            self.wifi_nearby_note.setText("扫描失败")
            self.wifi_nearby_label.setText(error or "扫描失败")
            self.wifi_nearby_label.setStyleSheet(
                f"color: {theme.ERROR}; background: transparent;")
            self.wifi_nearby_label.show()
            self.wifi_channel_advice_label.setText("")
            self._set_status("附近网络扫描未完成")
            return

        networks = result.get("networks") or []
        rows = []
        for net in networks[:8]:
            signal = int(net.get("signal") or 0)
            channel = net.get("channel")
            meta = " · ".join(part for part in (
                f"CH {channel}" if channel else "",
                _band_text(net),
                _short_auth(net.get("auth")),
            ) if part)
            rows.append((
                net.get("ssid") or "隐藏网络",
                meta,
                _signal_level(signal),
                f"{signal}%",
                "router" if net.get("connected") else "wifi",
                bool(net.get("connected")),
            ))
        self._render_wifi_rows(rows)
        self.wifi_nearby_note.setText(f"{len(networks)} FOUND")
        self.wifi_nearby_label.setText(
            "\n".join(
                f"{'●' if n.get('connected') else '○'} {n.get('ssid', '')}"
                f"    {n.get('signal', 0)}%"
                for n in networks[:8]) or "附近未发现其他 Wi-Fi 网络")
        self.wifi_nearby_label.setStyleSheet(
            f"color: {theme.TEXT_3}; background: transparent;")
        self.wifi_nearby_label.hide()

        advice = result.get("advice") or []
        self.wifi_channel_advice_label.setText("\n".join(advice))
        if advice:
            self.wifi_channel_advice_label.hide()
        self._refresh_wifi_spectrum(networks)
        self._refresh_wifi_interference(networks)
        self._refresh_wifi_recommend(advice)
        self.wifi_spec_hint.hide()
        self.wifi_recommend_action.setEnabled(True)
        self.wifi_head.set_desc(
            f"扫描到 {len(networks)} 个邻近网络；以下信道数据来自本次扫描。")
        self._set_status(f"扫描完成：发现 {len(networks)} 个网络")
        self._notify(f"扫描完成：{len(networks)} 个网络", "ok")

    def _refresh_wifi_spectrum(self, networks):
        current_channel = None
        for net in networks:
            if net.get("connected") and net.get("channel"):
                current_channel = int(net["channel"])
                break

        def bucket(band, channels):
            values = []
            for channel in channels:
                weight = 0
                for net in networks:
                    if network_band(net) != band:
                        continue
                    if net.get("channel") != channel:
                        continue
                    weight = max(weight, int(net.get("signal") or 0))
                style = "cur" if channel == current_channel else (
                    "mid" if weight >= 60 else "")
                values.append((weight / 100.0, style))
            return values

        five_channels = [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112,
                         116, 120, 124, 128, 132, 136, 140, 144, 149, 153,
                         157, 161, 165]
        self.wifi_spec_5g.set_values(
            bucket("5G", five_channels) if any(
                network_band(n) in ("5G", "6G") for n in networks)
            else [])
        self.wifi_spec_24.set_values(
            bucket("2.4G", list(range(1, 14))) if any(
                network_band(n) == "2.4G" for n in networks) else [])

    def _refresh_wifi_interference(self, networks):
        g24 = [n for n in networks if network_band(n) == "2.4G"]
        g5 = [n for n in networks if network_band(n) in ("5G", "6G")]
        current = next((n for n in networks if n.get("connected")), None)
        current_channel = current.get("channel") if current else None
        if current_channel:
            strong = [n for n in networks
                      if not n.get("connected")
                      and n.get("channel") == current_channel
                      and int(n.get("signal") or 0) >= 50]
        else:
            strong = []
        self._wifi_inter_labels["2.4 GHz 邻居"].setText(f"{len(g24)} 个")
        self._wifi_inter_labels["5 GHz 邻居"].setText(f"{len(g5)} 个")
        self._wifi_inter_labels["同信道强干扰"].setText(f"{len(strong)} 个")

    def _refresh_wifi_recommend(self, advice):
        if advice:
            title = advice[0]
            rest = advice[1:]
            self.wifi_recommend_pill.setText("来自实测")
            self.wifi_recommend_title.setText(title)
            self.wifi_recommend_desc.setText(
                "\n".join(rest) if rest else "扫描结果未发现明显信道拥堵。")
        else:
            self.wifi_recommend_pill.setText("暂无建议")
            self.wifi_recommend_title.setText("当前信道暂无明显问题")
            self.wifi_recommend_desc.setText(
                "附近网络较少或干扰不明显，可保持当前设置。")

    # ---------------------------------------------------------------- 检测
    def _start_wifi_check(self):
        self.logger.info("开始Wi-Fi检测")
        self.wifi_btn.setEnabled(False)
        self.wifi_btn.setText("检测中…")
        self._set_status("正在检测Wi-Fi...")
        self.worker = WifiCheckWorker()
        self.worker.done.connect(self._on_wifi_finished)
        self._start_worker(self.worker)

    def _on_wifi_finished(self, info):
        try:
            self._on_wifi_finished_impl(info)
        except Exception:
            self.logger.exception("Wi-Fi检测结果处理出现异常")
            self.wifi_btn.setEnabled(True)
            self.wifi_btn.setText("检测 Wi-Fi")
            self._set_wifi_empty_state()
            self.wifi_advice_label.setText(
                "检测遇到问题，请点击重新检测；若持续异常，请检查网络适配器是否正常")
            self._set_status("Wi-Fi检测完成（出现异常）")

    def _on_wifi_finished_impl(self, info):
        self.wifi_btn.setEnabled(True)
        self.wifi_btn.setText("检测 Wi-Fi")

        if info is None or not isinstance(info, dict):
            info = {"success": False, "connected": False,
                    "error": "未获取到Wi-Fi信息，请确认已安装无线网卡"}

        if not info.get("success") or not info.get("connected"):
            self._set_wifi_empty_state()
            self.wifi_signal_value.setText("--")
            self.wifi_signal_level.setText("未连接")
            self.wifi_signal_arc.set_signal(0, theme.ERROR)
            self.wifi_ssid_value.setText("未连接 Wi-Fi")
            self.wifi_link_meta.setText("--")
            self.wifi_channel_label.setText("信道 —")
            error_msg = info.get("error") or "未连接到Wi-Fi网络：请连接Wi-Fi后重新检测"
            self.wifi_advice_label.setText(error_msg)
            self.wifi_advice_label.show()
            self.wifi_diag_row.show()
            self.wifi_head.set_title("当前没有连接 Wi-Fi")
            self.wifi_head.set_desc(error_msg)
            self._set_status("Wi-Fi检测完成（未连接）")
            return

        fallback = info.get("_source") == "ipconfig" or "signal_strength" not in info
        if fallback:
            self.wifi_signal_value.setText("--")
            self.wifi_signal_level.setText("已连接")
            self.wifi_signal_arc.set_signal(0, theme.SUCCESS)
        else:
            signal = info.get("signal_strength", 0)
            self.wifi_signal_value.setText(str(signal))
            level_text, level_key, _ = self.wifi_checker.get_signal_level(signal)
            level_color = theme.LEVEL_COLORS.get(level_key, theme.TEXT_MAIN)
            self.wifi_signal_level.setText(level_text)
            self.wifi_signal_arc.set_signal(signal, level_color)

        ssid = info.get("ssid") or (
            "已有网络连接（名称暂未获取）" if fallback else "未知")
        self.wifi_ssid_value.setText(ssid)

        channel = info.get("channel")
        band = _band_text(info) if info.get("channel") else "—"
        radio = str(info.get("radio_type") or "")
        self.wifi_band_label.setText(f"频段 {band}" if band != "—" else "频段 —")
        self.wifi_channel_label.setText(
            f"信道 {channel}" if channel else "信道 —")
        self.wifi_radio_label.setText(_RADIO_LABELS.get(radio, radio or "—"))
        auth = str(info.get("auth") or "")
        self.wifi_auth_label.setText(
            f"加密 {_short_auth(auth)}" if auth else "加密 —")

        rx = info.get("rx_rate")
        tx = info.get("tx_rate")
        parts = []
        if isinstance(rx, (int, float)):
            parts.append(f"↓{rx:.0f} Mbps")
        if isinstance(tx, (int, float)):
            parts.append(f"↑{tx:.0f} Mbps")
        self.wifi_link_meta.setText(" · ".join(parts) or "协商速率未知")
        self._refresh_wifi_grid(info)

        advice_list = self.wifi_checker.get_wifi_advice(info) or []
        if fallback:
            advice_list.insert(
                0, "已确认电脑连接了Wi-Fi网络。当前系统未返回信号强度等详情，"
                   "可能与无线网卡驱动有关，可尝试重装/更新Wi-Fi驱动后重新检测。")
        self.wifi_advice_label.setText("\n".join(advice_list))
        self.wifi_advice_label.show()
        self._update_wifi_warning(info, fallback, advice_list)
        self.wifi_diag_row.hide()
        self.wifi_diag_btn.setText("复制诊断信息")
        self.wifi_head.set_title(f"已连接 {ssid}")
        self.wifi_head.set_desc(
            "信号与协商速率来自 Windows WlanAPI；信道建议请使用「扫描附近网络」。")
        self._set_status("Wi-Fi检测完成")
        try:
            self._notify("Wi-Fi 检测完成", "ok")
        except Exception:
            pass
        try:
            self.state.publish("wifi", info)
        except Exception:
            self.cache.save_result("wifi", info)

    def _on_wifi_warn_click(self, event):
        self._switch_page("repair")

    def _update_wifi_warning(self, info, fallback, advice_list):
        msg = ""
        if not fallback:
            signal = info.get("signal_strength", 100)
            if signal < 50:
                msg = "信号偏弱，可能影响网速，建议靠近路由器"
        if not msg:
            for advice in advice_list:
                if any(k in advice for k in ("信道", "拥堵", "干扰", "拥挤")):
                    msg = "检测到 Wi-Fi 信道可能拥挤或受干扰"
                    break
        if msg:
            self.wifi_warn_label.setText("!  " + msg)
            self.wifi_warn_bar.show()
        else:
            self.wifi_warn_bar.hide()

    # ---------------------------------------------------------------- 诊断导出
    def _start_wifi_diag(self, export=False):
        self._wifi_diag_export = bool(export)
        self.wifi_diag_btn.setEnabled(False)
        self.wifi_export_btn.setEnabled(False)
        self.wifi_diag_btn.setText("正在收集…")
        self._set_status("正在收集网络诊断信息...")
        worker = WifiDiagWorker()
        worker.done.connect(self._on_wifi_diag_done)
        self._wifi_diag_worker = worker
        self._start_worker(worker)

    def _on_wifi_diag_done(self, diag):
        export = getattr(self, "_wifi_diag_export", False)
        self.wifi_diag_btn.setEnabled(True)
        self.wifi_export_btn.setEnabled(True)
        self.wifi_diag_btn.setText("复制诊断信息")
        if not diag:
            self._set_status("收集诊断信息失败，请重试")
            return

        self._last_wifi_diag = diag
        if export:
            self._export_wifi_diag(diag)
            return

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
            self._notify("诊断信息已复制", "ok")
        else:
            self.wifi_diag_btn.setText("复制失败")
            self._set_status("复制诊断信息失败，请重试")
        QTimer.singleShot(2500, lambda: self.wifi_diag_btn.setText("复制诊断信息"))

    def _export_wifi_diag(self, diag):
        from core.report import ReportDoc, ReportSection

        doc = ReportDoc(
            kind="wifi",
            title="Wi-Fi 诊断报告",
            summary="Wi-Fi 状态与网络环境诊断",
            sections=[ReportSection("诊断信息", diag.splitlines())],
            meta={"版本": f"v{__version__}"},
        )
        saved = self._export_report_dialog(doc)
        if saved:
            self.wifi_diag_btn.setText("已导出报告")
            self._notify("Wi-Fi 诊断报告已导出", "ok")
            QTimer.singleShot(2500, lambda: self.wifi_diag_btn.setText("复制诊断信息"))
