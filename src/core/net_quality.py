"""网络质量测量：延迟统计、HTTP 首字节延迟、稳定窗口吞吐。

不含 Qt、不读配置，方便单独测试。方法学参考：
  - 延迟用 P50/P95 而不是单次平均值（namebench / GRC DNS Benchmark 的样本思想）；
  - 抖动按 RFC 3550 平滑公式，连续采样差的指数平均；
  - 吞吐用「多流同时活跃的最大 N 秒窗口」，并跳过开头的 TCP 慢启动期，
    避免低链接开局把均值拉低（cloudflare/speedtest 的多流 + 稳定窗口思路）。
"""

import http.client
import re
import socket
import ssl
import threading
import time
import urllib.parse
from collections import deque
from dataclasses import asdict, dataclass

from .cmd_utils import IS_WINDOWS, run_cmd_ex

# Windows/Linux ping 回复行中的单次 RTT，例如「时间=12ms」「时间<1ms」「time=12ms」
_PING_TIME_RE = re.compile(
    r"(?:时间|time)\s*(?:[=＝]\s*)?(<)?\s*([\d.]+)\s*ms", re.IGNORECASE)

USER_AGENT = "Mozilla/5.0 NetHelper/1.0"


def parse_ping_times(text):
    """从 ping 输出中提取全部单次 RTT（毫秒）。`<1ms` 按 0.5ms 计。"""
    samples = []
    for lt, value in _PING_TIME_RE.findall(text or ""):
        try:
            rtt = float(value)
        except ValueError:
            continue
        samples.append(0.5 if lt else rtt)
    return samples


@dataclass
class Stats:
    """一组延迟样本的统计结果（单位均为毫秒，loss 为百分比）。"""

    count: int = 0
    mean: float = 0.0
    p50: float = 0.0
    p95: float = 0.0
    min: float = 0.0
    max: float = 0.0
    jitter: float = 0.0
    loss: float = 0.0

    def as_dict(self):
        return asdict(self)


def _percentile(sorted_values, q):
    """线性插值分位数（q 取 0~100），与 numpy 默认算法一致。"""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    rank = (len(sorted_values) - 1) * q / 100.0
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    frac = rank - low
    return float(sorted_values[low] + (sorted_values[high] - sorted_values[low]) * frac)


def summarize(samples, sent=None):
    """把延迟样本汇总为 Stats。

    sent 为实际发送次数（默认等于样本数），用于计算丢包百分比；
    抖动用相邻样本差的指数平滑（RFC 3550：J += (|D| - J) / 16）。
    """
    values = sorted(float(s) for s in (samples or []) if s is not None)
    if not values:
        return Stats(loss=100.0 if sent else 0.0, count=0)
    count = len(values)
    sent = max(count, int(sent or count))
    jitter = 0.0
    raw = [float(s) for s in samples if s is not None]
    for prev, cur in zip(raw, raw[1:]):
        jitter += (abs(cur - prev) - jitter) / 16.0
    return Stats(
        count=count,
        mean=round(sum(values) / count, 1),
        p50=round(_percentile(values, 50), 1),
        p95=round(_percentile(values, 95), 1),
        min=round(values[0], 1),
        max=round(values[-1], 1),
        jitter=round(jitter, 1),
        loss=round((sent - count) / sent * 100, 1) if sent else 0.0,
    )


def icmp_latency(host, count=5, timeout_ms=2000, cancel=None):
    """ICMP 延迟采样（支持取消）。返回 samples 与 Stats。"""
    samples = []
    if IS_WINDOWS:
        total_timeout = max(6, int(count * (timeout_ms / 1000.0) + 3))
        res = run_cmd_ex(
            ["ping", "-n", str(count), "-w", str(timeout_ms), host],
            timeout=total_timeout, cancel=cancel)
        samples = parse_ping_times(res.stdout)
    else:
        for _ in range(count):
            if cancel is not None and cancel.is_set():
                break
            try:
                start = time.perf_counter()
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout_ms / 1000)
                sock.connect((host, 80))
                sock.close()
                samples.append((time.perf_counter() - start) * 1000)
            except OSError:
                pass
            time.sleep(0.05)
    return {
        "host": host,
        "samples": samples,
        "stats": summarize(samples, sent=count),
        "success": bool(samples),
    }


def _http_connection(parsed, timeout):
    if parsed.scheme == "https":
        return http.client.HTTPSConnection(
            parsed.netloc, timeout=timeout, context=ssl.create_default_context())
    return http.client.HTTPConnection(parsed.netloc, timeout=timeout)


