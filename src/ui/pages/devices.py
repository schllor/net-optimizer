"""局域网设备管理页：真实邻居表 + 自定义名称 + 路由器操作引导。

本工具无法直接读取路由器的逐设备流量/CPU，因此不再展示这些示例数据；
页面只呈现 ARP/邻居表能确认的设备、在线状态和扫描时间。
"""

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QGridLayout, QInputDialog, QLabel,
    QLineEdit, QMenu, QMessageBox, QWidget,
)

import core.theme as theme
from ui.kit import (
    Avatar, Card, ghost_button, hbox, hline, ic, lbl, mono, page_head,
    primary_button, vbox,
)
from ui.responsive import ResponsiveColumns
from ui.workers import DeviceScanWorker


def _badge(text, color=theme.TEXT_3, border=theme.LINE, bg=None):
    badge = QFrame()
    badge.setStyleSheet(
        f"QFrame {{ border: 1px solid {border}; border-radius: 4px;"
        f" background-color: {bg or 'transparent'}; }}")
    layout = hbox(0, (5, 3, 5, 3), badge)
    layout.addWidget(lbl(text, 9, color, 400, True, 0.5))
    return badge


class DevicesPageMixin:
    """设备管理页：局域网设备列表、重命名与限速/封禁引导。"""

    def _create_devices_page(self):
        page = QWidget()
        self.devices_page = page
        root = vbox(14, (0, 0, 0, 0), page)

        self.dev_scan_btn = ghost_button("扫描设备")
        self.dev_scan_btn.clicked.connect(self._start_devices_scan)
        rules_btn = primary_button("限速规则")
        rules_btn.clicked.connect(self._show_bandwidth_rules)
        self.dev_head = page_head(
            "DEVICES / LAN OVERVIEW",
            "看看局域网里都有谁。",
            "扫描前不会显示设备；扫描只读取系统邻居表，不会修改路由器。",
            [self.dev_scan_btn, rules_btn])
        root.addWidget(self.dev_head)

        root.addWidget(self._create_stat_strip())

        # 兼容旧接口：隐藏计数标签保留；筛选器移到列表头
        self.dev_count = QLabel("0 台设备", page)
        self.dev_count.hide()

        body = ResponsiveColumns(left_stretch=160, right_stretch=100)
        root.addWidget(body, 1)
        left = body.left
        right = body.right

        # ---------------- 左：设备表 ----------------
        table = Card(16, 0)
        table_head = hbox(10, (0, 0, 0, 14))
        table_head.addWidget(lbl("局域网设备", 11, theme.TEXT_MAIN, 600))
        table_head.addStretch()
        self.dev_filter = QComboBox()
        self.dev_filter.addItems(["全部设备", "仅在线", "仅离线"])
        self.dev_filter.setFixedWidth(96)
        self.dev_filter.currentIndexChanged.connect(self._refresh_devices_view)
        table_head.addWidget(self.dev_filter)
        table.body.addLayout(table_head)
        table.body.addWidget(self._dev_table_head())

        self.dev_list_widget = QWidget()
        self.dev_list_layout = vbox(0, (0, 0, 0, 0), self.dev_list_widget)
        self.dev_list_layout.addStretch()
        table.body.addWidget(self.dev_list_widget, 1)

        footer = hbox(0, (0, 10, 0, 0))
        self.dev_foot_note = lbl("尚未扫描", 9, theme.TEXT_3)
        self.dev_last_scan = mono("LAST SCAN --:--", 9, theme.TEXT_3, 0.8)
        footer.addWidget(self.dev_foot_note)
        footer.addStretch()
        footer.addWidget(self.dev_last_scan)
        table.body.addLayout(footer)
        left.addWidget(table, 1)

        # ---------------- 右：未知设备 + 说明 ----------------
        unknown_card = Card(16, 0, radius=14, bg=theme.AMBER_DIM,
                            border=theme.AMBER_LINE)
        unknown_head = hbox(10, (0, 0, 0, 0))
        unknown_head.addWidget(lbl("UNKNOWN DEVICE", 8, theme.WARNING, 400,
                                   True, 1.3))
        unknown_head.addStretch()
        unknown_head.addWidget(_badge("需确认", theme.WARNING, theme.AMBER_LINE))
        unknown_card.body.addLayout(unknown_head)

        self.dev_unknown_title = lbl("尚未扫描", 13, theme.TEXT_MAIN, 600)
        self.dev_unknown_title.setContentsMargins(0, 9, 0, 0)
        unknown_card.body.addWidget(self.dev_unknown_title)

        self.dev_unknown_desc = lbl(
            "扫描后，无法识别名称的设备会显示在这里。", 10,
            theme.TEXT_3, 400, False, 0, wrap=True)
        self.dev_unknown_desc.setContentsMargins(0, 6, 0, 0)
        unknown_card.body.addWidget(self.dev_unknown_desc)

        unknown_actions = hbox(8, (0, 12, 0, 0))
        self.dev_allow_btn = ghost_button("复制 MAC")
        self.dev_allow_btn.clicked.connect(self._allow_unknown_device)
        self.dev_limit_unknown_btn = primary_button("限速指引")
        self.dev_limit_unknown_btn.clicked.connect(self._limit_unknown_device)
        unknown_actions.addWidget(self.dev_allow_btn, 1)
        unknown_actions.addWidget(self.dev_limit_unknown_btn, 1)
        self.dev_allow_btn.setEnabled(False)
        self.dev_limit_unknown_btn.setEnabled(False)
        unknown_card.body.addLayout(unknown_actions)
        self.dev_unknown_card = unknown_card
        right.addWidget(unknown_card)

        note_card = Card(16, 0)
        note_card.body.addWidget(lbl("关于设备管理", 11, theme.TEXT_MAIN, 600))
        note_card.body.addSpacing(10)
        note_card.body.addWidget(lbl(
            "本工具读取 Windows 邻居表（GetIpNetTable2 / arp -a）并用 ARP "
            "确认在线状态，不会修改路由器的限速或黑名单。需要限速/封禁时，"
            "会复制目标设备的 MAC，并给出路由器后台的操作路径。",
            10, theme.TEXT_3, 400, False, 0, wrap=True))
        note_card.body.addSpacing(12)
        note_card.body.addWidget(hline())
        note_card.body.addSpacing(12)
        for key in ("双击设备行可重命名", "右键可复制 MAC / 查看限速指引",
                    "设备名称只保存在本机"):
            row = hbox(8, (0, 4, 0, 4))
            row.addWidget(ic("check", 11, theme.MINT))
            row.addWidget(lbl(key, 10, theme.TEXT_3), 1)
            note_card.body.addLayout(row)
        note_card.body.addStretch()
        right.addWidget(note_card, 1)

        self._devices = []
        self._add_devices_empty_state()
        self._update_dev_footer()

    # ---------------------------------------------------------------- 统计
    def _create_stat_strip(self):
        strip = QFrame()
        strip.setStyleSheet(
            f"QFrame {{ background-color: {theme.LINE};"
            f" border: 1px solid {theme.LINE}; border-radius: 12px; }}")
        row = hbox(1, (0, 0, 0, 0), strip)
        self.dev_stat_labels = {}
        cells = (
            ("online", "在线设备", "—", "台", theme.TEXT_MAIN),
            ("unknown", "未知设备", "—", "台", theme.WARNING),
            ("self", "本机", "—", "", theme.TEXT_MAIN),
            ("elapsed", "扫描耗时", "—", "s", theme.TEXT_MAIN),
        )
        for index, (key, caption, value, unit, color) in enumerate(cells):
            cell = QFrame()
            corners = ""
            if index == 0:
                corners = ("border-top-left-radius: 11px;"
                           " border-bottom-left-radius: 11px;")
            elif index == len(cells) - 1:
                corners = ("border-top-right-radius: 11px;"
                           " border-bottom-right-radius: 11px;")
            cell.setStyleSheet(
                f"QFrame {{ background-color: {theme.SURFACE};"
                f" border: none; {corners} }}")
            box = vbox(0, (14, 11, 14, 11), cell)
            box.addWidget(lbl(caption, 9, theme.TEXT_3, 400, False, 0.6))
            value_row = hbox(2, (0, 6, 0, 0))
            value_label = lbl(value, 19, color, 600, False, -0.5)
            value_row.addWidget(value_label)
            unit_label = lbl(unit, 9, theme.TEXT_3)
            unit_label.setContentsMargins(0, 0, 0, 3)
            value_row.addWidget(unit_label, 0, Qt.AlignBottom)
            value_row.addStretch()
            box.addLayout(value_row)
            row.addWidget(cell, 1)
            self.dev_stat_labels[key] = value_label
        return strip

    def _dev_grid(self, widget):
        grid = QGridLayout(widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(0)
        grid.setColumnMinimumWidth(0, 32)
        grid.setColumnStretch(1, 16)
        grid.setColumnStretch(2, 10)
        grid.setColumnMinimumWidth(3, 64)
        return grid

    def _dev_table_head(self):
        head = QFrame()
        head.setStyleSheet(
            f"QFrame {{ background: transparent; border: none;"
            f" border-bottom: 1px solid {theme.LINE}; }}")
        grid = self._dev_grid(head)
        grid.setContentsMargins(0, 0, 0, 8)
        for column, text in enumerate(("", "设备", "类型", "状态")):
            label = mono(text, 9, theme.TEXT_3, 0.8)
            if column == 3:
                label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(label, 0, column)
        return head

    # ---------------------------------------------------------------- 设备行
    def _device_icon(self, dev):
        name = str(dev.get("name") or "")
        if "TV" in name or "电视" in name:
            return "tv"
        if "iPhone" in name or "手机" in name or "iPad" in name or "平板" in name:
            return "phone"
        if "音箱" in name or "speaker" in name.lower():
            return "speaker"
        if dev.get("unknown") or name in ("", "未知设备"):
            return "search"
        return "laptop"

    def _device_type(self, dev):
        name = str(dev.get("name") or "").lower()
        if any(key in name for key in ("iphone", "android", "phone", "手机")):
            return "手机"
        if any(key in name for key in ("ipad", "tablet", "平板")):
            return "平板"
        if any(key in name for key in ("tv", "电视", "chromecast")):
            return "电视"
        if any(key in name for key in ("desktop", "pc", "台式")):
            return "台式机"
        if any(key in name for key in ("laptop", "macbook", "笔记本")):
            return "笔记本"
        if any(key in name for key in ("router", "路由器", "gateway")):
            return "路由器"
        if any(key in name for key in ("speaker", "音箱", "homepod")):
            return "智能音箱"
        return "未识别"

    def _add_device_row(self, dev, interactive=True):
        if self.dev_list_layout.count() > 1:
            self.dev_list_layout.insertWidget(
                self.dev_list_layout.count() - 1, hline())

        row = QWidget()
        grid = self._dev_grid(row)
        grid.setContentsMargins(0, 8, 0, 8)

        unknown = bool(dev.get("unknown")) or dev.get("name") in ("未知设备", "")
        avatar = Avatar(self._device_icon(dev), 32,
                        theme.WARNING if unknown else theme.TEXT_2,
                        theme.AMBER_LINE if unknown else theme.LINE_STRONG)
        grid.addWidget(avatar, 0, 0, Qt.AlignVCenter)

        name_cell = QWidget()
        name_box = vbox(3, (0, 0, 0, 0), name_cell)
        name_row = hbox(6, (0, 0, 0, 0))
        name_row.addWidget(lbl(self._device_display_name(dev), 11,
                               theme.TEXT_MAIN, 500))
        if dev.get("self"):
            name_row.addWidget(_badge("本机", theme.MINT, theme.MINT_LINE,
                                      "#0f8bffd1"))
        elif unknown:
            name_row.addWidget(_badge("未知", theme.WARNING, theme.AMBER_LINE))
        name_row.addStretch()
        name_box.addLayout(name_row)
        name_box.addWidget(mono(f"{dev.get('ip', '')} · {dev.get('mac', '')}",
                                9, theme.TEXT_3, 0.2))
        grid.addWidget(name_cell, 0, 1)

        grid.addWidget(lbl(self._device_type(dev), 9, theme.TEXT_3), 0, 2)

        online = bool(dev.get("online"))
        status = lbl("在线" if online else "离线", 10,
                     theme.MINT if online else theme.TEXT_3, 400, True, 0.2)
        status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(status, 0, 3)

        if interactive:
            row.setContextMenuPolicy(Qt.CustomContextMenu)
            row.customContextMenuRequested.connect(
                lambda pos, d=dev, w=row: self._device_menu(
                    d, w.mapToGlobal(pos)))
            row.mouseDoubleClickEvent = lambda event, d=dev: self._rename_device(d)
            row.setToolTip("双击重命名 · 右键更多操作")

        self.dev_list_layout.insertWidget(self.dev_list_layout.count() - 1, row)
        return row

    def _device_menu(self, dev, global_pos):
        menu = QMenu(self)
        menu.addAction("重命名", lambda: self._rename_device(dev))
        menu.addAction("复制 MAC", lambda: self._copy_mac(dev))
        if not dev.get("self"):
            menu.addAction("限速指引", lambda: self._confirm_limit_device(dev))
            menu.addAction("封禁指引", lambda: self._confirm_block_device(dev))
        menu.exec(global_pos)

    def _copy_mac(self, dev):
        try:
            QApplication.clipboard().setText(dev.get("mac", ""))
            self._set_status(f"已复制 MAC：{dev.get('mac', '')}")
            self._notify("MAC 地址已复制", "ok")
        except Exception:
            self._set_status("复制 MAC 失败")

    def _update_dev_footer(self):
        total = len(self._devices)
        online = sum(1 for d in self._devices if d.get("online"))
        offline = max(0, total - online)
        if self._devices:
            self.dev_foot_note.setText(
                f"在线 {online} 台 · 离线 {offline} 台"
                if offline else f"共 {total} 台，全部在线")
            self.dev_last_scan.setText(
                "LAST SCAN " + datetime.now().strftime("%H:%M"))
        else:
            self.dev_foot_note.setText("尚未扫描")
            self.dev_last_scan.setText("LAST SCAN --:--")

    # ---------------------------------------------------------------- 扫描
    def _start_devices_scan(self):
        self._devices = []
        self.dev_scan_btn.setEnabled(False)
        self.dev_scan_btn.setText("扫描中…")
        self.dev_head.set_title("正在扫描局域网…")
        self.dev_head.set_desc("读取系统邻居表并用 ARP 确认在线状态，通常需要 2–5 秒。")
        self._scan_started = datetime.now()
        w = DeviceScanWorker()
        w.done.connect(self._on_devices_scanned)
        self._dev_worker = w
        self._start_worker(w)

    def _on_devices_scanned(self, devs):
        self.dev_scan_btn.setEnabled(True)
        self.dev_scan_btn.setText("重新扫描")
        if devs is None:
            self.dev_head.set_title("扫描未完成")
            self.dev_head.set_desc("请确认设备与本机处于同一局域网后重试。")
            self._set_status("设备扫描未完成，请重试")
            return
        self._devices = list(devs)
        elapsed = 0.0
        if getattr(self, "_scan_started", None) is not None:
            elapsed = (datetime.now() - self._scan_started).total_seconds()
        self._scan_elapsed = elapsed
        self._refresh_devices_view()
        self._notify(f"扫描完成：{len(self._devices)} 台设备", "ok")

    def _refresh_devices_view(self):
        self.dev_count.setText(f"{len(self._devices)} 台设备")
        self._update_dev_stats()
        while self.dev_list_layout.count():
            item = self.dev_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.dev_list_layout.addStretch()
        filter_idx = self.dev_filter.currentIndex() if hasattr(
            self, "dev_filter") else 0
        shown = 0
        for dev in self._devices:
            if filter_idx == 1 and not dev.get("online"):
                continue
            if filter_idx == 2 and dev.get("online"):
                continue
            self._add_device_row(dev)
            shown += 1
        if shown == 0:
            self._add_devices_empty_state()
        self._update_dev_footer()
        total = len(self._devices)
        online = sum(1 for d in self._devices if d.get("online"))
        unknown = sum(1 for d in self._devices if self._is_unknown(d))
        self.dev_head.set_title(
            "局域网设备已扫描" if self._devices else "没有扫描到设备")
        self.dev_head.set_desc(
            f"共 {total} 台，在线 {online} 台，未知 {unknown} 台；"
            "数据仅来自本机邻居表。")

    def _is_unknown(self, dev):
        return (bool(dev.get("unknown"))
                or dev.get("name") in ("未知设备", "")
                or not dev.get("name"))

    def _update_dev_stats(self):
        labels = getattr(self, "dev_stat_labels", None)
        if not labels:
            return
        online = sum(1 for d in self._devices if d.get("online"))
        unknown = sum(1 for d in self._devices if self._is_unknown(d))
        self_dev = next((d for d in self._devices if d.get("self")), None)
        labels["online"].setText(str(online))
        labels["unknown"].setText(str(unknown))
        labels["self"].setText(
            str(self_dev.get("ip", "本机")) if self_dev else "—")
        elapsed = getattr(self, "_scan_elapsed", None)
        labels["elapsed"].setText(f"{elapsed:.1f}" if elapsed is not None else "—")

        if self._devices:
            if unknown:
                self.dev_unknown_title.setText(f"发现 {unknown} 台未知设备")
                first = next(d for d in self._devices if self._is_unknown(d))
                self.dev_unknown_desc.setText(
                    f"MAC {first.get('mac', '--')} · IP "
                    f"{first.get('ip', '--')}。可能是访客手机或智能家居。")
            else:
                self.dev_unknown_title.setText("未发现未知设备")
                self.dev_unknown_desc.setText(
                    "当前扫描到的设备均已识别名称，可继续关注新接入的设备。")
        else:
            self.dev_unknown_title.setText("尚未扫描")
            self.dev_unknown_desc.setText(
                "扫描后，无法识别名称的设备会显示在这里。")
        has_unknown = bool(unknown)
        self.dev_allow_btn.setEnabled(has_unknown)
        self.dev_limit_unknown_btn.setEnabled(has_unknown)

    def _add_devices_empty_state(self):
        box = QFrame()
        box.setStyleSheet("background: transparent;")
        bl = vbox(8, (24, 36, 24, 36), box)
        bl.setAlignment(Qt.AlignCenter)

        icon = ic("devices", 32, theme.TEXT_3)
        title = lbl("尚未扫描设备" if not self._devices else "当前筛选条件下没有设备",
                    11, theme.TEXT_MAIN, 500, align=Qt.AlignCenter)
        desc = lbl("点击上方「扫描设备」，确认设备与本机处于同一局域网。",
                   10, theme.TEXT_3, 400, False, 0, wrap=True,
                   align=Qt.AlignCenter)
        bl.addWidget(icon, 0, Qt.AlignCenter)
        bl.addWidget(title)
        bl.addWidget(desc)
        self.dev_list_layout.insertWidget(self.dev_list_layout.count() - 1, box)

    # ---------------------------------------------------------------- 操作
    def _device_display_name(self, dev):
        alias = self.cache.get_device_alias(dev.get("mac", ""))
        return alias or dev.get("name", "未知设备")

    def _unknown_device(self):
        for dev in self._devices:
            if self._is_unknown(dev):
                return dev
        return None

    def _show_bandwidth_rules(self):
        QMessageBox.information(
            self, "限速规则",
            "本工具不直接修改路由器配置。\n\n"
            "如需为设备限速：登录路由器管理页 → 限速 / QoS 带宽控制 → "
            "选择设备并设置上下行带宽即可。")

    def _allow_unknown_device(self):
        dev = self._unknown_device()
        if dev is None:
            self._set_status("当前没有未知设备")
            return
        self._copy_mac(dev)
        QMessageBox.information(
            self, "加入白名单",
            "为安全起见，本工具不直接修改路由器配置。\n\n"
            f"该设备的 MAC 地址已复制：{dev.get('mac', '')}\n\n"
            "请登录路由器管理页 → 设备管理 / 白名单 → 粘贴该 MAC 并允许接入。")

    def _limit_unknown_device(self):
        dev = self._unknown_device()
        if dev is None:
            self._set_status("当前没有未知设备")
            return
        self._confirm_limit_device(dev)

    def _rename_device(self, dev):
        mac = dev.get("mac", "").lower()
        current = self.cache.get_device_alias(mac)
        if current == "" and dev.get("name", "") != "未知设备":
            current = dev.get("name", "")
        text, ok = QInputDialog.getText(
            self, "重命名设备",
            "为该设备设置一个自定义名称（留空则恢复自动识别）：\n\n"
            f"IP：{dev.get('ip', '')}\nMAC：{dev.get('mac', '')}",
            QLineEdit.Normal, current)
        if not ok:
            return
        self.cache.save_device_alias(mac, text)
        self._refresh_devices_view()

    def _confirm_limit_device(self, dev):
        name = self._device_display_name(dev)
        ret = QMessageBox.question(
            self, "限速指引",
            f"将为这台设备复制 MAC，并给出路由器端操作路径。\n\n设备：{name}\n"
            f"IP：{dev.get('ip', '')}\nMAC：{dev.get('mac', '')}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        self._copy_mac(dev)
        QMessageBox.information(
            self, "限速说明",
            "为安全起见，本工具不直接修改路由器配置。\n\n"
            f"该设备的 MAC 地址已复制：{dev.get('mac', '')}\n\n"
            "请登录路由器管理页 → 限速/QoS 带宽控制 → 粘贴该 MAC 并设置限速即可。")

    def _confirm_block_device(self, dev):
        name = self._device_display_name(dev)
        ret = QMessageBox.question(
            self, "封禁指引",
            f"将为这台设备复制 MAC，并给出路由器端操作路径。\n\n设备：{name}\n"
            f"IP：{dev.get('ip', '')}\nMAC：{dev.get('mac', '')}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        self._copy_mac(dev)
        QMessageBox.information(
            self, "封禁说明",
            "为安全起见，本工具不直接修改路由器配置。\n\n"
            f"该设备的 MAC 地址已复制：{dev.get('mac', '')}\n\n"
            "请登录路由器管理页 → 设备管理/黑名单 → 粘贴该 MAC 并禁止其接入即可。")
