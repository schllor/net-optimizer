"""
网络优化助手核心模块单元测试。
覆盖：URL/主机安全校验、文件名清洗、编码解码、分块逻辑、进度计算。
运行：pytest tests/  （在源代码根目录下）
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.downloader import (
    is_private_host, validate_url, sanitize_filename, guess_filename, Downloader,
)
from core.cmd_utils import smart_decode, run_cmd, smart_run
from core.version import __version__


# ---------- 防 SSRF：内网/回环识别 ----------
@pytest.mark.parametrize("host,expected", [
    ("127.0.0.1", True),
    ("10.0.0.1", True),
    ("192.168.31.5", True),
    ("172.16.0.9", True),
    ("172.31.255.255", True),
    ("169.254.1.1", True),
    ("localhost", True),
    ("", True),  # 空主机按私有处理
    ("0.0.0.0", True),
    ("100.64.0.1", True),   # 运营商级 NAT 保留段
    ("::1", True),
    ("fe80::1", True),
    ("::ffff:127.0.0.1", True),
    ("2130706433", True),   # 整型写法 127.0.0.1
    ("example.local", True),
    ("[::1]", True),        # URL 中的方括号 IPv6
])
def test_private_hosts_are_blocked(host, expected):
    assert is_private_host(host) is expected


@pytest.mark.parametrize("host", ["8.8.8.8", "223.5.5.5", "example.com", "github.com"])
def test_public_hosts_are_allowed(host):
    assert is_private_host(host) is False


# ---------- URL 校验 ----------
@pytest.mark.parametrize("url,err_frag", [
    ("", "填入下载地址"),
    ("   ", "填入下载地址"),
    ("ftp://example.com/f.zip", "http/https"),
    ("file:///etc/passwd", "http/https"),
    ("http://192.168.1.1/a.zip", "内网"),
    ("http://10.0.0.1/a.zip", "内网"),
    ("http://", "主机名"),
    ("http://localhost/a.zip", "内网"),
])
def test_validate_url_rejects_bad_input(url, err_frag):
    msg = validate_url(url)
    assert err_frag in msg


def test_validate_url_accepts_public_https():
    assert validate_url("https://example.com/file.zip") == ""
    assert validate_url("http://github.com/x/y.zip") == ""


# ---------- 文件名清洗（防路径注入） ----------
@pytest.mark.parametrize("name,expected", [
    ("a:b*c?.zip", "a_b_c_.zip"),
    ("a/b\\c<d>e", "a_b_c_d_e"),
    ("..", "download.bin"),
    ("", "download.bin"),
    ("normal.zip", "normal.zip"),
    ('evil\x00name', "evil_name"),  # 控制字符剔除
])
def test_sanitize_filename(name, expected):
    assert sanitize_filename(name) == expected


def test_guess_filename_from_url():
    assert guess_filename("https://example.com/path/file.zip") == "file.zip"
    assert guess_filename("https://example.com/%E4%B8%AD%E6%96%87.zip") == "中文.zip"
    assert guess_filename("https://example.com/") == "download.bin"


# ---------- 编码智能解码 ----------
def test_smart_decode_utf8():
    assert smart_decode("中文".encode("utf-8")) == "中文"


def test_smart_decode_gbk_fallback():
    assert smart_decode("中文".encode("gbk")) == "中文"


def test_smart_decode_empty_and_str():
    assert smart_decode(b"") == ""
    assert smart_decode("abc") == "abc"  # 已是 str 原样返回


def test_smart_decode_garbled_never_raises():
    # 非法字节序列也保证不抛异常
    assert isinstance(smart_decode(b"\xff\xfe\x00"), str)


# ---------- 命令执行（本地，不依赖网络） ----------
def test_run_cmd_returns_decoded_text():
    out = run_cmd([sys.executable, "-c", "print('hello')"], timeout=10)
    assert "hello" in out


def test_run_cmd_chinese_output():
    out = run_cmd([sys.executable, "-c", "print('你好世界')"], timeout=10)
    assert "你好世界" in out


def test_smart_run_returncode():
    res = smart_run([sys.executable, "-c", "print('ok')"], timeout=10)
    assert res.returncode == 0
    assert "ok" in res.stdout


# ---------- 分段与进度逻辑（不触发网络） ----------
def _make_dl(total, supports_range=True, max_conn=8):
    d = Downloader.__new__(Downloader)  # 跳过 __init__，避免真实 URL
    import threading
    d.url = "https://example.com/f.zip"
    d.orig_url = d.url
    d.max_workers = max_conn
    d.max_conn = max_conn
    d.mirror = False
    d.total_size = total
    d.supports_range = supports_range
    d.done_bytes = 0
    d._single_mode = False
    d._segs = []
    d._lock = threading.RLock()
    d._wake = threading.Event()
    return d


def _assert_contiguous(segs, total):
    assert segs[0].start == 0
    assert segs[-1].end == total - 1
    for a, b in zip(segs, segs[1:]):
        assert b.start == a.end + 1


def test_init_segments_small_file_is_single():
    d = _make_dl(total=2 * 1024 * 1024)  # 2MB，小于 MIN_MULTI_SIZE
    d._init_segments()
    assert len(d._segs) == 1
    assert d._single_mode is False  # 仍支持 Range，只是不并行


def test_init_segments_large_file_starts_four():
    total = 20 * 1024 * 1024
    d = _make_dl(total=total, max_conn=8)
    d._init_segments()
    assert len(d._segs) == 4  # START_CONNECTIONS
    _assert_contiguous(d._segs, total)


def test_init_segments_respects_max_conn():
    total = 20 * 1024 * 1024
    d = _make_dl(total=total, max_conn=3)
    d._init_segments()
    assert len(d._segs) == 3
    _assert_contiguous(d._segs, total)


def test_init_segments_no_range_single_mode():
    d = _make_dl(total=10 * 1024 * 1024, supports_range=False)
    d._init_segments()
    assert len(d._segs) == 1
    assert d._single_mode is True


def test_split_segment_halves_and_keeps_coverage():
    total = 8 * 1024 * 1024
    d = _make_dl(total=total, max_conn=8)
    d._init_segments()
    seg = d._segs[0]
    old_end = seg.end
    cut = seg.start + (old_end - seg.start + 1) // 2
    seg.split_at = cut
    with d._lock:
        d._apply_split_locked(seg)
    assert seg.end == cut - 1
    assert d._segs[-1].start == cut
    assert d._segs[-1].end == old_end
    d._segs.sort(key=lambda s: s.start)
    _assert_contiguous(d._segs, total)


def test_split_rejects_tiny_tail():
    total = 8 * 1024 * 1024
    d = _make_dl(total=total, max_conn=8)
    d._init_segments()
    seg = d._segs[0]
    seg.split_at = seg.end  # 尾部只剩 1 字节，低于 MIN_SEGMENT
    before = len(d._segs)
    with d._lock:
        d._apply_split_locked(seg)
    assert len(d._segs) == before
    assert seg.split_at is None


def test_recount_counts_only_written_bytes():
    d = _make_dl(total=1024 * 1024)
    d._init_segments()  # 小于 4MB，单段
    seg = d._segs[0]
    seg.pos = 400 * 1024
    d._recount_locked()
    assert d.done_bytes == 400 * 1024
    seg.pos = seg.end + 1  # 完成
    d._recount_locked()
    assert d.done_bytes == 1024 * 1024


def test_resume_state_roundtrip(tmp_path):
    import threading
    total = 20 * 1024 * 1024
    d = _make_dl(total=total)
    d.filepath = str(tmp_path / "f.bin")
    d.state_path = d.filepath + ".netmeta.json"
    d._state_lock = threading.RLock()
    d._init_segments()
    d._segs[0].pos = 12345
    d._save_state()

    d2 = _make_dl(total=total)
    d2.filepath = d.filepath
    d2.state_path = d.state_path
    assert d2._load_resume() is True
    assert d2.resumed is True
    assert d2._segs[0].pos == 12345
    assert d2.done_bytes == 12345


def test_resume_rejects_mismatched_total(tmp_path):
    import json
    import threading
    total = 20 * 1024 * 1024
    d = _make_dl(total=total)
    d.filepath = str(tmp_path / "f.bin")
    d.state_path = d.filepath + ".netmeta.json"
    d._state_lock = threading.RLock()
    d._init_segments()
    d._save_state()

    with open(d.state_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["total"] = total + 1
    with open(d.state_path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    d2 = _make_dl(total=total)
    d2.filepath = d.filepath
    d2.state_path = d.state_path
    assert d2._load_resume() is False


def test_percent_unknown_size_is_zero():
    d = _make_dl(total=0)
    assert d.percent == 0.0


def test_percent_normal():
    d = _make_dl(total=100)
    d.done_bytes = 50
    assert d.percent == 50.0
    d.done_bytes = 999
    assert d.percent == 100.0  # 封顶


# ---------- 版本号一致性 ----------
def test_version_is_defined():
    assert __version__
    parts = __version__.split(".")
    assert len(parts) == 3