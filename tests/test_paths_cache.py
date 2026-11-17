"""路径回退与缓存可写性测试。"""

import os

import core.cache as cache_mod
import core.paths as paths_mod


def test_data_dir_falls_back_when_app_dir_not_writable(tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    local = tmp_path / "local"
    monkeypatch.setattr(paths_mod, "get_app_dir", lambda: str(blocker))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    data_dir = paths_mod.get_data_dir()
    assert data_dir == str(local / "网络优化助手" / "data")
    assert os.path.isdir(data_dir)


def test_data_dir_uses_app_dir_when_writable(tmp_path, monkeypatch):
    monkeypatch.setattr(paths_mod, "get_app_dir", lambda: str(tmp_path))
    assert paths_mod.get_data_dir() == str(tmp_path / "data")


def test_cache_save_result_reports_write_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_mod, "get_cache_dir", lambda: str(tmp_path))
    manager = cache_mod.CacheManager()

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(cache_mod.os, "replace", boom)
    assert manager.save_result("diagnostic", {"summary": "x"}) is False
    assert "disk full" in manager.last_error


def test_cache_save_result_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_mod, "get_cache_dir", lambda: str(tmp_path))
    manager = cache_mod.CacheManager()
    assert manager.save_result("diagnostic", {"summary": "ok"}) is True
    assert manager.last_error == ""
    assert manager.get_history("diagnostic")[0]["result"]["summary"] == "ok"
