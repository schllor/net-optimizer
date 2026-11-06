"""主窗口骨架：侧边栏导航、内容区装配与全局样式。"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QFrame, QScrollArea, QApplication,
)
from PySide6.QtGui import QColor, QPalette, QDesktopServices
from PySide6.QtCore import Qt, QEvent, QRect, QUrl

from core.version import __version__
import core.theme as theme
from core.theme import (
    ACCENT, ACCENT_LIGHT, BG_MAIN, BG_CARD, BG_INSET, BG_RAISED,
    SHADOW_DARK, BORDER, TEXT_MAIN, TEXT_SECONDARY, TEXT_LIGHT,
    RADIUS_SMALL,
)
from ui.common import Colors
from ui.titlebar import TitleBar
from ui.widgets import CometProgressBar

RELEASES_URL = "https://github.com/schllor/net-optimizer/releases"


class ShellMixin:
    def _setup_ui(self):
        """设置界面"""
        # 中央部件：顶部自绘标题栏 + 下方「侧边栏 / 内容区」
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        outer_layout = QVBoxLayout(central_widget)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.title_bar = TitleBar(self)
        outer_layout.addWidget(self.title_bar)

        body = QWidget()
        main_layout = QHBoxLayout(body)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        outer_layout.addWidget(body, 1)

        # 左侧导航栏
        self._setup_sidebar(main_layout)

        # 右侧内容区
        self._setup_content(main_layout)


    def _setup_sidebar(self, parent_layout):
        """设置侧边导航栏。

        顶部品牌区和底部系统入口固定，中间按使用场景分组的导航可滚动；
        分组标题、组间距与淡分割线共同划分层级，选中项用高对比色块标出。
        """
        sidebar = QFrame()
        self.sidebar = sidebar
        sidebar.setFixedWidth(200)
        sidebar.setStyleSheet(f"background-color: {Colors.BG_SIDEBAR};")
        sidebar_layout = QVBoxLayout(sidebar)
        # 左右留出内边距，让选中态的高亮圆角块不贴边
        sidebar_layout.setContentsMargins(10, 12, 10, 10)
        sidebar_layout.setSpacing(0)

        # ---------- 顶部：品牌区（固定） ----------
        brand = QWidget()
        brand_layout = QVBoxLayout(brand)
        brand_layout.setContentsMargins(4, 0, 4, 9)
        brand_layout.setSpacing(0)

        logo_label = QLabel("网络优化助手")
        logo_label.setStyleSheet(f"""
            color: {Colors.TEXT_MAIN};
            font-size: 17px;
            font-weight: bold;
            padding: 4px 6px 3px 6px;
        """)
        brand_layout.addWidget(logo_label)

        subtitle = QLabel("新手小白的网络管家")
        subtitle.setStyleSheet(f"""
            color: {Colors.TEXT_LIGHT};
            font-size: 11px;
            padding: 0px 6px;
        """)
        brand_layout.addWidget(subtitle)
        sidebar_layout.addWidget(brand)
        sidebar_layout.addWidget(self._sidebar_divider())

        # ---------- 中部：按场景分组的导航（入口过多时滚动） ----------
        self.nav_buttons = {}
        # 图标为 CJK 字体可渲染的几何符号，避免方框字
        groups = (
            ("总览", (("home", "⌂", "首页"),)),
            ("检测", (("wifi", "◈", "Wi-Fi检测"),
                      ("diagnose", "◎", "网络诊断"))),
            ("修复 · 优化", (("repair", "⊙", "网络修复"),
                             ("dns", "◆", "DNS优化"))),
            ("工具", (("devices", "▣", "设备管理"),
                      ("speed", "⇅", "网速测试"),
                      ("downloader", "↓", "下载器"))),
            ("记录", (("history", "≡", "历史记录"),)),
        )

        nav_scroll = QScrollArea()
        self.nav_scroll = nav_scroll
        nav_scroll.setWidgetResizable(True)
        nav_scroll.setFrameShape(QFrame.NoFrame)
        nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        nav_scroll.setStyleSheet(f"""
            QScrollArea {{ border: none; background: transparent; }}
            QScrollArea > QWidget > QWidget {{ background: transparent; }}
            QScrollBar:vertical {{
                width: 5px; background: transparent; margin: 2px 0;
            }}
            QScrollBar::handle:vertical {{
                min-height: 24px; border-radius: 2px;
                background-color: {Colors.SHADOW_DARK};
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {Colors.BORDER};
            }}
            QScrollBar::add-line, QScrollBar::sub-line {{
                height: 0px; width: 0px;
            }}
        """)

        nav_content = QWidget()
        nav_layout = QVBoxLayout(nav_content)
        nav_layout.setContentsMargins(0, 4, 0, 4)
        nav_layout.setSpacing(2)

        for group_index, (title, items) in enumerate(groups):
            # 组间留白明显大于行间距；组标题自身也留出上方呼吸空间
            if group_index:
                nav_layout.addSpacing(9)
            group_label = QLabel(title)
            group_label.setStyleSheet(f"""
                color: {theme.SIDEBAR_GROUP_TEXT};
                font-size: 11px;
                font-weight: bold;
                padding: {2 if group_index == 0 else 6}px 12px 4px 12px;
            """)
            nav_layout.addWidget(group_label)

            for key, icon, text in items:
                nav_layout.addWidget(self._create_nav_button(key, icon, text))

        nav_layout.addStretch()
        nav_scroll.setWidget(nav_content)
        sidebar_layout.addWidget(nav_scroll, 1)

        # ---------- 底部：系统入口 + 升级入口（固定） ----------
        sidebar_layout.addWidget(self._sidebar_divider())

        footer = QWidget()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(0, 7, 0, 0)
        footer_layout.setSpacing(5)

        footer_layout.addWidget(self._create_nav_button("settings", "▤", "设置"))

        self.upgrade_btn = QPushButton("↑   检查更新")
        self.upgrade_btn.setFixedHeight(36)
        self.upgrade_btn.setCursor(Qt.PointingHandCursor)
        self.upgrade_btn.setToolTip("打开 GitHub Releases 查看新版本")
        self.upgrade_btn.setStyleSheet(theme.upgrade_button())
        self.upgrade_btn.clicked.connect(self._open_releases)
        footer_layout.addWidget(self.upgrade_btn)

        version_label = QLabel(f"v{__version__} · 2026")
        version_label.setAlignment(Qt.AlignCenter)
        version_label.setStyleSheet(f"""
            color: {theme.SIDEBAR_GROUP_TEXT};
            font-size: 10px;
            padding: 1px 0 0 0;
        """)
        footer_layout.addWidget(version_label)
        sidebar_layout.addWidget(footer)

        self.current_page_key = None
        parent_layout.addWidget(sidebar)


    def _create_nav_button(self, key, icon, text):
        """创建一个导航项；所有入口统一登记，便于切换页时同步选中态。"""
        btn = QPushButton(f"{icon}   {text}")
        btn.setFixedHeight(36)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(theme.nav_button(active=False))
        btn.clicked.connect(lambda checked, k=key: self._switch_page(k))
        self.nav_buttons[key] = btn
        return btn


    def _sidebar_divider(self):
        """大块之间的淡分割线；只用于顶部/中部/底部三块的交界。"""
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(
            f"background-color: {theme.SIDEBAR_DIVIDER}; border: none;")
        return line


    def _open_releases(self):
        """在浏览器中打开版本发布页（升级入口）。"""
        self.logger.info("打开版本发布页")
        QDesktopServices.openUrl(QUrl(RELEASES_URL))


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
        self._create_settings_page()

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
        self.pages.addWidget(self.settings_page)

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
