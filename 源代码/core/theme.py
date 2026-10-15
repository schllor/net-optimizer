"""Voltagent-inspired dark utility theme with neutral surfaces and one accent."""

# ---------- Dark neutral palette ----------
BG_MAIN = "#111214"
BG_CARD = "#1a1d20"
BG_RAISED = "#252a2e"
BG_SIDEBAR = "#0c0f11"
BG_SIDEBAR_HOVER = "#20272a"
BG_INSET = "#15191c"

SHADOW_DARK = "#454d52"
SHADOW_LIGHT = "#202020"
BORDER = "#363d42"

# Electric green is reserved for actions, active states, and progress.
ACCENT = "#00d992"
ACCENT_DARK = "#00b87b"
ACCENT_LIGHT = "#173f35"
FOCUS = "#5eead4"

# Semantic colors are reserved for diagnostic and operation states.
SUCCESS = "#63d6a0"
SUCCESS_LIGHT = "#17372c"
WARNING = "#e7b86a"
WARNING_LIGHT = "#3a2f1e"
ERROR = "#f18484"
ERROR_LIGHT = "#3a2224"
INFO_LIGHT = "#20282d"

# Text
TEXT_MAIN = "#f2f2f2"
TEXT_SECONDARY = "#c4cbd0"
TEXT_LIGHT = "#8e989e"
TEXT_WHITE = "#ffffff"
TEXT_ON_ACCENT = "#06140f"

# Compact geometry for a quiet utility interface.
RADIUS = "8px"
RADIUS_SMALL = "6px"
RADIUS_PILL = "8px"


# ---------- Flat surfaces with hairline borders ----------
def _flat(bg, radius):
    """A flat surface with a restrained outline."""
    return (
        "QFrame {"
        f"background-color: {bg};"
        f"border-radius: {radius};"
        f"border: 1px solid {BORDER};"
        "}"
    )


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


def inset_surface(radius=RADIUS_SMALL, bg=BG_INSET):
    """Inset surface for logs, inputs, and progress tracks."""
    return _flat(bg, radius)


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


def success_button(radius=RADIUS_PILL):
    """Semantic success action."""
    return _solid_button(SUCCESS, radius, "#4fa978", TEXT_ON_ACCENT)


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


def accent_inline(radius=RADIUS_SMALL):
    """Compact primary action."""
    return _solid_button(ACCENT, radius, ACCENT_DARK, TEXT_ON_ACCENT).replace(
        "font-size: 15px", "font-size: 13px")


def nav_button(active=False):
    """Sidebar navigation with a subtle active rail."""
    if active:
        return (
            "QPushButton {"
            f"color: {TEXT_MAIN}; background-color: {BG_SIDEBAR_HOVER};"
            f"border: none; border-left: 3px solid {ACCENT};"
            "text-align: left; padding-left: 19px;"
            "font-size: 14px; font-weight: bold;"
            "}"
        )
    return (
        "QPushButton {"
        f"color: {TEXT_SECONDARY}; background-color: transparent;"
        "border: none;"
        "text-align: left; padding-left: 22px;"
        "font-size: 14px;"
        "}"
        "QPushButton:hover {"
        f"color: {TEXT_MAIN}; background-color: {BG_SIDEBAR_HOVER};"
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
