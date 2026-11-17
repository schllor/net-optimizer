"""线条图标：直接复用设计稿里的 SVG symbol 路径，用 QSvgRenderer 渲染。

设计稿用 24×24 viewBox、stroke 描边；这里保留同一份路径数据，
按需要的尺寸与颜色渲染成 QPixmap，保证与 HTML 中的图标一致。
"""

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

SYMBOLS = {
    "wifi": '<path d="M3 8.8a13.2 13.2 0 0 1 18 0M6.6 12.4a8.2 8.2 0 0 1 10.8 0M10 15.9a3.2 3.2 0 0 1 4 0"/>'
            '<circle cx="12" cy="19.2" r="1.1" fill="currentColor" stroke="none"/>',
    "grid": '<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/>'
            '<rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>',
    "pulse": '<path d="M2.5 12h4l2.5-7 4.5 14 2.6-7h5.4"/>',
    "tool": '<path d="M14.5 6.5a4.2 4.2 0 0 0 5 5L11 20a2.8 2.8 0 0 1-4-4l8.5-9.5Z"/><path d="M13 8l3 3"/>',
    "gauge": '<path d="M4 17a8 8 0 1 1 16 0"/><path d="M12 17l4-6"/><circle cx="12" cy="17" r="1.4"/>',
    "globe": '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.4 2.4 3.6 5.3 3.6 8.5s-1.2 6.1-3.6 8.5c-2.4-2.4-3.6-5.3-3.6-8.5S9.6 5.9 12 3.5Z"/>',
    "signal": '<path d="M5 19v-4M10 19v-7M15 19V8M20 19V5"/>',
    "devices": '<rect x="2.5" y="5" width="13" height="9" rx="1.6"/><path d="M6 18h6"/><rect x="17" y="9" width="5" height="10" rx="1.4"/>',
    "download": '<path d="M12 3v12M7.5 10.5 12 15l4.5-4.5"/><path d="M4 19h16"/>',
    "clock": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5.2l3.4 2"/>',
    "settings": '<path d="M5 6h14M5 12h14M5 18h14"/><circle cx="9" cy="6" r="2"/><circle cx="15" cy="12" r="2"/><circle cx="8" cy="18" r="2"/>',
    "check": '<path d="m4.5 12.5 5 5 10-11"/>',
    "alert": '<path d="M12 3.5 21 20H3L12 3.5Z"/><path d="M12 9v5M12 17.2v.2"/>',
    "x": '<path d="m6 6 12 12M18 6 6 18"/>',
    "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "lock": '<rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8.5 10V7.5a3.5 3.5 0 0 1 7 0V10"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
    "play": '<path d="M8 5.5v13L19 12 8 5.5Z"/>',
    "folder": '<path d="M3.5 7.5h6l2 2h9v9h-17v-11Z"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-1.8 6.5"/><path d="M20 4.5V11h-6.5"/>',
    "pause": '<path d="M8.5 5v14M15.5 5v14"/>',
    "router": '<rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 16.5h.1M11 16.5h.1M7 13V9M17 13V9"/>',
    "laptop": '<rect x="4" y="5" width="16" height="10" rx="1.6"/><path d="M2.5 18h19"/>',
    "phone": '<rect x="7" y="2.5" width="10" height="19" rx="2"/><path d="M11 18.5h2"/>',
    "tv": '<rect x="3" y="4.5" width="18" height="12" rx="1.8"/><path d="M8 20h8"/>',
    "speaker": '<rect x="6" y="2.5" width="12" height="19" rx="2"/><circle cx="12" cy="8" r="2.2"/><circle cx="12" cy="16" r="2.8"/>',
    "chevron": '<path d="m6 9 6 6 6-6"/>',
    "minus": '<path d="M6 12h12"/>',
    "plus": '<path d="M12 6v12M6 12h12"/>',
}

_CACHE = {}


def _svg(name, color, stroke):
    body = SYMBOLS[name].replace("currentColor", color)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
        f'stroke-linejoin="round">{body}</svg>'
    )


def pixmap(name, size=15, color="#ffffff", stroke=1.6, scale=None):
    """按像素尺寸渲染图标；scale 用于高分屏下保持线条锐利。"""
    if scale is None:
        try:
            from PySide6.QtGui import QGuiApplication
            screen = QGuiApplication.primaryScreen()
            dpr = float(screen.devicePixelRatio()) if screen else 1.0
            scale = max(2, int(dpr) + (1 if dpr > int(dpr) else 0))
        except Exception:
            scale = 2
    key = (name, size, color, stroke, scale)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    renderer = QSvgRenderer(QByteArray(_svg(name, color, stroke).encode("utf-8")))
    px = int(round(size * scale))
    image = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, px, px))
    painter.end()
    image.setDevicePixelRatio(scale)
    result = QPixmap.fromImage(image)
    _CACHE[key] = result
    return result
