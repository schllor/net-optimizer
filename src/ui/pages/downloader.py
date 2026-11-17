"""多线程下载器页面：分片泳道、镜像源与加速设置，对应设计稿 screen-08。"""

import os
import time

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QLabel, QLineEdit,
    QProgressBar, QPushButton, QSizePolicy, QWidget,
)

import core.theme as theme
from core.downloader import Downloader, validate_url
from core.paths import get_data_dir
from ui import icons
from ui.kit import (
    AreaChart, Bar, Card, LaneChart, Pill, ProgressRing, Switch, ghost_button,
    hbox, hline, ic, lbl, mono, page_head, primary_button, vbox,
)
from ui.responsive import ResponsiveColumns
from ui.workers import DownloadWorker

_EMPTY = "未开始下载"


class DownloaderPageMixin:
    """下载器页：多源加速、进度/速率与暂停续传。"""

    def _create_downloader_page(self):
        """创建多线程下载器页面"""
        self.downloader_page = QWidget()
        self._dl = None          # 当前 Downloader
        self._dl_worker = None   # DownloadWorker
        self._dl_timer = None    # 进度刷新定时器
        self._prev_done = 0.0
        self._prev_t = 0.0
        self._activity_at = 0.0   # 最近一次有实际下载进展的时间点（用于卡住提示）
        self._dl_ema = None       # 实时速率 EMA 平滑值（借鉴 PCL-CE 基于真实字节数平滑测速）

        layout = vbox(14, (0, 0, 0, 0), self.downloader_page)

        conns = self._dl_conns()
        self.dl_open_btn = ghost_button("打开文件夹")
        self.dl_open_btn.clicked.connect(self._open_download_dir)
        new_task = primary_button("新建任务")
        new_task.clicked.connect(self._dl_new_task)
        self.dl_head = page_head(
            "DOWNLOAD / SEGMENTED",
            "多线程，把带宽用满。",
            "镜像自动探测，支持断点续传；下载过程与结果都来自真实任务。",
            [self.dl_open_btn, new_task])
        layout.addWidget(self.dl_head)

        # ---- 地址栏：URL + 保存目录 + 开始下载 ----
        bar = QFrame()
        bar.setStyleSheet(
            f"QFrame#dlBar {{ border: 1px solid {theme.LINE}; border-radius: 10px;"
            f" background-color: {theme.INSET}; }}")
        bar.setObjectName("dlBar")
        bar.setFixedHeight(42)
        bar_layout = hbox(8, (13, 6, 6, 6), bar)
        bar_layout.addWidget(ic("globe", 13, theme.TEXT_3))

        self.dl_url_edit = QLineEdit()
        self.dl_url_edit.setPlaceholderText(
            "粘贴 http/https 下载链接，如 https://example.com/file.zip")
        self.dl_url_edit.setToolTip("粘贴 http/https 下载链接，会自动分段并发加速")
        self.dl_url_edit.setStyleSheet(
            "QLineEdit { background: transparent; border: none;"
            f" font-family: Consolas; font-size: {theme.text_size(10)}px;"
            f" color: {theme.TEXT_2}; padding: 0; }}"
            f"QLineEdit:focus {{ color: {theme.TEXT_MAIN}; }}")
        bar_layout.addWidget(self.dl_url_edit, 1)

        folder = QFrame()
        folder.setStyleSheet(
            f"QFrame#dlFolder {{ border-left: 1px solid {theme.LINE};"
            f" border-right: 1px solid {theme.LINE}; background: transparent; }}")
        folder.setObjectName("dlFolder")
        folder_layout = hbox(6, (10, 0, 10, 0), folder)
        folder_layout.addWidget(ic("folder", 11, theme.TEXT_4))
        self.dl_dir_edit = QLineEdit()
        self.dl_dir_edit.setReadOnly(True)
        self.dl_dir_edit.setFixedWidth(86)
        self.dl_dir_edit.setCursor(Qt.PointingHandCursor)
        self.dl_dir_edit.setToolTip("点击更换保存文件夹")
        self.dl_dir_edit.setStyleSheet(
            "QLineEdit { background: transparent; border: none;"
            f" font-family: Consolas; font-size: {theme.text_size(9)}px;"
            f" color: {theme.TEXT_3}; padding: 0; }}")
        self.dl_dir_edit.mousePressEvent = (
            lambda event: self._choose_download_dir())
        folder_layout.addWidget(self.dl_dir_edit)
        bar_layout.addWidget(folder)

        self.dl_start_btn = primary_button("开始下载")
        self.dl_start_btn.clicked.connect(self._start_download)
        bar_layout.addWidget(self.dl_start_btn)

        self.dl_settings_btn = QPushButton("⚙")
        self.dl_settings_btn.setFixedSize(32, 32)
        self.dl_settings_btn.setCursor(Qt.PointingHandCursor)
        self.dl_settings_btn.setToolTip("下载设置：进入设置页调整最大并发连接数")
        self.dl_settings_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.TEXT_2};"
            f" border: 1px solid {theme.LINE}; border-radius: 7px;"
            ' font-family: "Segoe UI Symbol"; font-size: 13px; padding: 0; }'
            f"QPushButton:hover {{ border-color: {theme.LINE_STRONG};"
            f" color: {theme.TEXT_MAIN}; }}")
        self.dl_settings_btn.clicked.connect(lambda: self._switch_page("settings"))
        bar_layout.addWidget(self.dl_settings_btn)
        layout.addWidget(bar, 0)

        body = ResponsiveColumns(left_stretch=16, right_stretch=10)
        layout.addWidget(body, 1)

        # ================= 左列：下载进度 + 队列 =================
        left = body.left

        progress_card = Card(16, 0)
        head = hbox(12, (0, 0, 0, 14))
        self.dl_status = lbl("正在下载", 11, theme.TEXT_MAIN, 600)
        self.dl_status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        head.addWidget(self.dl_status, 1)
        self.dl_speed_pill = Pill("-- MB/s", "dim", None, small=True)
        head.addWidget(self.dl_speed_pill)
        progress_card.body.addLayout(head)

        info_row = hbox(18, (0, 0, 0, 0))
        info_row.setAlignment(Qt.AlignVCenter)
        self.dl_ring = ProgressRing(104, 0)
        info_row.addWidget(self.dl_ring, 0, Qt.AlignVCenter)

        info = vbox(0, (0, 0, 0, 0))
        self.dl_file_label = lbl(_EMPTY, 12, theme.TEXT_MAIN, 600)
        self.dl_file_label.setMinimumWidth(0)
        info.addWidget(self.dl_file_label)

        self.dl_meta = mono(
            f"-- / -- · 剩余 --:-- · {conns} 线程", 9, theme.TEXT_3)
        self.dl_meta.setContentsMargins(0, 6, 0, 0)
        info.addWidget(self.dl_meta)

        self.dl_bar = Bar(0.0, theme.PAPER, 5)
        self.dl_bar.setContentsMargins(0, 12, 0, 0)
        info.addWidget(self.dl_bar)

        transfer = hbox(8, (0, 8, 0, 0))
        self.dl_done_label = mono("已下载 --", 8, theme.TEXT_4)
        self.dl_speed_label = mono("-- MB/s", 8, theme.MINT)
        transfer.addWidget(self.dl_done_label)
        transfer.addStretch()
        transfer.addWidget(self.dl_speed_label)
        info.addLayout(transfer)
        info_row.addLayout(info, 1)

        controls = hbox(6, (0, 0, 0, 0))
        self.dl_pause_btn = self._dl_icon_button("pause", "暂停 / 继续")
        self.dl_pause_btn.clicked.connect(self._toggle_pause)
        self.dl_cancel_btn = self._dl_icon_button("x", "取消下载")
        self.dl_cancel_btn.clicked.connect(self._cancel_download)
        self.dl_pause_btn.setEnabled(False)
        self.dl_cancel_btn.setEnabled(False)
        controls.addWidget(self.dl_pause_btn)
        controls.addWidget(self.dl_cancel_btn)
        info_row.addLayout(controls)
        progress_card.body.addLayout(info_row)

        progress_card.body.addSpacing(15)
        progress_card.body.addWidget(hline())
        progress_card.body.addSpacing(15)

        chunk_head = hbox(12, (0, 0, 0, 9))
        chunk_head.addWidget(lbl("分片进度", 9, theme.TEXT_3, 400, True, 1.0))
        chunk_head.addStretch()
        self.dl_lanes_note = lbl(f"{conns} 线程 · 自动分片", 9,
                                 theme.TEXT_3, 400, True, 0.8)
        chunk_head.addWidget(self.dl_lanes_note)
        progress_card.body.addLayout(chunk_head)

        self.dl_lanes = LaneChart(8, 40, 0)
        progress_card.body.addWidget(self.dl_lanes)

        legend = hbox(6, (0, 11, 0, 0))
        legend.addWidget(self._dl_legend("已完成分片", theme.MINT))
        legend.addStretch()
        legend.addWidget(self._dl_legend("正在写入", theme.PAPER))
        legend.addStretch()
        legend.addWidget(lbl("未分配", 8, theme.TEXT_4, 400, True))
        progress_card.body.addLayout(legend)

        # 保留原有 QProgressBar 属性（离屏 / 自动化兼容），界面用上面的 Bar 呈现
        self.dl_progress = QProgressBar()
        self.dl_progress.setRange(0, 1000)
        self.dl_progress.setValue(0)
        self.dl_progress.hide()
        progress_card.body.addWidget(self.dl_progress)
        left.addWidget(progress_card, 1)

        queue_card = Card(16, 0)
        queue_card.head("下载队列", "单任务")
        queue_card.body.addSpacing(10)
        self.dl_queue_hint = lbl(
            "当前版本一次处理一个下载任务。\n粘贴新链接并点击「开始下载」即可替换当前任务；"
            "完成后可在保存目录中查看文件。",
            10, theme.TEXT_3, 400, False, 0, wrap=True)
        queue_card.body.addWidget(self.dl_queue_hint)
        queue_card.body.addStretch()
        left.addWidget(queue_card)

        # ================= 右列：镜像源 + 实时速度 + 设置 =================
        right = body.right

        mirrors = Card(16, 0)
        mirrors.head("镜像源", "AUTO")
        mirrors.body.addSpacing(12)
        self.dl_mirror_note = lbl(
            "未开始下载。启用加速后，程序会在下载时探测镜像并选择较快的源。",
            10, theme.TEXT_3, 400, False, 0, wrap=True)
        mirrors.body.addWidget(self.dl_mirror_note)
        mirrors.body.addSpacing(10)
        hint_row = hbox(8, (10, 8, 10, 8))
        hint_row.addWidget(ic("check", 12, theme.MINT))
        self.dl_mirror_status = lbl("等待下载任务", 10, theme.TEXT_2)
        hint_row.addWidget(self.dl_mirror_status)
        hint_row.addStretch()
        hint = QFrame()
        hint.setLayout(hint_row)
        hint.setStyleSheet(
            f"QFrame {{ border: 1px solid {theme.LINE}; border-radius: 8px;"
            " background: transparent; }")
        mirrors.body.addWidget(hint)
        right.addWidget(mirrors)

        speed = Card(16, 0)
        speed_head = hbox(12, (0, 0, 0, 14))
        speed_head.addWidget(lbl("实时速度", 11, theme.TEXT_MAIN, 600))
        speed_head.addStretch()
        speed_head.addWidget(lbl("60 S", 9, theme.TEXT_3, 400, True, 0.8))
        speed.body.addLayout(speed_head)
        self.dl_chart = AreaChart([])
        speed.body.addWidget(self.dl_chart, 1)
        chart_foot = hbox(8, (0, 6, 0, 0))
        self.dl_chart_speed = mono("-- MB/s", 9, theme.TEXT_3)
        chart_foot.addWidget(self.dl_chart_speed)
        chart_foot.addStretch()
        self.dl_peak_label = mono("峰值 --", 9, theme.TEXT_3)
        chart_foot.addWidget(self.dl_peak_label)
        speed.body.addLayout(chart_foot)
        right.addWidget(speed, 1)

        settings = Card(16, 0)
        settings.head("加速设置", "SAVED")
        settings.body.addSpacing(14)
        settings.body.addWidget(self._dl_setting_row(
            "并发线程", self._dl_conn_select(conns), top_border=False))
        settings.body.addWidget(self._dl_setting_row(
            "分片方式", mono("自动", 10, theme.TEXT_MAIN), top_border=True))
        self.dl_resume_switch = Switch(True)
        self.dl_resume_switch.setToolTip("断点续传始终启用")
        settings.body.addWidget(self._dl_setting_row(
            "断点续传", self.dl_resume_switch, top_border=True))
        right.addWidget(settings)

        # 保留原控件（镜像加速勾选决定 Downloader 的多源策略）
        self.dl_accel_on = QCheckBox()
        self.dl_accel_on.setChecked(True)
        self.dl_accel_on.hide()

        self._dl_speed_hist = []
        self._dl_peak = 0.0

        self.dl_dir_edit.setText(self._default_dir())
        self._dl_sync_dir_label()

    # ---------------------------------------------------------------- 组件
    @staticmethod
    def _dl_icon_button(icon_name, tip):
        button = QPushButton()
        button.setFixedSize(32, 32)
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip(tip)
        button.setIcon(icons.pixmap(icon_name, 13, theme.TEXT_3, 1.6))
        button.setIconSize(QSize(13, 13))
        button.setStyleSheet(
            f"QPushButton {{ background: transparent; color: transparent;"
            f" border: 1px solid {theme.LINE}; border-radius: 7px; padding: 0; }}"
            f"QPushButton:hover {{ border-color: {theme.LINE_STRONG}; }}"
            "QPushButton:disabled { border-color: "
            f"{theme.LINE}; }}")
        return button

    @staticmethod
    def _dl_legend(text, color):
        row = QWidget()
        layout = hbox(6, (0, 0, 0, 0), row)
        swatch = QLabel()
        swatch.setFixedSize(7, 7)
        swatch.setStyleSheet(
            f"background-color: {color}; border-radius: 1px;")
        layout.addWidget(swatch)
        layout.addWidget(lbl(text, 8, theme.TEXT_4, 400, True))
        return row

    @staticmethod
    def _dl_mirror_row(name, value, ratio, value_color=theme.MINT,
                       top_border=False, top_pad=8, bottom_pad=8):
        row = QWidget()
        layout = vbox(0, (0, 0, 0, 0), row)
        if top_border:
            layout.addWidget(hline())
        inner = vbox(0, (0, top_pad, 0, bottom_pad))
        top = hbox(10, (0, 0, 0, 0))
        top.addWidget(lbl(name, 9, theme.TEXT_MAIN))
        top.addStretch()
        top.addWidget(lbl(value, 9, value_color, 400, True))
        inner.addLayout(top)
        bar = Bar(ratio, theme.PAPER, 4)
        bar.setContentsMargins(0, 6, 0, 0)
        inner.addWidget(bar)
        layout.addLayout(inner)
        return row

    @staticmethod
    def _dl_setting_row(key, control, top_border=False):
        row = QWidget()
        layout = vbox(0, (0, 0, 0, 0), row)
        if top_border:
            layout.addWidget(hline())
        inner = hbox(10, (0, 7, 0, 7))
        inner.addWidget(lbl(key, 9, theme.TEXT_3))
        inner.addStretch()
        inner.addWidget(control)
        layout.addLayout(inner)
        return row

    def _dl_conn_select(self, current):
        select = QComboBox()
        select.setFixedSize(46, 22)
        select.setCursor(Qt.PointingHandCursor)
        select.setToolTip("调整并发线程数")
        select.addItems(["1", "4", "8", "12", "16"])
        value = str(current if current in (1, 4, 8, 12, 16) else 8)
        select.setCurrentText(value)
        select.setStyleSheet(
            "QComboBox { background: transparent; border: none; padding: 0;"
            f" font-family: Consolas; font-size: {theme.text_size(9)}px;"
            f" color: {theme.TEXT_MAIN}; }}"
            "QComboBox::drop-down { width: 0px; border: none; }"
            "QComboBox QAbstractItemView {"
            f" background-color: {theme.BG_CARD}; color: {theme.TEXT_MAIN};"
            f" border: 1px solid {theme.LINE};"
            " selection-background-color: #17171a;"
            f" font-family: Consolas; font-size: {theme.text_size(9)}px; }}")
        select.currentTextChanged.connect(self._dl_conn_changed)
        return select

    def _dl_conn_changed(self, text):
        try:
            value = max(1, min(16, int(text)))
        except (TypeError, ValueError):
            return
        self.settings.update({"download_connections": value})
        self._set_status(f"并发线程数已设为 {value}")

    def _dl_conns(self):
        try:
            conns = int(self.settings.get("download_connections", 8))
        except (TypeError, ValueError):
            conns = 8
        return max(1, min(16, conns))

    def _dl_sync_dir_label(self):
        path = self.dl_dir_edit.text().strip() or self._default_dir()
        name = os.path.basename(path.rstrip("\\/")) or path
        self.dl_dir_edit.setText(name)
        self.dl_dir_edit.setToolTip(f"保存到：{path}（点击更换文件夹）")

    def _dl_new_task(self):
        """清空地址并聚焦输入，准备新任务。"""
        if self._dl_worker is not None and self._dl_worker.isRunning():
            self._set_status("当前已有下载任务进行中")
            return
        self.dl_url_edit.clear()
        self.dl_url_edit.setFocus()
        self.dl_status.setText("新建任务")
        self.dl_file_label.setText(_EMPTY)
        self.dl_meta.setText("-- / -- · 剩余 --:--")
        self.dl_ring.set_percent(0)
        self.dl_bar.set_ratio(0)
        self.dl_lanes.set_progress(0)
        self.dl_speed_pill.setText("-- MB/s")
        self.dl_done_label.setText("已下载 --")
        self.dl_speed_label.setText("-- MB/s")
        self.dl_chart_speed.setText("-- MB/s")
        try:
            self._dl_speed_hist = []
            self._dl_peak = 0.0
            self.dl_chart.set_series([])
            self.dl_peak_label.setText("峰值 --")
            self.dl_mirror_status.setText("等待下载任务")
            self.dl_mirror_note.setText(
                "未开始下载。启用加速后，程序会在下载时探测镜像并选择较快的源。")
        except Exception:
            pass

    # ---------------------------------------------------------------- 目录
    def _choose_download_dir(self):
        default = self.settings.get("download_dir", "") or get_data_dir()
        d = QFileDialog.getExistingDirectory(self, "选择保存文件夹", default)
        if d:
            self._prev_done = 0.0
            self.settings.update({"download_dir": d})
            self.dl_dir_edit.setText(d)
            self._dl_sync_dir_label()

    def _default_dir(self):
        configured = (self.settings.get("download_dir", "") or "").strip()
        if configured:
            try:
                os.makedirs(configured, exist_ok=True)
                return configured
            except OSError:
                pass
        d = os.path.join(get_data_dir(), "downloads")
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        return d

    def _open_download_dir(self):
        """用资源管理器打开当前文件所在目录（没开始下载时打开默认保存目录）"""
        target = None
        d = self._dl
        if d is not None and getattr(d, "filepath", ""):
            parent = os.path.dirname(d.filepath)
            if os.path.isdir(parent):
                target = parent
        if not target:
            configured = (self.settings.get("download_dir", "") or "").strip()
            target = configured or self._default_dir()
        try:
            os.makedirs(target, exist_ok=True)
            if os.name == "nt":
                os.startfile(target)   # type: ignore[attr-defined]
            else:
                self._set_status("仅支持 Windows 打开文件夹")
        except Exception as e:
            self._set_status(f"无法打开文件夹：{e}")

    # ---------------------------------------------------------------- 格式化
    def _fmt_size(self, n):
        try:
            n = max(0, int(n))
        except Exception:
            return "--"
        if n >= 1024 ** 3:
            return f"{n / 1024 ** 3:.1f} GB"
        if n >= 1024 ** 2:
            return f"{n / 1024 ** 2:.1f} MB"
        if n >= 1024:
            return f"{n / 1024:.1f} KB"
        return f"{n} B"

    def _fmt_dl_speed(self, bps):
        try:
            bps = max(0, int(bps))
        except Exception:
            return "--"
        return self._fmt_size(bps) + "/s"

    @staticmethod
    def _fmt_eta(seconds):
        try:
            seconds = max(0, int(seconds))
        except Exception:
            return "--:--"
        if seconds >= 3600:
            return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    # ---------------------------------------------------------------- 状态
    def _set_dl_controls(self, running):
        self.dl_start_btn.setEnabled(not running)
        self.dl_pause_btn.setEnabled(running)
        self.dl_cancel_btn.setEnabled(running)
        self.dl_url_edit.setEnabled(not running)
        self.dl_dir_edit.setEnabled(not running)
        if running:
            self.dl_pause_btn.setText("暂停")
            self.dl_pause_btn.setIcon(
                icons.pixmap("pause", 13, theme.TEXT_3, 1.6))

    def _start_download(self):
        if self._dl_worker is not None and self._dl_worker.isRunning():
            self._set_status("当前已有下载任务进行中")
            return
        url = self.dl_url_edit.text().strip()
        err = validate_url(url)
        if err:
            self.dl_status.setText(f"{err}")
            self.dl_status.setStyleSheet(
                f"color: {theme.ERROR}; background: transparent;")
            return
        save_dir = self._dl_save_dir()
        try:
            os.makedirs(save_dir, exist_ok=True)
        except Exception as e:
            self.dl_status.setText(f"无法创建保存文件夹：{e}")
            return

        conns = self._dl_conns()
        self._dl = Downloader(
            url, save_dir, max_workers=conns,
            mirror=self.dl_accel_on.isChecked())
        self._dl_worker = DownloadWorker(self._dl, self)
        self._dl_worker.done.connect(self._on_dl_worker_done)

        self._dl_speed_hist = []
        self._dl_peak = 0.0
        try:
            self.dl_chart.set_series([])
            self.dl_peak_label.setText("峰值 --")
            self.dl_lanes_note.setText(f"{conns} 线程 · 自动分片")
            self.dl_mirror_note.setText("正在探测镜像并按实测速度选择来源…")
            self.dl_mirror_status.setText("探测中")
        except Exception:
            pass
        self._set_dl_controls(True)
        self._begin_task("download")
        self._prev_done = 0.0
        self._prev_t = time.time()
        self._activity_at = time.time()
        self._dl_ema = None
        self.dl_progress.setValue(0)
        self.dl_ring.set_percent(0)
        self.dl_bar.set_ratio(0)
        self.dl_lanes.set_progress(0)
        self.dl_speed_pill.setText("连接中")
        self.dl_status.setText("正在连接下载地址…")
        self.dl_status.setStyleSheet(
            f"color: {theme.TEXT_MAIN}; background: transparent;")
        self.dl_file_label.setText("正在获取文件信息…")
        self.dl_meta.setText("-- / -- · 剩余 --:--")
        self.dl_done_label.setText("已下载 --")
        self.dl_speed_label.setText("-- MB/s")
        self.dl_chart_speed.setText("-- MB/s")

        if self._dl_timer is None:
            self._dl_timer = QTimer(self)
            self._dl_timer.setInterval(200)
            self._dl_timer.timeout.connect(self._tick_download)
        self._dl_timer.start()
        self._set_status("开始下载")
        self._dl_worker.start()

    def _dl_save_dir(self):
        """地址栏只显示目录名，真实路径来自设置 / 默认目录。"""
        configured = (self.settings.get("download_dir", "") or "").strip()
        return configured or self._default_dir()

    def _tick_download(self):
        d = self._dl
        if d is None:
            return
        now = time.time()
        done = d.done_bytes
        total = d.total_size
        dt = now - self._prev_t
        inst = (done - self._prev_done) / dt if dt > 0 and done >= self._prev_done else 0.0
        # 瞬时速率做 EMA 平滑，避免 0~峰值来回跳（借鉴 PCL-CE 基于真实字节数平滑测速）
        if self._dl_ema is None:
            self._dl_ema = inst
        else:
            self._dl_ema = 0.6 * self._dl_ema + 0.4 * inst
        speed = self._dl_ema
        self._prev_done = done
        self._prev_t = now
        if inst > 0:
            self._activity_at = now

        percent = d.percent if total > 0 else 0.0
        if total > 0:
            self._update_task("download", d.percent)
            self.dl_progress.setValue(int(round(d.percent * 10)))
        else:
            self.dl_progress.setValue(0)

        self.dl_ring.set_percent(int(round(percent)))
        self.dl_bar.set_ratio(percent / 100.0)
        self.dl_lanes.set_progress(int(round(percent)))

        remaining = ((total - done) / speed) if total > 0 and speed > 0 else 0
        workers = getattr(d, "active_workers", 0)
        name = getattr(d, "filename", None) or "download.bin"
        self.dl_file_label.setText(name)
        self.dl_meta.setText(
            f"{self._fmt_size(done)} / {self._fmt_size(total)}"
            f" · 剩余 {self._fmt_eta(remaining)} · {workers} 线程")
        self.dl_done_label.setText(f"已下载 {self._fmt_size(done)}")
        speed_text = self._fmt_dl_speed(speed)
        self.dl_speed_label.setText(speed_text)
        self.dl_speed_pill.setText(speed_text)
        self.dl_chart_speed.setText(speed_text)

        # 真实速度曲线：以字节/秒记录，按本次峰值归一化
        try:
            self._dl_speed_hist.append(max(0.0, float(speed)))
            if len(self._dl_speed_hist) > 60:
                self._dl_speed_hist = self._dl_speed_hist[-60:]
            peak = max(self._dl_speed_hist + [1.0])
            self._dl_peak = max(self._dl_peak, float(speed))
            self.dl_chart.set_series(
                [min(1.0, value / peak) for value in self._dl_speed_hist])
            self.dl_peak_label.setText(
                f"峰值 {self._fmt_dl_speed(self._dl_peak)}")
            if getattr(d, "mirror_used", False):
                source = getattr(d, "mirror_source", "") or "镜像"
                self.dl_mirror_status.setText("加速已启用")
                self.dl_mirror_note.setText(f"当前来源：{source}")
            else:
                self.dl_mirror_status.setText("直连下载")
                self.dl_mirror_note.setText(
                    "当前未走镜像；如速度不理想，可检查链接是否支持镜像。")
        except Exception:
            pass

        if d.completed:
            self.dl_status.setText("下载完成")
            self.dl_status.setStyleSheet(
                f"color: {theme.MINT}; background: transparent;")
            self.dl_progress.setValue(1000)
            self.dl_ring.set_percent(100)
            self.dl_bar.set_ratio(1.0)
            self.dl_lanes.set_progress(100)
            self.dl_speed_pill.setText("完成")
            self._set_dl_controls(False)
        elif d.error:
            self.dl_status.setText(f"{d.error}")
            self.dl_status.setStyleSheet(
                f"color: {theme.WARNING}; background: transparent;")
            self.dl_pause_btn.setEnabled(False)
            self.dl_cancel_btn.setEnabled(False)
        elif d.is_cancelled():
            self.dl_status.setText("下载已取消")
            self.dl_status.setStyleSheet(
                f"color: {theme.TEXT_2}; background: transparent;")
            self._set_dl_controls(False)
        elif d.is_paused():
            self.dl_status.setText("已暂停（点击「继续」恢复）")
            self.dl_status.setStyleSheet(
                f"color: {theme.WARNING}; background: transparent;")
        else:
            stall = now - self._activity_at
            if stall >= 15:
                self.dl_status.setText("已较长时间无进展，可能服务器已断开连接")
                self.dl_status.setStyleSheet(
                    f"color: {theme.ERROR}; background: transparent;")
            elif stall > 2.5:
                self.dl_status.setText(
                    f"网络波动，正在重连/重试（已自动重试 {d.retries} 次）…")
                self.dl_status.setStyleSheet(
                    f"color: {theme.WARNING}; background: transparent;")
            else:
                text = "正在下载"
                if getattr(d, "mirror_used", False):
                    src = getattr(d, "mirror_source", "") or ""
                    host = src.split("//")[-1].split("/")[0] if "//" in src else src
                    text = f"镜像加速：{host}"
                self.dl_status.setText(text)
                self.dl_status.setStyleSheet(
                    f"color: {theme.TEXT_MAIN}; background: transparent;")
            if not self.dl_pause_btn.isEnabled():
                self.dl_pause_btn.setEnabled(True)
                self.dl_cancel_btn.setEnabled(True)

    def _on_dl_worker_done(self, _result=None):
        self._on_dl_finished()

    def _on_dl_finished(self):
        # 线程已结束，做一次最终状态收尾
        self._end_task("download")
        d = self._dl
        if self._dl_timer is not None:
            self._dl_timer.stop()
        self._set_dl_controls(False)
        self.dl_start_btn.setText("开始下载")
        if d is None:
            return
        if d.completed:
            self.dl_status.setText("下载完成")
            self.dl_status.setStyleSheet(
                f"color: {theme.MINT}; background: transparent;")
            self.dl_progress.setValue(1000)
            self.dl_ring.set_percent(100)
            self.dl_bar.set_ratio(1.0)
            self.dl_lanes.set_progress(100)
            self.dl_speed_pill.setText("完成")
            if getattr(d, "mirror_used", False):
                src = getattr(d, "mirror_source", "") or ""
                host = src.split("//")[-1].split("/")[0] if "//" in src else src
                self.dl_meta.setText(f"已保存到：{d.filepath}（镜像 {host}）")
            else:
                self.dl_meta.setText(f"已保存到：{d.filepath}")
            self._set_status(f"下载完成：{d.filename}")
        elif d.error:
            # 探测失败（从未开始下载）时不宜提示"续传"，语义更准确的提示如下
            if getattr(d, "probed", False):
                self.dl_status.setText(f"{d.error}（可重新点击「开始下载」续传）")
            else:
                self.dl_status.setText(f"{d.error}")
            self.dl_status.setStyleSheet(
                f"color: {theme.WARNING}; background: transparent;")
        elif d.is_cancelled():
            self.dl_status.setText("下载已取消")
            self.dl_status.setStyleSheet(
                f"color: {theme.TEXT_2}; background: transparent;")

    def _toggle_pause(self):
        d = self._dl
        if d is None:
            return
        if d.is_paused():
            d.resume()
            self._resume_task("download")
            self.dl_pause_btn.setText("暂停")
            self.dl_pause_btn.setIcon(icons.pixmap("pause", 13, theme.TEXT_3, 1.6))
            self._set_status("已继续下载")
        else:
            d.pause()
            self._pause_task("download")
            self.dl_pause_btn.setText("继续")
            self.dl_pause_btn.setIcon(icons.pixmap("play", 13, theme.TEXT_3, 1.6))
            self._set_status("已暂停下载")

    def _cancel_download(self):
        d = self._dl
        if d is None:
            return
        d.cancel()
        self.dl_cancel_btn.setEnabled(False)
        self._set_status("正在取消下载...")
