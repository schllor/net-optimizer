"""窗口几何/状态持久化。"""

from PySide6.QtCore import QByteArray


def test_window_state_is_saved_to_settings(window, tmp_path):
    window.settings.path = str(tmp_path / "settings.json")
    window.settings._data = None
    window.resize(1200, 700)
    window._save_window_state()
    encoded = window.settings.get("window_geometry")
    assert encoded
    assert QByteArray.fromBase64(encoded.encode("ascii")).isEmpty() is False
    assert window.settings.get("window_state") in ("normal", "maximized")


def test_window_restore_does_not_raise(window):
    window._restore_window_state()
    assert window.minimumWidth() == 1024
    assert window.minimumHeight() == 640
