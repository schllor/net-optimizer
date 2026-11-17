"""主窗口骨架：212px 侧栏、44px 标题栏、内容区与 28px 状态条。

结构、尺寸与间距对齐 design/ui-samples.html：屏幕 1280×800 时右侧内容区
为 1068×800，标题栏 44、状态条 28、内容内边距 22/28/16。
"""

import os
import sys

from PySide6.QtCore import QEvent, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QStackedWidget, QVBoxLayout, QWidget,
)

from core.version import __version__
import core.theme as theme
from core.theme import (
    ACCENT, ACCENT_LIGHT, BG_MAIN, BG_CARD, BG_INSET, BG_RAISED,
    SHADOW_DARK, BORDER, TEXT_MAIN, TEXT_SECONDARY, TEXT_LIGHT,
    RADIUS_SMALL,
)
from ui import icons
from ui.kit import Dot, PageHead, hline, hbox, lbl, mono, vbox
from ui.responsive import PageScroll, ResponsiveColumns, mode_for
from ui.titlebar import TitleBar
from ui.widgets import CometProgressBar

PAGE_ORDER = (
    "home", "diagnose", "repair", "speed", "dns",
    "devices", "wifi", "downloader", "history", "settings",
)

NAV_ITEMS = (
    ("home", "grid", "总览", "01"),
    ("diagnose", "pulse", "网络诊断", "02"),
    ("repair", "tool", "一键修复", "03"),
    ("speed", "gauge", "网速测试", "04"),
    ("dns", "globe", "DNS 优化", "05"),
    ("devices", "devices", "设备管理", "06"),
    ("wifi", "signal", "Wi-Fi 检测", "07"),
    ("downloader", "download", "下载加速", "08"),
    ("history", "clock", "历史记录", "09"),
    ("settings", "settings", "设置", "10"),
)


