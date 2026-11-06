"""Voltagent-inspired dark utility theme with neutral surfaces and one accent."""

# ---------- Dark neutral palette ----------
BG_MAIN = "#111214"
BG_CARD = "#1a1d20"
BG_RAISED = "#252a2e"
BG_SIDEBAR = "#0c0f11"
BG_SIDEBAR_HOVER = "#20272a"
BG_INSET = "#15191c"

SHADOW_DARK = "#454d52"
BORDER = "#363d42"

# 侧栏层级：淡分割线、弱化分组标题，条目文字比次级文字再降一档但保持可读。
SIDEBAR_DIVIDER = "#1d2427"
SIDEBAR_GROUP_TEXT = "#7f8a92"
SIDEBAR_ITEM_TEXT = "#b0bac1"

# Cool white is reserved for actions, active states, and progress.
ACCENT = "#e6edf4"
ACCENT_DARK = "#c7d3e0"
ACCENT_LIGHT = "#1d262e"
FOCUS = "#f2f7fc"

# Semantic colors are reserved for diagnostic and operation states.
SUCCESS = "#63d6a0"
SUCCESS_LIGHT = "#17372c"
WARNING = "#e7b86a"
WARNING_LIGHT = "#3a2f1e"
ERROR = "#f18484"
INFO_LIGHT = "#20282d"

# Text
TEXT_MAIN = "#f2f2f2"
TEXT_SECONDARY = "#c4cbd0"
TEXT_LIGHT = "#8e989e"
TEXT_WHITE = "#ffffff"
TEXT_ON_ACCENT = "#0b1116"

# Compact geometry for a quiet utility interface.
RADIUS = "8px"
RADIUS_SMALL = "6px"
RADIUS_PILL = "8px"


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
        f"border: 1px solid {BORDER};"
        "font-size: 15px; font-weight: bold;"
        "}"
        "QPushButton:hover {"
        f"background-color: {hover_bg};"
        f"color: {text_color};"
        "}"
        "QPushButton:disabled {"
        f"background-color: {BG_RAISED}; color: {TEXT_LIGHT};"
        f"border: 1px solid {BORDER};"
        "}"
    )


def accent_button(radius=RADIUS_PILL):
    """Primary electric-green action button."""
    return _solid_button(ACCENT, radius, ACCENT_DARK, TEXT_ON_ACCENT)


def danger_button(radius=RADIUS_PILL):
    """Semantic destructive action."""
    return _solid_button(ERROR, radius, "#cf6262")


def secondary_button(radius=RADIUS_SMALL):
    """Quiet secondary action on a dark raised surface."""
    return (
        "QPushButton {"
        f"color: {TEXT_SECONDARY}; background-color: {BG_RAISED};"
        f"border: 1px solid {BORDER}; border-radius: {radius};"
        "font-size: 13px; padding: 6px 14px;"
        "}"
        "QPushButton:hover {"
        f"color: {TEXT_MAIN}; border-color: {SHADOW_DARK}; background-color: {ACCENT_LIGHT};"
        "}"
    )


def nav_button(active=False):
    """侧栏导航项。

    选中态用与侧栏背景对比明显的冷调白实心圆角块，块内文字转为深色；
    未选中文字比正文低一档（SIDEBAR_ITEM_TEXT），悬停时提亮并给浅色底衬。
    """
    if active:
        return (
            "QPushButton {"
            f"color: {TEXT_ON_ACCENT}; background-color: {ACCENT};"
            f"border: none; border-radius: {RADIUS_SMALL};"
            "text-align: left; padding-left: 12px;"
            "font-size: 14px; font-weight: bold;"
            "}"
        )
    return (
        "QPushButton {"
        f"color: {SIDEBAR_ITEM_TEXT}; background-color: transparent;"
        "border: none;"
        "text-align: left; padding-left: 12px;"
        "font-size: 14px;"
        "}"
        "QPushButton:hover {"
        f"color: {TEXT_MAIN}; background-color: {BG_SIDEBAR_HOVER};"
        f"border-radius: {RADIUS_SMALL};"
        "}"
    )


def upgrade_button():
    """底部升级入口：用强调色实心块保证在固定底栏中足够显眼。"""
    return (
        "QPushButton {"
        f"color: {TEXT_ON_ACCENT}; background-color: {ACCENT};"
        f"border: none; border-radius: {RADIUS_SMALL};"
        "font-size: 13px; font-weight: bold;"
        "}"
        "QPushButton:hover {"
        f"background-color: {ACCENT_DARK};"
        "}"
        "QPushButton:pressed {"
        f"background-color: {ACCENT_LIGHT}; color: {TEXT_MAIN};"
        "}"
    )


def progress_bar(chunk_color=ACCENT, radius=RADIUS_SMALL):
    """Neutral progress track with a semantic or accent fill."""
    chunk_fill = chunk_color
    return (
        "QProgressBar {"
        f"background-color: {BG_INSET}; border-radius: {radius};"
        f"border: 1px solid {BORDER}; text-align: center; color: {TEXT_SECONDARY}; font-size: 12px;"
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
