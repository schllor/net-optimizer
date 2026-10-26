"""首页页面：健康分环与功能入口。"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QScrollArea,
)
from PySide6.QtCore import Qt

import core.theme as theme
from ui.common import Colors
from ui.widgets import ScoreRingWidget


class HomePageMixin:
    """首页：健康分、实时概览与功能入口。"""

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
