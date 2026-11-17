"""
主窗口 - 网络优化助手

窗口骨架、导航与后台任务调度保留在此；各功能页面位于 ui/pages/，
工作线程位于 ui/workers.py，公共配色位于 ui/common.py。
"""

import time

from PySide6.QtWidgets import QMainWindow, QFrame, QMessageBox
from PySide6.QtCore import Qt, QEvent, QTimer, QByteArray

from core.diagnostic import NetworkDiagnostic
from core.repair import NetworkRepair, relaunch_as_admin
from core.speed_test import SpeedTest
from core.dns_optimizer import DNSOptimizer
from core.wifi_check import WiFiChecker
from core.cache import CacheManager
from core.cmd_utils import IS_WINDOWS
from core.logger import get_logger
from core.settings import Settings, apply_runtime
from core.traffic_monitor import TrafficMonitor
from core.version import __version__
import core.theme as theme
from ui.kit import PageHead
from ui.responsive import ResponsiveColumns, mode_for
from ui.shell import ShellMixin
from ui.state import AppState
from ui.titlebar import WindowGrip
from ui.workers import NetSnapshotWorker, TrafficSampler
from ui.pages import (
    HomePageMixin, DiagnosePageMixin, RepairPageMixin, SpeedPageMixin,
    DnsPageMixin, DevicesPageMixin, WifiPageMixin, DownloaderPageMixin,
    HistoryPageMixin, SettingsPageMixin,
)


