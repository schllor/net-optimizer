"""
主窗口 - 网络优化助手
基于PySide6构建的现代化界面，面向新手小白设计
"""

import sys
import os
import time
import platform
import datetime
import subprocess

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QFrame, QProgressBar, QScrollArea,
    QMessageBox, QApplication, QLineEdit, QFileDialog, QCheckBox, QComboBox,
    QPlainTextEdit, QInputDialog
)
from PySide6.QtGui import QColor, QPalette
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QPropertyAnimation, QEasingCurve, QRect, QPoint

from core.diagnostic import NetworkDiagnostic
from core.repair import NetworkRepair, relaunch_as_admin
from core.speed_test import SpeedTest
from core.dns_optimizer import DNSOptimizer
from core.wifi_check import WiFiChecker
from core.downloader import Downloader, validate_url
from core.cache import CacheManager
from core.logger import get_logger
from core.paths import get_data_dir
from core.version import __version__
from core.traffic_monitor import TrafficMonitor
from ui.widgets import SignalArcWidget, ScoreRingWidget, LatencyBarWidget
import core.theme as theme
from core.theme import (
    ACCENT, ACCENT_DARK, ACCENT_LIGHT,
    BG_MAIN, BG_CARD, BG_SIDEBAR, BG_SIDEBAR_HOVER, BG_INSET, BG_RAISED,
    SHADOW_DARK, BORDER,
    SUCCESS, SUCCESS_LIGHT, WARNING, WARNING_LIGHT,
    ERROR, ERROR_LIGHT,
    TEXT_MAIN, TEXT_SECONDARY, TEXT_LIGHT, TEXT_WHITE,
    RADIUS, RADIUS_SMALL,
)


# 深色黑白主题色板
# 兼容旧代码中 Colors.XXX 的调用，统一映射到 theme 模块
class Colors:
    PRIMARY = ACCENT
    PRIMARY_DARK = ACCENT_DARK
    PRIMARY_LIGHT = ACCENT_LIGHT
    SUCCESS = SUCCESS
    SUCCESS_LIGHT = SUCCESS_LIGHT
    WARNING = WARNING
    WARNING_LIGHT = WARNING_LIGHT
    ERROR = ERROR
    ERROR_LIGHT = ERROR_LIGHT
    INFO_LIGHT = theme.INFO_LIGHT
    BG_MAIN = BG_MAIN
    BG_CARD = BG_CARD
    BG_SIDEBAR = BG_SIDEBAR
    BG_SIDEBAR_HOVER = BG_SIDEBAR_HOVER
    BG_INSET = BG_INSET
    BG_RAISED = BG_RAISED
    TEXT_MAIN = TEXT_MAIN
    TEXT_SECONDARY = TEXT_SECONDARY
    TEXT_LIGHT = TEXT_LIGHT
    TEXT_WHITE = TEXT_WHITE
    TEXT_ON_ACCENT = theme.TEXT_ON_ACCENT
    BORDER = BORDER
    SHADOW_DARK = SHADOW_DARK
    RADIUS = RADIUS
    RADIUS_SMALL = RADIUS_SMALL


# 语义等级 -> 状态色（core 各评测方法返回 "ok"/"warning"/"error" 作为等级关键字）
LEVEL_COLORS = {
    "ok": Colors.SUCCESS,
    "warning": Colors.WARNING,
    "error": Colors.ERROR,
}


class DiagnosticWorker(QThread):
    """诊断工作线程"""
    progress = Signal(int, str)
    item_done = Signal(dict)
    finished = Signal(list)

    def run(self):
        diag = NetworkDiagnostic()
        def progress_cb(percent, name):
            self.progress.emit(percent, name)
        def item_cb(result):
            self.item_done.emit(result)
        results = diag.run_all_tests(progress_cb, item_cb)
        self.finished.emit(results)


class RepairWorker(QThread):
    """修复工作线程"""
    progress = Signal(int, str)
    item_done = Signal(dict)
    finished = Signal(list)

    def run(self):
        repair = NetworkRepair()
        def progress_cb(percent, name):
            self.progress.emit(percent, name)
        def item_cb(result):
            self.item_done.emit(result)
        results = repair.run_all_repairs(progress_cb, item_cb)
        self.finished.emit(results)


class SpeedTestWorker(QThread):
    """测速工作线程""" 
    progress = Signal(int)
    status = Signal(str)
    live = Signal(float)
    upline = Signal(float)
    finished = Signal(dict)

    def run(self):
        st = SpeedTest()
        def progress_cb(percent):
            self.progress.emit(percent)
        def status_cb(text):
            self.status.emit(text)
        def live_cb(mbps):
            if mbps > 0:
                self.live.emit(mbps)
        def uplive_cb(mbps):
            if mbps > 0:
                self.upline.emit(mbps)
        results = st.run_full_test(progress_cb, status_cb, live_cb, uplive_cb)
        self.finished.emit(results)


class DnsTestWorker(QThread):
    """DNS测试工作线程"""
    progress = Signal(int, str)
    finished = Signal(list)

    def run(self):
        dns = DNSOptimizer()
        def progress_cb(percent, name):
            self.progress.emit(percent, name)
        results = dns.test_all_dns(progress_cb)
        self.finished.emit(results)


class WifiCheckWorker(QThread):
    """Wi-Fi检测工作线程"""
    finished = Signal(dict)

    def run(self):
        wifi = WiFiChecker()
        info = wifi.get_wifi_info()
        self.finished.emit(info)


class DeviceScanWorker(QThread):
    """局域网设备扫描工作线程"""
    finished = Signal(list)

    def run(self):
        from core.lan_scan import scan_lan_devices
        try:
            devs = scan_lan_devices()
        except Exception:
            devs = []
        self.finished.emit(devs)


