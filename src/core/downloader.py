"""
多线程下载器模块 - 动态分块 + 自适应并发 + 多源加速

设计思路（参考 PCL2 / Ghost Downloader 3 / aria2）：
  1. 先探测资源与下载源：HEAD 失败用 Range 探针；可镜像源会实测吞吐并返回多个可用源。
  2. 分块不是固定等分：监督线程把"剩余量最大"的段对半切开，让新连接接力尾部，
     慢连接不会拖死整单；下载速度还有提升空间时逐步增加并发（4 → 设置上限，默认 8）。
  3. 每条连接独立 Range 请求、seek 写入同一文件的互不重叠区间；取消时主动关闭连接。
  4. 慢连接（6 秒不足 8KB）或卡死（8 秒无进展）会被掐断，剩余区间换源/重连续传。
  5. 断点续传按区间保存（v2），换线程数、换镜像后仍能正确续传。
  6. 只允许 http/https，拒绝内网地址/回环，文件名做清洗，规避 SSRF 与路径注入。

本模块纯标准库实现，不引入额外网络依赖，可在 QThread 中独立运行。
"""

import json
import os
import random
import re
import socket
import threading
import time
# urllib 导入会连带解析 email 等模块（约 20ms），按需在各函数内部导入以免拖慢启动

from .mirror import is_mirrorable, probe_sources   # 国内镜像/多源加速

CHUNK_SIZE = 256 * 1024         # 每次读取 256KB
MIN_SPLIT = 2 * 1024 * 1024     # 初始分段/动态切分阈值
MIN_SEGMENT = 1024 * 1024       # 动态切分后单段最小剩余
MIN_MULTI_SIZE = 4 * 1024 * 1024  # 小于 4MB 不并行
MIRROR_MIN_SIZE = 8 * 1024 * 1024  # 小于 8MB 不做多源吞吐探测
MIRROR_MAX_SOURCES = 3          # 最多同时使用的源（不含原始地址兜底）
DEFAULT_CONNECTIONS = 8         # 默认最大并发连接数
START_CONNECTIONS = 4           # 起始并发
MAX_CONNECTIONS_CAP = 16        # 硬上限
PROBE_TIMEOUT = 6               # HEAD/Range 探测超时
REQUEST_TIMEOUT = 15            # 下载连接读超时
MAX_RETRY = 3                   # 瞬态错误自动重试次数
RETRY_BASE = 0.5                # 退避基数（秒）
USER_AGENT = "Mozilla/5.0 NetHelper/1.0"
IDLE_TIMEOUT = 45               # 全局无任何字节增长的中止时间
LOW_SPEED_WINDOW = 6.0          # 慢连接统计窗口
LOW_SPEED_BYTES = 8 * 1024      # 窗口内不足该字节数视为慢连接
STALL_KILL = 8.0                # 单条连接无任何进展的掐断时间
RAMP_INTERVAL = 2.0             # 每 2 秒评估一次是否提速
RAMP_MIN_GAIN = 0.10            # 提速后速度至少提升 10% 才继续加线程
RAMP_MIN_REMAIN = 4 * 1024 * 1024  # 剩余量不足 4MB 不再加线程
SOURCE_COOLDOWN = 30.0          # 429/503 源的冷却时间
MAX_SEGMENT_FAILS = 3           # 同一段连续失败次数上限


class DownloadError(Exception):
    pass


class _RangeNotSupported(Exception):
    """该源忽略 Range 或返回的分段与请求不一致"""


class _SlowConnection(Exception):
    """单条连接持续低速"""


class _StreamClosed(Exception):
    """连接提前结束，需要从当前偏移重连"""


def is_private_host(host):
    """判断主机是否为内网/回环/保留地址（用于防 SSRF）。

    使用 ipaddress 判定，覆盖 IPv6、IPv4-mapped、0.0.0.0、100.64/10 等
    旧实现漏掉的地址段；非 IP 字面量（域名）只有在 localhost/.local 时拒绝。
    """
    import ipaddress
    host = (host or "").strip().lower().strip("[]")
    if not host:
        return True
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        # 兼容 http://2130706433/ 这类整型 IPv4 写法
        try:
            packed = socket.inet_aton(host)
        except OSError:
            return False
        addr = ipaddress.IPv4Address(packed)
    return not addr.is_global or addr.is_multicast