def _resource_base():
    """打包后资源解压到 sys._MEIPASS；源码运行时为 src 目录。"""
    return getattr(
        sys, "_MEIPASS",
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class NavItem(QWidget):
    """侧栏导航项：40px 高，选中为实心块 + 左缘 2px 纸白指示条。"""

    def __init__(self, key, icon_name, text, index, on_click, parent=None):
        super().__init__(parent)
        self.key = key
        self._icon_name = icon_name
        self._text = text
        self._index = index
        self._on_click = on_click
        self._active = False
        self._hover = False
        self._compact = False
        self.setFixedHeight(theme.HIT_NAV)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(text)
        self.setStyleSheet(theme.nav_item_state(False))

    def set_compact(self, compact):
        compact = bool(compact)
        if compact == self._compact:
            return
        self._compact = compact
        self.setToolTip(self._text if compact else "")
        self.update()

    def set_active(self, active):
        active = bool(active)
        if active == self._active:
            return
        self._active = active
        self.setStyleSheet(theme.nav_item_state(active))
        self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self._on_click(self.key)
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(
                event.position().toPoint()):
            self._on_click(self.key)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width = self.width()
        height = self.height()

        if self._compact:
            block = QRect(8, 0, width - 16, height)
        else:
            block = QRect(12, 0, width - 24, height)

        if self._active:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#111114"))
            painter.drawRoundedRect(block, 9, 9)
            painter.setPen(QPen(QColor(255, 255, 255, 13), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(block.adjusted(0, 0, -1, -1), 9, 9)
            painter.fillRect(QRect(0, (height - 16) // 2, 2, 16),
                             QColor(theme.PAPER))
        elif self._hover:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#0c0c0f"))
            painter.drawRoundedRect(block, 9, 9)

        icon_color = theme.TEXT_MAIN if self._active else theme.TEXT_2
        if self._compact:
            icon_size = 18
            painter.drawPixmap((width - icon_size) // 2,
                               (height - icon_size) // 2,
                               icons.pixmap(self._icon_name, icon_size,
                                            icon_color, 1.7))
        else:
            painter.drawPixmap(22, (height - 15) // 2,
                               icons.pixmap(self._icon_name, 15, icon_color, 1.6))

        if not self._compact:
            painter.setFont(QFont(theme.FONT_SANS))
            font = painter.font()
            font.setPixelSize(theme.text_size(12))
            font.setWeight(QFont.Weight(500 if self._active else 400))
            painter.setFont(font)
            painter.setPen(QColor(theme.TEXT_MAIN if self._active
                                  else theme.TEXT_2))
            painter.drawText(QRect(48, 0, width - 80, height),
                             Qt.AlignVCenter | Qt.AlignLeft, self._text)

            font.setPixelSize(theme.text_size(8))
            font.setWeight(QFont.Weight.Normal)
            font.setFamilies([theme.FONT_MONO])
            painter.setFont(font)
            painter.setPen(QColor(theme.TEXT_3 if self._active
                                  else theme.TEXT_4))
            painter.drawText(QRect(width - 44, 0, 26, height),
                             Qt.AlignVCenter | Qt.AlignRight, self._index)

        if self.hasFocus():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(theme.FOCUS), 1.5))
            painter.drawRoundedRect(block.adjusted(1, 1, -1, -1), 8, 8)
        painter.end()


class ShellMixin:
    def _setup_ui(self):
        """中央部件：左侧 212px 侧栏 + 右侧（标题栏 / 内容 / 状态条）。"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        outer = QHBoxLayout(central_widget)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._setup_sidebar(outer)
        self._setup_content(outer)

    # ---------------------------------------------------------------- 侧栏
    def _setup_sidebar(self, parent_layout):
        sidebar = QFrame()
        self.sidebar = sidebar
        sidebar.setFixedWidth(212)
        sidebar.setStyleSheet(
            f"QFrame#sidebar {{ background: qlineargradient(x1:0, y1:0, x2:0,"
            f" y2:1, stop:0 #08080a, stop:1 #060607);"
            f" border-right: 1px solid {theme.LINE}; }}")
        sidebar.setObjectName("sidebar")
        layout = vbox(0, (14, 20, 14, 16), sidebar)
        self.sidebar_layout = layout

        # 品牌区：32px 图标块 + 名称 + 等宽小字
        brand = QWidget()
        self.brand_widget = brand
        brand_layout = hbox(10, (8, 2, 8, 20), brand)
        logo = QLabel()
        logo.setFixedSize(32, 32)
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet(
            f"background-color: #0d0d10; border: 1px solid {theme.LINE_STRONG};"
            " border-radius: 9px;")
        pixmap = QPixmap(os.path.join(_resource_base(), "assets", "icons", "app.png"))
        if not pixmap.isNull():
            dpr = 1.0
            try:
                dpr = max(1.0, float(logo.devicePixelRatioF()))
            except Exception:
                dpr = 1.0
            scaled = pixmap.scaled(int(round(22 * dpr)), int(round(22 * dpr)),
                                   Qt.KeepAspectRatio, Qt.SmoothTransformation)
            scaled.setDevicePixelRatio(dpr)
            logo.setPixmap(scaled)
        brand_layout.addWidget(logo)

        brand_text_widget = QWidget()
        brand_text = vbox(0, (0, 0, 0, 0), brand_text_widget)
        brand_text.addWidget(lbl("网络优化助手", 12, theme.TEXT_MAIN, 600, False, 0.2))
        sub = lbl("NOCTURNE", 8, theme.TEXT_4, 400, True, 1.44)
        sub.setContentsMargins(0, 4, 0, 0)
        brand_text.addWidget(sub)
        self.brand_text_widget = brand_text_widget
        brand_layout.addWidget(brand_text_widget, 1)
        layout.addWidget(brand)

        # 导航：单个 MENU 分组，10 个入口；超出高度时可滚动
        self.nav_buttons = {}
        menu_label = lbl("MENU", 8, theme.TEXT_4, 400, True, 1.6)
        menu_label.setContentsMargins(10, 0, 10, 8)
        self.menu_label = menu_label
        layout.addWidget(menu_label)

        nav_scroll = QScrollArea()
        self.nav_scroll = nav_scroll
        nav_scroll.setWidgetResizable(True)
        nav_scroll.setFrameShape(QFrame.NoFrame)
        nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        nav_scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
            "QScrollBar:vertical { width: 4px; background: transparent; }"
            "QScrollBar::handle:vertical { min-height: 24px; border-radius: 2px;"
            " background-color: " + theme.LINE_STRONG + "; }"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }")

        nav_content = QWidget()
        nav_layout = vbox(2, (0, 0, 0, 0), nav_content)
        for key, icon_name, text, index in NAV_ITEMS:
            item = NavItem(key, icon_name, text, index, self._switch_page)
            self.nav_buttons[key] = item
            nav_layout.addWidget(item)
        nav_layout.addStretch()
        nav_scroll.setWidget(nav_content)
        layout.addWidget(nav_scroll, 1)

        # 底部：实时状态、上下行、管理员入口、版本
        layout.addWidget(hline())
        foot = QWidget()
        self.side_foot = foot
        foot_layout = vbox(0, (10, 12, 10, 0), foot)
        live = hbox(7, (0, 0, 0, 0))
        self.side_live_dot = Dot("warn")
        live.addWidget(self.side_live_dot)
        self.side_live_label = lbl("正在读取网络…", 10, theme.TEXT_2)
        live.addWidget(self.side_live_label)
        live.addStretch()
        foot_layout.addLayout(live)

        rates = hbox(12, (0, 10, 0, 0))
        down_group = vbox(0, (0, 0, 0, 0))
        self.side_down_label = lbl("--", 11, theme.TEXT_MAIN, 600, True)
        down_group.addWidget(self.side_down_label)
        down_group.addWidget(lbl("DOWN Mbps", 8, theme.TEXT_4, 400, True, 0.5))
        rates.addLayout(down_group)
        up_group = vbox(0, (0, 0, 0, 0))
        self.side_up_label = lbl("--", 11, theme.TEXT_MAIN, 600, True)
        up_group.addWidget(self.side_up_label)
        up_group.addWidget(lbl("UP Mbps", 8, theme.TEXT_4, 400, True, 0.5))
        rates.addLayout(up_group)
        rates.addStretch()
        foot_layout.addLayout(rates)

        self.admin_entry_btn = QPushButton("管理员权限")
        self.admin_entry_btn.setFixedHeight(theme.HIT_SMALL - 4)
        self.admin_entry_btn.setCursor(Qt.PointingHandCursor)
        self.admin_entry_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #b7bac1;"
            f" border: 1px solid {theme.LINE}; border-radius: 9px;"
            f" font-size: {theme.text_size(9)}px; padding: 0 9px;"
            " text-align: left; }"
            "QPushButton:hover { background-color: #10ffffff; }")
        self.admin_entry_btn.clicked.connect(self._on_admin_entry_clicked)
        admin_wrap = hbox(0, (0, 10, 0, 0))
        admin_wrap.addWidget(self.admin_entry_btn)
        admin_wrap.addStretch()
        foot_layout.addLayout(admin_wrap)
        self._refresh_admin_entry()

        self.version_label = lbl(f"v{__version__}", 8, theme.TEXT_4,
                                 400, True, 0.96)
        self.version_label.setContentsMargins(0, 14, 0, 0)
        foot_layout.addWidget(self.version_label)
        layout.addWidget(foot)

        parent_layout.addWidget(sidebar)

    def _refresh_admin_entry(self):
        """按当前是否提权更新管理员入口的状态点与提示。"""
        btn = getattr(self, "admin_entry_btn", None)
        if btn is None:
            return
        is_admin = self._is_admin_now()
        color = theme.SIDEBAR_ADMIN_ON if is_admin else theme.SIDEBAR_ADMIN_OFF
        btn.setIcon(self._status_dot_icon(color))
        btn.setIconSize(QSize(7, 7))
        btn.setToolTip(
            "当前已以管理员身份运行" if is_admin
            else "当前未以管理员身份运行，点击重新以管理员身份启动")

    def _on_admin_entry_clicked(self):
        if self._is_admin_now():
            self._set_status("当前已以管理员身份运行")
            return
        self._request_admin_relaunch()

    @staticmethod
    def _status_dot_icon(color):
        pixmap = QPixmap(20, 20)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(5, 5, 10, 10)
        painter.end()
        return QIcon(pixmap)

    # ---------------------------------------------------------------- 内容区
    def _setup_content(self, parent_layout):
        main = QWidget()
        main_layout = vbox(0, (0, 0, 0, 0), main)

        self.title_bar = TitleBar(self)
        self.title_label = self.title_bar.crumb_label
        self.subtitle_label = QLabel("")
        self.subtitle_label.hide()
        main_layout.addWidget(self.title_bar)

        content_widget = QWidget()
        self.content_widget = content_widget
        content_widget.setStyleSheet(f"background-color: {theme.VOID};")
        content_layout = vbox(14, (28, 22, 28, 16), content_widget)
        self.content_layout = content_layout

        self.pages = QStackedWidget()
        self.pages.setStyleSheet("background: transparent;")
        content_layout.addWidget(self.pages, 1)

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

        page_pairs = (
            ("home", self.home_page),
            ("diagnose", self.diagnose_page),
            ("repair", self.repair_page),
            ("speed", self.speed_page),
            ("dns", self.dns_page),
            ("devices", self.devices_page),
            ("wifi", self.wifi_page),
            ("downloader", self.downloader_page),
            ("history", self.history_page),
            ("settings", self.settings_page),
        )
        self.page_views = {}
        for key, page in page_pairs:
            view = PageScroll(page)
            self.page_views[key] = view
            self.pages.addWidget(view)

        # 28px 状态条：左侧实时网速，右侧页码
        status_bar = QFrame()
        self.status_bar_widget = status_bar
        status_bar.setFixedHeight(30)
        status_bar.setStyleSheet(
            f"QFrame {{ background: transparent; border: none;"
            f" border-top: 1px solid {theme.LINE}; }}")
        status = hbox(16, (26, 0, 18, 0), status_bar)
        status.setAlignment(Qt.AlignVCenter)

        self.bottom_up_label = mono("↑ --", 8, theme.TEXT_3, 0.6)
        self.bottom_down_label = mono("↓ --", 8, theme.TEXT_3, 0.6)
        self.status_latency = mono("延迟 --", 8, theme.TEXT_4, 0.6)
        self.status_dns = mono("DNS --", 8, theme.TEXT_4, 0.6)
        for index, widget in enumerate(
                (self.bottom_up_label, self.bottom_down_label,
                 self.status_latency, self.status_dns)):
            if index:
                status.addWidget(mono("·", 8, theme.TEXT_4))
            status.addWidget(widget)
        status.addStretch()

        self.status_bar = QLabel("网络就绪")
        self.status_bar.hide()
        self.status_dot = QLabel()
        self.status_dot.hide()

        self.screen_label = mono("01 / 10", 8, theme.TEXT_4, 0.9)
        status.addWidget(self.screen_label)
        content_layout.addWidget(status_bar)

        # 顶部彗星进度条：悬浮在内容区最上方，不进入布局
        self.comet_bar = CometProgressBar(content_widget)
        content_widget.installEventFilter(self)
        self._reposition_comet_bar()

        main_layout.addWidget(content_widget, 1)
        parent_layout.addWidget(main, 1)

        self.current_page_key = None

    def _reposition_comet_bar(self):
        bar = getattr(self, "comet_bar", None)
        if bar is None:
            return
        bar.setGeometry(
            QRect(0, 0, self.content_widget.width(), CometProgressBar.HEIGHT))
        bar.raise_()

    def eventFilter(self, obj, event):
        if obj is getattr(self, "content_widget", None) and event.type() in (
                QEvent.Resize, QEvent.Show):
            self._reposition_comet_bar()
        return super().eventFilter(obj, event)

    def set_screen(self, page_key):
        """更新状态条右侧页码与侧栏选中态。"""
        try:
            index = PAGE_ORDER.index(page_key) + 1
        except ValueError:
            index = 1
        self.screen_label.setText(f"{index:02d} / {len(PAGE_ORDER)}")

    # ---------------------------------------------------------------- 布局模式
    def apply_shell_mode(self, mode):
        """按 compact/regular/wide 调整侧栏、内容边距与状态条。"""
        compact = mode == "compact"
        wide = mode == "wide"
        self.sidebar.setFixedWidth(76 if compact else (232 if wide else 212))
        sidebar_layout = getattr(self, "sidebar_layout", None)
        if sidebar_layout is not None:
            sidebar_layout.setContentsMargins(
                *((8, 12, 8, 10) if compact else (14, 20, 14, 16)))

        brand_text = getattr(self, "brand_text_widget", None)
        if brand_text is not None:
            brand_text.setVisible(not compact)
        menu = getattr(self, "menu_label", None)
        if menu is not None:
            menu.setVisible(not compact)
        foot = getattr(self, "side_foot", None)
        if foot is not None:
            foot.setVisible(not compact)

        for item in getattr(self, "nav_buttons", {}).values():
            if hasattr(item, "set_compact"):
                item.set_compact(compact)

        content_layout = getattr(self, "content_layout", None)
        if content_layout is not None:
            if compact:
                content_layout.setContentsMargins(18, 16, 18, 12)
                content_layout.setSpacing(10)
            elif wide:
                content_layout.setContentsMargins(36, 24, 36, 18)
                content_layout.setSpacing(16)
            else:
                content_layout.setContentsMargins(28, 22, 28, 16)
                content_layout.setSpacing(14)

        for widget in (getattr(self, "status_latency", None),
                       getattr(self, "status_dns", None)):
            if widget is not None:
                widget.setVisible(not compact)
        status_widget = getattr(self, "status_bar_widget", None)
        if status_widget is not None:
            status_widget.setFixedHeight(26 if compact else 30)

        title_bar = getattr(self, "title_bar", None)
        if title_bar is not None and hasattr(title_bar, "set_compact"):
            title_bar.set_compact(compact)


    # ---------------------------------------------------------------- 全局样式
    def _setup_styles(self):
        """应用级深色调色板与通用控件样式。"""
        global_qss = f"""
        QWidget {{
            color: {TEXT_MAIN};
        }}

        QLabel {{
            background-color: transparent;
        }}

        QLineEdit {{
            background-color: {theme.INSET};
            border: 1px solid {theme.LINE};
            border-radius: 8px;
            padding: 8px 12px;
            font-size: {theme.text_size(11)}px;
            color: {TEXT_MAIN};
            selection-background-color: {theme.PAPER};
            selection-color: #050506;
        }}
        QLineEdit:focus {{
            border: 1px solid {theme.FOCUS};
        }}

        QComboBox {{
            background-color: {BG_CARD};
            border: 1px solid {theme.LINE};
            border-radius: 8px;
            padding: 6px 10px;
            font-size: {theme.text_size(11)}px;
        }}
        QComboBox:focus {{ border: 1px solid {theme.FOCUS}; }}
        QComboBox::drop-down {{ border: none; width: 22px; }}
        QComboBox QAbstractItemView {{
            background-color: {BG_CARD};
            border: 1px solid {theme.LINE};
            border-radius: 8px;
            selection-background-color: #17171a;
            selection-color: {TEXT_MAIN};
            outline: 0;
        }}

        QCheckBox {{
            color: {TEXT_MAIN};
            font-size: {theme.text_size(11)}px;
            spacing: 8px;
        }}
        QCheckBox::indicator {{
            width: 18px; height: 18px;
            border: 1px solid {theme.LINE_STRONG};
            border-radius: 4px;
            background-color: {BG_RAISED};
        }}
        QCheckBox::indicator:checked {{
            background-color: {theme.MINT};
            border-color: {theme.MINT};
        }}

        QMenu {{
            background-color: {BG_CARD};
            border: 1px solid {theme.LINE};
            border-radius: 8px;
            padding: 6px;
        }}
        QMenu::item {{
            padding: 7px 20px;
            border-radius: 6px;
            color: {TEXT_MAIN};
            font-size: {theme.text_size(11)}px;
        }}
        QMenu::item:selected {{
            background-color: #17171a;
            color: {TEXT_MAIN};
        }}
        QMenu::separator {{
            height: 1px;
            background-color: {theme.LINE};
            margin: 4px 8px;
        }}

        QPlainTextEdit, QTextEdit {{
            background-color: {theme.INSET};
            border: 1px solid {theme.LINE};
            border-radius: 8px;
            color: {TEXT_MAIN};
            selection-background-color: {theme.PAPER};
            selection-color: #050506;
        }}

        QTableWidget, QTableView, QListWidget, QTreeWidget {{
            background-color: transparent;
            alternate-background-color: transparent;
            color: {TEXT_MAIN};
            border: none;
            gridline-color: {theme.LINE};
            selection-background-color: #17171a;
            selection-color: {TEXT_MAIN};
        }}
        QHeaderView::section {{
            background-color: transparent;
            color: {theme.TEXT_3};
            border: none;
            border-bottom: 1px solid {theme.LINE};
            padding: 8px 10px;
            font-size: {theme.text_size(8)}px;
        }}

        QScrollBar:vertical {{
            width: 6px;
            background: transparent;
            margin: 2px;
        }}
        QScrollBar::handle:vertical {{
            min-height: 30px;
            border-radius: 3px;
            background-color: {theme.LINE_STRONG};
        }}
        QScrollBar::add-line, QScrollBar::sub-line {{
            height: 0px;
            width: 0px;
        }}

        QToolTip {{
            background-color: {BG_RAISED};
            color: {TEXT_MAIN};
            border: 1px solid {theme.LINE};
            padding: 7px 10px;
            border-radius: 8px;
            font-size: {theme.text_size(11)}px;
        }}
        """
        app = QApplication.instance()
        if app is not None:
            palette = app.palette()
            palette.setColor(QPalette.ColorRole.Window, QColor(theme.VOID))
            palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT_MAIN))
            palette.setColor(QPalette.ColorRole.Base, QColor(BG_CARD))
            palette.setColor(QPalette.ColorRole.AlternateBase, QColor(BG_RAISED))
            palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(BG_RAISED))
            palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT_MAIN))
            palette.setColor(QPalette.ColorRole.Text, QColor(TEXT_MAIN))
            palette.setColor(QPalette.ColorRole.Button, QColor(BG_RAISED))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT_MAIN))
            palette.setColor(QPalette.ColorRole.Highlight, QColor(theme.PAPER))
            palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#050506"))
            palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_LIGHT))
            app.setPalette(palette)
            app.setStyleSheet(global_qss)

    def _normalize_label_backgrounds(self, root=None):
        root = root or self
        for label in root.findChildren(QLabel):
            style = label.styleSheet()
            if "background" in style.lower():
                continue
            label.setStyleSheet(style + "\nbackground-color: transparent;")
