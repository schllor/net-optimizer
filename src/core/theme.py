"""夜航 NOCTURNE 设计令牌：纯黑底、纸白线、薄荷绿只做信号色。

界面层只引用这里的令牌，不再各自写死色值。换肤只改这一处。
"""

# ---------- 表面层级：从最深的画布到最亮的浮层 ----------
BG_MAIN = "#040405"        # 画布：纯黑
BG_CARD = "#0a0a0c"        # 卡片
BG_RAISED = "#121215"      # 卡片内的次级块 / 输入底
BG_SIDEBAR = "#060607"     # 侧栏
BG_SIDEBAR_HOVER = "#111114"
BG_INSET = "#0d0d0f"       # 凹槽：日志、进度槽

SHADOW_DARK = "#2e2f34"    # 悬停描边 / 滚动条滑块
BORDER = "#1b1b1f"         # 极细分割线与卡片描边

# 侧栏层级：分割线、分组标题、条目文字依次变亮
SIDEBAR_DIVIDER = "#151518"
SIDEBAR_GROUP_TEXT = "#7a7d85"
SIDEBAR_ITEM_TEXT = "#9a9da4"

# 侧栏管理员状态点：白底按钮上使用更深的红/绿，保证小图标清晰可辨。
SIDEBAR_ADMIN_ON = "#1f9d63"
SIDEBAR_ADMIN_OFF = "#d64545"

# 主操作使用纸白实心块；薄荷绿只出现在选中指示、进度与正向状态。
ACCENT = "#f3f4f6"
ACCENT_DARK = "#d7d9de"
ACCENT_LIGHT = "#17171a"
FOCUS = "#8bffd1"
MINT = "#8bffd1"

# 语义色：诊断与操作状态专用，合计面积刻意压到 5% 以内
SUCCESS = "#8bffd1"
SUCCESS_LIGHT = "#0f2a23"
WARNING = "#ffc46b"
WARNING_LIGHT = "#2b2317"
ERROR = "#ff8f8f"
INFO_LIGHT = "#141418"

# Text
# 小字号（10–12px）必须在纯黑底上达到 WCAG AA 4.5:1，
# 所以三级/四级灰比早期设计稿更亮；层级主要靠字号与字重区分。
TEXT_MAIN = "#f3f4f6"      # 18.6:1
TEXT_SECONDARY = "#b7bac1"  # 10.4:1
TEXT_LIGHT = "#8b8e95"      # 6.25:1
TEXT_WHITE = "#ffffff"
TEXT_ON_ACCENT = "#070708"

# Compact geometry for a quiet utility interface.
RADIUS = "10px"
RADIUS_SMALL = "8px"
RADIUS_PILL = "9px"

# ---------- 设计稿 ui-samples.html 的原始令牌（AA RRGGBB） ----------
VOID = "#040405"            # 画布 #040405
SURFACE = "#0a0a0c"         # 卡片
SURFACE_2 = "#0f0f12"       # 选中块
INSET = "#070708"           # 凹槽 / 终端
PAPER = "#f3f4f6"           # 纸白
LINE = "#14ffffff"          # rgba(255,255,255,.08)
LINE_STRONG = "#24ffffff"   # rgba(255,255,255,.14)
MINT_DIM = "#248bffd1"      # rgba(139,255,209,.14)
MINT_LINE = "#478bffd1"     # rgba(139,255,209,.28)
AMBER_LINE = "#3fffc46b"    # rgba(255,196,107,.25)
AMBER_DIM = "#08ffc46b"
AMBER = WARNING
WARNING_LINE = AMBER_LINE
CARD_TOP = "#08ffffff"      # rgba(255,255,255,.022)
CARD_BOTTOM = "#02ffffff"   # rgba(255,255,255,.006)

# 文字四级色：设计稿的 8px 灰字在真实桌面上不可读，统一提亮到 AA。
TEXT_2 = "#b7bac1"
TEXT_3 = "#8b8e95"
TEXT_4 = "#7a7d85"

# 间距网格：4 / 8 / 12 / 16 / 24 / 32
SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 24
SPACE_6 = 32

# 命中区高度（逻辑像素）
HIT_SMALL = 32
HIT_PRIMARY = 36
HIT_NAV = 40

# ---------- 字体阶：设计稿编号 -> 真实桌面可用字号 ----------
# 设计稿大量使用 7–10px（1280×800 视觉稿），在 1080p/125% 下几乎不可读。
# 这里做一次集中映射，页面调用点无需逐个改。
_SIZE_MAP = {
    7: 10,
    8: 11,
    9: 11,
    10: 12,
    11: 13,
    12: 13,
    13: 14,
    14: 15,
    15: 16,
    16: 17,
    17: 18,
    18: 20,
    19: 20,
    20: 21,
    21: 22,
    22: 23,
    23: 24,
    24: 26,
    26: 28,
    28: 30,
    30: 32,
    34: 36,
    36: 38,
    40: 42,
    44: 46,
    48: 50,
    56: 58,
    62: 62,
}


def text_size(size):
    """把设计稿字号映射为可读字号；至少 10px，超出 62 原样返回。"""
    try:
        value = int(round(float(size)))
    except (TypeError, ValueError):
        return 12
    if value >= 62:
        return value
    return _SIZE_MAP.get(value, max(10, value))