def validate_url(url):
    """校验下载地址：仅 http/https 且非内网地址，返回错误信息（空表示合法）"""
    import urllib.parse
    if not url or not url.strip():
        return "请先填入下载地址"
    try:
        p = urllib.parse.urlparse(url.strip())
    except Exception:
        return "下载地址格式不正确"
    if p.scheme.lower() not in ("http", "https"):
        return "仅支持 http/https 协议的下载地址"
    if not p.netloc or not p.hostname:
        return "下载地址缺少主机名"
    if is_private_host(p.hostname):
        return "不支持下载局域网/内网地址"
    return ""


_OPENER = None


def _build_opener():
    """构建带重定向校验的 opener：每一跳都必须通过 validate_url。"""
    global _OPENER
    if _OPENER is not None:
        return _OPENER
    import urllib.error
    import urllib.request

    class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            err = validate_url(newurl)
            if err:
                raise urllib.error.HTTPError(
                    newurl, code, f"重定向被拒绝：{err}", headers, fp)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    _OPENER = urllib.request.build_opener(_SafeRedirectHandler)
    return _OPENER


def open_url(req, timeout):
    """urlopen 的安全替代：跟随重定向时逐跳校验，禁止跳到内网。"""
    return _build_opener().open(req, timeout=timeout)


def sanitize_filename(name):
    """清洗文件名，剔除 Windows 非法字符；空则给默认名"""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name or "").strip().strip(".")
    return name or "download.bin"


def guess_filename(url, final_url=""):
    """从 URL 路径中推断文件名"""
    import urllib.parse
    raw = final_url or url
    p = urllib.parse.urlparse(raw)
    name = os.path.basename(urllib.parse.unquote(p.path or ""))
    return sanitize_filename(name)


