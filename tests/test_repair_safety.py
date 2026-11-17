"""修复预检、按项执行与代理备份。"""

import json
import os

import core.repair as repair_mod
from core.repair import NetworkRepair


def test_preview_marks_admin_and_reboot():
    preview = NetworkRepair().preview()
    by_name = {item["name"]: item for item in preview}
    assert by_name["重置Winsock目录"]["needs_reboot"] is True
    assert by_name["重置Winsock目录"]["reversible"] is False
    assert by_name["清除代理设置"]["reversible"] is True


def test_run_only_selected_items(monkeypatch):
    repair = NetworkRepair()
    calls = []

    def ok(name):
        def func():
            calls.append(name)
            return True, name + " ok"
        return func

    monkeypatch.setattr(repair, "flush_dns", ok("dns"))
    monkeypatch.setattr(repair, "clear_proxy", ok("proxy"))
    results = repair.run_all_repairs(only={"刷新DNS缓存", "清除代理设置"})
    assert [item["name"] for item in results] == ["刷新DNS缓存", "清除代理设置"]
    assert calls == ["dns", "proxy"]
    assert all(item["success"] for item in results)


def test_proxy_backup_writes_readable_file(tmp_path, monkeypatch):
    monkeypatch.setattr(repair_mod, "get_cache_dir", lambda: str(tmp_path))
    repair = NetworkRepair()
    monkeypatch.setattr(repair, "_read_proxy_settings",
                        lambda: {"ProxyEnable": 1,
                                 "ProxyServer": "127.0.0.1:8080"})
    path = repair.backup_proxy()
    assert path and os.path.exists(path)
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["values"]["ProxyServer"] == "127.0.0.1:8080"
