"""总览页：健康环、实时吞吐与当前网络 / 最近事件。

页面只展示真实数据：没有诊断记录时分数为“—”，没有采样时图表为空，
当前网络信息来自 AppState 的网络快照（见 core/net_snapshot.py）。
"""

import re
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

import core.theme as theme
from ui.kit import (
    AreaChart, Card, Metric, Pill, ScoreRing, card_head, eyebrow, ghost_button,
    hbox, hline, ic, lbl, mono, page_head, primary_button, vbox,
)
from ui.responsive import ResponsiveColumns


class HomePageMixin:
    """总览：一屏掌握健康度、实时吞吐与最近事件。"""

    def _create_home_page(self):
        page = QWidget()
        self.home_page = page
        layout = vbox(14, (0, 0, 0, 0), page)

        refresh = ghost_button("刷新数据")
        refresh.clicked.connect(self._home_refresh)
        optimize = primary_button("开始体检", "play")
        optimize.clicked.connect(self._home_start_diagnose)
        self.home_head = page_head(
            self._home_eyebrow(),
            f"{self._home_greeting()}，看看现在的网络状态。",
            "完成一次体检后，这里会显示真实的健康分与网络信息。",
            [refresh, optimize])
        layout.addWidget(self.home_head)

        # 首次启动引导：只出现一次，可跳过；不弹模态框打断用户
        self.home_welcome = self._home_welcome_card()
        layout.addWidget(self.home_welcome)
        try:
            self.home_welcome.setVisible(
                not bool(self.settings.get("onboarded", False)))
        except Exception:
            self.home_welcome.hide()

        body = ResponsiveColumns(left_stretch=16, right_stretch=10)
        layout.addWidget(body, 1)
        left = body.left
        right = body.right

        # ---------------- 左列：健康环 + 实时吞吐 ----------------
        health = Card(16, 0)
        health.setMinimumHeight(182)
        health_row = hbox(22, (0, 0, 0, 0))
        self.home_score_ring = ScoreRing(142, 0, "HEALTH SCORE")
        health_row.addWidget(self.home_score_ring, 0, Qt.AlignVCenter)
        health_row.addWidget(_vline())
        health_row.setStretch(1, 0)

        detail = vbox(0, (0, 0, 0, 0))
        top = hbox(10, (0, 0, 0, 0))
        top.addWidget(eyebrow("NETWORK HEALTH", 8, theme.TEXT_3))
        top.addStretch()
        self.home_health_pill = Pill("待检测", "dim", None, small=True)
        top.addWidget(self.home_health_pill)
        detail.addLayout(top)

        metrics = QGridLayout()
        metrics.setContentsMargins(0, 14, 0, 0)
        metrics.setHorizontalSpacing(22)
        metrics.setVerticalSpacing(12)
        self.home_down_metric = Metric("下行速率", "--")
        self.home_up_metric = Metric("上行速率", "--")
        self.home_ping_metric = Metric("平均延迟", "--", "ms")
        self.home_signal_metric = Metric("信号强度", "--", "%")
        metrics.addWidget(self.home_down_metric, 0, 0)
        metrics.addWidget(self.home_up_metric, 0, 1)
        metrics.addWidget(self.home_ping_metric, 1, 0)
        metrics.addWidget(self.home_signal_metric, 1, 1)
        metrics.setColumnStretch(0, 1)
        metrics.setColumnStretch(1, 1)
        detail.addLayout(metrics)

        self.home_health_note = lbl("尚未体检 · 点击右上角「开始体检」", 11,
                                    theme.TEXT_3, 400, False, 0.2)
        self.home_health_note.setContentsMargins(0, 10, 0, 0)
        detail.addWidget(self.home_health_note)

        health_row.addLayout(detail, 1)
        health.body.addLayout(health_row)
        left.addWidget(health)

        throughput = Card(16, 0)
        throughput_head = hbox(12, (0, 0, 0, 6))
        throughput_head.addWidget(lbl("实时吞吐", 11, theme.TEXT_MAIN, 600))
        self.home_live_pill = Pill("采样中", "dim", None, small=True)
        throughput_head.addWidget(self.home_live_pill)
        throughput_head.addStretch()
        legend = hbox(14, (0, 0, 0, 0))
        legend.addWidget(lbl("— 下行", 9, theme.TEXT_2, 400, True))
        legend.addWidget(lbl("— 上行", 9, theme.MINT, 400, True))
        legend.addWidget(lbl("60 s", 9, theme.TEXT_3, 400, True))
        throughput_head.addLayout(legend)
        throughput.body.addLayout(throughput_head)

        self.home_chart_hint = lbl("正在采样实时流量…", 11, theme.TEXT_3,
                                   align=Qt.AlignCenter)
        self.home_chart_hint.setContentsMargins(0, 18, 0, 0)
        throughput.body.addWidget(self.home_chart_hint)
        self.home_chart = AreaChart([], [])
        self.home_chart.setMinimumHeight(120)
        throughput.body.addWidget(self.home_chart, 1)

        axis = hbox(0, (0, 8, 0, 0))
        axis.addWidget(lbl("60 秒前", 9, theme.TEXT_3, 400, True))
        axis.addStretch()
        axis.addWidget(lbl("30 秒前", 9, theme.TEXT_3, 400, True))
        axis.addStretch()
        axis.addWidget(lbl("现在", 9, theme.TEXT_2, 400, True))
        throughput.body.addLayout(axis)
        left.addWidget(throughput, 1)

        # ---------------- 右列：当前网络 + 最近事件 ----------------
        network = Card(16, 0)
        network_head = hbox(12, (0, 0, 0, 12))
        network_head.addWidget(lbl("当前网络", 11, theme.TEXT_MAIN, 600))
        network_head.addStretch()
        self.home_net_note = lbl("读取中…", 9, theme.TEXT_3, 400, True, 0.6)
        network_head.addWidget(self.home_net_note)
        network.body.addLayout(network_head)

        self._home_net_labels = {}
        rows = ("连接方式", "Wi-Fi 名称", "频段 / 信道", "本机地址",
                "默认网关", "DNS", "协商速率")
        for index, key in enumerate(rows):
            if index:
                network.body.addWidget(hline())
            network.body.addWidget(self._home_net_row(key))

        network.body.addSpacing(10)
        hint_wrap = Card(0, 0, 8, bg=theme.MINT_DIM, border=theme.LINE)
        self.home_net_hint_card = hint_wrap
        hint = hbox(8, (10, 9, 10, 9))
        hint.addWidget(ic("check", 11, theme.MINT))
        self.home_net_hint = lbl("正在读取网络状态…", 10, theme.TEXT_2,
                                 wrap=True)
        hint.addWidget(self.home_net_hint, 1)
        hint_wrap.body.addLayout(hint)
        network.body.addWidget(hint_wrap)
        right.addWidget(network)

        events = Card(16, 0)
        events_head = hbox(12, (0, 0, 0, 6))
        events_head.addWidget(lbl("最近事件", 11, theme.TEXT_MAIN, 600))
        events_head.addStretch()
        events_head.addWidget(lbl("24 H", 9, theme.TEXT_3, 400, True, 0.8))
        events.body.addLayout(events_head)
        self.home_events_body = vbox(0, (0, 0, 0, 0))
        events.body.addLayout(self.home_events_body, 1)
        right.addWidget(events, 1)

        # 结果 / 流量更新：页面只订阅，不自己读盘
        try:
            self.state.result_published.connect(self._on_home_state_result)
            self.state.traffic_changed.connect(self._on_home_traffic)
        except Exception:
            pass

        self._refresh_home_score()
        self._refresh_home_metrics()
        self._refresh_home_network()
        self._refresh_home_chart()

    # ---------------------------------------------------------------- 视图
    def _home_net_row(self, key):
        row = QWidget()
        box = hbox(10, (0, 9, 0, 9), row)
        box.addWidget(lbl(key, 10, theme.TEXT_3))
        box.addStretch()
        value = mono("—", 10, theme.TEXT_MAIN)
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box.addWidget(value)
        self._home_net_labels[key] = value
        return row

    @staticmethod
    def _home_eyebrow():
        stamp = datetime.now().strftime("%m-%d %H:%M")
        return f"OVERVIEW / {stamp}"

    @staticmethod
    def _home_greeting():
        hour = datetime.now().hour
        if hour < 6:
            return "凌晨好"
        if hour < 11:
            return "早上好"
        if hour < 18:
            return "下午好"
        return "晚上好"

    # ---------------------------------------------------------------- 数据
    def _home_snapshot(self):
        try:
            return self.state.snapshot
        except Exception:
            return None

    def _latest_diagnostic(self):
        try:
            result = self.state.get_latest("diagnostic")
        except Exception:
            result = None
        if isinstance(result, list):
            return result
        try:
            records = self.cache.get_history("diagnostic") or []
            result = records[-1].get("result") if records else None
        except Exception:
            result = None
        return result if isinstance(result, list) else []

    def _latest_wifi(self):
        try:
            result = self.state.get_latest("wifi")
        except Exception:
            result = None
        if isinstance(result, dict):
            return result
        try:
            records = self.cache.get_history("wifi") or []
            result = records[-1].get("result") if records else None
        except Exception:
            result = None
        return result if isinstance(result, dict) else {}

    def _diag_item(self, name):
        for item in self._latest_diagnostic():
            if isinstance(item, dict) and item.get("name") == name:
                return item
        return None

    def _home_events(self):
        """最近事件：汇总各类历史记录，按时间倒序取前四条。"""
        names = {"diagnostic": "网络诊断", "repair": "网络修复",
                 "speed": "网速测试", "dns": "DNS 优化", "wifi": "Wi-Fi 检测"}
        entries = []
        try:
            history = self.cache.get_all_history() or {}
        except Exception:
            history = {}
        for category, records in history.items():
            for record in records or []:
                raw_stamp = str(record.get("timestamp", ""))
                stamp = (raw_stamp[11:16] if len(raw_stamp) >= 16
                         else (raw_stamp or "--:--"))
                result = record.get("result")
                title = names.get(category, category)
                if isinstance(result, (list, tuple)):
                    summary = f"完成 {len(result)} 项检查"
                elif isinstance(result, dict):
                    summary = str(result.get("summary")
                                  or result.get("message")
                                  or result.get("score") or "已完成")
                else:
                    summary = str(result or "已完成")
                if summary == title:
                    summary = "已完成"
                entries.append((raw_stamp, stamp, title, summary))
        entries.sort(key=lambda item: item[0], reverse=True)
        events = [(stamp, title, summary)
                  for _, stamp, title, summary in entries[:4]]
        if not events:
            events = [("现在", "暂无历史事件", "完成诊断或测速后会在这里留下记录")]
        return events

    @staticmethod
    def _event_row(time_text, title, desc):
        row = QWidget()
        layout = hbox(10, (0, 9, 0, 9), row)
        time_label = lbl(time_text, 9, theme.TEXT_3, 400, True)
        time_label.setFixedWidth(40)
        time_label.setAlignment(Qt.AlignTop)
        layout.addWidget(time_label)
        body = vbox(2, (0, 0, 0, 0))
        body.addWidget(lbl(title, 11, theme.TEXT_MAIN, 500))
        body.addWidget(lbl(desc, 10, theme.TEXT_3, 400, False, 0, wrap=True))
        layout.addLayout(body, 1)
        return row

    @staticmethod
    def _event_hint():
        wrap = QWidget()
        layout = hbox(8, (0, 8, 0, 0))
        layout.addWidget(ic("clock", 11, theme.TEXT_3))
        layout.addWidget(lbl("所有记录仅保存在本机", 10, theme.TEXT_3))
        layout.addStretch()
        wrap.setLayout(layout)
        return wrap

    def _rebuild_home_events(self):
        layout = getattr(self, "home_events_body", None)
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for index, (time_text, title, desc) in enumerate(self._home_events()):
            if index:
                layout.addWidget(hline())
            layout.addWidget(self._event_row(time_text, title, desc))
        layout.addStretch()
        layout.addWidget(self._event_hint())

    def _home_refresh(self):
        try:
            self._refresh_snapshot(force=True)
        except Exception:
            pass
        self._refresh_home_score()
        self._refresh_home_metrics()
        self._refresh_home_network()
        self._set_status("数据已刷新")
        try:
            self._notify("数据已刷新", "ok")
        except Exception:
            pass

    def _refresh_home_network(self):
        labels = getattr(self, "_home_net_labels", None)
        if not labels:
            return
        snap = self._home_snapshot()
        if snap is None:
            labels["连接方式"].setText("读取中…")
            note = getattr(self, "home_net_note", None)
            if note is not None:
                note.setText("读取中…")
            return

        kind_text = {"wifi": "Wi-Fi", "ethernet": "有线", "none": "未连接",
                     "unknown": "未知"}.get(snap.kind, "未知")
        channel = f"CH {snap.channel}" if snap.channel else "信道未知"
        band = f"{snap.band} · {channel}" if snap.band else channel
        rate = "—"
        if snap.rx_rate is not None or snap.tx_rate is not None:
            down = f"{snap.rx_rate:.0f}" if snap.rx_rate is not None else "—"
            up = f"{snap.tx_rate:.0f}" if snap.tx_rate is not None else "—"
            rate = f"↓{down} / ↑{up} Mbps"

        labels["连接方式"].setText(kind_text)
        labels["Wi-Fi 名称"].setText(snap.ssid or "—")
        labels["频段 / 信道"].setText(band if snap.kind == "wifi" else "—")
        labels["本机地址"].setText(snap.ipv4 or "—")
        labels["默认网关"].setText(snap.gateway or "—")
        labels["DNS"].setText("、".join(snap.dns_servers[:2]) or "—")
        labels["协商速率"].setText(rate)

        note = getattr(self, "home_net_note", None)
        if note is not None:
            if snap.kind == "wifi":
                note.setText((snap.radio_label or "Wi-Fi").upper())
            elif snap.kind == "ethernet":
                note.setText("ETHERNET")
            else:
                note.setText("OFFLINE")
        hint = getattr(self, "home_net_hint", None)
        if hint is not None:
            if snap.online:
                hint.setText(f"{snap.summary}，网络可用")
            elif snap.kind == "none":
                hint.setText("未检测到网络连接，请检查网线或 Wi-Fi 开关")
            else:
                hint.setText("已连接本地网络，但暂时无法访问互联网")

        card = getattr(self, "home_net_hint_card", None)
        if card is not None:
            bg = theme.MINT_DIM if snap.online else theme.AMBER_DIM
            border = theme.LINE if snap.online else theme.AMBER_LINE
            card.setStyleSheet(
                f"QFrame#kitCard {{ background-color: {bg};"
                f" border: 1px solid {border}; border-radius: 8px; }}")

    def _refresh_home_metrics(self):
        """把最近一次真实采样/诊断/Wi-Fi 结果写进健康卡。"""
        down = getattr(self, "home_down_metric", None)
        up = getattr(self, "home_up_metric", None)
        ping_m = getattr(self, "home_ping_metric", None)
        sig_m = getattr(self, "home_signal_metric", None)
        if down is None and up is None and ping_m is None and sig_m is None:
            return

        dn_text = getattr(self, "_last_down_text", None)
        up_text = getattr(self, "_last_up_text", None)
        if dn_text and down is not None:
            down.set_value(dn_text)
        if up_text and up is not None:
            up.set_value(up_text)

        if ping_m is not None:
            ping_val = self._extract_ping_from_cache()
            ping_m.set_value(ping_val if ping_val is not None else "--")

        if sig_m is not None:
            sig_val = self._extract_signal_from_cache()
            if sig_val is None:
                snap = self._home_snapshot()
                signal = getattr(snap, "signal_pct", None) if snap else None
                if isinstance(signal, (int, float)):
                    sig_val = str(int(signal))
            sig_m.set_value(sig_val if sig_val is not None else "--")

        self._refresh_home_dns_row()

    def _on_home_state_result(self, kind, _data):
        if kind == "diagnostic":
            self._refresh_home_score()
            self._refresh_home_metrics()
        elif kind in ("wifi", "speed", "dns"):
            self._refresh_home_metrics()
            self._rebuild_home_events()
        elif kind == "repair":
            self._rebuild_home_events()

    def _on_home_traffic(self, _up, _down):
        self._refresh_home_chart()

    def _refresh_home_chart(self):
        chart = getattr(self, "home_chart", None)
        hint = getattr(self, "home_chart_hint", None)
        if chart is None:
            return
        try:
            samples = self.state.traffic
        except Exception:
            samples = []
        if not samples:
            chart.set_series([], [])
            if hint is not None:
                hint.show()
            return
        downs = [down for _up, down in samples]
        ups = [up for up, _down in samples]
        peak = max(downs + ups + [1.0])
        chart.set_series([value / peak for value in downs],
                         [value / peak for value in ups])
        pill = getattr(self, "home_live_pill", None)
        if pill is not None:
            pill.setText("LIVE")
        if hint is not None:
            hint.hide()

    # ---------------------------------------------------------------- 缓存提取
    def _extract_ping_from_cache(self):
        """从最近一次诊断的结构化数据取平均延迟；旧记录回退解析文案。"""
        item = self._diag_item("多站点延迟")
        data = (item or {}).get("data") or {}
        if isinstance(data.get("avg_ms"), (int, float)):
            return str(int(round(data["avg_ms"])))
        item = self._diag_item("互联网连通性")
        data = (item or {}).get("data") or {}
        if isinstance(data.get("latency_ms"), (int, float)):
            return str(int(round(data["latency_ms"])))
        # 兼容旧缓存：从中文文案里提取
        for name in ("多站点延迟", "互联网连通性"):
            item = self._diag_item(name)
            if not item:
                continue
            msg = str(item.get("message", ""))
            match = re.search(r"平均\s*(\d+(?:\.\d+)?)\s*ms", msg)
            if match:
                return str(int(round(float(match.group(1)))))
        return None

    def _extract_signal_from_cache(self):
        """从最近一次 Wi-Fi 检测提取信号百分比；没有则返回 None。"""
        info = self._latest_wifi()
        if not info:
            return None
        signal = info.get("signal_strength")
        if isinstance(signal, (int, float)):
            return str(int(signal))
        return None

    def _refresh_home_dns_row(self):
        """当前网络卡片 DNS 行：显示系统当前 DNS（真实值）。"""
        label = getattr(self, "_home_net_labels", {}).get("DNS")
        if label is None:
            return
        snap = self._home_snapshot()
        servers = getattr(snap, "dns_servers", None) if snap else None
        label.setText("、".join(servers[:2]) if servers else "—")

    # ---------------------------------------------------------------- 引导
    def _home_welcome_card(self):
        card = Card(16, 0)
        row = hbox(16, (0, 0, 0, 0))
        text = vbox(0, (0, 0, 0, 0))
        text.addWidget(lbl("第一次用？按这 3 步来。", 13,
                           theme.TEXT_MAIN, 600))
        steps = lbl(
            "① 体检：检查 7 项网络状态  →  ② 修复：只处理发现的问题  →  "
            "③ 复查：确认修复效果", 10, theme.TEXT_3, wrap=True)
        steps.setContentsMargins(0, 6, 0, 0)
        text.addWidget(steps)
        row.addLayout(text, 1)

        actions = hbox(8, (0, 0, 0, 0))
        skip = ghost_button("先随便看看")
        skip.clicked.connect(self._dismiss_onboarding)
        start = primary_button("开始体检", "play")
        start.clicked.connect(self._home_start_diagnose)
        actions.addWidget(skip)
        actions.addWidget(start)
        row.addLayout(actions, 0)
        card.body.addLayout(row)
        return card

    def _dismiss_onboarding(self):
        try:
            self.settings.update({"onboarded": True})
        except Exception:
            pass
        card = getattr(self, "home_welcome", None)
        if card is not None:
            card.hide()

    def _home_start_diagnose(self):
        """主页主按钮：跳到诊断页并自动开始诊断。"""
        self._dismiss_onboarding()
        self._switch_page("diagnose")
        self._start_diagnose()

    def _refresh_home_score(self):
        """依据最近一次诊断结果刷新首页健康环。"""
        ring = getattr(self, "home_score_ring", None)
        if ring is None:
            return
        self._rebuild_home_events()
        pill = getattr(self, "home_health_pill", None)
        note = getattr(self, "home_health_note", None)
        items = self._latest_diagnostic()
        if not items:
            ring.set_unknown("HEALTH SCORE")
            if pill is not None:
                pill.setText("待检测")
            if note is not None:
                note.setText("尚未体检 · 点击右上角「开始体检」")
            return

        ok, total = 0, 0
        for item in items:
            if isinstance(item, dict):
                total += 1
                if item.get("status") == "ok":
                    ok += 1
        if total == 0:
            ring.set_unknown("HEALTH SCORE")
            return
        score = round(ok / total * 100)
        ring.set_score(score, None, "HEALTH SCORE")
        if pill is not None:
            pill.setText("优秀" if score >= 90 else
                         "良好" if score >= 75 else "待优化")
        if note is not None:
            stamp = ""
            try:
                records = self.cache.get_history("diagnostic") or []
                if records:
                    raw = str(records[-1].get("timestamp", ""))
                    stamp = raw[11:16] if len(raw) >= 16 else raw
            except Exception:
                stamp = ""
            note.setText(
                f"最近诊断 {stamp} · {ok}/{total} 项正常" if stamp
                else f"最近诊断 · {ok}/{total} 项正常")


def _vline():
    """轻量竖分割线，避免 home 直接依赖 kit.vline 的导入顺序。"""
    from ui.kit import vline
    return vline()
