"""
本地缓存模块 - 保存诊断/修复/测速/DNS/Wi-Fi历史记录
数据保存在程序目录下的 data/cache/ 文件夹中（与 EXE 同目录，方便迁移）

性能与安全：
  - 设备别名首次读取后常驻内存，设备列表刷新时不再逐行读盘（N 次 IO -> 1 次）。
  - 历史与别名写入使用「临时文件 + 原子替换」，避免断电/崩溃产生半截 JSON。
  - 读写加可重入锁，防止后台线程与界面线程同时操作导致文件损坏。
"""

import json
import os
import threading
from datetime import datetime

from core.paths import get_cache_dir

_HISTORY_CATEGORIES = ("diagnostic", "repair", "speed", "dns", "wifi")
_MAX_RECORDS = 20


class CacheManager:
    """缓存管理器 - 保存和读取历史操作记录"""

    def __init__(self):
        self.cache_dir = get_cache_dir()
        self.cache_file = os.path.join(self.cache_dir, "history.json")
        self._lock = threading.RLock()
        self._aliases = None
        self._ensure_dir()

    def _ensure_dir(self):
        """确保缓存目录存在"""
        os.makedirs(self.cache_dir, exist_ok=True)

    def _default_history(self):
        return {key: [] for key in _HISTORY_CATEGORIES}

    def _load_all(self):
        """读取全部缓存数据（文件缺失/损坏时返回空结构）"""
        with self._lock:
            try:
                if os.path.exists(self.cache_file):
                    with open(self.cache_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        for key in _HISTORY_CATEGORIES:
                            data.setdefault(key, [])
                        return data
            except (json.JSONDecodeError, IOError, OSError):
                pass
            return self._default_history()

    def _write_json(self, path, data):
        """原子写入 JSON：先写临时文件，再一次性替换，避免文件损坏。"""
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except (IOError, OSError):
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass

    def _save_all(self, data):
        """保存全部缓存数据"""
        self._write_json(self.cache_file, data)

    def save_result(self, category, result):
        """保存一条操作记录"""
        with self._lock:
            data = self._load_all()
            if category not in data:
                data[category] = []

            entry = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "result": self._serialize(result),
            }
            data[category].append(entry)

            if len(data[category]) > _MAX_RECORDS:
                data[category] = data[category][-_MAX_RECORDS:]

            self._save_all(data)

    def get_history(self, category):
        """获取某个类别的历史记录"""
        return self._load_all().get(category, [])

    def get_all_history(self):
        """获取全部历史记录"""
        return self._load_all()

    def clear_history(self, category=None):
        """清除历史记录"""
        with self._lock:
            if category:
                data = self._load_all()
                if category in data:
                    data[category] = []
            else:
                data = self._default_history()
            self._save_all(data)

    def _serialize(self, obj):
        """将对象序列化为可JSON存储的格式"""
        try:
            if isinstance(obj, (str, int, float, bool, type(None))):
                return obj
            elif isinstance(obj, dict):
                return {k: self._serialize(v) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple)):
                return [self._serialize(item) for item in obj]
            else:
                return str(obj)
        except Exception:
            return str(obj)

    # ---------- 设备自定义名称（按 MAC 地址存储，独立于历史记录） ----------
    def _alias_file(self):
        return os.path.join(self.cache_dir, "device_aliases.json")

    def _load_aliases(self):
        """读取全部设备自定义名称 {mac: name}（首次读取后缓存到内存）"""
        with self._lock:
            if self._aliases is not None:
                return self._aliases
            aliases = {}
            try:
                if os.path.exists(self._alias_file()):
                    with open(self._alias_file(), "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        aliases = {str(k).lower(): str(v) for k, v in data.items()}
            except (json.JSONDecodeError, IOError, OSError):
                aliases = {}
            self._aliases = aliases
            return aliases

    def _save_aliases(self, aliases):
        """保存全部设备自定义名称"""
        self._write_json(self._alias_file(), aliases)

    def get_device_alias(self, mac):
        """获取某设备的自定义名称；未设置返回空串"""
        mac = (mac or "").strip().lower()
        if not mac:
            return ""
        with self._lock:
            return self._load_aliases().get(mac, "")

    def save_device_alias(self, mac, name):
        """保存/删除设备自定义名称（name 为空则清除）"""
        mac = (mac or "").strip().lower()
        if not mac:
            return
        with self._lock:
            aliases = self._load_aliases()
            name = (name or "").strip()
            if name:
                aliases[mac] = name
            else:
                aliases.pop(mac, None)
            self._save_aliases(aliases)

    def get_all_device_aliases(self):
        """获取全部设备自定义名称（返回副本，避免外部误改内存缓存）"""
        with self._lock:
            return dict(self._load_aliases())
