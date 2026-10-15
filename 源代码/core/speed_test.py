"""
网速测试模块 - 测试网络延迟、下载与上传速度
面向新手小白，用简单易懂的方式展示网速。

测速思路（v1.5 集成开源方案优化）：
  1. 下载：并发多源聚合，接近真实带宽上限；引入预热期(grace time)跳过 TCP 慢启动，
     避免低链接开局拉低均值。
  2. 上传：多并发 POST 固定大小 payload 到公开上传端点(Cloudflare Speed)，流式发送并计时。
  3. 延迟：逐次采样 RTT，计算出平均/最小/最大/抖动(Jitter)与丢包率，
     不再是单次的"平均延迟"。
  4. 稳定性：所有源失败时优雅降级为不可用，不影响其它指标。
"""

import time
import socket
import threading
import http.client
import urllib.parse
import urllib.request
import urllib.error
import concurrent.futures


# 下载测速源（混合方案，任一可达即算成功，兼顾国内外网络）：
#  - speed.cloudflare.com/__down：官方测速端点，海外/直连时最佳
#  - npmmirror / dldir1.qq.com：国内阿里、腾讯 CDN，国内网络极快且稳定
#  - 避免使用已被 GFW 阻断的 jsdelivr 等境外静态源
TEST_URLS = [
    "https://speed.cloudflare.com/__down?bytes=16000000",
    "https://speed.cloudflare.com/__down?bytes=16000000",
    "https://cdn.npmmirror.com/binaries/node/v20.11.0/node-v20.11.0-x64.msi",
    "https://dldir1.qq.com/weixin/Windows/WeChatSetup_x86.exe",
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
UPLOAD_STREAMS = 3          # 并行上传连接数
UPLOAD_PAYLOAD = 8 * 1024 * 1024   # 每连接发送 8MB
UPLOAD_MAX_SECONDS = 12     # 单个连接最多测 12 秒（慢链路兜底，不无限拖时）

MAX_BYTES_PER_SOURCE = 4 * 1024 * 1024   # 每个下载源最多下载 4MB
CHUNK_BYTES = 64 * 1024                  # 64KB 分块
GRACE_SECONDS = 0.6                       # 下载预热期：跳过 TCP 慢启动
GRACE_SKIP_BYTES = 256 * 1024             # 预热期至少流回的数据量（避免把短连接当有效）
LIVE_INTERVAL = 0.25                     # 实时速度上报间隔（秒）


class SpeedTest:
    """网速测试器 - 测试延迟、下载与上传速度"""

    def __init__(self):
        self.is_running = False

    # ---------------- 延迟测试（含 Jitter / 丢包） ----------------
    def ping_test(self, host="www.baidu.com", count=5, timeout_ms=2000):
        """逐次采样 RTT，返回平均/最小/最大/抖动/丢包率。
        相比一次 ping 拿平均：能算出抖动(Jitter)与更真实的延迟分布。
        """
        import subprocess
        import re
        import platform

        is_windows = platform.system() == "Windows"
        samples = []
        sent = 0

        for _ in range(count):
            sent += 1
            try:
                if is_windows:
                    result = subprocess.run(
                        ["ping", "-n", "1", "-w", str(timeout_ms), host],
                        capture_output=True, text=True, encoding="gbk", errors="replace",
                        timeout=timeout_ms // 1000 + 2,
                    )
                    out = result.stdout or ""
                    m = re.search(r"时间\s*[=＝]\s*([\d.]+)\s*ms", out)
                    if not m:
                        m = re.search(r"time\s*[=＝]\s*([\d.]+)\s*ms", out, re.IGNORECASE)
                    if m:
                        samples.append(float(m.group(1)))
                else:
                    start = time.time()
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(timeout_ms / 1000)
                    s.connect((host, 80))
                    s.close()
                    samples.append((time.time() - start) * 1000)
            except Exception:
                pass
            time.sleep(0.05)

        if not samples:
            return {
                "host": host, "avg_latency": 0, "jitter_ms": 0,
                "min_latency": 0, "max_latency": 0,
                "loss_rate": 100, "samples": 0, "success": False,
            }

        avg = sum(samples) / len(samples)
        jitter = sum(abs(b - a) for a, b in zip(samples, samples[1:])) / max(len(samples) - 1, 1)
        loss_rate = round((sent - len(samples)) / sent * 100, 1)
        return {
            "host": host,
            "avg_latency": round(avg, 1),
            "jitter_ms": round(jitter, 1),
            "min_latency": round(min(samples), 1),
            "max_latency": round(max(samples), 1),
            "loss_rate": loss_rate,
            "samples": len(samples),
            "success": True,
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

    # ---------------- 下载测速（多源 + 预热 + 实时） ----------------
    def _download_one(self, url, report):
        """单源下载：预热后累计字节，按节流周期上报实时速度"""
        downloaded = 0      # 预热后计入的字节
        raw = 0             # 收到的全部字节（含预热）
        cold_start = time.time()
        start = None
        last_report = 0.0
        warmed = False
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 NetHelper/1.0",
                "Accept-Encoding": "identity",
            })
            with urllib.request.urlopen(req, timeout=12) as response:
                while True:
                    chunk = response.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    now = time.time()
                    raw += len(chunk)
                    if not warmed:
                        # 预热期不计速，等 TCP 窗口建立后再开始计时
                        if now - cold_start >= GRACE_SECONDS and raw >= GRACE_SKIP_BYTES:
                            start = now
                            downloaded = 0
                            last_report = now
                            warmed = True
                        else:
                            continue
                    downloaded += len(chunk)
                    if now - last_report >= LIVE_INTERVAL:
                        last_report = now
                        elapsed = now - start
                        if elapsed > 0:
                            mbps = (downloaded / elapsed * 8) / (1024 * 1024)
                            report(mbps)
                    if downloaded >= MAX_BYTES_PER_SOURCE:
                        break
        except (urllib.error.URLError, OSError, socket.timeout, http.client.HTTPException):
            pass

        if not warmed:
            # 预热未完成：若已收到足够数据，按起始时间兜底计入，避免浪费有效测量
            if raw < GRACE_SKIP_BYTES:
                return None
        else:
            raw = downloaded
        elapsed = time.time() - (start if warmed else cold_start)
        if elapsed <= 0 or raw <= 0:
            return None
        mbps = (raw / elapsed * 8) / (1024 * 1024)
        report(mbps)
        return (raw, elapsed, mbps)

    def download_speed_test(self, progress_callback=None, live_callback=None):
        """并发多源下载：聚合带宽接近真实上限，实时上报瞬时速度"""
        lock = threading.Lock()
        totals = {"downloaded": 0, "time": 0.0, "count": 0}
        best_live = {"mbps": 0.0}
        start_main = time.time()

        def report(mbps):
            with lock:
                if mbps > best_live["mbps"]:
                    best_live["mbps"] = mbps
            if live_callback:
                live_callback(mbps)

        def _worker(url):
            return self._download_one(url, report)

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(TEST_URLS)) as executor:
            futures = {executor.submit(_worker, url): url for url in TEST_URLS}
            resolved = 0
            total = len(futures)
            for future in concurrent.futures.as_completed(futures):
                resolved += 1
                if progress_callback:
                    progress_callback(int(resolved / total * 100))
                result = future.result()
                if result:
                    with lock:
                        totals["downloaded"] += result[0]
                        totals["time"] = max(totals["time"], result[1])
                        totals["count"] += 1

        elapsed = time.time() - start_main
        if totals["count"] > 0 and totals["downloaded"] > 10240:
            window = max(totals["time"], 0.3)
            speed_bps = totals["downloaded"] / window
            speed_mbps = speed_bps * 8 / (1024 * 1024)
            return {
                "speed_bps": speed_bps,
                "speed_kbps": round(speed_bps / 1024, 1),
                "speed_mbps": round(speed_mbps, 1),
                "peak_mbps": round(best_live["mbps"], 1),
                "sources": totals["count"],
                "downloaded_kb": round(totals["downloaded"] / 1024, 1),
                "duration_s": round(elapsed, 1),
                "success": True
            }
        return {"success": False, "error": DOWNLOAD_FAIL_HINT}

    # ---------------- 上传测速（多并发 POST） ----------------
    def _upload_one(self, endpoint, payload, report):
        """单连接上传：流式发送固定大小 body，计时并累计字节"""
        conn = None
        try:
            parsed = urllib.parse.urlparse(endpoint)
            conn = http.client.HTTPSConnection(parsed.netloc, timeout=15)
            conn.putrequest("POST", parsed.path or "/__up")
            conn.putheader("Content-Length", str(payload))
            conn.putheader("Content-Type", "application/octet-stream")
            conn.putheader("User-Agent", "Mozilla/5.0 NetHelper/1.0")
            conn.endheaders()

            start = time.time()
            sent = 0
            last_report = 0.0
            last_sent = 0
            chunk = bytes(CHUNK_BYTES)
            while sent < payload:
                if time.time() - start >= UPLOAD_MAX_SECONDS:
                    break
                n = min(CHUNK_BYTES, payload - sent)
                conn.send(chunk[:n])
                sent += n
                now = time.time()
                if now - last_report >= LIVE_INTERVAL:
                    dt = now - last_report
                    # 用滑动窗口增量算瞬时速率，并跳过连接建立后第 0.35s 内的 TCP 尖峰，
                    # 避免“send 无网络背压、时间极短”导致的峰值虚高（如误报 500Mbps）。
                    if dt > 0 and (now - start) >= 0.35:
                        report((((sent - last_sent) / dt) * 8) / (1024 * 1024))
                    last_report = now
                    last_sent = sent

            resp = conn.getresponse()
            resp.read()
            elapsed = time.time() - start
            if elapsed <= 0 or sent <= 0:
                return None
            mbps = (sent / elapsed * 8) / (1024 * 1024)
            report(mbps)
            return (sent, elapsed, mbps)
        except (OSError, http.client.HTTPException, socket.timeout):
            return None
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def upload_speed_test(self, progress_callback=None, live_callback=None):
        """多并发上传：聚合所有连接的上行带宽，实时上报"""
        lock = threading.Lock()
        totals = {"sent": 0, "time": 0.0, "count": 0}
        best_live = {"mbps": 0.0}
        start_main = time.time()

        def report(mbps):
            with lock:
                if mbps > best_live["mbps"]:
                    best_live["mbps"] = mbps
            if live_callback:
                live_callback(mbps)

        with concurrent.futures.ThreadPoolExecutor(max_workers=UPLOAD_STREAMS) as executor:
            futures = [executor.submit(
                self._upload_one, UPLOAD_URLS[i % len(UPLOAD_URLS)], UPLOAD_PAYLOAD, report
            ) for i in range(UPLOAD_STREAMS)]
            resolved = 0
            total = len(futures)
            for future in concurrent.futures.as_completed(futures):
                resolved += 1
                if progress_callback:
                    progress_callback(int(resolved / total * 100))
                result = future.result()
                if result:
                    with lock:
                        totals["sent"] += result[0]
                        totals["time"] = max(totals["time"], result[1])
                        totals["count"] += 1

        elapsed = time.time() - start_main
        if totals["count"] > 0 and totals["sent"] > 10240:
            window = max(totals["time"], 0.3)
            speed_bps = totals["sent"] / window
            speed_mbps = speed_bps * 8 / (1024 * 1024)
            return {
                "speed_bps": speed_bps,
                "speed_kbps": round(speed_bps / 1024, 1),
                "speed_mbps": round(speed_mbps, 1),
                "peak_mbps": round(best_live["mbps"], 1),
                "connections": totals["count"],
                "uploaded_kb": round(totals["sent"] / 1024, 1),
                "duration_s": round(elapsed, 1),
                "success": True
            }
        return {"success": False, "error": "无法连接到上传测速服务器"}

    # ---------------- 完整测速 ----------------
    def run_full_test(self, progress_callback=None, status_callback=None,
                      live_callback=None, uplive_callback=None):
        """完整测速：延迟 + 上传 + 下载（支持实时速度回调）"""
        self.is_running = True
        results = {}

        if status_callback:
            status_callback("正在测试网络延迟...")
        results["ping"] = self.ping_test()
        if progress_callback:
            progress_callback(10)

        if status_callback:
            status_callback("正在并发测速（上传）...")

        def up_progress(p):
            if progress_callback:
                progress_callback(10 + int(p * 0.2))

        results["upload"] = self.upload_speed_test(up_progress, uplive_callback)

        if progress_callback:
            progress_callback(35)

        if status_callback:
            status_callback("正在并发下载测速（多源）...")

        def speed_progress(p):
            if progress_callback:
                progress_callback(35 + int(p * 0.6))

        results["download"] = self.download_speed_test(speed_progress, live_callback)

        if progress_callback:
            progress_callback(100)
        if status_callback:
            status_callback("测速完成！")

        self.is_running = False
        return results

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

    def get_jitter_level(self, jitter_ms):
        """根据抖动给出评级"""
        if jitter_ms <= 5:
            return "稳定", "ok"
        elif jitter_ms <= 15:
            return "正常", "ok"
        elif jitter_ms <= 30:
            return "有抖动", "warning"
        else:
            return "抖动明显", "error"