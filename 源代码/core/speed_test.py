"""
网速测试模块 - 测试网络延迟、下载与上传速度
面向新手小白，用简单易懂的方式展示网速。

测速思路（v1.8 方法学升级）：
  1. 延迟：优先用 HTTP 首字节时间（连接复用，不受 ICMP 限速影响），
     输出 P50/P95、RFC3550 抖动与丢包率；HTTP 全部失败才回退 ping。
  2. 下载：多流并发（4 路起，按时间自适应补到 8 路），单次请求限量，
     用「跳过慢启动后的最大 3 秒窗口」计算吞吐，而不是总字节 ÷ 最慢流耗时。
  3. 上传：多流 keep-alive POST 固定大小分片，按稳定窗口计算上行带宽。
  4. 稳定性：所有源失败时优雅降级为不可用，不影响其它指标；全程可取消。
"""

import socket
import threading
import time
import concurrent.futures

from .net_quality import (
    ThroughputMeter, http_latency, icmp_latency, parse_ping_times,
)

# 兼容旧导入：parse_ping_times 已统一到 net_quality
__all__ = ["SpeedTest", "parse_ping_times", "TEST_URLS"]

# 下载测速源（任一可达即算成功，兼顾国内外网络）：
#  - speed.cloudflare.com/__down：官方测速端点，海外/直连时最佳
#  - npmmirror：国内阿里 CDN，国内网络快且稳定
#  - 不再使用 .exe 安装包源：版本会下线，链接容易失效
TEST_URLS = [
    "https://speed.cloudflare.com/__down?bytes=20000000",
    "https://speed.cloudflare.com/__down?bytes=10000000",
    "https://cdn.npmmirror.com/binaries/node/v20.11.0/node-v20.11.0-x64.msi",
    "https://registry.npmmirror.com/typescript/-/typescript-5.5.4.tgz",
]
DOWNLOAD_FAIL_HINT = (
    "无法连接到下载测速服务器。请检查：是否开启了代理/VPN、安全软件是否拦截了测速、"
    "或当前网络对境外及下载站点受限（可稍后重试）。"
)

# 上传测速端点（接受任意 POST body 并返回，用于测量上行带宽）
UPLOAD_URLS = [
    "https://speed.cloudflare.com/__up",
]

DL_DURATION = 8.0                 # 下载测速总时长（秒）
DL_STREAMS = 4                    # 起始并发连接数
DL_MAX_STREAMS = 8                # 自适应增加后的上限
DL_GROWTH_STEPS = (3.0, 5.0)      # 到这两个时间点各补 2 路连接
DL_SOURCE_CAP = 25 * 1024 * 1024  # 单次请求最多读取 25MB
DL_WINDOW = 3.0                   # 稳定窗口长度
DL_RAMP = 0.6                     # 跳过开头的 TCP 慢启动

UL_DURATION = 6.0                 # 上传测速总时长（秒）
UL_STREAMS = 4                    # 并行上传连接数
UL_POST_BYTES = 256 * 1024        # 单个 POST 分片大小（keep-alive 复用连接）
UL_TOTAL_CAP = 64 * 1024 * 1024   # 单连接总发送上限，防止无限流量

CHUNK_BYTES = 64 * 1024
LIVE_INTERVAL = 0.25

LATENCY_TARGETS = [
    ("www.baidu.com", "https://www.baidu.com/"),
    ("speed.cloudflare.com", "https://speed.cloudflare.com/__down?bytes=1000"),
]


