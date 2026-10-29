"""用户设置：JSON 持久化、默认值与原子写入。

设置保存在数据目录下的 settings.json（与历史记录同一目录），
读取时合并默认值，文件损坏或缺失都不会影响程序启动。
"""

import json
import os
import threading

from .paths import get_data_dir

DEFAULTS = {
    "download_dir": "",
    "report_dir": "",
    "speed_dl_seconds": 8,
    "speed_ul_seconds": 6,
    "dns_rounds": 3,
    "history_limit": 20,
    "animations": True,
    "native_api": True,
    "traffic_include_vpn": False,
}


def default_path():
    return os.path.join(get_data_dir(), "settings.json")


class Settings:
    """带内存缓存的设置读写。"""

    def __init__(self, path=None):
        self.path = path or default_path()
        self._lock = threading.RLock()
        self._data = None
        self.last_error = ""

    def _load(self):
        with self._lock:
            if self._data is not None:
                return self._data
            data = dict(DEFAULTS)
            try:
                if os.path.exists(self.path):
                    with open(self.path, "r", encoding="utf-8") as f:
                        stored = json.load(f)
                    if isinstance(stored, dict):
                        for key in DEFAULTS:
                            if key in stored:
                                data[key] = stored[key]
            except (json.JSONDecodeError, OSError, ValueError):
                pass
            self._data = data
            return data

    def get(self, key, default=None):
        data = self._load()
        return data.get(key, DEFAULTS.get(key, default))

    def as_dict(self):
        return dict(self._load())

    def update(self, values):
        """合并写入设置并落盘，返回是否成功（失败原因见 last_error）。"""
        with self._lock:
            data = self._load()
            data.update(values or {})
            self._data = data
            tmp = f"{self.path}.{os.getpid()}.tmp"
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
                self.last_error = ""
                return True
            except OSError as e:
                self.last_error = str(e)
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except OSError:
                    pass
                return False

    def reset(self):
        """恢复默认设置。"""
        self._data = dict(DEFAULTS)
        return self.update(self._data)


def apply_runtime(settings):
    """把需要立即生效的设置同步到运行环境。"""
    os.environ["NETHELPER_NATIVE"] = (
        "1" if settings.get("native_api", True) else "0")