def contrast_ratio(color_a, color_b="#040405"):
    """计算两色对比度，供测试与设计校验使用（WCAG 相对亮度）。"""
    def _lum(value):
        value = value.lstrip("#")
        channels = [int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
        linear = [c / 12.92 if c <= 0.03928
                  else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    a, b = _lum(color_a), _lum(color_b)
    high, low = max(a, b), min(a, b)
    return (high + 0.05) / (low + 0.05)

# CSS 字体栈：中文用雅黑，等宽用 Consolas
FONT_SANS = "Microsoft YaHei UI"
FONT_MONO = "Consolas"


# ---------- Flat surfaces with hairline borders ----------
def raised_card(radius=RADIUS, bg=BG_CARD):
    """A surface separated from the canvas by a precise hairline."""
    return (
        "QFrame#surfaceCard {"
        f"background-color: {bg};"
        f"border-radius: {radius};"
        f"border: 1px solid {BORDER};"
        "}"
        "QFrame#surfaceCard:hover {"
        f"border-color: {SHADOW_DARK};"
        "}"
    )


def _solid_button(bg, radius, hover_bg, text_color=TEXT_WHITE):
    """Solid action button with visible hover and disabled states."""
    return (
        "QPushButton {"
        f"background-color: {bg}; color: {text_color};"
        f"border-radius: {radius};"
        "border: none;"
        f"font-size: {text_size(12)}px; font-weight: 600;"
        "padding: 0 16px;"
        "}"
        "QPushButton:hover {"
        f"background-color: {hover_bg};"
        f"color: {text_color};"
        "}"
        "QPushButton:disabled {"
        f"background-color: {BG_RAISED}; color: {TEXT_LIGHT};"
        "}"
    )


def accent_button(radius=RADIUS_PILL):
    """Primary paper-white action button."""
    return _solid_button(ACCENT, radius, ACCENT_DARK, TEXT_ON_ACCENT)


def danger_button(radius=RADIUS_PILL):
    """Semantic destructive action."""
    return _solid_button(ERROR, radius, "#e87878", TEXT_ON_ACCENT)


def secondary_button(radius=RADIUS_SMALL):
    """Quiet ghost action: transparent with a hairline."""
    return (
        "QPushButton {"
        f"color: {TEXT_MAIN}; background-color: transparent;"
        f"border: 1px solid #2a2a2f; border-radius: {radius};"
        "font-size: 11px; padding: 6px 14px;"
        "}"
        "QPushButton:hover {"
        f"color: {TEXT_MAIN}; border-color: {SHADOW_DARK}; background-color: {BG_RAISED};"
        "}"
    )


def nav_item_state(active=False):
    """侧栏导航项的状态标记（绘制由 ui.shell.NavItem 完成，样式串用于状态区分）。"""
    if active:
        return "color: #f3f4f6; background-color: #111114;"
    return "color: #6a6d75; background-color: transparent;"


def nav_button(active=False):
    """侧栏导航项。

    选中态是比侧栏亮一档的实心块，左侧压一条 2px 薄荷绿指示条；
    未选中文字比正文低一档（SIDEBAR_ITEM_TEXT），悬停时提亮。
    """
    if active:
        return (
            "QPushButton {"
            f"color: {TEXT_MAIN}; background-color: {BG_SIDEBAR_HOVER};"
            f"border: 1px solid {BORDER};"
            f"border-left: 2px solid {MINT};"
            f"border-radius: {RADIUS_SMALL};"
            "text-align: left; padding-left: 10px;"
            f"font-size: {text_size(12)}px;"
            "}"
        )
    return (
        "QPushButton {"
        f"color: {SIDEBAR_ITEM_TEXT}; background-color: transparent;"
        "border: none;"
        "text-align: left; padding-left: 12px;"
        f"font-size: {text_size(12)}px;"
        "}"
        "QPushButton:hover {"
        f"color: {TEXT_MAIN}; background-color: {BG_SIDEBAR_HOVER};"
        f"border-radius: {RADIUS_SMALL};"
        "}"
    )


def admin_button():
    """底部管理员入口：用纸白实心块保证在固定底栏中足够显眼。"""
    return (
        "QPushButton {"
        f"color: {TEXT_ON_ACCENT}; background-color: {ACCENT};"
        f"border: none; border-radius: {RADIUS_SMALL};"
        "font-size: 11px; font-weight: 600;"
        "}"
        "QPushButton:hover {"
        f"background-color: {ACCENT_DARK};"
        "}"
        "QPushButton:pressed {"
        f"background-color: {SHADOW_DARK}; color: {TEXT_MAIN};"
        "}"
    )


def progress_bar(chunk_color=ACCENT, radius=RADIUS_SMALL):
    """Neutral progress track with a semantic or accent fill."""
    chunk_fill = chunk_color
    return (
        "QProgressBar {"
        f"background-color: {BG_INSET}; border-radius: {radius};"
        f"border: 1px solid {BORDER}; text-align: center; color: {TEXT_SECONDARY}; font-size: 10px;"
        "}"
        "QProgressBar::chunk {"
        f"background-color: {chunk_fill}; border-radius: {radius};"
        "}"
    )


def scroll_area(bg=BG_INSET, radius=RADIUS_SMALL):
    """Quiet scrollbars for dark content surfaces."""
    return (
        "QScrollArea {"
        "border: none;"
        "}"
        "QScrollBar:vertical {"
        "width: 8px; background: transparent; margin: 2px;"
        "}"
        "QScrollBar::handle:vertical {"
        "min-height: 30px; border-radius: 4px;"
        f"background-color: {SHADOW_DARK};"
        "}"
        "QScrollBar::handle:vertical:hover {"
        f"background-color: {BORDER};"
        "}"
        "QScrollBar::add-line, QScrollBar::sub-line {"
        "height: 0px; width: 0px;"
        "}"
    )


# 语义等级 -> 状态色（core 各评测方法返回 ok/warning/error 作为等级关键字）
LEVEL_COLORS = {
    "ok": SUCCESS,
    "warning": WARNING,
    "error": ERROR,
}