class SpeedTest:
    """网速测试器 - 测试延迟、下载与上传速度"""

    def __init__(self):
        self.is_running = False
        self._cancel = threading.Event()

    def cancel(self):
        """请求取消当前测速：各阶段会在下一个检查点尽快退出。"""
        self._cancel.set()

    def is_cancelled(self):
        return self._cancel.is_set()

    # ---------------- 延迟测试（HTTP TTFB，ping 兜底） ----------------
    def latency_test(self, cancel=None):
        """测量网络延迟：优先 HTTP 首字节时间，返回 P50/P95/抖动/丢包。"""
        cancel = cancel or self._cancel
        errors = []
        for host, url in LATENCY_TARGETS:
            if cancel.is_set():
                break
            try:
                res = http_latency(url, samples=6, timeout=2.0, cancel=cancel)
            except Exception as e:
                errors.append(f"{host}: {e}")
                continue
            stats = res["stats"]
            if res["success"] and stats.count >= 2:
                return self._latency_result(host, "http", stats)
            errors.append(f"{host}: 无有效响应")

        if not cancel.is_set():
            icmp = self.ping_test("www.baidu.com", count=5, cancel=cancel)
            if icmp["success"]:
                return icmp
        return {
            "host": "", "method": "", "avg_latency": 0, "p50": 0, "p95": 0,
            "jitter_ms": 0, "loss_rate": 100, "min_latency": 0, "max_latency": 0,
            "samples": 0, "success": False,
            "error": "；".join(errors) or "测速已取消",
        }

    @staticmethod
    def _latency_result(host, method, stats):
        return {
            "host": host,
            "method": method,
            "avg_latency": stats.mean,
            "p50": stats.p50,
            "p95": stats.p95,
            "jitter_ms": stats.jitter,
            "loss_rate": stats.loss,
            "min_latency": stats.min,
            "max_latency": stats.max,
            "samples": stats.count,
            "success": True,
        }

    def ping_test(self, host="www.baidu.com", count=5, timeout_ms=2000, cancel=None):
        """ICMP 延迟采样，返回平均/最小/最大/抖动/丢包率（保留旧字段）。"""
        result = icmp_latency(host, count=count, timeout_ms=timeout_ms,
                              cancel=cancel or self._cancel)
        stats = result["stats"]
        if not result["success"]:
            return self._empty_ping_result(host)
        data = self._latency_result(host, "icmp", stats)
        data["samples"] = stats.count
        return data

    @staticmethod
    def _empty_ping_result(host):
        return {
            "host": host, "method": "icmp", "avg_latency": 0, "p50": 0, "p95": 0,
            "jitter_ms": 0, "min_latency": 0, "max_latency": 0,
            "loss_rate": 100, "samples": 0, "success": False,
        }

    def multi_ping_test(self, hosts, count=3):
        """并发测量多个目标的延迟，供诊断模块使用（不阻塞单个慢目标）"""
        results = {}

        def one(host):
            return self.ping_test(host, count=count)

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(hosts)) as ex:
            futs = {ex.submit(one, h): h for h in hosts}
            for f in concurrent.futures.as_completed(futs):
                results[futs[f]] = f.result()
        return results

    # ---------------- 下载测速（多流 + 稳定窗口） ----------------
    def download_speed_test(self, progress_callback=None, live_callback=None,
                            duration=None, cancel=None):
        """多流并发下载，按稳定窗口计算吞吐，实时上报瞬时速度。"""
        cancel = cancel or self._cancel
        if cancel.is_set():
            return {"success": False, "cancelled": True}
        duration = float(duration or DL_DURATION)
        meter = ThroughputMeter()
        start = time.time()
        deadline = start + duration
        started_streams = 0
        growth = list(DL_GROWTH_STEPS)

        with concurrent.futures.ThreadPoolExecutor(
                max_workers=DL_MAX_STREAMS) as executor:
            futures = {}

            def spawn(count):
                nonlocal started_streams
                for sid in range(started_streams, min(count, DL_MAX_STREAMS)):
                    futures[executor.submit(
                        self._download_stream, sid, deadline, meter, cancel)] = sid
                started_streams = min(count, DL_MAX_STREAMS)

            spawn(DL_STREAMS)
            while time.time() < deadline and not cancel.is_set():
                time.sleep(LIVE_INTERVAL)
                live = meter.recent_mbps()
                if live_callback and live > 0:
                    live_callback(live)
                if progress_callback:
                    progress_callback(min(99, int((time.time() - start) / duration * 100)))
                if growth and time.time() - start >= growth[0]:
                    growth.pop(0)
                    spawn(started_streams + 2)
            concurrent.futures.wait(
                futures, timeout=max(1.0, deadline - time.time() + 2.0))

        elapsed = max(time.time() - start, 0.1)
        if meter.total_bytes <= 10240:
            return {"success": False, "error": DOWNLOAD_FAIL_HINT}

        result = meter.result(window=min(DL_WINDOW, max(duration / 2, 1.0)), ramp=DL_RAMP)
        mbps = result["mbps"]
        if mbps <= 0:
            mbps = meter.total_bytes / elapsed * 8 / (1024 * 1024)
        if progress_callback:
            progress_callback(100)
        return {
            "speed_bps": mbps * 1024 * 1024 / 8,
            "speed_kbps": round(mbps * 1024, 1),
            "speed_mbps": round(mbps, 1),
            "peak_mbps": round(max(result["peak_mbps"], meter.peak_mbps), 1),
            "sources": result["streams"] or 1,
            "streams": result["streams"],
            "downloaded_kb": round(meter.total_bytes / 1024, 1),
            "duration_s": round(elapsed, 1),
            "window_s": result["window"],
            "method": "stable-window",
            "success": True,
        }

    def _download_stream(self, stream_id, deadline, meter, cancel):
        """一条下载连接：轮换测速源，直到截止时间或全部源失败。"""
        index = stream_id
        failures = 0
        while not cancel.is_set() and time.time() < deadline:
            url = TEST_URLS[index % len(TEST_URLS)]
            index += 1
            got = self._fetch_stream(url, deadline, meter, stream_id, cancel)
            if got <= 0:
                failures += 1
                if failures >= len(TEST_URLS):
                    break
                time.sleep(0.2)
            else:
                failures = 0
        return

    def _fetch_stream(self, url, deadline, meter, stream_id, cancel):
        """流式读取单个 URL，按块记入 meter。返回本次读取字节数。"""
        import http.client
        import urllib.error
        import urllib.request

        got = 0
        # 单次连接超时不超过剩余时间太多，避免不可达的源拖长整个测速
        timeout = max(1.5, min(4.0, deadline - time.time() + 0.5))
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 NetHelper/1.0",
                "Accept-Encoding": "identity",
            })
            with urllib.request.urlopen(req, timeout=timeout) as response:
                while not cancel.is_set() and time.time() < deadline:
                    chunk = response.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    got += len(chunk)
                    meter.add(time.time(), len(chunk), stream_id)
                    if got >= DL_SOURCE_CAP:
                        break
        except (urllib.error.URLError, OSError, socket.timeout,
                http.client.HTTPException, ValueError):
            pass
        return got

    # ---------------- 上传测速（多流 keep-alive POST） ----------------
    def upload_speed_test(self, progress_callback=None, live_callback=None,
                          duration=None, cancel=None):
        """多流并行 POST 固定大小分片，按稳定窗口计算上行带宽。"""
        cancel = cancel or self._cancel
        if cancel.is_set():
            return {"success": False, "cancelled": True}
        duration = float(duration or UL_DURATION)
        meter = ThroughputMeter()
        start = time.time()
        deadline = start + duration

        with concurrent.futures.ThreadPoolExecutor(
                max_workers=UL_STREAMS) as executor:
            futures = [executor.submit(
                self._upload_stream, sid, deadline, meter, cancel)
                for sid in range(UL_STREAMS)]
            while time.time() < deadline and not cancel.is_set():
                time.sleep(LIVE_INTERVAL)
                live = meter.recent_mbps()
                if live_callback and live > 0:
                    live_callback(live)
                if progress_callback:
                    progress_callback(min(99, int((time.time() - start) / duration * 100)))
            concurrent.futures.wait(
                futures, timeout=max(1.0, deadline - time.time() + 2.0))

        elapsed = max(time.time() - start, 0.1)
        if meter.total_bytes <= 10240:
            return {"success": False, "error": "无法连接到上传测速服务器"}

        result = meter.result(window=min(DL_WINDOW, max(duration / 2, 1.0)), ramp=DL_RAMP)
        mbps = result["mbps"]
        if mbps <= 0:
            mbps = meter.total_bytes / elapsed * 8 / (1024 * 1024)
        if progress_callback:
            progress_callback(100)
        return {
            "speed_bps": mbps * 1024 * 1024 / 8,
            "speed_kbps": round(mbps * 1024, 1),
            "speed_mbps": round(mbps, 1),
            "peak_mbps": round(meter.peak_mbps, 1),
            "connections": result["streams"] or 1,
            "uploaded_kb": round(meter.total_bytes / 1024, 1),
            "duration_s": round(elapsed, 1),
            "window_s": result["window"],
            "method": "stable-window",
            "success": True,
        }

    def _upload_stream(self, stream_id, deadline, meter, cancel):
        """一条上传连接：keep-alive 连续 POST 分片，超时或取消即停。"""
        import http.client
        import urllib.parse

        endpoint = UPLOAD_URLS[stream_id % len(UPLOAD_URLS)]
        parsed = urllib.parse.urlparse(endpoint)
        payload = bytes(UL_POST_BYTES)
        path = parsed.path or "/__up"
        headers = {
            "Content-Type": "application/octet-stream",
            "User-Agent": "Mozilla/5.0 NetHelper/1.0",
        }
        sent_total = 0
        conn = None
        try:
            conn = http.client.HTTPSConnection(parsed.netloc, timeout=8)
            while (not cancel.is_set() and time.time() < deadline
                   and sent_total < UL_TOTAL_CAP):
                conn.request("POST", path, body=payload, headers=headers)
                resp = conn.getresponse()
                resp.read()
                if resp.status >= 400:
                    break
                sent_total += len(payload)
                meter.add(time.time(), len(payload), stream_id)
                if resp.will_close:
                    conn.close()
                    conn = http.client.HTTPSConnection(parsed.netloc, timeout=8)
        except (OSError, http.client.HTTPException, socket.timeout):
            pass
        finally:
            if conn is not None:
                try:
                    conn.close()
                except OSError:
                    pass
        return sent_total

    # ---------------- 完整测速 ----------------
    def run_full_test(self, progress_callback=None, status_callback=None,
                      live_callback=None, uplive_callback=None,
                      duration=None):
        """完整测速：延迟 + 上传 + 下载（支持实时速度回调与中途取消）"""
        self._cancel.clear()
        self.is_running = True
        results = {}
        try:
            if status_callback:
                status_callback("正在测试网络延迟...")
            results["ping"] = self.latency_test()
            results["latency_stats"] = dict(results["ping"])
            if progress_callback:
                progress_callback(10)

            if self._cancel.is_set():
                results["cancelled"] = True
                return results

            if status_callback:
                status_callback("正在并发测速（上传）...")

            def up_progress(p):
                if progress_callback:
                    progress_callback(10 + int(p * 0.15))

            results["upload"] = self.upload_speed_test(up_progress, uplive_callback)

            if progress_callback:
                progress_callback(25)

            if self._cancel.is_set():
                results["cancelled"] = True
                return results

            if status_callback:
                status_callback("正在并发下载测速（多流）...")

            def speed_progress(p):
                if progress_callback:
                    progress_callback(25 + int(p * 0.75))

            results["download"] = self.download_speed_test(
                speed_progress, live_callback,
                duration=duration and max(3.0, float(duration) * 0.6))

            if progress_callback:
                progress_callback(100)
            if status_callback:
                status_callback("测速完成！")
            return results
        finally:
            self.is_running = False

    # ---------------- 评级 ----------------
    def get_speed_level(self, speed_mbps):
        """根据网速给出评级（新手友好的描述）"""
        if speed_mbps >= 100:
            return "非常快", "ok", "您的网速非常快，可以流畅观看4K视频和玩大型游戏"
        elif speed_mbps >= 50:
            return "很快", "ok", "您的网速很快，可以流畅观看高清视频和玩网络游戏"
        elif speed_mbps >= 20:
            return "良好", "ok", "您的网速良好，可以流畅观看视频和浏览网页"
        elif speed_mbps >= 10:
            return "一般", "warning", "您的网速一般，浏览网页没问题，看高清视频可能会卡顿"
        elif speed_mbps >= 4:
            return "较慢", "warning", "您的网速较慢，建议关闭其他占用网速的程序"
        else:
            return "很慢", "error", "您的网速很慢，可能会影响正常使用，请检查网络"

    def get_latency_level(self, latency_ms):
        """根据延迟给出评级"""
        if latency_ms <= 30:
            return "极速", "ok", "网络延迟极低，玩游戏体验极佳"
        elif latency_ms <= 60:
            return "良好", "ok", "网络延迟良好，日常使用和游戏都没问题"
        elif latency_ms <= 100:
            return "一般", "warning", "网络延迟一般，浏览网页没问题，玩游戏可能有轻微卡顿"
        elif latency_ms <= 200:
            return "较高", "warning", "网络延迟较高，可能会影响游戏体验"
        else:
            return "很高", "error", "网络延迟很高，会严重影响上网体验"
