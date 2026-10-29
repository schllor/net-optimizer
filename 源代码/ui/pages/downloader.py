"""多线程下载器页面。"""

import os
import time

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QCheckBox, QFileDialog, QProgressBar,
)
from PySide6.QtCore import Qt, QTimer

import core.theme as theme
from core.downloader import Downloader, validate_url
from core.paths import get_data_dir
from ui.common import Colors
from ui.workers import DownloadWorker


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

        layout = QVBoxLayout(self.downloader_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        # ---- 卡片一：输入区 ----
        card = self._create_card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(25, 18, 25, 18)
        cl.setSpacing(12)

        url_lbl = QLabel("下载地址")
        url_lbl.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {Colors.TEXT_MAIN};")
        cl.addWidget(url_lbl)

        self.dl_url_edit = QLineEdit()
        self.dl_url_edit.setPlaceholderText("粘贴 http/https 下载链接，如 https://example.com/file.zip（会自动分段并发加速）")
        self.dl_url_edit.setFixedHeight(40)
        self.dl_url_edit.setStyleSheet(f"""
            QLineEdit {{ background-color: {Colors.BG_INSET}; border: 1px solid {Colors.BORDER}; border-radius: 6px;
                padding: 0 14px; font-size: 13px; color: {Colors.TEXT_MAIN}; }}
            QLineEdit:focus {{ border: 1px solid {theme.FOCUS}; }}
        """)
        cl.addWidget(self.dl_url_edit)

        dir_row = QHBoxLayout()
        dir_row.setSpacing(10)
        self.dl_dir_edit = QLineEdit()
        self.dl_dir_edit.setPlaceholderText("保存到软件的 download 文件夹（可点击右侧按钮修改）")
        self.dl_dir_edit.setFixedHeight(40)
        self.dl_dir_edit.setReadOnly(True)
        self.dl_dir_edit.setStyleSheet(f"""
            QLineEdit {{ background-color: {Colors.BG_INSET}; border: 1px solid {Colors.BORDER}; border-radius: 6px;
                padding: 0 14px; font-size: 13px; color: {Colors.TEXT_SECONDARY}; }}
        """)
        dir_row.addWidget(self.dl_dir_edit, 1)
        dir_btn = QPushButton("选择文件夹")
        dir_btn.setFixedHeight(40)
        dir_btn.setCursor(Qt.PointingHandCursor)
        dir_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {Colors.PRIMARY}; color: {Colors.TEXT_ON_ACCENT}; border: 1px solid {Colors.BORDER}; border-radius: 6px;
                font-size: 13px; font-weight: bold; padding: 0 18px; }}
            QPushButton:hover {{ background-color: {Colors.PRIMARY_DARK}; }}
        """)
        dir_btn.clicked.connect(self._choose_download_dir)
        dir_row.addWidget(dir_btn)
        cl.addLayout(dir_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.dl_start_btn = QPushButton("开始下载")
        self.dl_start_btn.setFixedHeight(42)
        self.dl_start_btn.setCursor(Qt.PointingHandCursor)
        self.dl_start_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {Colors.PRIMARY}; color: {Colors.TEXT_ON_ACCENT}; border: 1px solid {Colors.BORDER}; border-radius: 6px;
                font-size: 14px; font-weight: bold; padding: 0 24px; }}
            QPushButton:hover {{ background-color: {Colors.PRIMARY_DARK}; }}
            QPushButton:disabled {{ background-color: {Colors.BG_INSET}; color: {Colors.TEXT_LIGHT}; }}
        """)
        self.dl_start_btn.clicked.connect(self._start_download)
        btn_row.addWidget(self.dl_start_btn)

        self.dl_pause_btn = QPushButton("暂停")
        self.dl_pause_btn.setFixedHeight(42)
        self.dl_pause_btn.setEnabled(False)
        self.dl_pause_btn.setCursor(Qt.PointingHandCursor)
        self.dl_pause_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {Colors.BG_RAISED}; color: {Colors.TEXT_MAIN}; border: none; border-radius: 8px;
                font-size: 14px; font-weight: bold; padding: 0 24px; }}
            QPushButton:hover {{ background-color: {Colors.BORDER}; }}
            QPushButton:disabled {{ background-color: {Colors.BG_INSET}; color: {Colors.TEXT_LIGHT}; }}
        """)
        self.dl_pause_btn.clicked.connect(self._toggle_pause)
        btn_row.addWidget(self.dl_pause_btn)

        self.dl_cancel_btn = QPushButton("取消")
        self.dl_cancel_btn.setFixedHeight(42)
        self.dl_cancel_btn.setEnabled(False)
        self.dl_cancel_btn.setCursor(Qt.PointingHandCursor)
        self.dl_cancel_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {Colors.ERROR}; color: {Colors.TEXT_WHITE}; border: 1px solid {Colors.BORDER}; border-radius: 6px;
                font-size: 14px; font-weight: bold; padding: 0 24px; }}
            QPushButton:hover {{ background-color: #cf6262; }}
            QPushButton:disabled {{ background-color: {Colors.BG_INSET}; color: {Colors.TEXT_LIGHT}; }}
        """)
        self.dl_cancel_btn.clicked.connect(self._cancel_download)
        btn_row.addWidget(self.dl_cancel_btn)

        hint = QLabel("小提示：支持断点续传，中断后可重新点击「开始下载」继续；多个分块并发下载会比单线程更快。")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size: 12px; color: {Colors.TEXT_SECONDARY};")

        self.dl_accel_on = QCheckBox("国内镜像加速")
        self.dl_accel_on.setChecked(True)
        self.dl_accel_on.setCursor(Qt.PointingHandCursor)
        self.dl_accel_on.setToolTip("勾选后，遇到 GitHub 等国外源会自动探测并选择最快的国内镜像；国内直链不受影响")
        self.dl_accel_on.setStyleSheet(f"font-size: 12px; color: {Colors.TEXT_SECONDARY};")
        btn_row.addWidget(self.dl_accel_on)

        btn_row.addWidget(hint, 1)
        cl.addLayout(btn_row)
        layout.addWidget(card)

        # ---- 卡片二：进度区 ----
        pcard = self._create_card()
        pl = QVBoxLayout(pcard)
        pl.setContentsMargins(25, 18, 25, 18)
        pl.setSpacing(12)

        self.dl_progress = QProgressBar()
        self.dl_progress.setRange(0, 1000)
        self.dl_progress.setValue(0)
        self.dl_progress.setFixedHeight(22)
        self.dl_progress.setStyleSheet(f"""
            QProgressBar {{ background-color: {Colors.BG_INSET}; border: none; border-radius: 6px;
                text-align: center; font-size: 12px; color: {Colors.TEXT_MAIN}; }}
            QProgressBar::chunk {{ background-color: {Colors.PRIMARY}; border-radius: 6px; }}
        """)
        pl.addWidget(self.dl_progress)

        self.dl_status = QLabel("就绪：填好下载地址和保存位置，点击「开始下载」")
        self.dl_status.setWordWrap(True)
        self.dl_status.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {Colors.TEXT_MAIN};")
        pl.addWidget(self.dl_status)

        self.dl_meta = QLabel("进度 0%")
        self.dl_meta.setStyleSheet(f"font-size: 12px; color: {Colors.TEXT_SECONDARY};")

        meta_row = QHBoxLayout()
        meta_row.setSpacing(10)
        meta_row.addWidget(self.dl_meta, 1)
        self.dl_open_btn = QPushButton("打开文件夹")
        self.dl_open_btn.setFixedHeight(34)
        self.dl_open_btn.setCursor(Qt.PointingHandCursor)
        self.dl_open_btn.setToolTip("用资源管理器打开文件所在目录")
        self.dl_open_btn.setStyleSheet(f"""
            QPushButton {{ background-color: transparent; color: {Colors.PRIMARY};
                border: 1px solid {Colors.PRIMARY}; border-radius: 8px;
                font-size: 12px; font-weight: bold; padding: 0 14px; }}
            QPushButton:hover {{ background-color: {Colors.PRIMARY_LIGHT}; }}
        """)
        self.dl_open_btn.clicked.connect(self._open_download_dir)
        meta_row.addWidget(self.dl_open_btn)
        pl.addLayout(meta_row)

        layout.addWidget(pcard)
        layout.addStretch()

        # 默认保存目录（首次进入预填）
        self.dl_dir_edit.setText(self._default_dir())

    def _choose_download_dir(self):
        default = self.dl_dir_edit.text() or get_data_dir()
        d = QFileDialog.getExistingDirectory(self, "选择保存文件夹", default)
        if d:
            self._prev_done = 0.0
            self.dl_dir_edit.setText(d)

    def _default_dir(self):
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
        if d is not None and d.filepath:
            parent = os.path.dirname(d.filepath)
            if os.path.isdir(parent):
                target = parent
        if not target:
            target = self.dl_dir_edit.text().strip() or self._default_dir()
        try:
            os.makedirs(target, exist_ok=True)
            if os.name == "nt":
                os.startfile(target)   # type: ignore[attr-defined]
            else:
                self._set_status("仅支持 Windows 打开文件夹")
        except Exception as e:
            self._set_status(f"无法打开文件夹：{e}")

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

    def _set_dl_controls(self, running):
        self.dl_start_btn.setEnabled(not running)
        self.dl_pause_btn.setEnabled(running)
        self.dl_cancel_btn.setEnabled(running)
        self.dl_url_edit.setEnabled(not running)
        self.dl_dir_edit.setEnabled(not running)
        if running:
            self.dl_pause_btn.setText("暂停")

    def _start_download(self):
        if self._dl_worker is not None and self._dl_worker.isRunning():
            self._set_status("当前已有下载任务进行中")
            return
        url = self.dl_url_edit.text().strip()
        err = validate_url(url)
        if err:
            self.dl_status.setText(f"{err}")
            self.dl_status.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {Colors.ERROR};")
            return
        save_dir = self.dl_dir_edit.text().strip() or self._default_dir()
        try:
            os.makedirs(save_dir, exist_ok=True)
        except Exception as e:
            self.dl_status.setText(f"无法创建保存文件夹：{e}")
            return

        self._dl = Downloader(url, save_dir, mirror=self.dl_accel_on.isChecked())   # 并发取 core 内 MAX_WORKERS；国内镜像由 mirror 开关决定
        self._dl_worker = DownloadWorker(self._dl, self)
        self._dl_worker.finished.connect(self._on_dl_finished)

        self._set_dl_controls(True)
        self._begin_task("download")
        self._prev_done = 0.0
        self._prev_t = time.time()
        self._activity_at = time.time()
        self._dl_ema = None
        self.dl_progress.setValue(0)
        self.dl_status.setText("正在连接下载地址，获取文件信息...")
        self.dl_status.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {Colors.TEXT_MAIN};")
        self.dl_meta.setText("等待连接...")

        if self._dl_timer is None:
            self._dl_timer = QTimer(self)
            self._dl_timer.setInterval(200)
            self._dl_timer.timeout.connect(self._tick_download)
        self._dl_timer.start()
        self._set_status("开始下载")
        self._dl_worker.start()

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

        if total > 0:
            self._update_task("download", d.percent)
            self.dl_progress.setValue(int(round(d.percent * 10)))
        else:
            self.dl_progress.setValue(0)

        meta = f"已下载 {self._fmt_size(done)} / {self._fmt_size(total)}   |   {self._fmt_dl_speed(speed)}   |   {d.percent:.1f}%"
        self.dl_meta.setText(meta)

        if d.completed:
            self.dl_status.setText("下载完成")
            self.dl_status.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {Colors.SUCCESS};")
            self.dl_progress.setValue(1000)
            self._set_dl_controls(False)
        elif d.error:
            self.dl_status.setText(f"{d.error}")
            self.dl_status.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {Colors.WARNING};")
            self.dl_pause_btn.setEnabled(False)
            self.dl_cancel_btn.setEnabled(False)
        elif d.is_cancelled():
            self.dl_status.setText("下载已取消")
            self.dl_status.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {Colors.TEXT_SECONDARY};")
            self._set_dl_controls(False)
        elif d.is_paused():
            self.dl_status.setText("已暂停（点击「继续」恢复）")
            self.dl_status.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {Colors.WARNING};")
        else:
            stall = now - self._activity_at
            if stall >= 15:
                self.dl_status.setText("已较长时间无进展，可能服务器已断开连接（可「取消」后重新开始）")
                self.dl_status.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {Colors.ERROR};")
            elif stall > 2.5:
                self.dl_status.setText(f"网络波动，正在重连/重试（已自动重试 {d.retries} 次）…")
                self.dl_status.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {Colors.WARNING};")
            else:
                text = "正在下载"
                if getattr(d, "mirror_used", False):
                    src = getattr(d, "mirror_source", "") or ""
                    host = src.split("//")[-1].split("/")[0] if "//" in src else src
                    text = f"已启用国内镜像加速：{host}"
                self.dl_status.setText(text)
                self.dl_status.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {Colors.TEXT_MAIN};")
            if not self.dl_pause_btn.isEnabled():
                self.dl_pause_btn.setEnabled(True)
                self.dl_cancel_btn.setEnabled(True)

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
            self.dl_status.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {Colors.SUCCESS};")
            self.dl_progress.setValue(1000)
            if getattr(d, "mirror_used", False):
                src = getattr(d, "mirror_source", "") or ""
                host = src.split("//")[-1].split("/")[0] if "//" in src else src
                self.dl_meta.setText(f"已保存到：{d.filepath}\n（本次通过国内镜像 {host} 加速下载）")
            else:
                self.dl_meta.setText(f"已保存到：{d.filepath}")
            self._set_status(f"下载完成：{d.filename}")
        elif d.error:
            # 探测失败（从未开始下载）时不宜提示"续传"，语义更准确的提示如下
            if getattr(d, "probed", False):
                self.dl_status.setText(f"{d.error}（可重新点击「开始下载」续传）")
            else:
                self.dl_status.setText(f"{d.error}")
            self.dl_status.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {Colors.WARNING};")
        elif d.is_cancelled():
            self.dl_status.setText("下载已取消")
            self.dl_status.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {Colors.TEXT_SECONDARY};")

    def _toggle_pause(self):
        d = self._dl
        if d is None:
            return
        if d.is_paused():
            d.resume()
            self._resume_task("download")
            self.dl_pause_btn.setText("暂停")
            self._set_status("已继续下载")
        else:
            d.pause()
            self._pause_task("download")
            self.dl_pause_btn.setText("继续")
            self._set_status("已暂停下载")

    def _cancel_download(self):
        d = self._dl
        if d is None:
            return
        d.cancel()
        self.dl_cancel_btn.setEnabled(False)
        self._set_status("正在取消下载...")