def _parse_content_range(value):
    """返回 (start, total)；无法解析时返回 (None, 0)。"""
    m = re.match(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", value or "")
    if not m:
        return None, 0
    total = 0 if m.group(3) == "*" else int(m.group(3))
    return int(m.group(1)), total


class _Segment:
    """一段待下载的字节区间；pos 只由对应 worker 推进。"""

    __slots__ = ("start", "end", "pos", "src", "split_at", "fails",
                 "thread", "resp", "last_t", "dead")

    def __init__(self, start, end, src=-1):
        self.start = start
        self.end = end
        self.pos = start
        self.src = src
        self.split_at = None
        self.fails = 0
        self.thread = None
        self.resp = None
        self.last_t = time.monotonic()
        self.dead = False


class Downloader:
    """多连接分段下载器（线程安全，可被 QThread 驱动）"""

    def __init__(self, url, save_dir, max_workers=None, mirror=False):
        self.url = url.strip()
        self.orig_url = self.url
        self.save_dir = save_dir
        try:
            conns = int(max_workers) if max_workers is not None else DEFAULT_CONNECTIONS
        except (TypeError, ValueError):
            conns = DEFAULT_CONNECTIONS
        self.max_workers = max(1, min(MAX_CONNECTIONS_CAP, conns))
        self.max_conn = self.max_workers
        self.mirror = mirror           # 是否启用国内镜像/多源加速
        self.mirror_used = False       # 实际是否走了镜像（供 UI 提示）
        self.mirror_source = None      # 实际选中的镜像地址（供 UI 展示）
        self.filename = "download.bin"
        self.filepath = ""
        self.state_path = ""

        self.total_size = 0          # 总字节
        self.supports_range = False  # 是否支持分段
        self.done_bytes = 0          # 已下载字节（按区间重算）
        self.resumed = False         # 是否为续传
        self.completed = False       # 是否已完成
        self.error = None            # 失败原因
        self.retries = 0             # 自动重试累计次数（供 UI 展示）
        self.probed = False          # 是否已成功探测到资源信息

        self._segs = []              # [_Segment, ...]，只追加
        self._sources = [self.url]   # 可用下载源（原始地址/镜像）
        self._source_bad = [False]   # 永久失效
        self._source_cool = [0.0]    # 429/503 冷却截止时间
        self._source_rr = 0          # 轮询指针
        self._single_url = self.url
        self._single_mode = False
        self._fallback = threading.Event()   # 所有源都不支持 Range 时置位

        self._lock = threading.RLock()
        self._cond_lock = self._lock         # 兼容 ui/workers.py 的错误写入
        self._state_lock = threading.RLock()
        self._cancel = threading.Event()
        self._pause = threading.Event()
        self._pause.set()                    # 默认不暂停
        self._wake = threading.Event()       # 监督线程唤醒
        self._resps = {}                     # idx -> 活动响应（取消时主动关闭）
        self._live = {}                      # idx -> Thread
        self._threads = []
        self._state_timer = 0.0

        self._ramp_base_speed = None
        self._ramp_stopped = False

    # ---------- 探测 ----------
    def probe(self):
        """探测资源信息：total_size / supports_range / filename。失败抛 DownloadError"""
        info = self._head_probe()
        if info is None or not info["supports_range"] or info["length"] <= 0:
            ranged = self._range_probe()
            if ranged is not None:
                if info is None:
                    info = ranged
                else:
                    if ranged["supports_range"]:
                        info["supports_range"] = True
                    if not info["length"]:
                        info["length"] = ranged["length"]
        if info is None:
            raise DownloadError("无法访问下载地址，请检查链接是否有效")
        return self._apply_info(info)

    def _head_probe(self):
        import urllib.request
        try:
            req = urllib.request.Request(
                self.url, method="HEAD",
                headers={"User-Agent": USER_AGENT,
                         "Accept-Encoding": "identity"})
            with open_url(req, PROBE_TIMEOUT) as resp:
                return self._info_from_resp(resp)
        except Exception:
            return None

    def _range_probe(self):
        """HEAD 不支持/失败时，用 Range: bytes=0-0 请求一个字节判断是否支持分段"""
        import urllib.request
        try:
            req = urllib.request.Request(
                self.url,
                headers={"User-Agent": USER_AGENT,
                         "Accept-Encoding": "identity",
                         "Range": "bytes=0-0"})
            with open_url(req, PROBE_TIMEOUT) as resp:
                return self._info_from_resp(resp, ranged=(resp.status == 206))
        except Exception:
            return None

    def _info_from_resp(self, resp, ranged=False):
        import urllib.parse
        length = resp.headers.get("Content-Length")
        accept = (resp.headers.get("Accept-Ranges") or "").lower()
        _, total = _parse_content_range(resp.headers.get("Content-Range"))
        final_url = resp.geturl() or self.url
        # 防 SSRF：跟随重定向后仍须为公共 http/https 且非内网
        fp = urllib.parse.urlparse(final_url)
        if fp.scheme.lower() not in ("http", "https") or not fp.hostname:
            return None
        if is_private_host(fp.hostname):
            raise DownloadError("目标地址指向内网/回环，已被安全拦截")
        length = int(length) if (length or "").isdigit() else 0
        if total:
            length = total
        supports = (accept == "bytes" or ranged or total > 0)
        name = guess_filename(self.url, final_url)
        return {"length": length, "supports_range": supports, "filename": name}

    def _apply_info(self, info):
        """把探测结果落到文件名/路径，返回是否为同名文件续传。"""
        self.total_size = max(0, int(info.get("length") or 0))
        self.supports_range = bool(info.get("supports_range")) and self.total_size > 0
        self.filename = sanitize_filename(
            info.get("filename") or guess_filename(self.url))
        self.filepath = os.path.join(self.save_dir, self.filename)

        appended = False
        if os.path.exists(self.filepath):
            base, ext = os.path.splitext(self.filename)
            i = 2
            while os.path.exists(self.filepath) and os.path.getsize(self.filepath) != self.total_size:
                self.filename = f"{base}({i}){ext}"
                self.filepath = os.path.join(self.save_dir, self.filename)
                i += 1
            appended = os.path.exists(self.filepath)
        return appended

    def _resolve_sources(self):
        """探测原始地址；失败或可镜像时再实测镜像，填充 self._sources。"""
        self._sources = [self.url]
        self._source_bad = [False]
        self._source_cool = [0.0]
        try:
            appended = self.probe()
            probed = True
        except DownloadError:
            appended, probed = False, False

        if probed:
            if (self.mirror and is_mirrorable(self.orig_url)
                    and self.total_size >= MIRROR_MIN_SIZE):
                self._rank_mirrors(self.total_size)
            return appended

        # 原始地址打不开：尝试镜像
        if self.mirror and is_mirrorable(self.orig_url):
            best = self._rank_mirrors(None)
            if best is not None:
                info = {
                    "length": best.total,
                    # 拿不到总大小时无法分段，只能走单流
                    "supports_range": best.supports_range and best.total > 0,
                    "filename": guess_filename(self.orig_url, best.url),
                }
                self._apply_info(info)
                self.probed = True
                return False
        raise DownloadError("无法访问下载地址，请检查链接是否有效")

    def _rank_mirrors(self, require_total):
        """实测镜像吞吐，选出最优源列表；返回最优 Source 或 None。"""
        try:
            ranked = probe_sources(self.orig_url)
        except Exception:
            ranked = []
        usable = [
            s for s in ranked
            if s.supports_range and (require_total is None or s.total == require_total)
        ]
        if not usable:
            usable = [s for s in ranked if s.supports_range]
        if not usable and require_total is None:
            usable = ranked          # 全都不支持 Range 时至少保留一个可流式读取的源
        if not usable:
            return None

        urls = []
        for s in usable[:MIRROR_MAX_SOURCES]:
            if s.url not in urls:
                urls.append(s.url)
        # 原始地址只有实测可用时才保留为兜底，避免把死源轮询给分块
        probed_urls = {s.url for s in ranked}
        if self.orig_url not in urls and self.orig_url in probed_urls:
            urls.append(self.orig_url)
        self._sources = urls
        self._source_bad = [False] * len(urls)
        self._source_cool = [0.0] * len(urls)
        self._source_rr = 0
        mirrors = [u for u in urls if u != self.orig_url]
        self.mirror_used = bool(mirrors)
        self.mirror_source = mirrors[0] if mirrors else None
        return usable[0]

    # ---------- 分段 ----------
    def _initial_count(self):
        total = self.total_size
        if total < MIN_MULTI_SIZE:
            return 1
        n = min(START_CONNECTIONS, self.max_conn, max(1, total // MIN_SPLIT))
        return max(1, n)

    def _init_segments(self):
        total = self.total_size
        if not self.supports_range or total <= 0:
            self._single_mode = True
            end = total - 1 if total > 0 else 0
            self._segs = [_Segment(0, end)]
            return
        n = self._initial_count()
        step = total // n
        segs = []
        for i in range(n):
            s = i * step
            e = (i + 1) * step - 1 if i < n - 1 else total - 1
            segs.append(_Segment(s, e))
        self._segs = segs

    def _recount_locked(self):
        self.done_bytes = sum(
            max(0, min(s.pos, s.end + 1) - s.start) for s in self._segs)

    def _apply_split_locked(self, seg):
        """把 seg 的剩余区间对半切开；尾部由监督线程补线程。"""
        cut = seg.split_at
        seg.split_at = None
        if cut is None or cut <= seg.pos or cut > seg.end:
            return
        if cut - seg.pos < MIN_SEGMENT or seg.end - cut + 1 < MIN_SEGMENT:
            return
        old_end = seg.end
        seg.end = cut - 1
        self._segs.append(_Segment(cut, old_end))
        self._wake.set()

    def _request_split(self, count):
        with self._lock:
            for _ in range(count):
                if len(self._live) >= self.max_conn:
                    return
                best = None
                best_remain = 0
                for seg in self._segs:
                    if seg.dead or seg.pos > seg.end or seg.split_at is not None:
                        continue
                    if seg.thread is None or not seg.thread.is_alive():
                        continue
                    remain = seg.end - seg.pos + 1
                    if remain >= MIN_SPLIT and remain > best_remain:
                        best, best_remain = seg, remain
                if best is None:
                    return
                cut = best.pos + best_remain // 2
                if cut - best.pos < MIN_SEGMENT or best.end - cut + 1 < MIN_SEGMENT:
                    return
                best.split_at = cut
                self._wake.set()

    # ---------- 下载源选择 ----------
    def _pick_source_locked(self):
        n = len(self._sources)
        if n == 0:
            return -1
        now = time.monotonic()
        for _ in range(n):
            idx = self._source_rr % n
            self._source_rr += 1
            if not self._source_bad[idx] and self._source_cool[idx] <= now:
                return idx
        return -1

    def _has_usable_source_locked(self):
        now = time.monotonic()
        return any(
            not self._source_bad[i] and self._source_cool[i] <= now
            for i in range(len(self._sources)))

    def _all_sources_dead_locked(self):
        return not self._sources or all(self._source_bad)

    def _fail_source(self, idx, fatal=False, cooldown=False):
        with self._lock:
            if not (0 <= idx < len(self._source_bad)):
                return
            if fatal:
                self._source_bad[idx] = True
            elif cooldown:
                self._source_cool[idx] = time.monotonic() + SOURCE_COOLDOWN

    # ---------- 启动与监督 ----------
    def start(self, timeout=None):
        """开始下载（阻塞直至完成/取消/出错）。应放入 QThread 调用。

        timeout 为可选的整段下载上限（秒），None 表示不限制总时长；
        另有 IDLE_TIMEOUT 停滞看门狗：长时间无任何字节增长会主动中止并保留续传进度。
        """
        self._cancel.clear()
        self._pause.set()
        self._fallback.clear()
        self._single_mode = False
        self._wake.clear()
        self._ramp_base_speed = None
        self._ramp_stopped = False

        self._resolve_sources()
        if self._cancel.is_set():
            return self
        self.state_path = self.filepath + ".netmeta.json"

        if self.total_size <= 0 and self.supports_range:
            self.completed = True
            return self

        # 预创建目标文件；已存在的同尺寸文件不能截断，否则续传会丢数据
        exists = (os.path.exists(self.filepath)
                  and self.total_size > 0
                  and os.path.getsize(self.filepath) == self.total_size)
        with open(self.filepath, "r+b" if exists else "w+b") as f:
            if self.total_size > 0:
                f.truncate(self.total_size)

        if not (self.total_size > 0 and self._load_resume()):
            self._init_segments()
        else:
            self._recount_locked()

        self._spawn_pending()

        started = time.monotonic()
        last_done = self.done_bytes
        last_progress = started
        last_sample_t = started
        last_sample_done = self.done_bytes
        next_ramp = started + RAMP_INTERVAL

        while True:
            now = time.monotonic()
            with self._lock:
                self._recount_locked()
                done = self.done_bytes
                complete = bool(self._segs) and all(s.pos > s.end for s in self._segs)
            if complete:
                break
            if self._cancel.is_set():
                break

            self._spawn_pending()

            if done != last_done:
                last_done, last_progress = done, now
            if timeout is not None and now - started > timeout:
                self._abort_download("下载超时，进度已保存")
                break
            if now - last_progress > IDLE_TIMEOUT:
                self._abort_download("下载停滞，进度已保存")
                break

            # 每秒采样速度，按 2 秒节拍决定是否继续加线程
            dt = now - last_sample_t
            speed = 0.0
            if dt >= 1.0:
                speed = max(0.0, (done - last_sample_done) / dt)
                last_sample_t, last_sample_done = now, done
            if (now >= next_ramp and not self._single_mode
                    and not self._ramp_stopped):
                next_ramp = now + RAMP_INTERVAL
                self._consider_ramp(speed)

            self._kill_stalled(now)
            self._maybe_save_state()

            with self._lock:
                live = len(self._live)
                pending = any(
                    not s.dead and s.pos <= s.end and i not in self._live
                    for i, s in enumerate(self._segs))
                all_dead = self._all_sources_dead_locked()
            if live == 0 and pending and all_dead and not self._single_mode:
                with self._lock:
                    if not self.error:
                        self.error = "下载源不可用，请稍后重试或关闭镜像加速"
                self._cancel.set()
                break

            self._wake.wait(0.2)
            self._wake.clear()

        self._finish_check()
        # 用户主动取消时立即落盘进度，下次「开始下载」可接着续传
        if self._cancel.is_set() and not self.completed:
            self._close_active()
            for t in list(self._threads):
                if t.is_alive():
                    t.join(0.5)
            self._save_state_quiet()
        elif self.completed:
            self._close_active()
            for t in list(self._threads):
                if t.is_alive():
                    t.join(0.5)
        return self

    def _consider_ramp(self, speed):
        with self._lock:
            live = len(self._live)
            largest = 0
            for seg in self._segs:
                if seg.pos <= seg.end:
                    largest = max(largest, seg.end - seg.pos + 1)
        if live >= self.max_conn or largest < RAMP_MIN_REMAIN:
            self._ramp_stopped = True
            return
        if self._ramp_base_speed is not None:
            if speed < self._ramp_base_speed * (1 + RAMP_MIN_GAIN):
                self._ramp_stopped = True
                return
        self._request_split(min(2, self.max_conn - live))
        self._ramp_base_speed = speed

    def _spawn_pending(self):
        to_start = []
        with self._lock:
            if self._single_mode:
                if self._live:
                    return
                seg = self._segs[0] if self._segs else None
                if seg is None or seg.pos > seg.end or seg.thread is not None:
                    return
                t = threading.Thread(target=self._worker, args=(0,), daemon=True,
                                     name="netdl-single")
                seg.thread = t
                self._live[0] = t
                self._threads.append(t)
                to_start.append(t)
            else:
                for idx, seg in enumerate(self._segs):
                    if len(self._live) >= self.max_conn:
                        break
                    if seg.dead or seg.pos > seg.end or idx in self._live:
                        continue
                    if not self._has_usable_source_locked():
                        break
                    if seg.src is None or seg.src < 0 or self._source_bad[seg.src]:
                        seg.src = self._pick_source_locked()
                    if seg.src < 0:
                        break
                    seg.last_t = time.monotonic()
                    t = threading.Thread(target=self._worker, args=(idx,), daemon=True,
                                         name=f"netdl-{idx}")
                    seg.thread = t
                    self._live[idx] = t
                    self._threads.append(t)
                    to_start.append(t)
        for t in to_start:
            t.start()

    def _kill_stalled(self, now):
        victims = []
        with self._lock:
            for seg in self._segs:
                if seg.pos > seg.end or seg.thread is None:
                    continue
                if now - seg.last_t >= STALL_KILL:
                    victims.append(seg.resp)
                    seg.last_t = now      # 避免同一连接被反复掐
        for resp in victims:
            if resp is None:
                continue
            try:
                resp.close()
            except Exception:
                pass

    # ---------- 工作线程 ----------
    def _worker(self, idx):
        import urllib.error
        seg = self._segs[idx]
        try:
            with open(self.filepath, "r+b") as f:
                if self._single_mode:
                    self._stream_body(f, seg, idx)
                else:
                    self._range_body(f, seg, idx)
        except _RangeNotSupported:
            self._enter_single_mode(seg)
        except (urllib.error.URLError, OSError, socket.timeout,
                ValueError, _SlowConnection):
            with self._lock:
                if not self.error and not self._cancel.is_set():
                    self.error = "下载连接中断"
        finally:
            with self._lock:
                self._live.pop(idx, None)
                seg.thread = None
                seg.resp = None
                self._resps.pop(idx, None)
            self._wake.set()

    def _range_body(self, f, seg, idx):
        import urllib.error
        attempt = 0
        while True:
            if self._cancel.is_set() or self._fallback.is_set():
                return
            self._pause.wait()
            if self._cancel.is_set():
                return
            with self._lock:
                if seg.split_at is not None:
                    self._apply_split_locked(seg)
                if seg.pos > seg.end or seg.dead:
                    return
                if seg.src is None or seg.src < 0 or self._source_bad[seg.src]:
                    seg.src = self._pick_source_locked()
                if seg.src < 0:
                    return
                start, end, src = seg.pos, seg.end, seg.src
                url = self._sources[src]
            try:
                self._download_range(f, seg, idx, url, start, end)
                return
            except _RangeNotSupported:
                self._fail_source(src, fatal=True)
                with self._lock:
                    seg.src = -1
                    seg.fails += 1
                    all_dead = self._all_sources_dead_locked()
                if all_dead:
                    raise
                return
            except _SlowConnection:
                self._fail_source(src, cooldown=True)
                with self._lock:
                    seg.src = -1
                    seg.fails += 1
                return
            except (urllib.error.HTTPError, urllib.error.URLError,
                    OSError, socket.timeout, ValueError, _StreamClosed) as e:
                if self._cancel.is_set() or self._fallback.is_set():
                    return
                code = getattr(e, "code", None) if isinstance(e, urllib.error.HTTPError) else None
                with self._lock:
                    seg.fails += 1
                if code in (401, 403, 404, 410):
                    self._fail_source(src, fatal=True)
                    with self._lock:
                        seg.src = -1
                    return
                if code in (429, 503):
                    self._fail_source(src, cooldown=True)
                    self._ramp_stopped = True
                    with self._lock:
                        seg.src = -1
                    return
                attempt += 1
                if attempt > MAX_RETRY or seg.fails >= MAX_SEGMENT_FAILS:
                    self._fail_source(src, cooldown=True)
                    with self._lock:
                        seg.src = -1
                    return
                with self._lock:
                    self.retries += 1
                delay = RETRY_BASE * (2 ** (attempt - 1)) + 0.3 * random.random()
                deadline = time.monotonic() + delay
                while time.monotonic() < deadline:
                    if self._cancel.wait(0.05):
                        return

    def _download_range(self, f, seg, idx, url, start, end):
        import urllib.error
        import urllib.request
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "identity",
            "Range": f"bytes={start}-{end}",
        })
        resp = open_url(req, REQUEST_TIMEOUT)
        try:
            if resp.status != 206:
                raise _RangeNotSupported()
            cr_start, cr_total = _parse_content_range(
                resp.headers.get("Content-Range"))
            if cr_start != start:
                raise _RangeNotSupported()
            if cr_total and self.total_size and cr_total != self.total_size:
                raise _RangeNotSupported()

            with self._lock:
                seg.resp = resp
                seg.last_t = time.monotonic()
                self._resps[idx] = resp

            pos = start
            window_t = time.monotonic()
            window_bytes = 0
            while True:
                if self._cancel.is_set() or self._fallback.is_set():
                    return
                self._pause.wait()
                if self._cancel.is_set():
                    return
                with self._lock:
                    if seg.split_at is not None:
                        self._apply_split_locked(seg)
                    cur_end = seg.end
                if pos > cur_end:
                    return
                chunk = resp.read(CHUNK_SIZE)
                if not chunk:
                    raise _StreamClosed("连接提前结束")
                n = min(len(chunk), cur_end - pos + 1)
                f.seek(pos)
                f.write(chunk[:n])
                pos += n
                with self._lock:
                    seg.pos = pos
                    seg.last_t = time.monotonic()
                window_bytes += n
                now = time.monotonic()
                if now - window_t >= LOW_SPEED_WINDOW:
                    if window_bytes < LOW_SPEED_BYTES:
                        raise _SlowConnection()
                    window_t, window_bytes = now, 0
                if pos > cur_end:
                    return
        finally:
            with self._lock:
                if seg.resp is resp:
                    seg.resp = None
                self._resps.pop(idx, None)
            try:
                resp.close()
            except Exception:
                pass

    def _enter_single_mode(self, seg):
        """所有源都不支持 Range：停止分段，改为单流从头下载。"""
        with self._lock:
            if self._single_mode:
                return
            src = seg.src
            self._single_url = (
                self._sources[src] if 0 <= src < len(self._sources) else self.orig_url)
            self._single_mode = True
            self._fallback.set()
            end = self.total_size - 1 if self.total_size > 0 else 0
            self._segs = [_Segment(0, end)]
            self._sources = [self._single_url]
            self._source_bad = [False]
            self._source_cool = [0.0]
            self._source_rr = 0
            self.done_bytes = 0
        self._wake.set()

    def _stream_body(self, f, seg, idx):
        import urllib.error
        import urllib.request
        attempt = 0
        while True:
            if self._cancel.is_set():
                return
            with self._lock:
                url = self._single_url
                seg.pos = 0
                seg.last_t = time.monotonic()
            f.seek(0)
            pos = 0
            window_t = time.monotonic()
            window_bytes = 0
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept-Encoding": "identity",
            })
            try:
                resp = open_url(req, REQUEST_TIMEOUT)
                try:
                    with self._lock:
                        seg.resp = resp
                        self._resps[idx] = resp
                    length = resp.headers.get("Content-Length")
                    if (length or "").isdigit() and int(length) > 0:
                        self.total_size = int(length)
                        with self._lock:
                            seg.end = self.total_size - 1
                    while True:
                        if self._cancel.is_set():
                            return
                        self._pause.wait()
                        if self._cancel.is_set():
                            return
                        chunk = resp.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        f.seek(pos)
                        f.write(chunk)
                        pos += len(chunk)
                        with self._lock:
                            seg.pos = pos
                            seg.last_t = time.monotonic()
                        window_bytes += len(chunk)
                        now = time.monotonic()
                        if now - window_t >= LOW_SPEED_WINDOW:
                            if window_bytes < LOW_SPEED_BYTES:
                                raise _SlowConnection()
                            window_t, window_bytes = now, 0
                finally:
                    with self._lock:
                        if seg.resp is resp:
                            seg.resp = None
                        self._resps.pop(idx, None)
                    try:
                        resp.close()
                    except Exception:
                        pass

                if self.total_size <= 0 or pos >= self.total_size:
                    with self._lock:
                        self.total_size = max(self.total_size, pos)
                        seg.end = self.total_size - 1
                        seg.pos = pos
                    return
                raise _StreamClosed("连接提前结束")
            except (urllib.error.URLError, OSError, socket.timeout,
                    ValueError, _StreamClosed, _SlowConnection):
                if self._cancel.is_set():
                    return
                attempt += 1
                if attempt > MAX_RETRY:
                    raise
                with self._lock:
                    self.retries += 1
                delay = RETRY_BASE * (2 ** (attempt - 1)) + 0.3 * random.random()
                deadline = time.monotonic() + delay
                while time.monotonic() < deadline:
                    if self._cancel.wait(0.05):
                        return

    # ---------- 状态 ----------
    def _maybe_save_state(self):
        if self._single_mode:
            return
        now = time.monotonic()
        with self._state_lock:
            if now - self._state_timer < 1.0:
                return
            self._state_timer = now
        self._save_state_quiet()

    def _save_state_quiet(self):
        try:
            self._save_state()
        except Exception:
            pass

    def _save_state(self):
        if not self.state_path or self._single_mode:
            return
        with self._lock:
            segs = [[s.start, s.end, s.pos] for s in self._segs]
        data = {
            "v": 2,
            "url": self.orig_url,
            "file": self.filepath,
            "total": self.total_size,
            "segs": segs,
        }
        with self._state_lock:
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, self.state_path)

    def _load_resume(self):
        """读取 v2 续传状态；不匹配/损坏返回 False。"""
        st = self.state_path
        if not st or not os.path.exists(st):
            return False
        try:
            with open(st, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return False
        if not isinstance(data, dict) or data.get("v") != 2:
            return False
        if data.get("url") != self.orig_url or data.get("file") != self.filepath:
            return False
        if int(data.get("total", -1)) != self.total_size:
            return False
        segs = []
        try:
            for item in data.get("segs", []):
                s, e, p = (int(x) for x in item)
                if s < 0 or e < s or e >= self.total_size:
                    return False
                p = min(max(p, s), e + 1)
                segs.append(_Segment(s, e))
                segs[-1].pos = p
        except (TypeError, ValueError):
            return False
        if not segs:
            return False
        segs.sort(key=lambda x: x.start)
        if segs[0].start != 0 or segs[-1].end != self.total_size - 1:
            return False
        for a, b in zip(segs, segs[1:]):
            if b.start != a.end + 1:
                return False
        self._segs = segs
        self._recount_locked()
        self.resumed = True
        return True

    def _finish_check(self):
        """下载结束后统一判定完成状态，完成则清理续传标记"""
        with self._lock:
            self._recount_locked()
        if self._cancel.is_set():
            return
        if self.total_size > 0:
            self.completed = (
                bool(self._segs)
                and all(s.pos > s.end for s in self._segs)
                and self.done_bytes >= self.total_size)
        else:
            self.completed = self.done_bytes > 0
        if self.completed:
            try:
                if self.state_path and os.path.exists(self.state_path):
                    os.remove(self.state_path)
            except OSError:
                pass

    # ---------- 控制 ----------
    def _abort_download(self, message):
        """看门狗触发：取消下载并记录原因，已写入的进度会落盘供续传。"""
        self._cancel.set()
        self._pause.set()
        with self._lock:
            if not self.error:
                self.error = message
        self._close_active()

    def _close_active(self):
        with self._lock:
            resps = list(self._resps.values())
            self._resps = {}
        for resp in resps:
            if resp is None:
                continue
            try:
                resp.close()
            except Exception:
                pass

    def cancel(self):
        self._cancel.set()
        self._pause.set()
        self._close_active()

    def pause(self):
        self._pause.clear()

    def resume(self):
        self._pause.set()
        self._wake.set()

    def is_paused(self):
        return not self._pause.is_set()

    def is_cancelled(self):
        return self._cancel.is_set()

    @property
    def active_workers(self):
        with self._lock:
            return len(self._live)

    @property
    def active_sources(self):
        with self._lock:
            return len({s.src for s in self._segs
                        if s.src is not None and s.src >= 0 and s.pos <= s.end})

    @property
    def percent(self):
        if self.total_size <= 0:
            return 0.0
        return min(100.0, self.done_bytes / self.total_size * 100)
