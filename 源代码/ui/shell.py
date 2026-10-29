"""主窗口骨架：侧边栏导航、内容区装配与全局样式。"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QFrame, QApplication,
)
from PySide6.QtGui import QColor, QPalette
from PySide6.QtCore import Qt, QEvent, QRect

from core.version import __version__
import core.theme as theme
from core.theme import (
    ACCENT, ACCENT_LIGHT, BG_MAIN, BG_CARD, BG_INSET, BG_RAISED,
    SHADOW_DARK, BORDER, TEXT_MAIN, TEXT_SECONDARY, TEXT_LIGHT,
    RADIUS_SMALL,
)
from ui.common import Colors
from ui.widgets import CometProgressBar


class ShellMixin:
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
        self.content_widget = content_widget
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

        # 顶部彗星进度条：悬浮在内容区最上方，不进入布局，显隐不挤动页面
        self.comet_bar = CometProgressBar(content_widget)
        content_widget.installEventFilter(self)
        self._reposition_comet_bar()

        parent_layout.addWidget(content_widget, 1)


    def _reposition_comet_bar(self):
        """让悬浮进度条始终贴合内容区顶部，并保持在最上层。"""
        bar = getattr(self, "comet_bar", None)
        if bar is None:
            return
        bar.setGeometry(QRect(0, 0, self.content_widget.width(), CometProgressBar.HEIGHT))
        bar.raise_()


    def eventFilter(self, obj, event):
        if obj is getattr(self, "content_widget", None) and event.type() in (QEvent.Resize, QEvent.Show):
            self._reposition_comet_bar()
        return super().eventFilter(obj, event)


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
