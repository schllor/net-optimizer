"""下载器集成测试：本地限速 HTTP 服务（支持/不支持 Range）。

覆盖：并发分块正确性与提速、无 Range 回退单流、取消后续传、源轮询。
所有请求走 127.0.0.1，测试内临时放行回环地址。
"""

import hashlib
import os
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import core.downloader as downloader
from core.downloader import Downloader

FILE_SIZE = 8 * 1024 * 1024
RATE = 2 * 1024 * 1024          # 单连接限速 2MB/s
SINGLE_EST = FILE_SIZE / RATE   # 单连接理论耗时约 4s


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    data = b""
    rate = 0
    allow_range = True
    chunk = 32 * 1024
    lock = threading.Lock()
    state = None

    def log_message(self, *args):
        pass

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.data)))
        self.send_header("Accept-Ranges",
                         "bytes" if self.allow_range else "none")
        self.end_headers()

    def do_GET(self):
        total = len(self.data)
        start, end, partial = 0, total - 1, False
        rng = self.headers.get("Range") or ""
        if self.allow_range and rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            start = int(a) if a else 0
            end = min(int(b) if b else total - 1, total - 1)
            partial = start <= end
            if not partial:
                start, end = 0, total - 1
        body = self.data[start:end + 1]

        if partial:
            self.send_response(206)
            self.send_header("Content-Range",
                             f"bytes {start}-{end}/{total}")
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Accept-Ranges",
                         "bytes" if self.allow_range else "none")
        self.end_headers()

        with self.lock:
            self.state["active"] += 1
            self.state["peak"] = max(self.state["peak"], self.state["active"])
            self.state["gets"] += 1
        try:
            delay = self.chunk / self.rate if self.rate else 0
            for off in range(0, len(body), self.chunk):
                self.wfile.write(body[off:off + self.chunk])
                self.wfile.flush()
                if delay:
                    time.sleep(delay)
        except (BrokenPipeError, ConnectionResetError,
                ConnectionAbortedError, OSError):
            pass
        finally:
            with self.lock:
                self.state["active"] -= 1


def _start_server(data, rate=0, allow_range=True):
    state = {"active": 0, "peak": 0, "gets": 0, "lock": threading.Lock()}
    handler = type("Handler", (_Handler,), {
        "data": data,
        "rate": rate,
        "allow_range": allow_range,
        "lock": state["lock"],
        "state": state,
    })
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/file.bin"
    return srv, state, url


@pytest.fixture
def net_env(monkeypatch):
    # 回环地址在测试内视为公网；清掉可能存在的系统代理配置
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setattr(downloader, "_OPENER", None)
    monkeypatch.setattr(downloader, "is_private_host", lambda host: False)


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def test_parallel_download_is_faster_and_correct(tmp_path, net_env):
    data = random.Random(20261101).randbytes(FILE_SIZE)
    srv, state, url = _start_server(data, rate=RATE)
    try:
        d = Downloader(url, str(tmp_path), max_workers=4)
        t0 = time.monotonic()
        d.start(timeout=60)
        elapsed = time.monotonic() - t0
    finally:
        srv.shutdown()
        srv.server_close()

    assert d.completed, d.error
    assert d.done_bytes == FILE_SIZE
    assert _sha256_file(d.filepath) == hashlib.sha256(data).hexdigest()
    assert state["peak"] >= 4, f"峰值并发只有 {state['peak']}"
    # 4 路并发应在单连接理论耗时的一半左右完成
    assert elapsed < SINGLE_EST * 0.7, f"耗时 {elapsed:.2f}s 未达提速预期"


def test_no_range_server_falls_back_to_single_stream(tmp_path, net_env):
    data = random.Random(7).randbytes(3 * 1024 * 1024)
    srv, _state, url = _start_server(data, rate=RATE, allow_range=False)
    try:
        d = Downloader(url, str(tmp_path), max_workers=8)
        d.start(timeout=60)
    finally:
        srv.shutdown()
        srv.server_close()

    assert d.completed, d.error
    assert d._single_mode is True
    assert _sha256_file(d.filepath) == hashlib.sha256(data).hexdigest()


def test_cancel_then_resume(tmp_path, net_env):
    data = random.Random(99).randbytes(FILE_SIZE)
    rate = 1024 * 1024
    srv, _state, url = _start_server(data, rate=rate)
    try:
        d = Downloader(url, str(tmp_path), max_workers=4)
        th = threading.Thread(target=d.start, kwargs={"timeout": 60}, daemon=True)
        th.start()

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and d.done_bytes < FILE_SIZE // 4:
            time.sleep(0.03)
        assert d.done_bytes > 0, "下载未开始"
        d.cancel()
        th.join(20)
        assert not th.is_alive()
        assert not d.completed
        assert os.path.exists(d.filepath + ".netmeta.json")

        d2 = Downloader(url, str(tmp_path), max_workers=4)
        d2.start(timeout=60)
    finally:
        srv.shutdown()
        srv.server_close()

    assert d2.completed, d2.error
    assert d2.resumed is True
    assert d2.filepath == d.filepath
    assert _sha256_file(d2.filepath) == hashlib.sha256(data).hexdigest()


def test_pick_source_skips_dead_and_cooling():
    d = Downloader("https://example.com/f.zip", ".", max_workers=4)
    d._sources = ["a", "b", "c"]
    d._source_bad = [False, True, False]
    d._source_cool = [0.0, 0.0, time.monotonic() + 30]
    assert d._pick_source_locked() == 0
    assert d._pick_source_locked() == 0

    d._source_cool[0] = time.monotonic() + 30
    assert d._pick_source_locked() == -1
    assert d._has_usable_source_locked() is False
    assert d._all_sources_dead_locked() is False  # 只是冷却，不是永久失效
