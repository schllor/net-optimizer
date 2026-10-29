"""
主窗口 - 网络优化助手

窗口骨架、导航与后台任务调度保留在此；各功能页面位于 ui/pages/，
工作线程位于 ui/workers.py，公共配色位于 ui/common.py。
"""

import time

from PySide6.QtWidgets import QMainWindow, QFrame, QMessageBox
from PySide6.QtCore import QTimer, Qt, QEvent

from core.diagnostic import NetworkDiagnostic
from core.repair import NetworkRepair, relaunch_as_admin
from core.speed_test import SpeedTest
from core.dns_optimizer import DNSOptimizer
from core.wifi_check import WiFiChecker
from core.cache import CacheManager
from core.cmd_utils import IS_WINDOWS
from core.logger import get_logger
from core.traffic_monitor import TrafficMonitor
from core.version import __version__
import core.theme as theme
from ui.common import Colors
from ui.shell import ShellMixin
from ui.titlebar import WindowGrip
from ui.pages import (
    HomePageMixin, DiagnosePageMixin, RepairPageMixin, SpeedPageMixin,
    DnsPageMixin, DevicesPageMixin, WifiPageMixin, DownloaderPageMixin,
    HistoryPageMixin,
)


class MainWindow(ShellMixin, HomePageMixin, DiagnosePageMixin, RepairPageMixin,
                  SpeedPageMixin, DnsPageMixin, DevicesPageMixin, WifiPageMixin,
                  DownloaderPageMixin, HistoryPageMixin, QMainWindow):
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
        self.setMinimumSize(1024, 680)
        self.resize(1120, 740)

        # 初始化核心模块
        self.diagnostic = NetworkDiagnostic()
        self.repair = NetworkRepair()
        self.speed_test = SpeedTest()
        self.dns_optimizer = DNSOptimizer()
        self.wifi_checker = WiFiChecker()
        self.cache = CacheManager()
        self.traffic = TrafficMonitor()

        # 实时网速定时刷新（每秒一次，采集开销极小）
        self.net_timer = QTimer(self)
        self.net_timer.setInterval(1000)
        self.net_timer.timeout.connect(self._update_net_rates)
        self.net_timer.start()

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

        # 默认显示首页
        self._switch_page("home")


    def _start_worker(self, worker):
        """统一管理工作线程的启动：不阻塞界面，允许不同页面的任务并行。

        旧实现会在 GUI 线程上 wait(2000) 等待旧线程，切换页面执行新任务时
        界面会明显卡顿；现在只清理已结束的引用，任务之间不再互相等待。
        """
        self._workers = [w for w in self._workers if w.isRunning()]
        worker.finished.connect(lambda *args, w=worker: self._on_worker_finished(w))
        if hasattr(worker, "progress"):
            worker.progress.connect(
                lambda *args, w=worker: self._update_task(w, args[0] if args else 0))
        self._workers.append(worker)
        self.worker = worker
        self._begin_task(worker)
        worker.start()


    def _on_worker_finished(self, worker):
        """工作线程完成后清理引用"""
        if worker in self._workers:
            self._workers.remove(worker)
        if self.worker is worker:
            self.worker = None
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

    def changeEvent(self, event):
        if event.type() == QEvent.WindowStateChange:
            self._layout_window_grips()
        super().changeEvent(event)

    def closeEvent(self, event):
        """窗口关闭时确保所有线程安全退出"""
        # 停止每秒刷新的流量采样定时器
        if self.net_timer.isActive():
            self.net_timer.stop()

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
            "home": (self.home_page, "首页", "欢迎使用网络优化助手"),
            "diagnose": (self.diagnose_page, "一键诊断", "自动检测网络问题，找出故障原因"),
            "repair": (self.repair_page, "一键修复", "自动修复常见网络问题"),
            "speed": (self.speed_page, "网速测试", "测试您的网络速度和延迟"),
            "dns": (self.dns_page, "DNS优化", "测试并推荐最优DNS服务器"),
            "devices": (self.devices_page, "设备管理", "查看并管理局域网已连接设备"),
            "wifi": (self.wifi_page, "Wi-Fi检测", "检测Wi-Fi信号质量，获取优化建议"),
            "downloader": (self.downloader_page, "多线程下载器", "分段并发加速下载网页与文件"),
            "history": (self.history_page, "历史记录", "查看之前的诊断、修复和测速记录"),
        }

        if page_key in page_map:
            page, title, subtitle = page_map[page_key]
            self.pages.setCurrentWidget(page)
            self.title_label.setText(title)
            self.subtitle_label.setText(subtitle)

            self.logger.info("切换到页面: %s", title)

            # 切换到修复页时刷新管理员状态提示
            if page_key == "repair":
                self._refresh_admin_status()

            # 当前DNS在首次进入 DNS 页时才检测，避免启动时执行 ipconfig
            if page_key == "dns" and not getattr(self, "_dns_loaded", False):
                self._load_current_dns()

            # 更新导航按钮状态
            for key, btn in self.nav_buttons.items():
                btn.setStyleSheet(theme.nav_button(active=(key == page_key)))

            self.current_page_key = page_key


    def _set_status(self, text):
        """设置状态栏文字"""
        self.status_bar.setText(text)


    def _create_card(self):
        """创建带细描边的通用卡片。"""
        card = QFrame()
        card.setObjectName("surfaceCard")
        card.setStyleSheet(theme.raised_card(bg=Colors.BG_CARD))
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


    def _refresh_admin_status(self):
        """刷新修复页管理员状态提示"""
        if not hasattr(self, "admin_status_card"):
            return
        if self._is_admin_now():
            self.admin_status_card.setStyleSheet(
                f"background-color: {Colors.SUCCESS_LIGHT}; border-radius: 8px;")
            self.admin_status_label.setText("当前以【管理员身份】运行，可执行全部修复功能。")
            self.admin_status_label.setStyleSheet(
                f"font-size: 13px; color: {Colors.SUCCESS}; line-height: 1.6;")
            self.admin_btn.hide()
        else:
            self.admin_status_card.setStyleSheet(
                f"background-color: {Colors.WARNING_LIGHT}; border-radius: 8px;")
            self.admin_status_label.setText(
                "当前【未】以管理员身份运行，部分修复功能会失败。")
            self.admin_status_label.setStyleSheet(
                f"font-size: 13px; color: {Colors.WARNING}; line-height: 1.6;")
            self.admin_btn.show()


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
