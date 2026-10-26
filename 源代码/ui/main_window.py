"""
主窗口 - 网络优化助手

窗口骨架、导航与后台任务调度保留在此；各功能页面位于 ui/pages/，
工作线程位于 ui/workers.py，公共配色位于 ui/common.py。
"""

import time

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QFrame, QMessageBox, QApplication,
)
from PySide6.QtGui import QColor, QPalette
from PySide6.QtCore import Qt, QTimer

from core.diagnostic import NetworkDiagnostic
from core.repair import NetworkRepair, relaunch_as_admin
from core.speed_test import SpeedTest
from core.dns_optimizer import DNSOptimizer
from core.wifi_check import WiFiChecker
from core.cache import CacheManager
from core.logger import get_logger
from core.traffic_monitor import TrafficMonitor
from core.version import __version__
import core.theme as theme
from core.theme import (
    ACCENT, ACCENT_LIGHT, BG_MAIN, BG_CARD, BG_INSET, BG_RAISED,
    SHADOW_DARK, BORDER, TEXT_MAIN, TEXT_SECONDARY, TEXT_LIGHT,
    RADIUS_SMALL,
)
from ui.common import Colors
from ui.pages import (
    HomePageMixin, DiagnosePageMixin, RepairPageMixin, SpeedPageMixin,
    DnsPageMixin, DevicesPageMixin, WifiPageMixin, DownloaderPageMixin,
    HistoryPageMixin,
)


class MainWindow(HomePageMixin, DiagnosePageMixin, RepairPageMixin, SpeedPageMixin,
              DnsPageMixin, DevicesPageMixin, WifiPageMixin,
              DownloaderPageMixin, HistoryPageMixin, QMainWindow):
    """主窗口：负责整体布局、页面导航与后台任务的生命周期。"""

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
        """设置侧边导航栏（分组标题 + 图标导航项 + 黑色实心圆角选中块）"""
        sidebar = QFrame()
        self.sidebar = sidebar
        sidebar.setFixedWidth(200)
        sidebar.setStyleSheet(f"background-color: {Colors.BG_SIDEBAR};")
        sidebar_layout = QVBoxLayout(sidebar)
        # 左右留出内边距，让选中态的黑色圆角块不贴边
        sidebar_layout.setContentsMargins(10, 20, 10, 20)
        sidebar_layout.setSpacing(4)

        # Logo区域
        logo_label = QLabel("网络优化助手")
        logo_label.setStyleSheet(f"""
            color: {Colors.TEXT_MAIN};
            font-size: 18px;
            font-weight: bold;
            padding: 10px 10px 16px 10px;
        """)
        sidebar_layout.addWidget(logo_label)

        subtitle = QLabel("新手小白的网络管家")
        subtitle.setStyleSheet(f"""
            color: {Colors.TEXT_SECONDARY};
            font-size: 11px;
            padding: 0px 10px 18px 10px;
        """)
        sidebar_layout.addWidget(subtitle)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"background-color: {Colors.BORDER}; max-height: 1px;")
        sidebar_layout.addWidget(line)

        sidebar_layout.addSpacing(10)

        # 导航按钮（图标 + 文字；图标为 CJK 字体可渲染的几何符号，避免方框字）
        self.nav_buttons = {}
        nav_items = [
            ("home", "⌂", "首页"),
            ("wifi", "◈", "Wi-Fi检测"),
            ("diagnose", "◎", "网络诊断"),
            ("repair", "⊙", "网络修复"),
            ("dns", "◆", "DNS优化"),
            ("devices", "▣", "设备管理"),
            ("speed", "⇅", "网速测试"),
            ("downloader", "↓", "下载器"),
            ("history", "≡", "历史记录"),
        ]

        # 用于标记在哪个导航项之前插入分组标题（分级：总览 → 检测 → 修复优化 → 工具 → 记录）
        group_title = {
            "wifi": "检测",
            "repair": "修复 · 优化",
            "devices": "工具",
            "history": "记录",
        }

        for key, icon, text in nav_items:
            if key in group_title:
                group_label = QLabel(group_title[key])
                group_label.setStyleSheet(f"""
                    color: {Colors.TEXT_LIGHT};
                    font-size: 11px;
                    font-weight: bold;
                    padding: 10px 12px 3px 12px;
                """)
                sidebar_layout.addWidget(group_label)
            btn = QPushButton(f"{icon}   {text}")
            btn.setFixedHeight(40)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(theme.nav_button(active=False))
            btn.clicked.connect(lambda checked, k=key: self._switch_page(k))
            sidebar_layout.addWidget(btn)
            self.nav_buttons[key] = btn

        self.current_page_key = None

        sidebar_layout.addStretch()

        # 底部版本信息
        version_label = QLabel(f"v{__version__} · 2026")
        version_label.setStyleSheet(f"""
            color: {Colors.TEXT_LIGHT};
            font-size: 11px;
            padding: 10px 10px;
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
            selection-color: {Colors.TEXT_ON_ACCENT};
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
        """统一管理工作线程的启动：不阻塞界面，允许不同页面的任务并行。

        旧实现会在 GUI 线程上 wait(2000) 等待旧线程，切换页面执行新任务时
        界面会明显卡顿；现在只清理已结束的引用，任务之间不再互相等待。
        """
        self._workers = [w for w in self._workers if w.isRunning()]
        worker.finished.connect(lambda *args, w=worker: self._on_worker_finished(w))
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
        # 停止每秒刷新的流量采样定时器
        if self.net_timer.isActive():
            self.net_timer.stop()

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
