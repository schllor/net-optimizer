"""Windows 原生网络 API 公共层：DLL 懒加载、WLAN 会话与错误映射。

winapi_* 模块只返回数据或 None，绝不向上抛异常；失败由调用方回退
netsh/arp 文本解析。设置环境变量 NETHELPER_NATIVE=0 可整体强制旧路径。
"""

import ctypes
import os
import sys
from ctypes import wintypes

IS_WINDOWS = sys.platform == "win32"


class Win32Error(Exception):
    """原生 API 调用失败（保留函数名与错误码，便于回退时记录原因）。"""

    def __init__(self, func, code):
        self.func = func
        self.code = int(code)
        super().__init__(f"{func} 失败，错误码 {self.code}")


def native_enabled():
    """是否允许调用原生 API（非 Windows 或显式关闭时返回 False）。"""
    if not IS_WINDOWS:
        return False
    return os.environ.get("NETHELPER_NATIVE", "1").strip() != "0"


_DLL_CACHE = {}


def load_dll(name):
    """按名称懒加载系统 DLL（失败抛 OSError，由上层转成回退）。"""
    dll = _DLL_CACHE.get(name)
    if dll is None:
        dll = ctypes.WinDLL(name)
        _DLL_CACHE[name] = dll
    return dll


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


if IS_WINDOWS:
    assert ctypes.sizeof(GUID) == 16, "GUID 结构体大小异常"


class WlanSession:
    """WlanOpenHandle / WlanCloseHandle 的上下文管理，确保句柄释放。"""

    def __init__(self):
        self.dll = load_dll("wlanapi")
        self.handle = wintypes.HANDLE()
        self.negotiated = wintypes.DWORD()

    def __enter__(self):
        ret = self.dll.WlanOpenHandle(
            2, None, ctypes.byref(self.negotiated), ctypes.byref(self.handle))
        if ret != 0:
            raise Win32Error("WlanOpenHandle", ret)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.handle:
            try:
                self.dll.WlanCloseHandle(self.handle, None)
            except Exception:
                pass
            self.handle = None
        return False

    def free(self, ptr):
        """释放 WlanAPI 分配的内存（WlanFreeMemory）。"""
        if ptr:
            try:
                self.dll.WlanFreeMemory(ptr)
            except Exception:
                pass
