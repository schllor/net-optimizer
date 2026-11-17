"""响应式布局与页面滚动容器。"""

from ui.kit import PageHead
from ui.responsive import ResponsiveColumns, mode_for


def test_mode_thresholds():
    assert mode_for(1024, 640) == "compact"
    assert mode_for(1280, 720) == "compact"
    assert mode_for(1280, 800) == "regular"
    assert mode_for(1920, 1080) == "wide"
    assert mode_for(2560, 1440) == "wide"


def test_page_views_and_compact_sidebar(app, window):
    assert len(window.page_views) == 10
    assert window.pages.count() == 10
    window._switch_page("home")
    assert window.pages.currentWidget() is window.page_views["home"]

    window.resize(1024, 640)
    window._apply_layout_mode()
    app.processEvents()
    assert window.layout_mode == "compact"
    assert window.sidebar.width() == 76
    heads = window.findChildren(PageHead)
    assert heads and all(head._compact for head in heads)
    columns = window.findChildren(ResponsiveColumns)
    assert columns and all(column.compact for column in columns)

    window.resize(1280, 800)
    window.layout_mode = None  # 强制重新计算
    window._apply_layout_mode()
    app.processEvents()
    assert window.layout_mode == "regular"
    assert window.sidebar.width() == 212
