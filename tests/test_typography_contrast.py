"""字体可读性与对比度回归。"""

from PySide6.QtWidgets import QLabel

from core import theme


def test_text_size_never_below_readable_floor():
    for design_size in range(7, 13):
        assert theme.text_size(design_size) >= 10
    assert theme.text_size(12) >= 13
    assert theme.text_size(24) >= 26


def test_secondary_text_meets_wcag_aa_on_canvas():
    for color in (theme.TEXT_SECONDARY, theme.TEXT_3, theme.TEXT_4):
        assert theme.contrast_ratio(color, theme.BG_MAIN) >= 4.5
    for color in (theme.SUCCESS, theme.WARNING, theme.ERROR):
        assert theme.contrast_ratio(color, theme.BG_MAIN) >= 4.5


def test_window_has_no_tiny_labels(window):
    sizes = [label.font().pixelSize()
             for label in window.findChildren(QLabel)
             if label.text() and label.font().pixelSize() > 0]
    assert sizes
    assert min(sizes) >= 10