class MainWindow(ShellMixin, HomePageMixin, DiagnosePageMixin, RepairPageMixin,
                  SpeedPageMixin, DnsPageMixin, DevicesPageMixin, WifiPageMixin,
                  DownloaderPageMixin, HistoryPageMixin, SettingsPageMixin,
                  QMainWindow):
    """主窗口：负责整体布局、页面导航与后台任务的生命周期。"""

    def __init__(self):
        super().__init__()
        # 系统标题栏是浅色的，压在深色界面上会多出一条白条；
        # 改为无边框窗口 + ui/titlebar.py 的自绘标题栏
        self.setWindowFlags(
            Qt.Window | Qt.FramelessWindowHint | Qt.WindowSystemMenuHint
            | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint)
        self.setWindowTitle(f"网络优化助手 v{__version__}")
        self.setMinimumSize(1024, 640)
        self.resize(1280, 800)

        # 用户设置：文件缺失/损坏时回退默认值，不影响启动
        self.settings = Settings()
        apply_runtime(self.settings)

        # 初始化核心模块
        self.diagnostic = NetworkDiagnostic()
        self.repair = NetworkRepair()
        self.speed_test = SpeedTest()
        self.dns_optimizer = DNSOptimizer()
        self.wifi_checker = WiFiChecker()
        self.cache = CacheManager()
        self._apply_history_limit()
        self.traffic = TrafficMonitor(
            include_vpn=bool(self.settings.get("traffic_include_vpn", False)))
        self.state = AppState(self.cache)

        # 实时网速：后台线程每秒采样，避免在 GUI 线程执行 ctypes/IP Helper
        self.net_sampler = TrafficSampler(self.traffic)
        self.net_sampler.rates.connect(self._apply_net_rates)
        self.net_sampler.start()

        # 网络快照：启动后异步采集，之后每 30 秒刷新一次
        self._snapshot_worker = None
        self._snapshot_timer = QTimer(self)
        self._snapshot_timer.setInterval(30_000)
        self._snapshot_timer.timeout.connect(self._refresh_snapshot)
        self._snapshot_timer.start()

        # 运行日志
        self.logger = get_logger()
        self.logger.info("程序启动 (管理员: %s)", self._is_admin_now())

        # 工作线程
        self.worker = None
        self._workers = []

        # 顶部进度条的任务台账：token -> 百分比（None 表示未知）
        self._task_progress = {}
        self._paused_tasks = set()
        self._closing = False

        self._setup_ui()
        self._setup_window_grips()
        self._setup_styles()
        self._normalize_label_backgrounds()
        self._apply_animation_setting()
        self._restore_window_state()
        self._apply_layout_mode()
        QTimer.singleShot(0, self._refresh_snapshot)

        # 默认显示首页
        self._switch_page("home")


    # ---------------------------------------------------------------- 网络快照
    def _refresh_snapshot(self, force=False):
        """后台采集当前网络快照；上一条未结束时跳过，避免线程堆积。"""
        if self._closing:
            return
        worker = getattr(self, "_snapshot_worker", None)
        if worker is not None and worker.isRunning():
            return
        worker = NetSnapshotWorker(force=force)
        worker.done.connect(self._on_snapshot)
        self._snapshot_worker = worker
        self._start_worker(worker)

    def _on_snapshot(self, snapshot):
        self._snapshot_worker = None
        if snapshot is None or self._closing:
            return
        self.state.set_snapshot(snapshot)
        try:
            title = getattr(self, "title_bar", None)
            if title is not None:
                title.conn_label.setText(snapshot.summary)
                title.conn_pill.setToolTip(
                    f"IP {snapshot.ipv4 or '--'} · 网关 {snapshot.gateway or '--'}"
                    f" · DNS {', '.join(snapshot.dns_servers) or '--'}")
                if getattr(title, "conn_dot", None) is not None:
                    title.conn_dot.set_style(
                        "ok" if snapshot.online else "error")
            if getattr(self, "side_live_label", None) is not None:
                self.side_live_label.setText(snapshot.summary)
            if getattr(self, "side_live_dot", None) is not None:
                self.side_live_dot.set_style(
                    "ok" if snapshot.online else "error")
            if getattr(self, "status_latency", None) is not None:
                self.status_latency.setText(
                    f"网关 {snapshot.gateway or '--'}")
            if getattr(self, "status_dns", None) is not None:
                dns = snapshot.dns_servers[0] if snapshot.dns_servers else "--"
                self.status_dns.setText(f"DNS {dns}")
            self._refresh_home_metrics()
            self._refresh_home_network()
        except Exception:
            self.logger.exception("应用网络快照失败")

    # ---------------------------------------------------------------- 布局模式
    def _apply_layout_mode(self):
        """按窗口尺寸统一切换 compact / regular / wide。"""
        mode = mode_for(self.width(), self.height())
        if getattr(self, "layout_mode", None) == mode:
            return
        self.layout_mode = mode
        compact = mode == "compact"
        try:
            self.apply_shell_mode(mode)
            for head in self.findChildren(PageHead):
                head.set_compact(compact)
            for columns in self.findChildren(ResponsiveColumns):
                columns.set_compact(compact)
        except Exception:
            self.logger.exception("切换布局模式失败")

    # ---------------------------------------------------------------- 窗口状态
    def _restore_window_state(self):
        encoded = str(self.settings.get("window_geometry", "") or "")
        if encoded:
            try:
                self.restoreGeometry(QByteArray.fromBase64(encoded.encode("ascii")))
            except Exception:
                pass
        if str(self.settings.get("window_state", "")) == "maximized":
            self.showMaximized()
        self._clamp_to_screen()

    def _clamp_to_screen(self):
        """把窗口夹回可用工作区，避免恢复后出现在已拔掉的显示器上。"""
        if self.isMaximized() or self.isFullScreen():
            return
        try:
            from PySide6.QtGui import QGuiApplication
            screen = self.screen() or QGuiApplication.primaryScreen()
            if screen is None:
                return
            available = screen.availableGeometry()
            geo = self.frameGeometry()
            width = min(max(geo.width(), 1024), available.width())
            height = min(max(geo.height(), 640), available.height())
            x = min(max(geo.x(), available.left()), available.right() - width + 1)
            y = min(max(geo.y(), available.top()), available.bottom() - height + 1)
            if (geo.width() != width or geo.height() != height
                    or geo.x() != x or geo.y() != y):
                self.setGeometry(x, y, width, height)
        except Exception:
            pass

    def _save_window_state(self):
        try:
            geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
            state = "maximized" if self.isMaximized() else "normal"
            self.settings.update({"window_geometry": geometry,
                                  "window_state": state})
        except Exception:
            pass

    def _start_worker(self, worker):
        """统一管理工作线程的启动：不阻塞界面，允许不同页面的任务并行。

        旧实现会在 GUI 线程上 wait(2000) 等待旧线程，切换页面执行新任务时
        界面会明显卡顿；现在只清理已结束的引用，任务之间不再互相等待。
        """
        self._workers = [w for w in self._workers if w.isRunning()]
        # finished 是 QThread 自带的线程结束信号，只用于清理任务台账；
        # 业务结果统一走 done / failed，避免被 Qt 的同名信号覆盖。
        worker.finished.connect(lambda *args, w=worker: self._on_worker_finished(w))
        worker.failed.connect(
            lambda msg, detail, w=worker: self._on_worker_failed(w, msg, detail))
        if hasattr(worker, "progress"):
            worker.progress.connect(
                lambda *args, w=worker: self._update_task(w, args[0] if args else 0))
        self._workers.append(worker)
        if not isinstance(worker, NetSnapshotWorker):
            self.worker = worker
            self._begin_task(worker)
        worker.start()


    def _on_worker_failed(self, worker, message, detail):
        """后台任务异常：状态栏提示 + 日志记录，不弹模态框打断用户。"""
        self.logger.error("后台任务失败 %s: %s | %s",
                          type(worker).__name__, message, detail)
        if not self._closing:
            self._set_status(message)


    def _apply_history_limit(self):
        """把设置中的历史上限同步到缓存模块。"""
        try:
            self.cache.max_records = max(1, int(self.settings.get("history_limit", 20)))
        except (TypeError, ValueError):
            self.cache.max_records = 20


    def _on_worker_finished(self, worker):
        """工作线程完成后清理引用"""
        if worker in self._workers:
            self._workers.remove(worker)
        if self.worker is worker:
            self.worker = None
        if not isinstance(worker, NetSnapshotWorker):
            self._end_task(worker)


    # ---------------------------------------------------------------- 顶部进度条
    def _begin_task(self, token, percent=None):
        """登记后台任务；百分比未知时进度条先循环扫过。"""
        self._task_progress[token] = None if percent is None else float(percent)
        self._paused_tasks.discard(token)
        self._refresh_task_progress()


    def _update_task(self, token, percent):
        if token not in self._task_progress:
            return
        try:
            value = float(percent)
        except (TypeError, ValueError):
            return
        self._task_progress[token] = max(0.0, min(100.0, value))
        self._refresh_task_progress()


    def _pause_task(self, token):
        if token in self._task_progress:
            self._paused_tasks.add(token)
            self._refresh_task_progress()


    def _resume_task(self, token):
        if token in self._task_progress:
            self._paused_tasks.discard(token)
            self._refresh_task_progress()


    def _end_task(self, token):
        self._task_progress.pop(token, None)
        self._paused_tasks.discard(token)
        bar = getattr(self, "comet_bar", None)
        if bar is None or self._closing:
            return
        if not self._task_progress:
            bar.finish()
        else:
            self._refresh_task_progress()


    def _refresh_task_progress(self):
        """汇总并行任务：任一任务未知则循环扫过，否则取最大百分比。"""
        bar = getattr(self, "comet_bar", None)
        if bar is None or self._closing or not self._task_progress:
            return
        active = {k: v for k, v in self._task_progress.items()
                  if k not in self._paused_tasks}
        if not active:
            bar.pause()
            return
        if any(v is None for v in active.values()):
            if bar.state != "indeterminate":
                bar.start(None)
            return
        value = max(active.values())
        if bar.state in ("idle", "paused"):
            bar.start(value)
        else:
            bar.set_progress(value)


    def _setup_window_grips(self):
        """无边框窗口的四边/四角缩放热区（系统边框被去掉后由它们发起缩放）。"""
        specs = (
            ("left", (Qt.LeftEdge,), Qt.SizeHorCursor),
            ("right", (Qt.RightEdge,), Qt.SizeHorCursor),
            ("top", (Qt.TopEdge,), Qt.SizeVerCursor),
            ("bottom", (Qt.BottomEdge,), Qt.SizeVerCursor),
            ("top-left", (Qt.LeftEdge, Qt.TopEdge), Qt.SizeFDiagCursor),
            ("top-right", (Qt.RightEdge, Qt.TopEdge), Qt.SizeBDiagCursor),
            ("bottom-left", (Qt.LeftEdge, Qt.BottomEdge), Qt.SizeBDiagCursor),
            ("bottom-right", (Qt.RightEdge, Qt.BottomEdge), Qt.SizeFDiagCursor),
        )
        self._grips = [WindowGrip(self, anchor, edges, cursor, self)
                       for anchor, edges, cursor in specs]
        self._layout_window_grips()

    def _layout_window_grips(self):
        grips = getattr(self, "_grips", None)
        if not grips:
            return
        visible = not (self.isMaximized() or self.isFullScreen())
        for grip in grips:
            grip.place(self.width(), self.height())
            grip.setVisible(visible)
            if visible:
                grip.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_window_grips()
        self._apply_layout_mode()

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_layout_mode()

    def changeEvent(self, event):
        if event.type() == QEvent.WindowStateChange:
            self._layout_window_grips()
        super().changeEvent(event)

    def closeEvent(self, event):
        """窗口关闭时确保所有线程安全退出"""
        self._save_window_state()
        timer = getattr(self, "_snapshot_timer", None)
        if timer is not None:
            timer.stop()
        # 停止流量采样线程，避免退出时仍在使用已销毁的监控对象
        sampler = getattr(self, "net_sampler", None)
        if sampler is not None:
            sampler.stop()
            sampler.wait(1500)

        # 停止顶部进度条动画，避免退出时定时器仍在运行
        self._closing = True
        if getattr(self, "comet_bar", None) is not None:
            self.comet_bar.stop()
        self._task_progress.clear()
        self._paused_tasks.clear()

        # 取消进行中的下载，避免退出时线程残留占用文件
        if getattr(self, "_dl", None) is not None:
            self._dl.cancel()

        # 通知支持取消的任务（测速/DNS）尽快退出
        for w in list(self._workers):
            cancel = getattr(w, "cancel", None)
            if callable(cancel):
                try:
                    cancel()
                except Exception:
                    pass

        # 统一截止时间，避免逐个线程各等 3 秒导致关闭明显变慢
        deadline = time.monotonic() + 2.0
        for w in list(self._workers):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if w.isRunning():
                w.wait(int(remaining * 1000))
        self._workers.clear()
        event.accept()


    def _switch_page(self, page_key):
        """切换页面"""
        page_map = {
            "home": (self.home_page, "总览", "欢迎使用网络优化助手"),
            "diagnose": (self.diagnose_page, "网络诊断", "自动检测网络问题，找出故障原因"),
            "repair": (self.repair_page, "一键修复", "自动修复常见网络问题"),
            "speed": (self.speed_page, "网速测试", "测试您的网络速度和延迟"),
            "dns": (self.dns_page, "DNS 优化", "测试并推荐最优DNS服务器"),
            "devices": (self.devices_page, "设备管理", "查看并管理局域网已连接设备"),
            "wifi": (self.wifi_page, "Wi-Fi 检测", "检测Wi-Fi信号质量，获取优化建议"),
            "downloader": (self.downloader_page, "下载加速", "分段并发加速下载网页与文件"),
            "history": (self.history_page, "历史记录", "查看之前的诊断、修复和测速记录"),
            "settings": (self.settings_page, "设置", "调整测速、历史与探测方式"),
        }

        if page_key in page_map:
            page, title, subtitle = page_map[page_key]
            view = getattr(self, "page_views", {}).get(page_key, page)
            self.pages.setCurrentWidget(view)
            self.title_label.setText(title)
            self.subtitle_label.setText(subtitle)

            self.logger.info("切换到页面: %s", title)

            # 当前DNS在首次进入 DNS 页时才检测，避免启动时执行 ipconfig
            if page_key == "dns" and not getattr(self, "_dns_loaded", False):
                self._load_current_dns()

            # 更新导航按钮状态
            for key, btn in self.nav_buttons.items():
                if hasattr(btn, "set_active"):
                    btn.set_active(key == page_key)
                else:
                    btn.setStyleSheet(theme.nav_button(active=(key == page_key)))
            self.set_screen(page_key)
            # 中部滚动区里，确保选中项在可视范围内
            active_btn = self.nav_buttons.get(page_key)
            if active_btn is not None and self.nav_scroll.widget().isAncestorOf(active_btn):
                self.nav_scroll.ensureWidgetVisible(active_btn, 0, 8)

            self.current_page_key = page_key

            # 切页时刷新依赖历史/快照的页面，避免展示启动时的旧数据
            try:
                if page_key == "history":
                    self._load_history()
                elif page_key == "home":
                    self._refresh_home_score()
                    self._refresh_home_metrics()
                    self._refresh_home_network()
                elif page_key in ("wifi", "settings"):
                    snapshot = self.state.snapshot
                    if snapshot is None:
                        self._refresh_snapshot()
            except Exception:
                self.logger.exception("刷新页面数据失败: %s", page_key)


    def _set_status(self, text):
        """设置状态栏文字；侧栏状态行只显示网络连接，避免被任务文案覆盖。"""
        self.status_bar.setText(text)

    def _notify(self, text, tone="info", duration_ms=2800):
        """在内容区底部显示一条轻量反馈。"""
        try:
            from ui.toast import notify
            return notify(self.content_widget, text, tone, duration_ms)
        except Exception:
            return None


    def _create_card(self):
        """创建带细描边的通用卡片。"""
        card = QFrame()
        card.setObjectName("surfaceCard")
        card.setStyleSheet(theme.raised_card(bg=theme.BG_CARD))
        return card


    def _is_admin_now(self):
        """检测当前是否以管理员身份运行"""
        try:
            if not IS_WINDOWS:
                return True
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False


    def _request_admin_relaunch(self):
        """请求以管理员身份重新启动程序"""
        reply = QMessageBox.question(
            self, "以管理员身份运行",
            "即将关闭当前程序，并以【管理员身份】重新启动。\n"
            "重新启动后会自动弹出系统权限确认窗口，请点击「是」。\n\n"
            "是否继续？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.logger.info("用户请求以管理员身份重新启动")
        started = relaunch_as_admin()
        if started:
            self.close()
        else:
            QMessageBox.warning(
                self, "启动失败",
                "无法以管理员身份启动。\n请手动关闭软件后，右键图标选择「以管理员身份运行」。")
