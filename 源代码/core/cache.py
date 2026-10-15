"""
本地缓存模块 - 保存诊断/修复/测速/DNS/Wi-Fi历史记录
数据保存在程序目录下的 data/cache/ 文件夹中（与 EXE 同目录，方便迁移）
"""

import json
import os
from datetime import datetime

from core.paths import get_cache_dir


class CacheManager:
    """缓存管理器 - 保存和读取历史操作记录"""

    def __init__(self):
        self.cache_dir = get_cache_dir()
        self.cache_file = os.path.join(self.cache_dir, "history.json")
        self._ensure_dir()

    def _ensure_dir(self):
        """确保缓存目录存在"""
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)

    def _load_all(self):
        """读取全部缓存数据"""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
        return {"diagnostic": [], "repair": [], "speed": [], "dns": [], "wifi": []}

    def _save_all(self, data):
        """保存全部缓存数据"""
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except IOError:
            pass

    def save_result(self, category, result):
        """保存一条操作记录"""
        data = self._load_all()
        if category not in data:
            data[category] = []

        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "result": self._serialize(result),
        }
        data[category].append(entry)

        max_records = 20
        if len(data[category]) > max_records:
            data[category] = data[category][-max_records:]

        self._save_all(data)

    def get_history(self, category):
        """获取某个类别的历史记录"""
        data = self._load_all()
        return data.get(category, [])

    def get_all_history(self):
        """获取全部历史记录"""
        return self._load_all()

    def clear_history(self, category=None):
        """清除历史记录"""
        data = self._load_all()
        if category:
            if category in data:
                data[category] = []
        else:
            data = {"diagnostic": [], "repair": [], "speed": [], "dns": [], "wifi": []}
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
        """读取全部设备自定义名称 {mac: name}"""
        try:
            if os.path.exists(self._alias_file()):
                with open(self._alias_file(), "r", encoding="utf-8") as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
        return {}

    def _save_aliases(self, aliases):
        """保存全部设备自定义名称"""
        try:
            with open(self._alias_file(), "w", encoding="utf-8") as f:
                json.dump(aliases, f, ensure_ascii=False, indent=2)
        except IOError:
            pass

    def get_device_alias(self, mac):
        """获取某设备的自定义名称；未设置返回空串"""
        mac = (mac or "").strip().lower()
        if not mac:
            return ""
        return self._load_aliases().get(mac, "")

    def save_device_alias(self, mac, name):
        """保存/删除设备自定义名称（name 为空则清除）"""
        mac = (mac or "").strip().lower()
        if not mac:
            return
        aliases = self._load_aliases()
        name = (name or "").strip()
        if name:
            aliases[mac] = name
        else:
            aliases.pop(mac, None)
        self._save_aliases(aliases)

    def get_all_device_aliases(self):
        """获取全部设备自定义名称"""
        return self._load_aliases()