class DownloadWorker(QThread):
    """下载工作线程：在后台运行阻塞式的 Downloader.start()"""
    finished = Signal()

    def __init__(self, downloader, parent=None):
        super().__init__(parent)
        self.d = downloader

    def run(self):
        try:
            self.d.start()
        except Exception as e:
            # 探测/启动阶段的异常也写入 error，便于 UI 呈现
            with self.d._cond_lock:
                if not self.d.error:
                    self.d.error = str(e)
        finally:
            self.finished.emit()


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
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

        self._setup_ui()
        self._setup_styles()
        self._normalize_label_backgrounds()

        # 默认显示首页
        self._switch_page("home")

    def _setup_ui(self):
        """设置界面"""
        # 中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 左侧导航栏
        self._setup_sidebar(main_layout)

        # 右侧内容区
        self._setup_content(main_layout)

    def _setup_sidebar(self, parent_layout):
        """设置侧边导航栏"""
        sidebar = QFrame()
        self.sidebar = sidebar
        sidebar.setFixedWidth(200)
        sidebar.setStyleSheet(f"background-color: {Colors.BG_SIDEBAR};")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 20, 0, 20)
        sidebar_layout.setSpacing(5)

        # Logo区域
        logo_label = QLabel("网络优化助手")
        logo_label.setStyleSheet(f"""
            color: {Colors.TEXT_MAIN};
            font-size: 18px;
            font-weight: bold;
            padding: 10px 20px 20px 20px;
        """)
        sidebar_layout.addWidget(logo_label)

        subtitle = QLabel("新手小白的网络管家")
        subtitle.setStyleSheet(f"""
            color: {Colors.TEXT_SECONDARY};
            font-size: 11px;
            padding: 0px 20px 20px 20px;
        """)
        sidebar_layout.addWidget(subtitle)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"background-color: {Colors.BORDER}; max-height: 1px;")
        sidebar_layout.addWidget(line)

        sidebar_layout.addSpacing(10)

        # 导航按钮
        self.nav_buttons = {}
        nav_items = [
            ("home", "首页"),
            ("wifi", "Wi-Fi检测"),
            ("diagnose", "网络诊断"),
            ("repair", "网络修复"),
            ("dns", "DNS优化"),
            ("devices", "设备管理"),
            ("speed", "网速测试"),
            ("downloader", "下载器"),
            ("history", "历史记录"),
        ]

        # 用于标记在哪个导航项之前插入分组标题（分级：总览 → 检测 → 修复优化 → 工具 → 记录）
        group_title = {
            "wifi": "检测",
            "repair": "修复 · 优化",
            "devices": "工具",
            "history": "记录",
        }

        for key, text in nav_items:
            if key in group_title:
                group_label = QLabel(group_title[key])
                group_label.setStyleSheet(f"""
                    color: {Colors.TEXT_LIGHT};
                    font-size: 11px;
                    font-weight: bold;
                    padding: 10px 22px 3px 22px;
                """)
                sidebar_layout.addWidget(group_label)
            btn = QPushButton(text)
            btn.setFixedHeight(42)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(theme.nav_button(active=False))
            btn.clicked.connect(lambda checked, k=key: self._switch_page(k))
            sidebar_layout.addWidget(btn)
            self.nav_buttons[key] = btn

        # 选中指示条（白色，随切换滑动动画）
        self.nav_indicator = QFrame(sidebar)
        self.nav_indicator.setFixedSize(3, 42)
        self.nav_indicator.setStyleSheet(
            f"background-color: {theme.TEXT_MAIN}; border-radius: 2px;")
        self.nav_indicator.hide()
        self._nav_anim = QPropertyAnimation(self.nav_indicator, b"geometry", self)
        self._nav_anim.setDuration(220)
        self._nav_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self.current_page_key = None

        sidebar_layout.addStretch()

        # 底部版本信息
        version_label = QLabel(f"v{__version__} · 2026")
        version_label.setStyleSheet(f"""
            color: {Colors.TEXT_LIGHT};
            font-size: 11px;
            padding: 10px 20px;
        """)
        sidebar_layout.addWidget(version_label)

        parent_layout.addWidget(sidebar)

    def _setup_content(self, parent_layout):
        """设置内容区域"""
        content_widget = QWidget()
        content_widget.setStyleSheet(f"background-color: {Colors.BG_MAIN};")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.setSpacing(15)

        # 顶部标题栏
        self.title_label = QLabel("网络优化助手")
        self.title_label.setStyleSheet(f"""
            font-size: 20px;
            font-weight: bold;
            color: {Colors.TEXT_MAIN};
            padding: 5px 0;
        """)
        content_layout.addWidget(self.title_label)

        self.subtitle_label = QLabel("")
        self.subtitle_label.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_SECONDARY};
            padding-bottom: 5px;
        """)
        content_layout.addWidget(self.subtitle_label)

        # 页面堆栈
        self.pages = QStackedWidget()
        self.pages.setStyleSheet(f"background-color: {Colors.BG_MAIN};")
        content_layout.addWidget(self.pages)

        # 创建各页面
        self._create_home_page()
        self._create_diagnose_page()
        self._create_repair_page()
        self._create_speed_page()
        self._create_dns_page()
        self._create_devices_page()
        self._create_wifi_page()
        self._create_downloader_page()
        self._create_history_page()

        # 将所有页面加入堆栈
        self.pages.addWidget(self.home_page)
        self.pages.addWidget(self.diagnose_page)
        self.pages.addWidget(self.repair_page)
        self.pages.addWidget(self.speed_page)
        self.pages.addWidget(self.dns_page)
        self.pages.addWidget(self.devices_page)
        self.pages.addWidget(self.wifi_page)
        self.pages.addWidget(self.downloader_page)
        self.pages.addWidget(self.history_page)

        # 底部状态栏：左侧状态，右侧实时上下行网速
        bottom_bar = QFrame()
        bottom_bar.setStyleSheet(
            f"background-color: {Colors.BG_CARD}; border: 1px solid {Colors.BORDER}; border-radius: {RADIUS_SMALL};")
        bb = QHBoxLayout(bottom_bar)
        bb.setContentsMargins(14, 8, 14, 8)
        bb.setSpacing(8)

        self.status_dot = QLabel("●")
        self.status_dot.setToolTip("网络实时状态")
        self.status_dot.setStyleSheet(f"color: {Colors.SUCCESS}; font-size: 14px;")

        self.status_bar = QLabel("网络就绪")
        self.status_bar.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;")

        self.bottom_down_label = QLabel("↓ --")
        self.bottom_up_label = QLabel("↑ --")
        for _lbl in (self.bottom_down_label, self.bottom_up_label):
            _lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;")

        bb.addWidget(self.status_dot)
        bb.addWidget(self.status_bar)
        bb.addStretch()
        bb.addWidget(self.bottom_down_label)
        bb.addSpacing(14)
        bb.addWidget(self.bottom_up_label)
        content_layout.addWidget(bottom_bar)

        parent_layout.addWidget(content_widget, 1)

    def _setup_styles(self):
        """设置应用级深色调色板与通用控件样式。"""
        global_qss = f"""
        QWidget {{
            color: {TEXT_MAIN};
        }}

        QLabel {{
            background-color: transparent;
        }}

        QLineEdit {{
            background-color: {BG_INSET};
            border: 1px solid {BORDER};
            border-radius: {RADIUS_SMALL};
            padding: 8px 12px;
            font-size: 14px;
            color: {TEXT_MAIN};
            selection-background-color: {ACCENT};
            selection-color: {TEXT_WHITE};
        }}
        QLineEdit:focus {{
            border: 1px solid {theme.FOCUS};
        }}

        QComboBox {{
            background-color: {BG_CARD};
            border: 1px solid {BORDER};
            border-radius: {RADIUS_SMALL};
            padding: 6px 10px;
            font-size: 13px;
            color: {TEXT_MAIN};
        }}
        QComboBox:focus {{ border: 1px solid {theme.FOCUS}; }}
        QComboBox::drop-down {{ border: none; width: 22px; }}
        QComboBox QAbstractItemView {{
            background-color: {BG_CARD};
            border: 1px solid {BORDER};
            border-radius: {RADIUS_SMALL};
            selection-background-color: {ACCENT_LIGHT};
            selection-color: {TEXT_MAIN};
            outline: 0;
        }}

        QCheckBox {{
            color: {TEXT_MAIN};
            font-size: 13px;
            spacing: 8px;
        }}
        QCheckBox::indicator {{
            width: 18px; height: 18px;
            border: 1px solid {BORDER};
            border-radius: 4px;
            background-color: {BG_RAISED};
        }}
        QCheckBox::indicator:hover {{ border-color: {theme.FOCUS}; }}
        QCheckBox::indicator:checked {{
            background-color: {TEXT_MAIN};
            border-color: {TEXT_MAIN};
        }}

        QMenu {{
            background-color: {BG_CARD};
            border: 1px solid {BORDER};
            border-radius: {RADIUS_SMALL};
            padding: 6px;
        }}
        QMenu::item {{
            padding: 7px 22px;
            border-radius: 6px;
            color: {TEXT_MAIN};
            font-size: 13px;
        }}
        QMenu::item:selected {{
            background-color: {ACCENT_LIGHT};
            color: {TEXT_MAIN};
        }}
        QMenu::separator {{
            height: 1px;
            background-color: {BORDER};
            margin: 4px 8px;
        }}

        QPlainTextEdit, QTextEdit {{
            background-color: {BG_INSET};
            border: 1px solid {BORDER};
            border-radius: {RADIUS_SMALL};
            color: {TEXT_MAIN};
            selection-background-color: {ACCENT_LIGHT};
            selection-color: {TEXT_MAIN};
        }}

        QTableWidget, QTableView, QListWidget, QTreeWidget {{
            background-color: {BG_CARD};
            alternate-background-color: {BG_RAISED};
            color: {TEXT_MAIN};
            border: 1px solid {BORDER};
            gridline-color: {BORDER};
            selection-background-color: {ACCENT_LIGHT};
            selection-color: {TEXT_MAIN};
        }}
        QHeaderView::section {{
            background-color: {BG_RAISED};
            color: {TEXT_SECONDARY};
            border: none;
            border-bottom: 1px solid {BORDER};
            padding: 7px 10px;
        }}

        QScrollBar:vertical {{
            width: 8px;
            background: transparent;
            margin: 2px;
        }}
        QScrollBar::handle:vertical {{
            min-height: 30px;
            border-radius: 4px;
            background-color: {SHADOW_DARK};
        }}
        QScrollBar::handle:vertical:hover {{
            background-color: #555555;
        }}
        QScrollBar::add-line, QScrollBar::sub-line {{
            height: 0px;
            width: 0px;
        }}

        QToolTip {{
            background-color: {BG_RAISED};
            color: {TEXT_MAIN};
            border: 1px solid {BORDER};
            padding: 6px 10px;
            border-radius: {RADIUS_SMALL};
            font-size: 12px;
        }}
        """
        app = QApplication.instance()
        if app is not None:
            palette = app.palette()
            palette.setColor(QPalette.ColorRole.Window, QColor(BG_MAIN))
            palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT_MAIN))
            palette.setColor(QPalette.ColorRole.Base, QColor(BG_CARD))
            palette.setColor(QPalette.ColorRole.AlternateBase, QColor(BG_RAISED))
            palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(BG_RAISED))
            palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT_MAIN))
            palette.setColor(QPalette.ColorRole.Text, QColor(TEXT_MAIN))
            palette.setColor(QPalette.ColorRole.Button, QColor(BG_RAISED))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT_MAIN))
            palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT_LIGHT))
            palette.setColor(QPalette.ColorRole.HighlightedText, QColor(TEXT_MAIN))
            palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_LIGHT))
            app.setPalette(palette)
            app.setStyleSheet(global_qss)

    def _normalize_label_backgrounds(self, root=None):
        """Keep ordinary text labels transparent without changing intentional badges."""
        root = root or self
        for label in root.findChildren(QLabel):
            style = label.styleSheet()
            if "background" in style.lower():
                continue
            label.setStyleSheet(style + "\nbackground-color: transparent;")

    def _start_worker(self, worker):
        """统一管理工作线程的启动：先清理旧线程再启动新线程"""
        # 清理已完成的旧线程引用
        self._workers = [w for w in self._workers if w.isRunning()]
        # 若有正在运行的线程，先等待其结束（底层命令均有 timeout，最坏也会在超时后自行退出）
        for w in self._workers:
            w.quit()
            w.wait(2000)
        # wait 超时后仍残留的运行中线程：记录日志但继续（任务按钮在运行期已禁用，正常不会到这一步）
        still_running = [w for w in self._workers if w.isRunning()]
        if still_running:
            self.logger.warning("启动新任务时仍有 %d 个线程在运行", len(still_running))
        self._workers = []
        # 连接 finished 信号以便自动清理引用
        worker.finished.connect(lambda *args: self._on_worker_finished(worker))
        self._workers.append(worker)
        self.worker = worker
        worker.start()

    def _on_worker_finished(self, worker):
        """工作线程完成后清理引用"""
        if worker in self._workers:
            self._workers.remove(worker)
        if self.worker is worker:
            self.worker = None

    def closeEvent(self, event):
        """窗口关闭时确保所有线程安全退出"""
        # 取消进行中的下载，避免退出时线程残留占用文件
        if getattr(self, "_dl", None) is not None:
            self._dl.cancel()
        for w in self._workers:
            if w.isRunning():
                w.quit()
                w.wait(3000)
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

            # 更新导航按钮状态
            for key, btn in self.nav_buttons.items():
                btn.setStyleSheet(theme.nav_button(active=(key == page_key)))

            # 滑动选中指示条到当前项（带动画）
            self.current_page_key = page_key
            self._position_indicator(animate=True)

    def _position_indicator(self, animate=True):
        """将黑色选中指示条定位到当前导航项（首次直接定位，之后滑动动画）"""
        btn = self.nav_buttons.get(self.current_page_key)
        if btn is None:
            return
        if not self.isVisible():
            # 窗口尚未显示，布局未完成，直接定位
            self.nav_indicator.setGeometry(0, btn.y(), 3, btn.height())
            self.nav_indicator.show()
            self.nav_indicator.raise_()
            return
        y = btn.mapTo(self.sidebar, QPoint(0, 0)).y()
        target = QRect(0, y, 3, btn.height())
        self.nav_indicator.raise_()
        self.nav_indicator.show()
        if animate:
            self._nav_anim.stop()
            self._nav_anim.setStartValue(self.nav_indicator.geometry())
            self._nav_anim.setEndValue(target)
            self._nav_anim.start()
        else:
            self._nav_anim.stop()
            self.nav_indicator.setGeometry(target)

    def showEvent(self, event):
        """窗口显示后，重新校正指示条位置（首次布局完成）"""
        super().showEvent(event)
        if hasattr(self, "nav_indicator"):
            self._position_indicator(animate=False)

    def _set_status(self, text):
        """设置状态栏文字"""
        self.status_bar.setText(text)

    # ==================== 首页 ====================
    def _create_home_page(self):
        """创建首页"""
        self.home_page = QScrollArea()
        self.home_page.setWidgetResizable(True)
        self.home_page.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: transparent;
            }}
        """)

        content = QWidget()
        self.home_page.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        # 欢迎卡片（左侧欢迎语 + 右侧健康分环）
        welcome_card = self._create_card()
        welcome_layout = QHBoxLayout(welcome_card)
        welcome_layout.setContentsMargins(30, 25, 30, 25)
        welcome_layout.setSpacing(20)

        welcome_text_layout = QVBoxLayout()
        welcome_text_layout.setSpacing(8)

        welcome_title = QLabel("欢迎使用网络优化助手！")
        welcome_title.setStyleSheet(f"""
            font-size: 22px;
            font-weight: bold;
            color: {Colors.TEXT_MAIN};
            background: transparent;
        """)
        welcome_text_layout.addWidget(welcome_title)

        welcome_desc = QLabel("不知道网络哪里出问题？跟着下面的步骤，轻松搞定网络问题！")
        welcome_desc.setWordWrap(True)
        welcome_desc.setStyleSheet(f"""
            font-size: 14px;
            color: {Colors.TEXT_SECONDARY};
            line-height: 1.6;
            background: transparent;
        """)
        welcome_text_layout.addWidget(welcome_desc)

        welcome_layout.addLayout(welcome_text_layout, 1)

        # 健康分环（依据最近一次诊断结果）
        self.home_score_ring = ScoreRingWidget()
        self.home_score_ring.setFixedSize(130, 130)
        self.home_score_ring.set_unknown("健康分")
        welcome_layout.addWidget(self.home_score_ring)

        layout.addWidget(welcome_card)
        self._refresh_home_score()

        # 核心功能区 - 两个大卡片
        core_func_layout = QHBoxLayout()
        core_func_layout.setSpacing(15)

        # 一键诊断大卡片
        diag_card = self._create_big_feature_card(
            "＋", "一键诊断", "自动检测网卡、IP、DNS、网关等\n全面了解网络状态",
            lambda: self._switch_page("diagnose")
        )
        core_func_layout.addWidget(diag_card)

        # 一键修复大卡片
        repair_card = self._create_big_feature_card(
            "◆", "一键修复", "刷新DNS、重置网络、修复配置\n自动解决常见网络问题",
            lambda: self._switch_page("repair")
        )
        core_func_layout.addWidget(repair_card)

        layout.addLayout(core_func_layout)

        # 其他功能区
        other_label = QLabel("更多功能")
        other_label.setStyleSheet(f"""
            font-size: 16px;
            font-weight: bold;
            color: {Colors.TEXT_MAIN};
            padding-top: 10px;
            background: transparent;
        """)
        layout.addWidget(other_label)

        other_func_layout = QHBoxLayout()
        other_func_layout.setSpacing(15)

        speed_card = self._create_feature_card(
            "▲", "网速测试", "测测你的网速有多快",
            lambda: self._switch_page("speed")
        )
        other_func_layout.addWidget(speed_card, 1)

        dns_card = self._create_feature_card(
            "●", "DNS优化", "让网页打开更快",
            lambda: self._switch_page("dns")
        )
        other_func_layout.addWidget(dns_card, 1)

        wifi_card = self._create_feature_card(
            "★", "Wi-Fi检测", "查看信号质量",
            lambda: self._switch_page("wifi")
        )
        other_func_layout.addWidget(wifi_card, 1)

        layout.addLayout(other_func_layout)

        # 使用步骤提示
        tip_card = QFrame()
        tip_card.setStyleSheet(f"""
            background-color: {Colors.BG_INSET};
            border: 1px solid {Colors.BORDER};
            border-radius: 8px;
            padding: 15px;
        """)
        tip_layout = QVBoxLayout(tip_card)
        tip_layout.setContentsMargins(20, 15, 20, 15)

        tip_title = QLabel("使用建议")
        tip_title.setStyleSheet(f"""
            font-size: 14px;
            font-weight: bold;
            color: {Colors.TEXT_MAIN};
            background: transparent;
        """)
        tip_layout.addWidget(tip_title)

        tip_text = QLabel(
            "第1步：点击「一键诊断」，让软件帮您检查网络哪里有问题\n"
            "第2步：查看诊断结果，了解问题所在\n"
            "第3步：点击「一键修复」，自动解决检测到的问题\n"
            "第4步：修复后建议重启电脑，使设置完全生效\n"
            "第5步：在「历史记录」中可查看之前的操作结果"
        )
        tip_text.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_SECONDARY};
            padding-top: 8px;
            line-height: 1.8;
            background: transparent;
        """)
        tip_layout.addWidget(tip_text)

        layout.addWidget(tip_card)

        # 首页引导按钮：立即开始诊断
        start_btn = QPushButton("立即开始诊断网络")
        start_btn.setFixedHeight(55)
        start_btn.setCursor(Qt.PointingHandCursor)
        start_btn.setStyleSheet(theme.accent_button())
        start_btn.clicked.connect(self._home_start_diagnose)
        layout.addWidget(start_btn)

        layout.addStretch()

    def _home_start_diagnose(self):
        """首页引导按钮：跳到诊断页并自动开始诊断"""
        self._switch_page("diagnose")
        self._start_diagnose()

    def _refresh_home_score(self):
        """依据最近一次诊断结果刷新首页健康分环"""
        ring = getattr(self, "home_score_ring", None)
        if ring is None:
            return
        try:
            hist = self.cache.get_history("diagnostic")
            if not hist:
                ring.set_unknown("健康分")
                return
            result = hist[-1].get("result")
            items = result if isinstance(result, list) else []
            if not items:
                ring.set_unknown("健康分")
                return
            ok, total = 0, 0
            for it in items:
                if isinstance(it, dict):
                    total += 1
                    if it.get("status") == "ok":
                        ok += 1
            if total == 0:
                ring.set_unknown("健康分")
                return
            score = round(ok / total * 100)
            color = Colors.SUCCESS if score >= 80 else (Colors.WARNING if score >= 60 else Colors.ERROR)
            ring.set_score(score, color, "健康分")
        except Exception:
            ring.set_unknown("健康分")

    def _create_card(self):
        """创建带细描边的通用卡片。"""
        card = QFrame()
        card.setObjectName("surfaceCard")
        card.setStyleSheet(theme.raised_card(bg=Colors.BG_CARD))
        return card

    def _create_big_feature_card(self, icon, title, desc, callback):
        """创建大功能卡片"""
        card = QFrame()
        card.setObjectName("surfaceCard")
        card.setCursor(Qt.PointingHandCursor)
        card.setMinimumHeight(140)
        card.setStyleSheet(theme.raised_card(bg=Colors.BG_CARD))
        card.mousePressEvent = lambda e: callback()

        layout = QHBoxLayout(card)
        layout.setContentsMargins(25, 20, 25, 20)
        layout.setSpacing(20)

        # Icon tile: a raised neutral surface with a reserved green active cue.
        icon_label = QLabel(icon)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setFixedSize(60, 60)
        if icon == "＋":
            tile_bg, tile_border, tile_color = Colors.PRIMARY_LIGHT, Colors.PRIMARY_DARK, Colors.PRIMARY
        elif icon == "◆":
            tile_bg, tile_border, tile_color = Colors.INFO_LIGHT, Colors.BORDER, Colors.TEXT_MAIN
        else:
            tile_bg, tile_border, tile_color = Colors.BG_RAISED, Colors.BORDER, Colors.TEXT_MAIN
        icon_label.setStyleSheet(f"""
            background-color: {tile_bg};
            border: 1px solid {tile_border};
            border-radius: 8px;
            font-size: 28px;
            color: {tile_color};
            background-clip: padding;
        """)
        layout.addWidget(icon_label)

        # 文字区域
        text_layout = QVBoxLayout()
        text_layout.setSpacing(8)

        title_label = QLabel(title)
        title_label.setStyleSheet(f"""
            font-size: 18px;
            font-weight: bold;
            color: {Colors.TEXT_MAIN};
            background: transparent;
        """)
        text_layout.addWidget(title_label)

        desc_label = QLabel(desc)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_SECONDARY};
            line-height: 1.6;
            background: transparent;
        """)
        text_layout.addWidget(desc_label)

        text_layout.addStretch()

        layout.addLayout(text_layout, 1)

        # 箭头
        arrow = QLabel("→")
        arrow.setStyleSheet(f"""
            font-size: 24px;
            color: {Colors.PRIMARY};
            font-weight: bold;
            background: transparent;
        """)
        layout.addWidget(arrow)

        return card

    def _create_feature_card(self, icon, title, desc, callback):
        """创建普通功能卡片"""
        card = QFrame()
        card.setObjectName("surfaceCard")
        card.setCursor(Qt.PointingHandCursor)
        card.setMinimumHeight(120)
        card.setStyleSheet(theme.raised_card(bg=Colors.BG_CARD))
        card.mousePressEvent = lambda e: callback()

        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignCenter)

        icon_label = QLabel(icon)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setFixedSize(44, 44)
        icon_label.setStyleSheet(f"""
            background-color: {Colors.BG_RAISED};
            border: 1px solid {Colors.BORDER};
            border-radius: 8px;
            font-size: 22px;
            color: {Colors.PRIMARY};
            background-clip: padding;
        """)
        layout.addWidget(icon_label)

        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(f"""
            font-size: 15px;
            font-weight: bold;
            color: {Colors.TEXT_MAIN};
            background: transparent;
        """)
        layout.addWidget(title_label)

        desc_label = QLabel(desc)
        desc_label.setAlignment(Qt.AlignCenter)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet(f"""
            font-size: 12px;
            color: {Colors.TEXT_LIGHT};
            background: transparent;
        """)
        layout.addWidget(desc_label)

        arrow = QLabel("开启 →")
        arrow.setAlignment(Qt.AlignCenter)
        arrow.setStyleSheet(f"""
            font-size: 12px;
            font-weight: bold;
            color: {Colors.PRIMARY};
            padding-top: 2px;
            background: transparent;
        """)
        layout.addWidget(arrow)

        return card

    # ==================== 诊断页面 ====================
    def _create_diagnose_page(self):
        """创建诊断页面"""
        self.diagnose_page = QWidget()
        layout = QVBoxLayout(self.diagnose_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        # 操作按钮区
        btn_card = self._create_card()
        btn_layout = QVBoxLayout(btn_card)
        btn_layout.setContentsMargins(30, 20, 30, 20)
        btn_layout.setSpacing(15)

        self.diag_btn = QPushButton("开始诊断")
        self.diag_btn.setFixedHeight(50)
        self.diag_btn.setCursor(Qt.PointingHandCursor)
        self.diag_btn.setStyleSheet(theme.accent_button())
        self.diag_btn.clicked.connect(self._start_diagnose)
        btn_layout.addWidget(self.diag_btn)

        # 进度条
        self.diag_progress = QProgressBar()
        self.diag_progress.setFixedHeight(20)
        self.diag_progress.setTextVisible(False)
        self.diag_progress.setStyleSheet(theme.progress_bar(chunk_color=Colors.PRIMARY))
        self.diag_progress.hide()
        btn_layout.addWidget(self.diag_progress)

        self.diag_progress_label = QLabel("")
        self.diag_progress_label.setAlignment(Qt.AlignCenter)
        self.diag_progress_label.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_SECONDARY};
        """)
        self.diag_progress_label.hide()
        btn_layout.addWidget(self.diag_progress_label)

        layout.addWidget(btn_card)

        # 检测步骤清单（诊断时逐项点亮）
        self._diag_steps_card = self._create_card()
        steps_layout = QVBoxLayout(self._diag_steps_card)
        steps_layout.setContentsMargins(25, 18, 25, 18)
        steps_layout.setSpacing(8)

        steps_title = QLabel("检测进度")
        steps_title.setStyleSheet(f"""
            font-size: 14px;
            font-weight: bold;
            color: {Colors.TEXT_MAIN};
            padding-bottom: 4px;
        """)
        steps_layout.addWidget(steps_title)

        self._diag_steps_layout = QVBoxLayout()
        self._diag_steps_layout.setSpacing(6)
        steps_layout.addLayout(self._diag_steps_layout)

        self._diag_step_items = {}   # name -> (icon_label, name_label)
        self._diag_steps_card.hide()
        layout.addWidget(self._diag_steps_card)

        # 结果摘要
        self.diag_summary_card = self._create_card()
        summary_layout = QHBoxLayout(self.diag_summary_card)
        summary_layout.setContentsMargins(25, 20, 25, 20)

        self.diag_summary_icon = QLabel("·")
        self.diag_summary_icon.setStyleSheet("font-size: 36px;")
        self.diag_summary_icon.setFixedWidth(50)
        summary_layout.addWidget(self.diag_summary_icon)

        self.diag_summary_text = QLabel("点击上方按钮，开始检测您的网络状态")
        self.diag_summary_text.setWordWrap(True)
        self.diag_summary_text.setStyleSheet(f"""
            font-size: 15px;
            color: {Colors.TEXT_SECONDARY};
        """)
        summary_layout.addWidget(self.diag_summary_text, 1)

        layout.addWidget(self.diag_summary_card)

        # 详细结果 - 滚动区域
        results_scroll = QScrollArea()
        results_scroll.setWidgetResizable(True)
        results_scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: {Colors.BG_CARD};
                border-radius: 8px;
                border: none;
            }}
            QScrollBar:vertical {{
                width: 8px;
                background: {Colors.BG_INSET};
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {Colors.SHADOW_DARK};
                border-radius: 4px;
            }}
        """)

        self.diag_results_widget = QWidget()
        self.diag_results_layout = QVBoxLayout(self.diag_results_widget)
        self.diag_results_layout.setContentsMargins(25, 15, 25, 15)
        self.diag_results_layout.setSpacing(10)

        # 初始提示
        hint = QLabel("诊断结果将显示在这里...")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_LIGHT};
            padding: 30px 0;
        """)
        self.diag_results_layout.addWidget(hint)

        self.diag_results_layout.addStretch()
        results_scroll.setWidget(self.diag_results_widget)
        layout.addWidget(results_scroll, 1)

    def _start_diagnose(self):
        """开始诊断"""
        self.logger.info("开始一键诊断")
        self.diag_btn.setEnabled(False)
        self.diag_btn.setText("诊断中...")
        self.diag_progress.show()
        self.diag_progress_label.show()
        self.diag_progress.setValue(0)

        self._clear_diag_results()
        self._build_diag_steps()

        self.diag_summary_icon.setText("·")
        self.diag_summary_text.setText("正在检测网络状态，请稍候...")

        self._set_status("正在进行网络诊断...")

        self.worker = DiagnosticWorker()
        self.worker.progress.connect(self._on_diag_progress)
        self.worker.item_done.connect(self._on_diag_item_done)
        self.worker.finished.connect(self._on_diag_finished)
        self._start_worker(self.worker)

    def _build_diag_steps(self):
        """构建诊断步骤清单（全部置为等待中）"""
        # 清空旧步骤
        while self._diag_steps_layout.count() > 0:
            item = self._diag_steps_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._diag_step_items = {}

        step_names = ["网卡状态", "IP地址", "网关连通性", "DNS解析", "互联网连通性", "多站点延迟", "代理设置"]
        for name in step_names:
            row = QHBoxLayout()
            row.setSpacing(10)
            icon_label = QLabel("○")
            icon_label.setStyleSheet("font-size: 14px;")
            icon_label.setFixedWidth(24)
            row.addWidget(icon_label)

            name_label = QLabel(name)
            name_label.setStyleSheet(f"""
                font-size: 13px;
                color: {Colors.TEXT_SECONDARY};
            """)
            row.addWidget(name_label)
            row.addStretch()

            holder = QWidget()
            holder.setLayout(row)
            self._diag_steps_layout.addWidget(holder)
            self._diag_step_items[name] = (icon_label, name_label)

        self._diag_steps_card.show()

    def _on_diag_item_done(self, result):
        """诊断某项完成：点亮对应步骤"""
        name = result.get("name", "")
        pair = self._diag_step_items.get(name)
        if not pair:
            return
        icon_label, name_label = pair
        status = result.get("status", "ok")
        status_map = {
            "ok": ("√", Colors.SUCCESS),
            "warning": ("!", Colors.WARNING),
            "error": ("×", Colors.ERROR),
        }
        icon, color = status_map.get(status, ("√", Colors.SUCCESS))
        icon_label.setText(icon)
        name_label.setStyleSheet(f"font-size: 13px; color: {color}; font-weight: bold;")

    def _on_diag_progress(self, percent, item_name):
        """诊断进度更新"""
        self.diag_progress.setValue(percent)
        self.diag_progress_label.setText(f"正在检测: {item_name} ({percent}%)")

    def _on_diag_finished(self, results):
        """诊断完成"""
        self.diag_btn.setEnabled(True)
        self.diag_btn.setText("重新诊断")
        self.diag_progress.hide()
        self.diag_progress_label.hide()
        self._diag_steps_card.hide()

        self.diagnostic.results = results

        summary, status = self.diagnostic.get_summary()
        status_icons = {"ok": "√", "warning": "!", "error": "×", "info": "·"}
        status_colors = {
            "ok": Colors.SUCCESS,
            "warning": Colors.WARNING,
            "error": Colors.ERROR,
            "info": Colors.TEXT_SECONDARY
        }

        self.diag_summary_icon.setText(status_icons.get(status, "·"))
        self.diag_summary_text.setText(summary)
        self.diag_summary_text.setStyleSheet(f"font-size: 15px; color: {status_colors.get(status, Colors.TEXT_MAIN)}; font-weight: bold;")

        # 显示详细结果
        self._clear_diag_results()

        title = QLabel("详细检测结果")
        title.setStyleSheet(f"""
            font-size: 15px;
            font-weight: bold;
            color: {Colors.TEXT_MAIN};
            padding-bottom: 5px;
        """)
        self.diag_results_layout.addWidget(title)

        for result in results:
            self._add_diag_result_item(result)

        # 如果有问题，添加修复按钮
        if self.diagnostic.has_issues():
            fix_btn = QPushButton("立即修复（前往一键修复）")
            fix_btn.setFixedHeight(40)
            fix_btn.setCursor(Qt.PointingHandCursor)
            fix_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {Colors.ERROR};
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-size: 14px;
                    font-weight: bold;
                    margin-top: 10px;
                }}
                QPushButton:hover {{
                    background-color: #cf6262;
                }}
            """)
            fix_btn.clicked.connect(lambda: self._switch_page("repair"))
            self.diag_results_layout.addWidget(fix_btn)

        self.diag_results_layout.addStretch()
        self._set_status("诊断完成")

        self.cache.save_result("diagnostic", results)
        self._refresh_home_score()

    def _clear_diag_results(self):
        """清空诊断结果"""
        while self.diag_results_layout.count() > 0:
            item = self.diag_results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _add_diag_result_item(self, result):
        """添加诊断结果项"""
        item_frame = QFrame()
        item_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_RAISED};
                border-radius: 6px;
                padding: 10px;
            }}
        """)
        item_layout = QHBoxLayout(item_frame)
        item_layout.setContentsMargins(15, 10, 15, 10)
        item_layout.setSpacing(15)

        status_colors = {
            "ok": Colors.SUCCESS,
            "warning": Colors.WARNING,
            "error": Colors.ERROR
        }
        status_icons = {"ok": "√", "warning": "!", "error": "×"}

        icon_label = QLabel(status_icons.get(result["status"], "?"))
        icon_label.setStyleSheet("font-size: 18px;")
        icon_label.setFixedWidth(30)
        item_layout.addWidget(icon_label)

        name_label = QLabel(result["name"])
        name_label.setStyleSheet(f"""
            font-size: 14px;
            font-weight: bold;
            color: {Colors.TEXT_MAIN};
        """)
        name_label.setFixedWidth(100)
        item_layout.addWidget(name_label)

        msg_label = QLabel(result["message"])
        msg_label.setStyleSheet(f"""
            font-size: 13px;
            color: {status_colors.get(result['status'], Colors.TEXT_SECONDARY)};
        """)
        msg_label.setWordWrap(True)
        item_layout.addWidget(msg_label, 1)

        self.diag_results_layout.addWidget(item_frame)

    # ==================== 修复页面 ====================
    def _is_admin_now(self):
        """检测当前是否以管理员身份运行"""
        try:
            import platform
            if platform.system() != "Windows":
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

    def _create_repair_page(self):
        """创建修复页面"""
        self.repair_page = QWidget()
        layout = QVBoxLayout(self.repair_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        # 警告提示
        warn_card = QFrame()
        warn_card.setStyleSheet(f"""
            background-color: {Colors.WARNING_LIGHT};
            border-radius: 8px;
        """)
        warn_layout = QHBoxLayout(warn_card)
        warn_layout.setContentsMargins(20, 15, 20, 15)

        warn_icon = QLabel("!")
        warn_icon.setStyleSheet("font-size: 24px;")
        warn_icon.setFixedWidth(35)
        warn_layout.addWidget(warn_icon)

        warn_text = QLabel(
            "部分修复功能需要【管理员权限】。如果修复失败，请右键点击本软件，选择「以管理员身份运行」后再试。\n"
            "修复过程中网络可能会短暂断开，修复完成后建议重启电脑使设置完全生效。"
        )
        warn_text.setWordWrap(True)
        warn_text.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.WARNING};
            line-height: 1.6;
        """)
        warn_layout.addWidget(warn_text, 1)

        layout.addWidget(warn_card)

        # 管理员状态提示
        self.admin_status_card = QFrame()
        admin_bg, admin_color, admin_icon = (
            Colors.SUCCESS_LIGHT, Colors.SUCCESS, "√" if self._is_admin_now() else "!"
        )
        admin_msg = (
            "当前以【管理员身份】运行，可执行全部修复功能。"
            if self._is_admin_now()
            else "当前【未】以管理员身份运行，部分修复功能会失败。"
        )
        self.admin_status_card.setStyleSheet(f"background-color: {admin_bg}; border-radius: 8px;")
        admin_layout = QHBoxLayout(self.admin_status_card)
        admin_layout.setContentsMargins(20, 12, 20, 12)
        admin_icon_label = QLabel(admin_icon)
        admin_icon_label.setStyleSheet("font-size: 20px;")
        admin_icon_label.setFixedWidth(30)
        admin_layout.addWidget(admin_icon_label)
        self.admin_status_label = QLabel(admin_msg)
        self.admin_status_label.setWordWrap(True)
        self.admin_status_label.setStyleSheet(f"font-size: 13px; color: {admin_color}; line-height: 1.6;")
        admin_layout.addWidget(self.admin_status_label, 1)

        # 以管理员身份运行按钮（仅非管理员时显示）
        self.admin_btn = QPushButton("以管理员身份运行")
        self.admin_btn.setFixedHeight(32)
        self.admin_btn.setCursor(Qt.PointingHandCursor)
        self.admin_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.PRIMARY};
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 12px;
                font-weight: bold;
                padding: 0 12px;
            }}
            QPushButton:hover {{
                background-color: {Colors.PRIMARY_DARK};
            }}
        """)
        self.admin_btn.clicked.connect(self._request_admin_relaunch)
        if self._is_admin_now():
            self.admin_btn.hide()
        admin_layout.addWidget(self.admin_btn)
        layout.addWidget(self.admin_status_card)

        # 操作按钮
        btn_card = self._create_card()
        btn_layout = QVBoxLayout(btn_card)
        btn_layout.setContentsMargins(30, 20, 30, 20)
        btn_layout.setSpacing(15)

        self.repair_btn = QPushButton("开始修复")
        self.repair_btn.setFixedHeight(50)
        self.repair_btn.setCursor(Qt.PointingHandCursor)
        self.repair_btn.setStyleSheet(theme.accent_button())
        self.repair_btn.clicked.connect(self._start_repair)
        btn_layout.addWidget(self.repair_btn)

        self.repair_progress = QProgressBar()
        self.repair_progress.setFixedHeight(20)
        self.repair_progress.setTextVisible(False)
        self.repair_progress.setStyleSheet(theme.progress_bar(chunk_color=Colors.PRIMARY))
        self.repair_progress.hide()
        btn_layout.addWidget(self.repair_progress)

        self.repair_progress_label = QLabel("")
        self.repair_progress_label.setAlignment(Qt.AlignCenter)
        self.repair_progress_label.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_SECONDARY};
        """)
        self.repair_progress_label.hide()
        btn_layout.addWidget(self.repair_progress_label)

        layout.addWidget(btn_card)

        # 结果摘要
        self.repair_summary_card = self._create_card()
        summary_layout = QHBoxLayout(self.repair_summary_card)
        summary_layout.setContentsMargins(25, 20, 25, 20)

        self.repair_summary_icon = QLabel("·")
        self.repair_summary_icon.setStyleSheet("font-size: 36px;")
        self.repair_summary_icon.setFixedWidth(50)
        summary_layout.addWidget(self.repair_summary_icon)

        self.repair_summary_text = QLabel("点击上方按钮，开始修复网络问题")
        self.repair_summary_text.setWordWrap(True)
        self.repair_summary_text.setStyleSheet(f"""
            font-size: 15px;
            color: {Colors.TEXT_SECONDARY};
        """)
        summary_layout.addWidget(self.repair_summary_text, 1)

        layout.addWidget(self.repair_summary_card)

        # 实时修复日志
        self.repair_log_card = self._create_card()
        log_layout = QVBoxLayout(self.repair_log_card)
        log_layout.setContentsMargins(20, 15, 20, 15)
        log_layout.setSpacing(8)

        log_title = QLabel("实时修复日志")
        log_title.setStyleSheet(f"""
            font-size: 14px;
            font-weight: bold;
            color: {Colors.TEXT_MAIN};
        """)
        log_layout.addWidget(log_title)

        self.repair_log_view = QPlainTextEdit()
        self.repair_log_view.setReadOnly(True)
        self.repair_log_view.setFixedHeight(150)
        self.repair_log_view.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {Colors.BG_RAISED};
                border: none;
                border-radius: 6px;
                padding: 10px;
                font-family: Consolas, Monaco, monospace;
                font-size: 12px;
                color: {Colors.TEXT_SECONDARY};
            }}
        """)
        log_layout.addWidget(self.repair_log_view)

        self.repair_log_card.hide()
        layout.addWidget(self.repair_log_card)

        # 详细结果
        results_scroll = QScrollArea()
        results_scroll.setWidgetResizable(True)
        results_scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: {Colors.BG_CARD};
                border-radius: 8px;
                border: none;
            }}
            QScrollBar:vertical {{
                width: 8px;
                background: {Colors.BG_INSET};
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {Colors.SHADOW_DARK};
                border-radius: 4px;
            }}
        """)

        self.repair_results_widget = QWidget()
        self.repair_results_layout = QVBoxLayout(self.repair_results_widget)
        self.repair_results_layout.setContentsMargins(25, 15, 25, 15)
        self.repair_results_layout.setSpacing(10)

        hint = QLabel("修复结果将显示在这里...")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_LIGHT};
            padding: 30px 0;
        """)
        self.repair_results_layout.addWidget(hint)

        self.repair_results_layout.addStretch()
        results_scroll.setWidget(self.repair_results_widget)
        layout.addWidget(results_scroll, 1)

    def _start_repair(self):
        """开始修复"""
        self.logger.info("开始一键修复 (管理员: %s)", self._is_admin_now())
        reply = QMessageBox.question(
            self, "确认修复",
            "即将执行网络修复操作，修复过程中网络可能会短暂断开。\n\n是否继续？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.repair_btn.setEnabled(False)
        self.repair_btn.setText("修复中...")
        self.repair_progress.show()
        self.repair_progress_label.show()
        self.repair_progress.setValue(0)

        self._clear_repair_results()

        # 清空并显示实时日志
        self.repair_log_view.clear()
        self.repair_log_view.appendPlainText(
            f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 开始修复...")
        self.repair_log_card.show()

        self.repair_summary_icon.setText("·")
        self.repair_summary_text.setText("正在修复网络问题，请稍候...")
        self.repair_summary_text.setStyleSheet(f"font-size: 15px; color: {Colors.TEXT_SECONDARY};")

        self._set_status("正在进行网络修复...")

        self.worker = RepairWorker()
        self.worker.progress.connect(self._on_repair_progress)
        self.worker.item_done.connect(self._on_repair_item_done)
        self.worker.finished.connect(self._on_repair_finished)
        self._start_worker(self.worker)

    def _on_repair_item_done(self, result):
        """修复某项完成：实时追加日志行并自动滚动到底部"""
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        name = result.get("name", "")
        success = result.get("success", False)
        message = result.get("message", "")
        flag = "√" if success else "×"
        self.repair_log_view.appendPlainText(f"[{ts}] {flag} {name}：{message}")
        # 自动滚动到底部
        sb = self.repair_log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_repair_progress(self, percent, item_name):
        """修复进度更新"""
        self.repair_progress.setValue(percent)
        self.repair_progress_label.setText(f"正在修复: {item_name} ({percent}%)")

    def _on_repair_finished(self, results):
        """修复完成"""
        self.repair_btn.setEnabled(True)
        self.repair_btn.setText("重新修复")
        self.repair_progress.hide()
        self.repair_progress_label.hide()

        summary, status = self.repair.get_summary(results)
        status_icons = {"ok": "√", "warning": "!", "error": "×"}
        status_colors = {
            "ok": Colors.SUCCESS,
            "warning": Colors.WARNING,
            "error": Colors.ERROR
        }

        self.repair_summary_icon.setText(status_icons.get(status, "·"))
        self.repair_summary_text.setText(summary)
        self.repair_summary_text.setStyleSheet(f"font-size: 15px; color: {status_colors.get(status, Colors.TEXT_MAIN)}; font-weight: bold;")

        self._clear_repair_results()

        title = QLabel("修复详情")
        title.setStyleSheet(f"""
            font-size: 15px;
            font-weight: bold;
            color: {Colors.TEXT_MAIN};
            padding-bottom: 5px;
        """)
        self.repair_results_layout.addWidget(title)

        for result in results:
            self._add_repair_result_item(result)

        # 重启提示
        restart_hint = QLabel("修复完成后建议重启电脑，使所有设置完全生效")
        restart_hint.setAlignment(Qt.AlignCenter)
        restart_hint.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.PRIMARY};
            padding: 10px 0;
        """)
        self.repair_results_layout.addWidget(restart_hint)

        self.repair_results_layout.addStretch()
        self._set_status("修复完成")

        # 实时日志补一行完成标记
        self.repair_log_view.appendPlainText(
            f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 修复完成：{summary}")

        self.cache.save_result("repair", results)

        # 总结弹窗
        icon = QMessageBox.Information if status == "ok" else (QMessageBox.Warning if status == "warning" else QMessageBox.Critical)
        msg_box = QMessageBox(self)
        msg_box.setIcon(icon)
        msg_box.setWindowTitle("修复完成")
        msg_box.setText(summary)
        msg_box.setInformativeText("修复完成后建议重启电脑，使所有设置完全生效。")
        msg_box.setStandardButtons(QMessageBox.Ok)
        msg_box.exec()

    def _clear_repair_results(self):
        """清空修复结果"""
        while self.repair_results_layout.count() > 0:
            item = self.repair_results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _add_repair_result_item(self, result):
        """添加修复结果项"""
        item_frame = QFrame()
        item_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_RAISED};
                border-radius: 6px;
                padding: 10px;
            }}
        """)
        item_layout = QHBoxLayout(item_frame)
        item_layout.setContentsMargins(15, 10, 15, 10)
        item_layout.setSpacing(15)

        icon = "√" if result["success"] else "×"
        color = Colors.SUCCESS if result["success"] else Colors.ERROR

        icon_label = QLabel(icon)
        icon_label.setStyleSheet("font-size: 18px;")
        icon_label.setFixedWidth(30)
        item_layout.addWidget(icon_label)

        name_label = QLabel(result["name"])
        name_label.setStyleSheet(f"""
            font-size: 14px;
            font-weight: bold;
            color: {Colors.TEXT_MAIN};
        """)
        name_label.setFixedWidth(130)
        item_layout.addWidget(name_label)

        msg_label = QLabel(result["message"])
        msg_label.setStyleSheet(f"""
            font-size: 13px;
            color: {color};
        """)
        msg_label.setWordWrap(True)
        item_layout.addWidget(msg_label, 1)

        self.repair_results_layout.addWidget(item_frame)

    # ==================== 测速页面 ====================
    def _create_speed_page(self):
        """创建测速页面"""
        self.speed_page = QWidget()
        layout = QVBoxLayout(self.speed_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        # 测速按钮
        btn_card = self._create_card()
        btn_layout = QVBoxLayout(btn_card)
        btn_layout.setContentsMargins(30, 20, 30, 20)
        btn_layout.setSpacing(15)

        self.speed_btn = QPushButton("开始测速")
        self.speed_btn.setFixedHeight(50)
        self.speed_btn.setCursor(Qt.PointingHandCursor)
        self.speed_btn.setStyleSheet(theme.accent_button())
        self.speed_btn.clicked.connect(self._start_speed_test)
        btn_layout.addWidget(self.speed_btn)

        self.speed_progress = QProgressBar()
        self.speed_progress.setFixedHeight(20)
        self.speed_progress.setTextVisible(False)
        self.speed_progress.setStyleSheet(theme.progress_bar(chunk_color=Colors.PRIMARY))
        self.speed_progress.hide()
        btn_layout.addWidget(self.speed_progress)

        self.speed_status_label = QLabel("")
        self.speed_status_label.setAlignment(Qt.AlignCenter)
        self.speed_status_label.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_SECONDARY};
        """)
        self.speed_status_label.hide()
        btn_layout.addWidget(self.speed_status_label)

        layout.addWidget(btn_card)

        # 结果卡片区域
        results_layout = QHBoxLayout()
        results_layout.setSpacing(15)

        # 延迟卡片
        ping_card = self._create_card()
        ping_layout = QVBoxLayout(ping_card)
        ping_layout.setContentsMargins(20, 20, 20, 20)
        ping_layout.setSpacing(8)

        ping_title = QLabel("网络延迟")
        ping_title.setAlignment(Qt.AlignCenter)
        ping_title.setStyleSheet(f"""
            font-size: 14px;
            color: {Colors.TEXT_SECONDARY};
        """)
        ping_layout.addWidget(ping_title)

        self.ping_value = QLabel("--")
        self.ping_value.setAlignment(Qt.AlignCenter)
        self.ping_value.setStyleSheet(f"""
            font-size: 42px;
            font-weight: bold;
            color: {Colors.TEXT_LIGHT};
        """)
        ping_layout.addWidget(self.ping_value)

        ping_unit = QLabel("毫秒 (ms)")
        ping_unit.setAlignment(Qt.AlignCenter)
        ping_unit.setStyleSheet(f"""
            font-size: 12px;
            color: {Colors.TEXT_LIGHT};
        """)
        ping_layout.addWidget(ping_unit)

        self.ping_level = QLabel("等待测试")
        self.ping_level.setAlignment(Qt.AlignCenter)
        self.ping_level.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_LIGHT};
            padding-top: 5px;
        """)
        ping_layout.addWidget(self.ping_level)

        results_layout.addWidget(ping_card)

        # 下载速度卡片
        download_card = self._create_card()
        dl_layout = QVBoxLayout(download_card)
        dl_layout.setContentsMargins(20, 20, 20, 20)
        dl_layout.setSpacing(8)

        dl_title = QLabel("下载速度")
        dl_title.setAlignment(Qt.AlignCenter)
        dl_title.setStyleSheet(f"""
            font-size: 14px;
            color: {Colors.TEXT_SECONDARY};
        """)
        dl_layout.addWidget(dl_title)

        self.download_value = QLabel("--")
        self.download_value.setAlignment(Qt.AlignCenter)
        self.download_value.setStyleSheet(f"""
            font-size: 42px;
            font-weight: bold;
            color: {Colors.TEXT_LIGHT};
        """)
        dl_layout.addWidget(self.download_value)

        dl_unit = QLabel("Mbps")
        dl_unit.setAlignment(Qt.AlignCenter)
        dl_unit.setStyleSheet(f"""
            font-size: 12px;
            color: {Colors.TEXT_LIGHT};
        """)
        dl_layout.addWidget(dl_unit)

        self.download_level = QLabel("等待测试")
        self.download_level.setAlignment(Qt.AlignCenter)
        self.download_level.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_LIGHT};
            padding-top: 5px;
        """)
        dl_layout.addWidget(self.download_level)

        results_layout.addWidget(download_card)

        # 上传速度卡片
        upload_card = self._create_card()
        ul_layout = QVBoxLayout(upload_card)
        ul_layout.setContentsMargins(20, 20, 20, 20)
        ul_layout.setSpacing(8)

        ul_title = QLabel("上传速度")
        ul_title.setAlignment(Qt.AlignCenter)
        ul_title.setStyleSheet(f"""
            font-size: 14px;
            color: {Colors.TEXT_SECONDARY};
        """)
        ul_layout.addWidget(ul_title)

        self.upload_value = QLabel("--")
        self.upload_value.setAlignment(Qt.AlignCenter)
        self.upload_value.setStyleSheet(f"""
            font-size: 42px;
            font-weight: bold;
            color: {Colors.TEXT_LIGHT};
        """)
        ul_layout.addWidget(self.upload_value)

        ul_unit = QLabel("Mbps")
        ul_unit.setAlignment(Qt.AlignCenter)
        ul_unit.setStyleSheet(f"""
            font-size: 12px;
            color: {Colors.TEXT_LIGHT};
        """)
        ul_layout.addWidget(ul_unit)

        self.upload_level = QLabel("等待测试")
        self.upload_level.setAlignment(Qt.AlignCenter)
        self.upload_level.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_LIGHT};
            padding-top: 5px;
        """)
        ul_layout.addWidget(self.upload_level)

        results_layout.addWidget(upload_card)

        layout.addLayout(results_layout)

        # 实时网速卡片
        net_card = self._create_card()
        net_layout = QVBoxLayout(net_card)
        net_layout.setContentsMargins(20, 15, 20, 15)
        net_layout.setSpacing(10)

        net_title = QLabel("实时网速（每秒刷新，计算机当前全部网卡流量）")
        net_title.setStyleSheet(f"""
            font-size: 14px;
            font-weight: bold;
            color: {Colors.TEXT_MAIN};
        """)
        net_layout.addWidget(net_title)

        net_row = QHBoxLayout()
        net_row.setSpacing(20)

        up_box = QFrame()
        up_box.setStyleSheet(f"background-color: {Colors.PRIMARY_LIGHT}; border-radius: 10px;")
        up_l = QVBoxLayout(up_box)
        up_l.setContentsMargins(16, 12, 16, 12)
        up_tag = QLabel("▲ 上传")
        up_tag.setAlignment(Qt.AlignCenter)
        up_tag.setStyleSheet(f"font-size: 12px; color: {Colors.PRIMARY_DARK};")
        up_l.addWidget(up_tag)
        self.net_up_label = QLabel("--")
        self.net_up_label.setAlignment(Qt.AlignCenter)
        self.net_up_label.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {Colors.TEXT_MAIN};")
        up_l.addWidget(self.net_up_label)

        dn_box = QFrame()
        dn_box.setStyleSheet(f"background-color: {Colors.PRIMARY_LIGHT}; border-radius: 10px;")
        dn_l = QVBoxLayout(dn_box)
        dn_l.setContentsMargins(16, 12, 16, 12)
        dn_tag = QLabel("▼ 下载")
        dn_tag.setAlignment(Qt.AlignCenter)
        dn_tag.setStyleSheet(f"font-size: 12px; color: {Colors.PRIMARY_DARK};")
        dn_l.addWidget(dn_tag)
        self.net_dn_label = QLabel("--")
        self.net_dn_label.setAlignment(Qt.AlignCenter)
        self.net_dn_label.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {Colors.TEXT_MAIN};")
        dn_l.addWidget(self.net_dn_label)

        net_row.addWidget(up_box, 1)
        net_row.addWidget(dn_box, 1)
        net_layout.addLayout(net_row)

        if not self.traffic.enabled:
            hint = QLabel("提示：未安装 psutil，实时网速不可用（不影响测速）")
            hint.setStyleSheet(f"font-size: 12px; color: {Colors.WARNING};")
            net_layout.addWidget(hint)

        layout.addWidget(net_card)

        # 小知识
        tip_card = QFrame()
        tip_card.setStyleSheet(f"""
            background-color: {Colors.PRIMARY_LIGHT};
            border-radius: 8px;
        """)
        tip_layout = QHBoxLayout(tip_card)
        tip_layout.setContentsMargins(20, 12, 20, 12)

        tip_icon = QLabel("!")
        tip_icon.setStyleSheet("font-size: 20px;")
        tip_layout.addWidget(tip_icon)

        tip_text = QLabel("小知识：Mbps是网速单位，10Mbps ≈ 每秒下载1MB。网速越高，打开网页和下载文件越快。")
        tip_text.setStyleSheet(f"""
            font-size: 12px;
            color: {Colors.PRIMARY_DARK};
        """)
        tip_layout.addWidget(tip_text, 1)

        layout.addWidget(tip_card)
        layout.addStretch()

    def _start_speed_test(self):
        """开始测速"""
        self.logger.info("开始网速测试")
        self.speed_btn.setEnabled(False)
        self.speed_btn.setText("测速中...")
        self.speed_progress.show()
        self.speed_status_label.show()
        self.speed_progress.setValue(0)

        self.ping_value.setText("--")
        self.ping_value.setStyleSheet(f"font-size: 42px; font-weight: bold; color: {Colors.TEXT_LIGHT};")
        self.ping_level.setText("测试中...")
        self.ping_level.setStyleSheet(f"font-size: 13px; color: {Colors.TEXT_LIGHT}; padding-top: 5px;")

        self.download_value.setText("--")
        self.download_value.setStyleSheet(f"font-size: 42px; font-weight: bold; color: {Colors.TEXT_LIGHT};")
        self.download_level.setText("等待中（实时显示当前速度）...")
        self.download_level.setStyleSheet(f"font-size: 13px; color: {Colors.TEXT_LIGHT}; padding-top: 5px;")

        self.upload_value.setText("--")
        self.upload_value.setStyleSheet(f"font-size: 42px; font-weight: bold; color: {Colors.TEXT_LIGHT};")
        self.upload_level.setText("等待中...")
        self.upload_level.setStyleSheet(f"font-size: 13px; color: {Colors.TEXT_LIGHT}; padding-top: 5px;")

        self._set_status("正在进行网速测试...")

        self.worker = SpeedTestWorker()
        self.worker.progress.connect(self._on_speed_progress)
        self.worker.status.connect(self._on_speed_status)
        self.worker.live.connect(self._on_speed_live)
        self.worker.upline.connect(self._on_speed_uplive)
        self.worker.finished.connect(self._on_speed_finished)
        self._start_worker(self.worker)

    def _on_speed_progress(self, percent):
        """测速进度更新"""
        self.speed_progress.setValue(percent)

    def _on_speed_status(self, text):
        """测速状态更新"""
        self.speed_status_label.setText(text)

    def _on_speed_live(self, mbps):
        """实时显示当前瞬时下载速度"""
        self.download_value.setText(f"{mbps:.1f}")
        self.download_value.setStyleSheet(
            f"font-size: 42px; font-weight: bold; color: {Colors.PRIMARY};")
        self.download_level.setText("实时测速中...")

    def _on_speed_uplive(self, mbps):
        """实时显示当前瞬时上传速度"""
        self.upload_value.setText(f"{mbps:.1f}")
        self.upload_value.setStyleSheet(
            f"font-size: 42px; font-weight: bold; color: {Colors.PRIMARY};")
        self.upload_level.setText("实时上传测速中...")

    def _fmt_rate(self, bps):
        """把字节/秒格式化为易读字符串"""
        if bps is None:
            return "--"
        if bps < 0:
            bps = 0.0
        if bps >= 1024 * 1024:
            return f"{bps / (1024 * 1024):.1f} MB/s"
        if bps >= 1024:
            return f"{bps / 1024:.0f} KB/s"
        return f"{bps:.0f} B/s"

    def _update_net_rates(self):
        """每帧由定时器调用，更新底部实时网速显示（psutil 缺失时给一次性提示）"""
        up, dn = self.traffic.sample()
        if not self.traffic.enabled:
            if not getattr(self, "_psutil_warned", False):
                self._psutil_warned = True
                self._set_status("实时网速暂不可用（缺少 psutil 组件），其余功能正常")
            return
        up_l = getattr(self, "net_up_label", None)
        dn_l = getattr(self, "net_dn_label", None)
        if up_l is not None:
            up_l.setText(self._fmt_rate(up))
        if dn_l is not None:
            dn_l.setText(self._fmt_rate(dn))
        bup = getattr(self, "bottom_up_label", None)
        bdn = getattr(self, "bottom_down_label", None)
        if bup is not None:
            bup.setText("↑ " + self._fmt_rate(up))
        if bdn is not None:
            bdn.setText("↓ " + self._fmt_rate(dn))

    def _on_speed_finished(self, results):
        """测速完成"""
        self.speed_btn.setEnabled(True)
        self.speed_btn.setText("重新测速")
        self.speed_progress.hide()
        self.speed_status_label.hide()

        # 延迟结果
        ping_result = results.get("ping", {})
        if ping_result.get("success"):
            latency = ping_result["avg_latency"]
            self.ping_value.setText(str(latency))
            self.ping_value.setStyleSheet(f"font-size: 42px; font-weight: bold; color: {Colors.TEXT_MAIN};")

            level_text, level_key, _ = self.speed_test.get_latency_level(latency)
            level_color = LEVEL_COLORS.get(level_key, Colors.TEXT_MAIN)
            jitter = ping_result.get("jitter_ms")
            loss = ping_result.get("loss_rate", 0)
            detail = level_text
            if jitter is not None:
                detail += f"  ·  抖动{jitter}ms"
            if loss:
                detail += f"  ·  丢包{loss}%"
            self.ping_level.setText(detail)
            self.ping_level.setStyleSheet(f"font-size: 13px; color: {level_color}; padding-top: 5px; font-weight: bold;")
        else:
            self.ping_value.setText("失败")
            self.ping_value.setStyleSheet(f"font-size: 42px; font-weight: bold; color: {Colors.ERROR};")
            self.ping_level.setText("无法测试")
            self.ping_level.setStyleSheet(f"font-size: 13px; color: {Colors.ERROR}; padding-top: 5px;")

        # 下载速度结果
        download_result = results.get("download", {})
        if download_result.get("success"):
            speed = download_result["speed_mbps"]
            self.download_value.setText(str(speed))
            self.download_value.setStyleSheet(f"font-size: 42px; font-weight: bold; color: {Colors.TEXT_MAIN};")

            level_text, level_key, _ = self.speed_test.get_speed_level(speed)
            level_color = LEVEL_COLORS.get(level_key, Colors.TEXT_MAIN)
            sources = download_result.get("sources")
            peak = download_result.get("peak_mbps")
            detail = level_text
            if sources:
                detail += f"  ·  {sources} 个测速源"
            if peak is not None:
                detail += f"  ·  峰值 {peak}Mbps"
            self.download_level.setText(detail)
            self.download_level.setStyleSheet(f"font-size: 13px; color: {level_color}; padding-top: 5px; font-weight: bold;")
        else:
            self.download_value.setText("失败")
            self.download_value.setStyleSheet(f"font-size: 42px; font-weight: bold; color: {Colors.ERROR};")
            self.download_level.setText("无法测试")
            self.download_level.setStyleSheet(f"font-size: 13px; color: {Colors.ERROR}; padding-top: 5px;")

        # 上传速度结果
        upload_result = results.get("upload", {})
        if upload_result.get("success"):
            up_speed = upload_result["speed_mbps"]
            self.upload_value.setText(str(up_speed))
            self.upload_value.setStyleSheet(f"font-size: 42px; font-weight: bold; color: {Colors.TEXT_MAIN};")

            _, up_key, _ = self.speed_test.get_speed_level(up_speed)
            up_color = LEVEL_COLORS.get(up_key, Colors.TEXT_MAIN)
            peak = upload_result.get("peak_mbps")
            conns = upload_result.get("connections")
            detail = f"{conns} 路上传"
            if peak is not None:
                detail += f"  ·  峰值 {peak}Mbps"
            self.upload_level.setText(detail)
            self.upload_level.setStyleSheet(f"font-size: 13px; color: {up_color}; padding-top: 5px; font-weight: bold;")
        else:
            self.upload_value.setText("暂不可测")
            self.upload_value.setStyleSheet(f"font-size: 28px; font-weight: bold; color: {Colors.WARNING};")
            self.upload_level.setText("本次无法连接到上传服务器，不影响其它指标")
            self.upload_level.setStyleSheet(f"font-size: 12px; color: {Colors.WARNING}; padding-top: 5px;")

        self._set_status("测速完成")

        self.cache.save_result("speed", results)

    # ==================== DNS优化页面 ====================
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
            empty = QLabel("暂无设备。点击右上角「扫描设备」刷新。" if not self._devices else "当前筛选条件下没有设备。")
            empty.setStyleSheet(f"color: {Colors.TEXT_LIGHT}; font-size: 13px; padding: 24px;")
            self.dev_list_layout.insertWidget(self.dev_list_layout.count() - 1, empty)

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

    def _create_dns_page(self):
        """创建DNS优化页面"""
        self.dns_page = QWidget()
        layout = QVBoxLayout(self.dns_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        # 当前DNS信息
        info_card = self._create_card()
        info_layout = QHBoxLayout(info_card)
        info_layout.setContentsMargins(25, 15, 25, 15)

        info_icon = QLabel("●")
        info_icon.setStyleSheet("font-size: 24px;")
        info_icon.setFixedWidth(35)
        info_layout.addWidget(info_icon)

        info_text_layout = QVBoxLayout()
        info_text_layout.setSpacing(3)

        info_title = QLabel("当前DNS")
        info_title.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_SECONDARY};
        """)
        info_text_layout.addWidget(info_title)

        self.current_dns_label = QLabel("检测中...")
        self.current_dns_label.setStyleSheet(f"""
            font-size: 15px;
            font-weight: bold;
            color: {Colors.PRIMARY};
        """)
        info_text_layout.addWidget(self.current_dns_label)

        info_layout.addLayout(info_text_layout, 1)
        layout.addWidget(info_card)

        # 测试按钮
        btn_card = self._create_card()
        btn_layout = QVBoxLayout(btn_card)
        btn_layout.setContentsMargins(30, 20, 30, 20)
        btn_layout.setSpacing(15)

        self.dns_btn = QPushButton("测试所有DNS，推荐最优")
        self.dns_btn.setFixedHeight(50)
        self.dns_btn.setCursor(Qt.PointingHandCursor)
        self.dns_btn.setStyleSheet(theme.accent_button())
        self.dns_btn.clicked.connect(self._start_dns_test)
        btn_layout.addWidget(self.dns_btn)

        self.dns_progress = QProgressBar()
        self.dns_progress.setFixedHeight(20)
        self.dns_progress.setTextVisible(False)
        self.dns_progress.setStyleSheet(theme.progress_bar(chunk_color=Colors.PRIMARY))
        self.dns_progress.hide()
        btn_layout.addWidget(self.dns_progress)

        self.dns_progress_label = QLabel("")
        self.dns_progress_label.setAlignment(Qt.AlignCenter)
        self.dns_progress_label.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_SECONDARY};
        """)
        self.dns_progress_label.hide()
        btn_layout.addWidget(self.dns_progress_label)

        layout.addWidget(btn_card)

        # 推荐结果
        self.dns_recommend_card = self._create_card()
        rec_layout = QHBoxLayout(self.dns_recommend_card)
        rec_layout.setContentsMargins(25, 15, 25, 15)

        rec_icon = QLabel("★")
        rec_icon.setStyleSheet("font-size: 28px;")
        rec_icon.setFixedWidth(40)
        rec_layout.addWidget(rec_icon)

        self.dns_recommend_text = QLabel("点击上方按钮，测试并推荐最优DNS服务器")
        self.dns_recommend_text.setWordWrap(True)
        self.dns_recommend_text.setStyleSheet(f"""
            font-size: 14px;
            color: {Colors.TEXT_SECONDARY};
        """)
        rec_layout.addWidget(self.dns_recommend_text, 1)

        layout.addWidget(self.dns_recommend_card)

        # DNS列表 - 滚动区域
        list_card = self._create_card()
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(15, 15, 15, 15)

        list_title = QLabel("DNS服务器排名")
        list_title.setStyleSheet(f"""
            font-size: 14px;
            font-weight: bold;
            color: {Colors.TEXT_MAIN};
            padding-bottom: 10px;
        """)
        list_layout.addWidget(list_title)

        # 表头
        header_frame = QFrame()
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(10, 5, 10, 5)
        header_layout.setSpacing(0)

        headers = [("排名", 46), ("DNS名称", 96), ("DNS地址", 150), ("延迟", 70), ("地区", 52), ("延迟对比", 0)]
        for text, width in headers:
            label = QLabel(text)
            label.setStyleSheet(f"""
                font-size: 12px;
                font-weight: bold;
                color: {Colors.TEXT_LIGHT};
            """)
            if width:
                label.setFixedWidth(width)
            header_layout.addWidget(label, 1 if width == 0 else 0)

        list_layout.addWidget(header_frame)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"background-color: {Colors.BORDER}; max-height: 1px;")
        list_layout.addWidget(line)

        # 列表滚动区
        list_scroll = QScrollArea()
        list_scroll.setWidgetResizable(True)
        list_scroll.setMinimumHeight(200)
        list_scroll.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: {Colors.BG_INSET};
            }}
            QScrollBar:vertical {{
                width: 8px;
                background: {Colors.BG_INSET};
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {Colors.SHADOW_DARK};
                border-radius: 4px;
            }}
        """)

        self.dns_list_widget = QWidget()
        self.dns_list_layout = QVBoxLayout(self.dns_list_widget)
        self.dns_list_layout.setContentsMargins(10, 5, 10, 5)
        self.dns_list_layout.setSpacing(3)

        # 初始提示
        hint = QLabel("点击上方按钮开始测试...")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_LIGHT};
            padding: 20px 0;
        """)
        self.dns_list_layout.addWidget(hint)

        self.dns_list_layout.addStretch()
        list_scroll.setWidget(self.dns_list_widget)
        list_layout.addWidget(list_scroll, 1)

        layout.addWidget(list_card, 1)

        # 加载当前DNS
        self._load_current_dns()

    def _load_current_dns(self):
        """加载当前DNS"""
        dns_list = self.dns_optimizer.get_current_dns()
        dns_text = "、".join(dns_list)
        self.current_dns_label.setText(dns_text)

    def _start_dns_test(self):
        """开始DNS测试"""
        self.logger.info("开始DNS测试")
        self.dns_btn.setEnabled(False)
        self.dns_btn.setText("测试中...")
        self.dns_progress.show()
        self.dns_progress_label.show()
        self.dns_progress.setValue(0)

        self._clear_dns_list()

        self._set_status("正在测试DNS服务器...")

        self.worker = DnsTestWorker()
        self.worker.progress.connect(self._on_dns_progress)
        self.worker.finished.connect(self._on_dns_finished)
        self._start_worker(self.worker)

    def _on_dns_progress(self, percent, name):
        """DNS测试进度"""
        self.dns_progress.setValue(percent)
        self.dns_progress_label.setText(f"正在测试: {name} ({percent}%)")

    def _on_dns_finished(self, results):
        """DNS测试完成"""
        self.dns_btn.setEnabled(True)
        self.dns_btn.setText("重新测试")
        self.dns_progress.hide()
        self.dns_progress_label.hide()

        # 推荐最佳DNS
        best_dns, advice = self.dns_optimizer.get_best_dns(results)
        if best_dns:
            self.dns_recommend_text.setText(
                f"推荐使用: {best_dns['name']} ({best_dns['ip']})\n"
                f"延迟: {best_dns['latency']}ms | {advice}"
            )
            self.dns_recommend_text.setStyleSheet(f"""
                font-size: 14px;
                color: {Colors.SUCCESS};
                font-weight: bold;
                line-height: 1.6;
            """)
        else:
            self.dns_recommend_text.setText(f"{advice}")
            self.dns_recommend_text.setStyleSheet(f"""
                font-size: 14px;
                color: {Colors.ERROR};
                font-weight: bold;
            """)

        # 显示列表
        self._clear_dns_list()

        # 统一比例：以所有可用 DNS 中的最大延迟为满刻度，便于横向对比快慢
        latencies = [d.get("latency") for d in results if d.get("success")]
        max_latency = max(latencies) if latencies else 1

        for i, dns in enumerate(results):
            self._add_dns_list_item(i + 1, dns, max_latency)

        # 应用按钮必须加在 addStretch() 之前，否则会被挤压到底部不可见
        if best_dns:
            apply_btn = QPushButton("一键应用最优DNS")
            apply_btn.setFixedHeight(40)
            apply_btn.setCursor(Qt.PointingHandCursor)
            apply_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {Colors.PRIMARY};
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-size: 14px;
                    font-weight: bold;
                    margin-top: 8px;
                }}
                QPushButton:hover {{
                    background-color: {Colors.PRIMARY_DARK};
                }}
                QPushButton:disabled {{
                    background-color: {Colors.SHADOW_DARK};
                }}
            """)
            self._dns_best_ip = best_dns["ip"]
            apply_btn.clicked.connect(self._apply_best_dns)
            self.dns_list_layout.addWidget(apply_btn)

        self.dns_list_layout.addStretch()
        self._set_status("DNS测试完成")

        self.cache.save_result("dns", results)

    def _clear_dns_list(self):
        """清空DNS列表"""
        while self.dns_list_layout.count() > 0:
            item = self.dns_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _add_dns_list_item(self, rank, dns, max_latency=1):
        """添加DNS列表项"""
        item_frame = QFrame()
        is_best = rank == 1
        bg_color = Colors.SUCCESS_LIGHT if is_best else Colors.BG_RAISED
        item_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_color};
                border-radius: 4px;
            }}
        """)
        item_layout = QHBoxLayout(item_frame)
        item_layout.setContentsMargins(10, 8, 10, 8)
        item_layout.setSpacing(0)

        # 排名
        rank_text = f"★ {rank}" if is_best else f"   {rank}"
        rank_color = Colors.SUCCESS if is_best else Colors.TEXT_SECONDARY
        rank_label = QLabel(rank_text)
        rank_label.setStyleSheet(f"""
            font-size: 13px;
            color: {rank_color};
            font-weight: {'bold' if is_best else 'normal'};
        """)
        rank_label.setFixedWidth(46)
        item_layout.addWidget(rank_label)

        # 名称
        name_label = QLabel(dns.get("name", ""))
        name_label.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_MAIN};
            font-weight: {'bold' if is_best else 'normal'};
        """)
        name_label.setFixedWidth(96)
        item_layout.addWidget(name_label)

        # IP
        ip_label = QLabel(dns.get("ip", ""))
        ip_label.setStyleSheet(f"""
            font-size: 12px;
            color: {Colors.TEXT_SECONDARY};
            font-family: Consolas, Monaco, monospace;
        """)
        ip_label.setFixedWidth(150)
        item_layout.addWidget(ip_label)

        # 延迟
        if dns.get("success"):
            latency = dns["latency"]
            latency_text = f"{latency}ms"
            if latency < 30:
                latency_color = Colors.SUCCESS
            elif latency < 100:
                latency_color = Colors.WARNING
            else:
                latency_color = Colors.ERROR
        else:
            latency_text = "不可用"
            latency_color = Colors.ERROR

        latency_label = QLabel(latency_text)
        latency_label.setStyleSheet(f"""
            font-size: 13px;
            color: {latency_color};
            font-weight: bold;
        """)
        latency_label.setFixedWidth(70)
        item_layout.addWidget(latency_label)

        # 地区
        region = dns.get("region", "")
        region_color = Colors.PRIMARY if region == "国内" else Colors.TEXT_LIGHT
        region_label = QLabel(region)
        region_label.setStyleSheet(f"""
            font-size: 12px;
            color: {region_color};
        """)
        region_label.setFixedWidth(52)
        item_layout.addWidget(region_label)

        # 延迟对比条（占满剩余宽度，统一满刻度）
        bar = LatencyBarWidget()
        if dns.get("success"):
            bar.set_latency(dns["latency"], max_latency, latency_color)
        else:
            bar.set_unavailable()
        item_layout.addWidget(bar, 1)

        self.dns_list_layout.addWidget(item_frame)

    # ==================== Wi-Fi检测页面 ====================
    def _create_wifi_page(self):
        """创建Wi-Fi检测页面"""
        self.wifi_page = QWidget()
        layout = QVBoxLayout(self.wifi_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        # 检测按钮
        btn_card = self._create_card()
        btn_layout = QVBoxLayout(btn_card)
        btn_layout.setContentsMargins(30, 20, 30, 20)

        self.wifi_btn = QPushButton("检测Wi-Fi状态")
        self.wifi_btn.setFixedHeight(50)
        self.wifi_btn.setCursor(Qt.PointingHandCursor)
        self.wifi_btn.setStyleSheet(theme.accent_button())
        self.wifi_btn.clicked.connect(self._start_wifi_check)
        btn_layout.addWidget(self.wifi_btn)

        layout.addWidget(btn_card)

        # Wi-Fi信息卡片
        info_layout = QHBoxLayout()
        info_layout.setSpacing(15)

        # 信号强度卡片
        signal_card = self._create_card()
        signal_layout = QVBoxLayout(signal_card)
        signal_layout.setContentsMargins(20, 20, 20, 20)
        signal_layout.setSpacing(8)

        signal_title = QLabel("信号强度")
        signal_title.setAlignment(Qt.AlignCenter)
        signal_title.setStyleSheet(f"""
            font-size: 14px;
            color: {Colors.TEXT_SECONDARY};
        """)
        signal_layout.addWidget(signal_title)

        self.wifi_signal_value = QLabel("--%")
        self.wifi_signal_value.setAlignment(Qt.AlignCenter)
        self.wifi_signal_value.setStyleSheet(f"""
            font-size: 42px;
            font-weight: bold;
            color: {Colors.TEXT_LIGHT};
        """)
        signal_layout.addWidget(self.wifi_signal_value)

        self.wifi_signal_level = QLabel("等待检测")
        self.wifi_signal_level.setAlignment(Qt.AlignCenter)
        self.wifi_signal_level.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_LIGHT};
            padding-top: 5px;
        """)
        signal_layout.addWidget(self.wifi_signal_level)

        # Wi-Fi 四段弧信号表（替换单调进度条，弱/满一眼可辨）
        self.wifi_signal_arc = SignalArcWidget()
        self.wifi_signal_arc.setFixedHeight(96)
        self.wifi_signal_arc.set_signal(0, Colors.TEXT_LIGHT)
        signal_layout.addWidget(self.wifi_signal_arc)

        info_layout.addWidget(signal_card)

        # Wi-Fi名称卡片
        name_card = self._create_card()
        name_layout = QVBoxLayout(name_card)
        name_layout.setContentsMargins(20, 20, 20, 20)
        name_layout.setSpacing(8)

        name_title = QLabel("Wi-Fi名称")
        name_title.setAlignment(Qt.AlignCenter)
        name_title.setStyleSheet(f"""
            font-size: 14px;
            color: {Colors.TEXT_SECONDARY};
        """)
        name_layout.addWidget(name_title)

        self.wifi_ssid_value = QLabel("--")
        self.wifi_ssid_value.setAlignment(Qt.AlignCenter)
        self.wifi_ssid_value.setWordWrap(True)
        self.wifi_ssid_value.setStyleSheet(f"""
            font-size: 22px;
            font-weight: bold;
            color: {Colors.TEXT_LIGHT};
        """)
        name_layout.addWidget(self.wifi_ssid_value, 1)

        self.wifi_channel_label = QLabel("")
        self.wifi_channel_label.setAlignment(Qt.AlignCenter)
        self.wifi_channel_label.setStyleSheet(f"""
            font-size: 12px;
            color: {Colors.TEXT_LIGHT};
        """)
        name_layout.addWidget(self.wifi_channel_label)

        info_layout.addWidget(name_card)

        layout.addLayout(info_layout)

        # 弱信号 / 冲突信道 橙色预警条（点击跳转一键优化）
        self.wifi_warn_bar = QFrame()
        self.wifi_warn_bar.setCursor(Qt.PointingHandCursor)
        self.wifi_warn_bar.mousePressEvent = self._on_wifi_warn_click
        self.wifi_warn_bar.setStyleSheet(f"""
            background-color: {Colors.WARNING_LIGHT};
            border-radius: {RADIUS_SMALL};
        """)
        _wl = QHBoxLayout(self.wifi_warn_bar)
        _wl.setContentsMargins(14, 10, 14, 10)
        self.wifi_warn_label = QLabel("")
        self.wifi_warn_label.setStyleSheet(
            f"color: {Colors.WARNING}; font-size: 13px; font-weight: bold;")
        _wl.addWidget(self.wifi_warn_label)
        _wl.addStretch()
        _warn_go = QLabel("去一键优化  →")
        _warn_go.setStyleSheet(f"color: {Colors.PRIMARY}; font-size: 13px; font-weight: bold;")
        _wl.addWidget(_warn_go)
        self.wifi_warn_bar.hide()
        layout.addWidget(self.wifi_warn_bar)

        # 优化建议
        advice_card = QFrame()
        advice_card.setStyleSheet(f"""
            background-color: {Colors.SUCCESS_LIGHT};
            border-radius: 8px;
        """)
        advice_layout = QVBoxLayout(advice_card)
        advice_layout.setContentsMargins(20, 15, 20, 15)
        advice_layout.setSpacing(8)

        advice_title = QLabel("Wi-Fi优化建议")
        advice_title.setStyleSheet(f"""
            font-size: 14px;
            font-weight: bold;
            color: {Colors.SUCCESS};
        """)
        advice_layout.addWidget(advice_title)

        self.wifi_advice_label = QLabel("点击上方按钮检测Wi-Fi状态，获取个性化优化建议")
        self.wifi_advice_label.setWordWrap(True)
        self.wifi_advice_label.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.SUCCESS};
            line-height: 1.8;
        """)
        advice_layout.addWidget(self.wifi_advice_label)

        # 复制诊断信息按钮（未连接/异常时显示，便于跨电脑排查）
        self.wifi_diag_btn = QPushButton("复制诊断信息")
        self.wifi_diag_btn.setCursor(Qt.PointingHandCursor)
        self.wifi_diag_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.BG_RAISED}; color: {Colors.TEXT_MAIN};
                border: 1px solid {Colors.BORDER}; border-radius: 6px;
                padding: 9px; font-size: 13px; font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {Colors.PRIMARY_LIGHT};
            }}
        """)
        self.wifi_diag_btn.clicked.connect(self._copy_diag_info)
        self.wifi_diag_btn.hide()
        advice_layout.addWidget(self.wifi_diag_btn)

        layout.addWidget(advice_card)
        layout.addStretch()

    def _start_wifi_check(self):
        """开始Wi-Fi检测"""
        self.logger.info("开始Wi-Fi检测")
        self.wifi_btn.setEnabled(False)
        self.wifi_btn.setText("检测中...")
        self._set_status("正在检测Wi-Fi...")

        self.worker = WifiCheckWorker()
        self.worker.finished.connect(self._on_wifi_finished)
        self._start_worker(self.worker)

    def _on_wifi_finished(self, info):
        """Wi-Fi检测完成（安全包装：任何异常都不会以报错形式外泄到界面）"""
        try:
            self._on_wifi_finished_impl(info)
        except Exception:
            self.logger.exception("Wi-Fi检测结果处理出现异常")
            self.wifi_btn.setEnabled(True)
            self.wifi_btn.setText("重新检测")
            self.wifi_signal_value.setText("--")
            self.wifi_ssid_value.setText("未连接Wi-Fi")
            self.wifi_advice_label.setText("检测遇到问题，请点击重新检测；若持续异常，请检查网络适配器是否正常")
            self.wifi_advice_label.setStyleSheet(
                f"font-size: 13px; color: {Colors.ERROR}; line-height: 1.8;")
            self._set_status("Wi-Fi检测完成（出现异常）")

    def _on_wifi_finished_impl(self, info):
        """Wi-Fi检测完成（内部实现）"""
        self.wifi_btn.setEnabled(True)
        self.wifi_btn.setText("重新检测")

        if info is None or not isinstance(info, dict):
            info = {"success": False, "connected": False,
                    "error": "未获取到Wi-Fi信息，请确认已安装无线网卡"}

        if not info.get("success") or not info.get("connected"):
            self.wifi_signal_value.setText("--")
            self.wifi_signal_value.setStyleSheet(f"font-size: 42px; font-weight: bold; color: {Colors.ERROR};")
            self.wifi_signal_level.setText("未连接")
            self.wifi_signal_level.setStyleSheet(f"font-size: 13px; color: {Colors.ERROR}; padding-top: 5px;")
            self.wifi_signal_arc.set_signal(0, Colors.ERROR)

            self.wifi_ssid_value.setText("未连接Wi-Fi")
            self.wifi_ssid_value.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {Colors.ERROR};")
            self.wifi_channel_label.setText("")

            error_msg = info.get("error") or "未连接到Wi-Fi网络：请连接Wi-Fi后重新检测"
            self.wifi_advice_label.setText(error_msg)
            self.wifi_advice_label.setStyleSheet(f"font-size: 13px; color: {Colors.ERROR}; line-height: 1.8;")
            self.wifi_diag_btn.show()
            self.wifi_warn_bar.hide()

            self._set_status("Wi-Fi检测完成（未连接）")
            return

        # 信号强度（netsh 不可用时由 ipconfig 兜底判定为已连接，无信号量则显示占位）
        fallback = info.get("_source") == "ipconfig" or "signal_strength" not in info
        if fallback:
            self.wifi_signal_value.setText("--")
            self.wifi_signal_value.setStyleSheet(f"font-size: 42px; font-weight: bold; color: {Colors.TEXT_MAIN};")
            self.wifi_signal_level.setText("已连接")
            self.wifi_signal_level.setStyleSheet(f"font-size: 13px; color: {Colors.SUCCESS}; padding-top: 5px; font-weight: bold;")
            self.wifi_signal_arc.set_signal(0, Colors.SUCCESS)
        else:
            signal = info.get("signal_strength", 0)
            self.wifi_signal_value.setText(f"{signal}%")
            self.wifi_signal_value.setStyleSheet(f"font-size: 42px; font-weight: bold; color: {Colors.TEXT_MAIN};")

            level_text, level_key, _ = self.wifi_checker.get_signal_level(signal)
            level_color = LEVEL_COLORS.get(level_key, Colors.TEXT_MAIN)
            self.wifi_signal_level.setText(level_text)
            self.wifi_signal_level.setStyleSheet(f"font-size: 13px; color: {level_color}; padding-top: 5px; font-weight: bold;")

            # 按信号强度点亮四段弧信号表
            self.wifi_signal_arc.set_signal(signal, level_color)

        # SSID
        if info.get("ssid"):
            ssid = info["ssid"]
        else:
            ssid = "已有网络连接（名称暂未获取）" if fallback else "未知"
        self.wifi_ssid_value.setText(ssid)
        self.wifi_ssid_value.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {Colors.TEXT_MAIN};")

        # 频道
        channel = info.get("channel", "")
        if channel:
            self.wifi_channel_label.setText(f"频道: {channel}")
            self.wifi_channel_label.setStyleSheet(f"font-size: 12px; color: {Colors.TEXT_SECONDARY};")
        elif fallback:
            self.wifi_channel_label.setText("信号强度与频道详情需升级驱动后获取")
            self.wifi_channel_label.setStyleSheet(f"font-size: 12px; color: {Colors.WARNING};")

        # 优化建议
        advice_list = self.wifi_checker.get_wifi_advice(info) or []
        if fallback:
            advice_list.insert(0, "已确认电脑连接了Wi-Fi网络。当前系统未返回信号强度等详情，可能与无线网卡驱动有关，可尝试重装/更新Wi-Fi驱动后重新检测。")
        advice_text = "\n".join(advice_list)
        self.wifi_advice_label.setText(advice_text)
        self.wifi_advice_label.setStyleSheet(f"font-size: 13px; color: {Colors.SUCCESS}; line-height: 1.8;")
        self._update_wifi_warning(info, fallback, advice_list)
        self.wifi_diag_btn.hide()
        self.wifi_diag_btn.setText("复制诊断信息")

        self._set_status("Wi-Fi检测完成")

        self.cache.save_result("wifi", info)

    def _on_wifi_warn_click(self, event):
        """点击预警条时跳转到一键修复页"""
        self._switch_page("repair")

    def _update_wifi_warning(self, info, fallback, advice_list):
        """根据检测结果显示弱信号/信道冲突的橙色预警条"""
        msg = ""
        if not fallback:
            signal = info.get("signal_strength", 100)
            if signal < 50:
                msg = "信号偏弱，可能影响网速，建议靠近路由器"
        if not msg:
            for a in advice_list:
                if any(k in a for k in ("信道", "拥堵", "干扰", "拥挤")):
                    msg = "检测到Wi-Fi信道可能拥挤或受干扰"
                    break
        if msg:
            self.wifi_warn_label.setText("!  " + msg)
            self.wifi_warn_bar.show()
        else:
            self.wifi_warn_bar.hide()

    def _run_diag_cmd(self, cmd):
        """安全运行命令并返回解码后的文本（逐条自动识别 GBK/UTF-8，禁止抛错）"""
        from core.cmd_utils import run_cmd
        return run_cmd(cmd, timeout=12)

    def _gather_wifi_diag(self):
        """汇总网络环境诊断文本（便于复制后跨电脑排查）"""
        parts = [
            "【网络优化助手 诊断信息】",
            f"版本: v{__version__}",
            f"系统: {platform.platform()}",
            f"Python/PyInstaller 目标: {platform.machine()}",
            f"生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "==== netsh wlan show interfaces ====",
            self._run_diag_cmd(["netsh", "wlan", "show", "interfaces"]),
            "",
            "==== netsh wlan show drivers ====",
            self._run_diag_cmd(["netsh", "wlan", "show", "drivers"]),
            "",
            "==== 无线本地信息 (ipconfig /all) ====",
            self._run_diag_cmd(["ipconfig", "/all"]),
        ]
        return "\n".join(parts)

    def _copy_diag_info(self):
        """一键复制诊断信息到剪贴板，并另存一份到软件同目录(便于迁移)"""
        diag = self._gather_wifi_diag()
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
        else:
            self.wifi_diag_btn.setText("复制失败")
            self._set_status("复制诊断信息失败，请重试")
        QTimer.singleShot(2500, lambda: self.wifi_diag_btn.setText("复制诊断信息"))

    def _apply_best_dns(self):
        """一键应用最优DNS"""
        dns_ip = getattr(self, "_dns_best_ip", None)
        if not dns_ip:
            return

        reply = QMessageBox.question(
            self, "确认设置DNS",
            f"即将将DNS设置为 {dns_ip}\n\n"
            "这会修改您电脑的网络设置，需要管理员权限。\n"
            "设置后可能需要重启浏览器才能生效。\n\n"
            "是否继续？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self._set_status("正在设置DNS...")

        success, message = self.dns_optimizer.set_dns(dns_ip)
        if success:
            QMessageBox.information(self, "设置成功", message)
            self._load_current_dns()
        else:
            QMessageBox.warning(self, "设置失败", message)

        self._set_status("就绪")

    # ==================== 历史记录页面 ====================
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
            self.dl_pause_btn.setText("暂停")
            self._set_status("已继续下载")
        else:
            d.pause()
            self.dl_pause_btn.setText("继续")
            self._set_status("已暂停下载")

    def _cancel_download(self):
        d = self._dl
        if d is None:
            return
        d.cancel()
        self.dl_cancel_btn.setEnabled(False)
        self._set_status("正在取消下载...")

    def _create_history_page(self):
        """创建历史记录页面"""
        self.history_page = QWidget()
        layout = QVBoxLayout(self.history_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        # 操作栏
        btn_card = self._create_card()
        btn_layout = QHBoxLayout(btn_card)
        btn_layout.setContentsMargins(25, 15, 25, 15)
        btn_layout.setSpacing(10)

        refresh_btn = QPushButton("刷新记录")
        refresh_btn.setFixedHeight(38)
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.PRIMARY};
                color: {Colors.TEXT_ON_ACCENT};
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-weight: bold;
                padding: 0 20px;
            }}
            QPushButton:hover {{
                background-color: {Colors.PRIMARY_DARK};
            }}
        """)
        refresh_btn.clicked.connect(self._load_history)
        btn_layout.addWidget(refresh_btn)

        clear_btn = QPushButton("清除所有记录")
        clear_btn.setFixedHeight(38)
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.ERROR};
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-weight: bold;
                padding: 0 20px;
            }}
            QPushButton:hover {{
                background-color: #cf6262;
            }}
        """)
        clear_btn.clicked.connect(self._clear_history)
        btn_layout.addWidget(clear_btn)

        log_btn = QPushButton("打开数据文件夹")
        log_btn.setFixedHeight(38)
        log_btn.setCursor(Qt.PointingHandCursor)
        log_btn.setToolTip("打开日志和历史记录所在的文件夹，反馈Bug时可一并提供")
        log_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.BG_RAISED};
                color: {Colors.TEXT_MAIN};
                border: 1px solid {Colors.BORDER};
                border-radius: 6px;
                font-size: 13px;
                padding: 0 20px;
            }}
            QPushButton:hover {{
                background-color: {Colors.PRIMARY_LIGHT};
            }}
        """)
        log_btn.clicked.connect(self._open_log_dir)
        btn_layout.addWidget(log_btn)

        btn_layout.addStretch()
        layout.addWidget(btn_card)

        # 历史记录内容
        results_scroll = QScrollArea()
        results_scroll.setWidgetResizable(True)
        results_scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: {Colors.BG_CARD};
                border-radius: 8px;
                border: none;
            }}
            QScrollBar:vertical {{
                width: 8px;
                background: {Colors.BG_INSET};
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {Colors.SHADOW_DARK};
                border-radius: 4px;
            }}
        """)

        self.history_widget = QWidget()
        self.history_layout = QVBoxLayout(self.history_widget)
        self.history_layout.setContentsMargins(25, 15, 25, 15)
        self.history_layout.setSpacing(10)

        results_scroll.setWidget(self.history_widget)
        layout.addWidget(results_scroll, 1)

        self._load_history()

    def _load_history(self):
        """加载历史记录"""
        while self.history_layout.count() > 0:
            item = self.history_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        all_data = self.cache.get_all_history()

        category_labels = {
            "diagnostic": ("诊断记录", Colors.PRIMARY),
            "repair": ("修复记录", Colors.SUCCESS),
            "speed": ("测速记录", Colors.PRIMARY),
            "dns": ("DNS测试记录", Colors.PRIMARY),
            "wifi": ("Wi-Fi检测记录", Colors.PRIMARY),
        }

        has_records = False

        for category, (label_text, color) in category_labels.items():
            records = all_data.get(category, [])
            if not records:
                continue

            has_records = True

            # 分类标题
            cat_label = QLabel(label_text)
            cat_label.setStyleSheet(f"""
                font-size: 15px;
                font-weight: bold;
                color: {color};
                padding: 10px 0 5px 0;
            """)
            self.history_layout.addWidget(cat_label)

            # 最近5条记录
            for record in records[-5:]:
                self._add_history_item(record, category)

        if not has_records:
            hint = QLabel("暂无历史记录\n\n使用「一键诊断」「一键修复」「网速测试」等功能后，\n结果会自动保存在这里，方便您下次查看")
            hint.setAlignment(Qt.AlignCenter)
            hint.setStyleSheet(f"""
                font-size: 14px;
                color: {Colors.TEXT_LIGHT};
                padding: 60px 0;
            """)
            self.history_layout.addWidget(hint)

        self.history_layout.addStretch()

    def _add_history_item(self, record, category):
        """添加历史记录项"""
        item_frame = QFrame()
        item_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_RAISED};
                border-radius: 6px;
            }}
        """)
        item_layout = QVBoxLayout(item_frame)
        item_layout.setContentsMargins(15, 10, 15, 10)
        item_layout.setSpacing(5)

        # 时间戳
        time_label = QLabel(record.get("timestamp", "未知时间"))
        time_label.setStyleSheet(f"""
            font-size: 12px;
            color: {Colors.TEXT_LIGHT};
        """)
        item_layout.addWidget(time_label)

        # 结果摘要
        result = record.get("result", {})
        summary_text = self._format_history_summary(category, result)

        summary_label = QLabel(summary_text)
        summary_label.setWordWrap(True)
        summary_label.setStyleSheet(f"""
            font-size: 13px;
            color: {Colors.TEXT_SECONDARY};
        """)
        item_layout.addWidget(summary_label)

        self.history_layout.addWidget(item_frame)

    def _format_history_summary(self, category, result):
        """格式化历史记录摘要"""
        try:
            if category == "diagnostic":
                ok = sum(1 for r in result if r.get("status") == "ok")
                warn = sum(1 for r in result if r.get("status") == "warning")
                err = sum(1 for r in result if r.get("status") == "error")
                return f"正常{ok}项 | 警告{warn}项 | 异常{err}项"

            elif category == "repair":
                ok = sum(1 for r in result if r.get("success"))
                fail = sum(1 for r in result if not r.get("success"))
                return f"成功{ok}项 | 失败{fail}项"

            elif category == "speed":
                ping = result.get("ping", {})
                dl = result.get("download", {})
                ul = result.get("upload", {})
                latency = ping.get("avg_latency", "--")
                speed = dl.get("speed_mbps", "--")
                up = ul.get("speed_mbps", "--")
                return f"延迟: {latency}ms | 下载: {speed}Mbps | 上传: {up}Mbps"

            elif category == "dns":
                best = None
                for r in result:
                    if r.get("success"):
                        best = r
                        break
                if best:
                    return f"最优DNS: {best.get('name', '')} ({best.get('ip', '')}) 延迟{best.get('latency', '--')}ms"
                return "DNS测试无可用结果"

            elif category == "wifi":
                if result.get("connected"):
                    ssid = result.get("ssid", "未知")
                    signal = result.get("signal_strength", 0)
                    return f"Wi-Fi: {ssid} | 信号: {signal}%"
                else:
                    return "Wi-Fi未连接"

        except Exception:
            pass

        return "记录详情不可用"

    def _open_log_dir(self):
        """打开数据文件夹（包含日志和历史记录），便于反馈Bug时提供"""
        self.logger.info("用户打开数据文件夹")
        from core.paths import get_data_dir
        data_dir = get_data_dir()
        try:
            import os
            if not os.path.exists(data_dir):
                os.makedirs(data_dir)
            os.startfile(data_dir)
        except Exception:
            QMessageBox.information(
                self, "数据位置", "数据文件夹位于：\n" + data_dir)

    def _clear_history(self):
        """清除所有历史记录"""
        reply = QMessageBox.question(
            self, "确认清除",
            "确定要清除所有历史记录吗？\n此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.cache.clear_history()
        self._load_history()
        self._set_status("历史记录已清除")
