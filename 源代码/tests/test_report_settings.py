"""设置与报告模块测试：原子写入、默认值、渲染与历史转换。"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.report import (
    ReportDoc, ReportSection, default_filename, export, from_history,
    render_json, render_markdown, render_text, safe_filename,
)
from core.settings import DEFAULTS, Settings


def test_settings_returns_defaults_when_file_missing(tmp_path):
    settings = Settings(str(tmp_path / "settings.json"))
    assert settings.get("history_limit") == DEFAULTS["history_limit"]
    assert settings.get("native_api") is True
    assert settings.get("missing", 42) == 42


def test_settings_update_roundtrip_and_reset(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings(str(path))

    assert settings.update({"history_limit": 7, "animations": False})
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["history_limit"] == 7
    assert stored["animations"] is False
    assert stored["speed_dl_seconds"] == DEFAULTS["speed_dl_seconds"]

    reloaded = Settings(str(path))
    assert reloaded.get("history_limit") == 7
    assert reloaded.get("animations") is False

    assert settings.reset()
    assert settings.get("history_limit") == DEFAULTS["history_limit"]
    assert settings.get("animations") is True


def test_settings_tolerates_corrupt_file(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    settings = Settings(str(path))
    assert settings.get("history_limit") == DEFAULTS["history_limit"]


def test_report_renderers_include_summary_and_sections():
    doc = ReportDoc(
        kind="diagnostic",
        title="网络诊断报告",
        created_at="2026-01-02 03:04:05",
        summary="一切正常",
        sections=[ReportSection("网卡状态", ["已连接"])],
        meta={"版本": "v1.8.0"},
    )

    markdown = render_markdown(doc)
    assert "# 网络诊断报告" in markdown
    assert "**结论：一切正常**" in markdown
    assert "## 网卡状态" in markdown

    text = render_text(doc)
    assert "【网卡状态】" in text
    assert "结论：一切正常" in text

    payload = json.loads(render_json(doc))
    assert payload["sections"][0]["lines"] == ["已连接"]
    assert payload["meta"]["版本"] == "v1.8.0"


def test_report_export_writes_atomically(tmp_path):
    doc = ReportDoc(kind="wifi", title="Wi-Fi 诊断报告", summary="ok")
    path = export(doc, str(tmp_path / "wifi.md"))
    assert os.path.exists(path)
    assert "Wi-Fi 诊断报告" in open(path, encoding="utf-8").read()
    assert not [p for p in os.listdir(tmp_path) if p.endswith(".tmp")]


def test_report_filename_is_sanitized(tmp_path):
    assert safe_filename('a/b:c*?"<>|') == "a_b_c"
    doc = ReportDoc(kind="diagnostic", title="诊断 报告",
                    created_at="2026-01-02 03:04:05")
    name = default_filename(doc, directory=str(tmp_path))
    assert name.endswith("_20260102_030405.md")
    assert os.path.dirname(name) == str(tmp_path)


def test_from_history_keeps_record_payload():
    record = {"timestamp": "2026-01-02 03:04:05", "result": {"ok": True}}
    doc = from_history("speed", record)
    assert doc.created_at == "2026-01-02 03:04:05"
    assert any("true" in line for line in doc.sections[0].lines)