def http_latency(url, samples=6, timeout=2.0, cancel=None):
    """用 HTTP 首字节时间（TTFB）测量延迟，连接复用，不受 ICMP 限速影响。

    计时从发出请求到收到响应首字节；建连（TCP/TLS 握手）发生在计时之外。
    返回 {"url", "samples", "stats", "success"}。
    """
    parsed = urllib.parse.urlsplit(url)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
    }
    latencies = []
    sent = max(1, int(samples))
    conn = None
    try:
        for _ in range(sent):
            if cancel is not None and cancel.is_set():
                break
            try:
                if conn is None:
                    conn = _http_connection(parsed, timeout)
                    conn.connect()
                start = time.perf_counter()
                conn.request("GET", path, headers=headers)
                resp = conn.getresponse()
                resp.read(1)
                latencies.append((time.perf_counter() - start) * 1000)
                resp.read()
                if resp.will_close:
                    conn.close()
                    conn = None
            except (OSError, http.client.HTTPException, ValueError):
                if conn is not None:
                    try:
                        conn.close()
                    except OSError:
                        pass
                    conn = None
                time.sleep(0.05)
    finally:
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass
    return {
        "url": url,
        "samples": latencies,
        "stats": summarize(latencies, sent=sent),
        "success": bool(latencies),
    }


def stable_throughput(samples, window=3.0, ramp=0.6, bin_seconds=0.25):
    """从 (timestamp, delta_bytes, streams) 事件计算稳定窗口吞吐。

    按 bin_seconds 聚合后，跳过开头 ramp 秒（TCP 慢启动），
    在剩余区间里找字节数最大的 window 秒窗口。窗口短于 window 时按实际长度折算。
    返回 {"success", "mbps", "bytes", "window", "peak_mbps", "streams", "span"}。
    """
    events = [(float(t), int(b), int(s or 1))
              for t, b, s in (samples or []) if b and b > 0]
    if not events:
        return {"success": False, "mbps": 0.0, "bytes": 0, "window": 0.0,
                "peak_mbps": 0.0, "streams": 0, "span": 0.0}

    t0 = min(t for t, _, _ in events)
    span = max(t for t, _, _ in events) - t0
    bins = {}
    for t, nbytes, streams in events:
        idx = int((t - t0) / bin_seconds)
        slot = bins.setdefault(idx, [0, set()])
        slot[0] += nbytes
        slot[1].add(streams)
    last_idx = max(bins)
    ramp_bins = int(round(max(0.0, ramp) / bin_seconds))
    start_idx = ramp_bins if last_idx >= ramp_bins else 0
    usable = {i: v for i, v in bins.items() if i >= start_idx} or bins

    span_bins = max(1, int(round(window / bin_seconds)))
    max_start = max(usable)
    best_bytes, best_start = 0, min(usable)
    first = min(usable)
    for start in range(first, max_start + 1):
        total = sum(usable.get(i, [0, set()])[0]
                    for i in range(start, start + span_bins))
        if total > best_bytes:
            best_bytes, best_start = total, start
    covered = min(span_bins, max_start - best_start + 1)
    effective = max(covered * bin_seconds, bin_seconds)
    streams = set()
    for i in range(best_start, best_start + covered):
        streams |= usable.get(i, [0, set()])[1]

    peak = 0.0
    for i, (nbytes, _s) in usable.items():
        peak = max(peak, nbytes / bin_seconds * 8 / (1024 * 1024))
    mbps = best_bytes / effective * 8 / (1024 * 1024)
    return {
        "success": True,
        "mbps": round(mbps, 1),
        "bytes": best_bytes,
        "window": round(effective, 2),
        "peak_mbps": round(peak, 1),
        "streams": len(streams),
        "span": round(max(0.0, span), 2),
    }


class ThroughputMeter:
    """线程安全的吞吐采集器：记录 (时间, 字节增量, 连接号) 并给出瞬时/峰值速率。"""

    def __init__(self, recent_window=1.0):
        self._lock = threading.Lock()
        self._events = []
        self._recent = deque()
        self._recent_window = recent_window
        self._total = 0
        self._peak = 0.0
        self._last_rate = 0.0

    def add(self, timestamp, nbytes, stream_id=1):
        nbytes = int(nbytes or 0)
        if nbytes <= 0:
            return 0.0
        with self._lock:
            self._events.append((float(timestamp), nbytes, int(stream_id)))
            self._total += nbytes
            self._recent.append((float(timestamp), nbytes))
            while self._recent and timestamp - self._recent[0][0] > self._recent_window:
                self._recent.popleft()
            if len(self._recent) >= 2:
                covered = max(timestamp - self._recent[0][0], 0.25)
            else:
                covered = self._recent_window
            rate = sum(b for _, b in self._recent) / covered * 8 / (1024 * 1024)
            self._last_rate = rate
            if rate > self._peak:
                self._peak = rate
            return rate

    def recent_mbps(self):
        with self._lock:
            return self._last_rate

    @property
    def peak_mbps(self):
        with self._lock:
            return self._peak

    @property
    def total_bytes(self):
        with self._lock:
            return self._total

    def events(self):
        with self._lock:
            return list(self._events)

    def result(self, window=3.0, ramp=0.6):
        result = stable_throughput(self.events(), window=window, ramp=ramp)
        result["peak_mbps"] = round(max(result["peak_mbps"], self.peak_mbps), 1)
        result["total_bytes"] = self.total_bytes
        return result
