"""报告导出：把诊断/测速/Wi-Fi 等结果渲染为 Markdown / JSON / 纯文本。

只做本地文件写入，不联网、不上传；写入使用临时文件 + 原子替换。
"""

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime

from .paths import get_data_dir

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\s]+')


@dataclass
class ReportSection:
    title: str
    lines: list = field(default_factory=list)


@dataclass
class ReportDoc:
    kind: str
    title: str
    created_at: str = ""
    summary: str = ""
    sections: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.sections = [
            s if isinstance(s, ReportSection) else ReportSection(
                str(s.get("title", "")), list(s.get("lines") or []))
            for s in (self.sections or [])
        ]

    def as_dict(self):
        return asdict(self)


def report_dir():
    path = os.path.join(get_data_dir(), "reports")
    os.makedirs(path, exist_ok=True)
    return path


def safe_filename(text, fallback="report"):
    cleaned = _INVALID_CHARS.sub("_", (text or "").strip()).strip("_")
    return cleaned[:60] or fallback


def default_filename(doc, directory=None, ext=".md"):
    """生成默认文件名：标题_时间.md，统一放在 reports 目录。"""
    directory = directory or report_dir()
    stamp = (doc.created_at or "").replace("-", "").replace(":", "").replace(" ", "_")
    name = f"{safe_filename(doc.title, doc.kind)}_{stamp}{ext}"
    return os.path.join(directory, name)


def render_markdown(doc):
    lines = [f"# {doc.title}", "", f"- 生成时间：{doc.created_at}"]
    for key, value in (doc.meta or {}).items():
        lines.append(f"- {key}：{value}")
    if doc.summary:
        lines.extend(["", f"**结论：{doc.summary}**"])
    for section in doc.sections:
        lines.extend(["", f"## {section.title}"])
        lines.extend(f"- {line}" for line in section.lines)
    return "\n".join(lines) + "\n"


def render_text(doc):
    lines = [doc.title, f"生成时间：{doc.created_at}"]
    for key, value in (doc.meta or {}).items():
        lines.append(f"{key}：{value}")
    if doc.summary:
        lines.extend(["", f"结论：{doc.summary}"])
    for section in doc.sections:
        lines.extend(["", f"【{section.title}】"])
        lines.extend(section.lines)
    return "\n".join(lines) + "\n"


def render_json(doc):
    return json.dumps(doc.as_dict(), ensure_ascii=False, indent=2) + "\n"


_RENDERERS = {
    ".md": render_markdown,
    ".json": render_json,
    ".txt": render_text,
}


def export(doc, path=None, fmt=None):
    """把报告写到 path（默认 reports 目录），返回实际路径。

    fmt 可显式指定 md/json/txt；否则按文件后缀判断。写入失败抛 OSError。
    """
    ext = ("." + fmt.lstrip(".")).lower() if fmt else os.path.splitext(path or "")[1].lower()
    if ext not in _RENDERERS:
        ext = ".md"
    path = path or default_filename(doc, ext=ext)
    if not os.path.splitext(path)[1]:
        path += ext
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(_RENDERERS[ext](doc))
        os.replace(tmp, path)
    except OSError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise
    return path


def from_history(category, record):
    """把一条历史记录转换成可导出的报告（结果按 JSON 展开）。"""
    result = record.get("result")
    if isinstance(result, (dict, list)):
        body = json.dumps(result, ensure_ascii=False, indent=2).splitlines()
    else:
        body = [str(result)]
    return ReportDoc(
        kind=category,
        title=f"{category} 记录",
        created_at=record.get("timestamp", ""),
        summary="历史记录详情",
        sections=[ReportSection("结果", body)],
        meta={"记录类型": category},
    )
