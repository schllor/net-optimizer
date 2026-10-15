"""Ensure PySide6 and Shiboken DLLs can resolve each other in a frozen app."""

import os
import sys


if sys.platform.startswith("win") and getattr(sys, "_MEIPASS", None):
    _bundle_root = sys._MEIPASS
    _dll_dirs = [
        os.path.join(_bundle_root, "PySide6"),
        os.path.join(_bundle_root, "shiboken6"),
        _bundle_root,
    ]

    _dll_handles = []
    for _dll_dir in _dll_dirs:
        if os.path.isdir(_dll_dir):
            try:
                _dll_handles.append(os.add_dll_directory(_dll_dir))
            except (AttributeError, OSError):
                pass

    os.environ["PATH"] = os.pathsep.join(
        _dll_dirs + [os.environ.get("PATH", "")]
    )
