"""局域网设备管理页面。"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QLineEdit, QComboBox, QInputDialog, QMessageBox, QApplication,
)
from PySide6.QtCore import Qt

import core.theme as theme
from core.theme import RADIUS_SMALL
from ui.common import Colors
from ui.workers import DeviceScanWorker


class DevicesPageMixin:
    """设备管理页：局域网设备列表、重命名与操作引导。"""

    def _create_devices_page(self):
        """局域网设备管理页（只读扫描 + 定位；危险操作二次确认）"""
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # 顶部说明卡片
        card = self._create_card()
        cl = QVBoxLayout(card)
        title = QLabel("局域网设备")
        title.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {Colors.TEXT_MAIN};")
        hint = QLabel("扫描当前路由下最近活跃的设备，了解谁在连接你的网络")
        hint.setStyleSheet(f"font-size: 12px; color: {Colors.TEXT_SECONDARY};")
        cl.addWidget(title)
        cl.addWidget(hint)

        bar = QHBoxLayout()
        self.dev_filter = QComboBox()
        self.dev_filter.addItems(["全部设备", "仅在线", "仅离线"])
        self.dev_filter.currentIndexChanged.connect(self._refresh_devices_view)
        self.dev_count = QLabel("0 台设备")
        self.dev_count.setStyleSheet(f"color: {Colors.TEXT_LIGHT}; font-size: 12px;")
        self.dev_scan_btn = QPushButton("扫描设备")
        self.dev_scan_btn.setCursor(Qt.PointingHandCursor)
        self.dev_scan_btn.setStyleSheet(theme.accent_button(RADIUS_SMALL))
        self.dev_scan_btn.clicked.connect(self._start_devices_scan)
        bar.addWidget(self.dev_filter)
        bar.addWidget(self.dev_count)
        bar.addStretch()
        bar.addWidget(self.dev_scan_btn)
        cl.addLayout(bar)
        root.addWidget(card)

        # 统计卡行（参考设计：大数字 + 小标签，一眼看清设备总量）
        stat_row = QHBoxLayout()
        stat_row.setSpacing(12)
        self.dev_stat_labels = {}
        for skey, stitle in (("total", "全部设备"), ("online", "在线"), ("offline", "离线")):
            scard = QFrame()
            scard.setObjectName("surfaceCard")   # 与 raised_card 的选择器对齐
            scard.setStyleSheet(theme.raised_card(RADIUS_SMALL))
            sl = QVBoxLayout(scard)
            sl.setContentsMargins(16, 12, 16, 12)
            sl.setSpacing(2)
            slabel = QLabel(stitle)
            slabel.setStyleSheet(f"font-size: 12px; color: {Colors.TEXT_SECONDARY};")
            svalue = QLabel("0")
            svalue.setStyleSheet(
                f"font-size: 24px; font-weight: bold; color: {Colors.TEXT_MAIN};")
            sl.addWidget(slabel)
            sl.addWidget(svalue)
            stat_row.addWidget(scard, 1)
            self.dev_stat_labels[skey] = svalue
        root.addLayout(stat_row)

        # 设备列表（白卡滚动）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(theme.scroll_area())
        self.dev_list_widget = QWidget()
        self.dev_list_layout = QVBoxLayout(self.dev_list_widget)
        self.dev_list_layout.setContentsMargins(12, 12, 12, 12)
        self.dev_list_layout.setSpacing(8)
        self.dev_list_layout.addStretch()
        scroll.setWidget(self.dev_list_widget)
        root.addWidget(scroll, 1)

        self._devices = []
        page.setLayout(root)
        self.devices_page = page

    def _start_devices_scan(self):
        """启动设备扫描（后台线程）"""
        self._devices = []
        self.dev_scan_btn.setEnabled(False)
        self.dev_scan_btn.setText("扫描中…")
        w = DeviceScanWorker()
        w.finished.connect(self._on_devices_scanned)
        self._dev_worker = w
        w.start()

    def _on_devices_scanned(self, devs):
        """设备扫描完成"""
        self._devices = devs
        self.dev_scan_btn.setEnabled(True)
        self.dev_scan_btn.setText("重新扫描")
        self._refresh_devices_view()

    def _refresh_devices_view(self):
        """按筛选条件重建设备列表"""
        self.dev_count.setText(f"{len(self._devices)} 台设备")
        self._update_dev_stats()
        while self.dev_list_layout.count() > 1:
            item = self.dev_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        filter_idx = self.dev_filter.currentIndex()  # 0全部 1在线 2离线
        shown = 0
        for d in self._devices:
            if filter_idx == 1 and not d.get("online"):
                continue
            if filter_idx == 2 and d.get("online"):
                continue
            self._add_device_row(d)
            shown += 1
        if shown == 0:
            self._add_devices_empty_state()

    def _update_dev_stats(self):
        """刷新顶部统计卡数字（全部 / 在线 / 离线）"""
        labels = getattr(self, "dev_stat_labels", None)
        if not labels:
            return
        total = len(self._devices)
        online = sum(1 for d in self._devices if d.get("online"))
        labels["total"].setText(str(total))
        labels["online"].setText(str(online))
        labels["offline"].setText(str(total - online))

    def _add_devices_empty_state(self):
        """列表为空时的占位（参考设计：图标 + 标题 + 说明，居中排布）"""
        box = QFrame()
        box.setStyleSheet("background: transparent;")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(24, 36, 24, 36)
        bl.setSpacing(8)
        bl.setAlignment(Qt.AlignCenter)

        icon = QLabel("▣")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(f"font-size: 32px; color: {Colors.TEXT_LIGHT};")
        title = QLabel("未扫描到设备" if not self._devices else "当前筛选条件下没有设备")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {Colors.TEXT_MAIN};")
        desc = QLabel("点击上方「扫描设备」刷新，或确认设备与本机处于同一局域网。")
        desc.setAlignment(Qt.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet(f"font-size: 12px; color: {Colors.TEXT_SECONDARY};")

        bl.addWidget(icon)
        bl.addWidget(title)
        bl.addWidget(desc)
        self.dev_list_layout.insertWidget(self.dev_list_layout.count() - 1, box)

    def _device_display_name(self, dev):
        """返回设备显示名：优先自定义名称，其次自动识别名"""
        alias = self.cache.get_device_alias(dev.get("mac", ""))
        return alias or dev.get("name", "未知设备")

    def _add_device_row(self, dev):
        """添加一行设备卡片"""
        row = QFrame()
        row.setStyleSheet(theme.raised_card(RADIUS_SMALL))
        lay = QHBoxLayout(row)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(12)

        online = bool(dev.get("online"))
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {Colors.SUCCESS if online else Colors.TEXT_LIGHT}; font-size: 16px;")
        dot.setToolTip("在线" if online else "离线")

        is_unknown = dev.get("name", "") == "未知设备"
        icon = QLabel("?" if is_unknown else "●")
        icon.setStyleSheet(f"font-size: 16px; color: {Colors.WARNING if is_unknown else Colors.TEXT_MAIN};")
        icon.setToolTip("未知设备（未识别名称）" if is_unknown else "已识别设备")

        name_lbl = QLabel(self._device_display_name(dev))
        name_lbl.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {Colors.TEXT_MAIN};")
        meta_lbl = QLabel(f"{dev.get('ip','')} · {dev.get('mac','')}" + (" · 本机" if dev.get("self") else ""))
        meta_lbl.setStyleSheet(f"font-size: 12px; color: {Colors.TEXT_SECONDARY};")

        infos = QVBoxLayout()
        infos.setSpacing(2)
        infos.addWidget(name_lbl)
        infos.addWidget(meta_lbl)

        lay.addWidget(dot)
        lay.addWidget(icon)
        lay.addLayout(infos)
        lay.addStretch()

        # 自定义名称（所有设备均可）
        rename_btn = QPushButton("重命名")
        rename_btn.setCursor(Qt.PointingHandCursor)
        rename_btn.setStyleSheet(theme.secondary_button())
        rename_btn.clicked.connect(lambda *_, d=dev: self._rename_device(d))
        lay.addWidget(rename_btn)

        if dev.get("self"):
            self_lbl = QLabel("本机")
            self_lbl.setStyleSheet(
                f"color: {Colors.PRIMARY}; background-color: {Colors.PRIMARY_LIGHT};"
                "border-radius: 6px; padding: 4px 10px; font-size: 12px; font-weight: bold;")
            lay.addWidget(self_lbl)
        else:
            limit_btn = QPushButton("限速")
            limit_btn.setCursor(Qt.PointingHandCursor)
            limit_btn.setStyleSheet(theme.secondary_button())
            limit_btn.clicked.connect(lambda *_, d=dev: self._confirm_limit_device(d))
            lay.addWidget(limit_btn)

            block_btn = QPushButton("封禁")
            block_btn.setCursor(Qt.PointingHandCursor)
            block_btn.setStyleSheet(theme.danger_button(RADIUS_SMALL))
            block_btn.clicked.connect(lambda *_, d=dev: self._confirm_block_device(d))
            lay.addWidget(block_btn)

        self.dev_list_layout.insertWidget(self.dev_list_layout.count() - 1, row)

    def _rename_device(self, dev):
        """自定义设备名称（留空则恢复自动识别）"""
        mac = dev.get("mac", "").lower()
        current = self.cache.get_device_alias(mac)
        if current == "" and dev.get("name", "") != "未知设备":
            current = dev.get("name", "")
        text, ok = QInputDialog.getText(
            self, "重命名设备",
            "为该设备设置一个自定义名称（留空则恢复自动识别）：\n\n"
            f"IP：{dev.get('ip','')}\nMAC：{dev.get('mac','')}",
            QLineEdit.Normal, current)
        if not ok:
            return
        self.cache.save_device_alias(mac, text)
        self._refresh_devices_view()

    def _confirm_limit_device(self, dev):
        """限速操作：定位设备供用户在路由器 QoS 端处理"""
        name = self._device_display_name(dev)
        ret = QMessageBox.question(
            self, "确认限速",
            f"确定要对这台设备限速吗？\n\n设备：{name}\nIP：{dev.get('ip','')}\nMAC：{dev.get('mac','')}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        # 本工具不做路由篡改，引导用户到路由器端操作（已复制 MAC 便于粘贴）
        try:
            QApplication.clipboard().setText(dev.get("mac", ""))
        except Exception:
            pass
        QMessageBox.information(
            self, "限速说明",
            "为安全起见，本工具不直接修改路由器配置。\n\n"
            f"该设备的 MAC 地址已复制：{dev.get('mac','')}\n\n"
            "请登录路由器管理页 → 限速/QoS 带宽控制 → 粘贴该 MAC 并设置限速即可。")

    def _confirm_block_device(self, dev):
        """封禁操作：定位设备供用户在路由器黑名单端处理"""
        name = self._device_display_name(dev)
        ret = QMessageBox.question(
            self, "确认封禁",
            f"确定要封禁这台设备吗？封禁后该设备将无法上网。\n\n设备：{name}\nIP：{dev.get('ip','')}\nMAC：{dev.get('mac','')}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        # 本工具不做路由篡改，引导用户到路由器端操作（已复制 MAC 便于粘贴）
        try:
            QApplication.clipboard().setText(dev.get("mac", ""))
        except Exception:
            pass
        QMessageBox.information(
            self, "封禁说明",
            "为安全起见，本工具不直接修改路由器配置。\n\n"
            f"该设备的 MAC 地址已复制：{dev.get('mac','')}\n\n"
            "请登录路由器管理页 → 设备管理/黑名单 → 粘贴该 MAC 并禁止其接入即可。")
