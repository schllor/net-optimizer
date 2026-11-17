"""应用状态中心：把“最近一次结果”和“当前网络快照”集中到一处。

此前各页面各自从 CacheManager 读历史、各自写假默认值，导致同一数据
在不同页面不一致。现在约定：

  - 后台任务结果统一通过 ``publish(kind, data)`` 写入；
  - 页面通过信号刷新，不再自己读盘；
  - AppState 只关心数据和信号，不持有任何 Qt 控件。
"""

from collections import deque

from PySide6.QtCore import QObject, Signal

CATEGORIES = ("diagnostic", "repair", "speed", "dns", "wifi")


class AppState(QObject):
    """全局只读快照 + 最近结果 + 60 秒流量缓冲。"""

    snapshot_changed = Signal(object)
    result_published = Signal(str, object)
    traffic_changed = Signal(float, float)
    online_changed = Signal(bool)

    def __init__(self, cache, parent=None):
        super().__init__(parent)
        self.cache = cache
        self._latest = {key: None for key in CATEGORIES}
        self._snapshot = None
        self._online = None
        self._traffic = deque(maxlen=60)
        self._load_latest()

    # ---------------------------------------------------------------- 初始化
    def _load_latest(self):
        """从缓存载入每类最近一条，避免首页重启后一片空白。"""
        try:
            data = self.cache.get_all_history() or {}
        except Exception:
            data = {}
        for key in CATEGORIES:
            records = data.get(key) or []
            if records:
                self._latest[key] = records[-1].get("result")

    # ---------------------------------------------------------------- 结果
    @property
    def latest(self):
        return dict(self._latest)

    def get_latest(self, kind):
        return self._latest.get(kind)

    def publish(self, kind, data, save=True):
        """登记一次任务结果；save=True 时同时写入本地历史。"""
        if kind not in self._latest:
            self._latest[kind] = data
        else:
            self._latest[kind] = data
        if save and self.cache is not None:
            try:
                self.cache.save_result(kind, data)
            except Exception:
                pass
        self.result_published.emit(kind, data)
        return data

    # ---------------------------------------------------------------- 快照
    @property
    def snapshot(self):
        return self._snapshot

    def set_snapshot(self, snapshot):
        self._snapshot = snapshot
        self.snapshot_changed.emit(snapshot)
        online = bool(getattr(snapshot, "online", False))
        if self._online is None or online != self._online:
            self._online = online
            self.online_changed.emit(online)

    # ---------------------------------------------------------------- 流量
    @property
    def traffic(self):
        return list(self._traffic)

    def push_traffic(self, up, down):
        try:
            up = float(up or 0.0)
            down = float(down or 0.0)
        except (TypeError, ValueError):
            return
        self._traffic.append((up, down))
        self.traffic_changed.emit(up, down)
