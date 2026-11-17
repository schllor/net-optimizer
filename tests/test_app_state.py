"""AppState 数据中枢与网络快照的单元测试。"""

from core.net_snapshot import Snapshot
from ui.state import AppState


class FakeCache:
    def __init__(self):
        self.saved = []

    def get_all_history(self):
        return {"diagnostic": [{"result": [{"name": "网卡状态",
                                            "status": "ok"}]}]}

    def save_result(self, kind, data):
        self.saved.append((kind, data))
        return True


def test_app_state_loads_latest_and_publishes(qtapp):
    cache = FakeCache()
    state = AppState(cache)
    assert state.get_latest("diagnostic")[0]["name"] == "网卡状态"

    seen = []
    state.result_published.connect(lambda kind, data: seen.append((kind, data)))
    state.publish("speed", {"download": {"speed_mbps": 100}})
    assert seen and seen[-1][0] == "speed"
    assert state.get_latest("speed")["download"]["speed_mbps"] == 100
    assert cache.saved[-1][0] == "speed"


def test_app_state_traffic_and_snapshot(qtapp):
    state = AppState(FakeCache())
    values = []
    state.traffic_changed.connect(lambda up, down: values.append((up, down)))
    state.push_traffic(10, 20)
    state.push_traffic(30, 40)
    assert state.traffic == [(10.0, 20.0), (30.0, 40.0)]
    assert values[-1] == (30.0, 40.0)

    online = []
    state.online_changed.connect(online.append)
    state.set_snapshot(Snapshot(kind="wifi", ssid="Home",
                                band="5G", online=True))
    state.set_snapshot(Snapshot(kind="wifi", ssid="Home",
                                band="5G", online=False))
    assert online == [True, False]


def test_snapshot_summary_uses_real_fields():
    assert Snapshot(kind="wifi", ssid="Home", band="5G").summary == (
        "已连接 · Home · 5G")
    assert Snapshot(kind="ethernet", ipv4="192.168.1.2").summary == "有线连接"
    assert Snapshot().summary == "未连接"
