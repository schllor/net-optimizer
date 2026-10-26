"""
多线程下载器模块 - 基于 HTTP Range 分段并发下载
面向小白用户，实现网页/文件的加速下载。

设计思路（参考 aria2 / bdownload / IDM 式分段下载）：
  1. 先 HEAD 探测：获取 Content-Length 与 Accept-Ranges，不支持 Range 则退化单线程整块下载。
  2. 支持 Range 时按字节区间分段，每段一个线程并发拉取，seek+write 写入同一文件。
  3. 通过 threading.Event 实现安全的取消/暂停，不依赖反射式中断。
  4. 断点续传：每个分段记录已完成字节并落盘到状态 json，重启/重新开始时自动续传。
  5. 只允许 http/https，拒绝内网地址/回环，文件名做清洗，规避 SSRF 与路径注入。

本模块纯标准库实现，不引入额外网络依赖，可在 QThread 中独立运行。
"""

import os
import re
import json
import time
import socket
import random
import threading
import urllib.parse
import urllib.request
import urllib.error

from .mirror import is_mirrorable, pick_fastest_url   # 国内镜像加速（顶层静态导入，便于打包分析）

CHUNK_SIZE = 256 * 1024         # 每次读取 256KB（增大缓冲减少系统调用，降低 CPU 占用）
MIN_SPLIT = 4 * 1024 * 1024     # 小于 4MB 视为小文件、顺序单段下载（借鉴 PCL-CE 的 SmallFileThreshold，省去分片/探测开销）
MAX_WORKERS = 3                 # 同主机并发上限（签名直链 CDN 对高并发 Range 易限流，3 路更稳更快）
REQUEST_TIMEOUT = 20            # 单次请求超时（秒）；urllib 不支持 (连接,读取) 双值，用标量+自动重试兜底断连
MAX_RETRY = 3                   # 瞬态网络错误自动重试次数
RETRY_BASE = 0.5                # 退避基数（秒），指数退避 0.5/1/2
USER_AGENT = "Mozilla/5.0 NetHelper/1.0"

ST = "start"     # 分段状态：未完成
DONE = "done"    # 分段状态：已完成


class DownloadError(Exception):
    pass


def is_private_host(host):
    """判断主机是否为内网/回环地址（用于防 SSRF）"""
    host = (host or "").lower().strip("[]")
    if not host or host in ("localhost",):
        return True
    # 字面量 IP 判断
    parts = host.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        nums = [int(p) for p in parts]
        return (nums[0] == 10
                or nums[0] == 127
                or (nums[0] == 192 and nums[1] == 168)
                or (nums[0] == 172 and 16 <= nums[1] <= 31)
                or (nums[0] == 169 and nums[1] == 254))
    return False


def validate_url(url):
    """校验下载地址：仅 http/https 且非内网地址，返回错误信息（空表示合法）"""
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


def sanitize_filename(name):
    """清洗文件名，剔除 Windows 非法字符；空则给默认名"""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name or "").strip().strip(".")
    return name or "download.bin"


def guess_filename(url, final_url=""):
    """从 URL 路径中推断文件名"""
    raw = final_url or url
    p = urllib.parse.urlparse(raw)
    name = os.path.basename(urllib.parse.unquote(p.path or ""))
    return sanitize_filename(name)


class Downloader:
    """多线程分段下载器（线程安全，可被 QThread 驱动）"""

    def __init__(self, url, save_dir, max_workers=None, mirror=False):
        self.url = url.strip()
        self.save_dir = save_dir
        self.max_workers = max_workers or MAX_WORKERS
        self.mirror = mirror           # 是否启用国内镜像加速（针对国外托管源）
        self.mirror_used = False       # 实际是否走了镜像（供 UI 提示）
        self.mirror_source = None      # 实际选中的镜像地址（供 UI 展示）
        self.filename = "download.bin"
        self.filepath = ""
        self.state_path = ""

        self.total_size = 0          # 总字节
        self.supports_range = False  # 是否支持分段
        self.done_bytes = 0          # 已下载字节（含断点续传的初始值）
        self.resumed = False         # 是否为续传
        self.completed = False       # 是否已完成
        self.error = None            # 失败原因
        self.retries = 0             # 自动重试累计次数（供 UI 展示）
        self.probed = False          # 是否已成功探测到资源信息（用于区分"无法访问"与"中断续传"）

        self._chunks = []            # [(start, end), ...]
        self._chunk_pos = {}         # {index: 当前已写到的 offset}
        self._cond_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._cancel = threading.Event()
        self._pause = threading.Event()
        self._pause.set()            # 默认不暂停
        self._state_timer = 0.0      # 上次状态落盘时间
        self._threads = []
        self._fallback = False       # 服务器实际不支持分段时置位

    # ---------- 探测 ----------
    def probe(self):
        """探测资源信息：total_size / supports_range / filename。失败抛 DownloadError"""
        # 先 HEAD
        info = self._head_probe()
        if info is None:
            info = self._range_probe()   # HEAD 失败则用 Range: bytes=0-0 探针
            if info is None:
                # 两者都失败，退化：尝试确认至少可访问（GET 一次读一块）
                raise DownloadError("无法访问下载地址，请检查链接是否有效")

        self.total_size = info["length"]
        self.supports_range = info["supports_range"] and self.total_size > 0
        self.probed = True
        self.filename = sanitize_filename(info.get("filename") or guess_filename(self.url))
        self.filepath = os.path.join(self.save_dir, self.filename)

        appended = False
        if os.path.exists(self.filepath):
            # 同名文件已存在：若大小与目标一致则当作续传目标，否则重命名避免覆盖（小白友好）
            base, ext = os.path.splitext(self.filename)
            i = 2
            while os.path.exists(self.filepath) and os.path.getsize(self.filepath) != self.total_size:
                self.filename = f"{base}({i}){ext}"
                self.filepath = os.path.join(self.save_dir, self.filename)
                i += 1
            appended = os.path.exists(self.filepath)
        return appended

    def _head_probe(self):
        try:
            req = urllib.request.Request(self.url, method="HEAD",
                                         headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return self._info_from_resp(resp)
        except Exception:
            return None

    def _range_probe(self):
        """HEAD 不支持/失败时，用 Range: bytes=0-0 请求一个字节判断是否支持分段"""
        try:
            req = urllib.request.Request(self.url,
                                         headers={"User-Agent": USER_AGENT,
                                                  "Range": "bytes=0-0"})
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return self._info_from_resp(resp, ranged=(resp.status == 206))
        except Exception:
            return None

    def _info_from_resp(self, resp, ranged=False):
        length = resp.headers.get("Content-Length")
        accept = (resp.headers.get("Accept-Ranges") or "").lower()
        final_url = resp.geturl() or self.url
        # 防 SSRF：跟随重定向后仍须为公共 http/https 且非内网
        fp = urllib.parse.urlparse(final_url)
        if fp.scheme.lower() not in ("http", "https") or not fp.hostname:
            return None
        if is_private_host(fp.hostname):
            raise DownloadError("目标地址指向内网/回环，已被安全拦截")
        length = int(length) if (length or "").isdigit() else 0
        supports = (accept == "bytes" or ranged)
        name = guess_filename(self.url, final_url)
        return {"length": length, "supports_range": supports, "filename": name}

    # ---------- 分块与启动 ----------
    def _build_chunks(self):
        if not self.supports_range:
            self._chunks = [(0, self.total_size - 1)] if self.total_size > 0 else [(0, 0)]
            self._chunk_pos = {0: 0}
            return
        n = min(self.max_workers, max(1, self.total_size // MIN_SPLIT))
        if n <= 1:
            self._chunks = [(0, self.total_size - 1)]
        else:
            step = self.total_size // n
            self._chunks = []
            for i in range(n):
                s = i * step
                e = (i + 1) * step - 1 if i < n - 1 else self.total_size - 1
                self._chunks.append((s, e))
        self._chunk_pos = {i: s for i, (s, e) in enumerate(self._chunks)}

    def _load_resume(self):
        """尝试从状态 json 恢复续传，返回分段起点 dict"""
        st = self.state_path
        if not st or not os.path.exists(st):
            return {}
        try:
            with open(st, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return {}
        if data.get("url") != self.url or data.get("file") != self.filepath:
            return {}
        if "chunks" not in data or "total" not in data:
            return {}
        if data.get("total") != self.total_size:
            return {}
        try:
            filled = {int(k): int(v) for k, v in data["chunks"].items()}
        except Exception:
            return {}
        # 仅保留有效分段内的偏移
        result = {}
        for i, (s, e) in enumerate(self._chunks):
            pos = filled.get(i, s)
            result[i] = min(max(pos, s), e + 1)
        return result

    def start(self):
        """开始下载（阻塞直至完成/取消/出错）。应放入 QThread 调用。"""
        self._cancel.clear()
        self._pause.set()
        self._fallback = False
        # 国内镜像加速：仅对国外托管源、且开启时，选最优可用镜像作为实际下载地址
        if self.mirror:
            try:
                if is_mirrorable(self.url):
                    chosen = pick_fastest_url(self.url)
                    if chosen and chosen != self.url:
                        self.url = chosen
                        self.mirror_used = True
                        self.mirror_source = chosen
            except Exception:
                pass   # 镜像加速失败则退回原始地址直连
        self.probe()

        if not self.supports_range and self.total_size <= 0:
            self.completed = True
            return

        self._build_chunks()

        # 预创建目标文件
        with open(self.filepath, "w+b") as f:
            if self.total_size:
                f.truncate(self.total_size)

        # 断点续传
        self.state_path = self.filepath + ".netmeta.json"
        resume_pos = self._load_resume() if os.path.exists(self.state_path) else {}
        if resume_pos:
            self.resumed = True
            self._chunk_pos = resume_pos
        # done_bytes 只统计"实际写入的字节"= 各段已写偏移 - 各段起始偏移
        with self._cond_lock:
            self.done_bytes = sum(
                self._chunk_pos[i] - s for i, (s, e) in enumerate(self._chunks))

        self._threads = []
        for i, (s, e) in enumerate(self._chunks):
            t = threading.Thread(target=self._worker, args=(i, s, e), daemon=True)
            self._threads.append(t)
            t.start()

        for t in self._threads:
            t.join()

        self._finish_check()
        # 用户主动取消时立即落盘进度，下次「开始下载」可接着续传
        if self._cancel.is_set() and not self.completed:
            self._save_state_quiet()
        return self

    def _worker(self, idx, start, end):
        pos = self._chunk_pos[idx]
        try:
            with open(self.filepath, "r+b") as f:
                while pos <= end:
                    self._pause.wait()   # 暂停时阻塞
                    if self._cancel.is_set():
                        return
                    retry = 0
                    # 连接+读取该分段；遇瞬态网络错误按指数退避自动重试，避免单次断连把速度打到 0
                    while True:
                        self._pause.wait()
                        if self._cancel.is_set():
                            return
                        try:
                            headers = {"User-Agent": USER_AGENT}
                            if self.supports_range:
                                headers["Range"] = f"bytes={pos}-{end}"
                            req = urllib.request.Request(self.url, headers=headers)
                            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                                if self.supports_range and resp.status != 206:
                                    # 服务器实际忽略 Range：退化为单流整块，仅由 idx==0 完成
                                    with self._cond_lock:
                                        if not self._fallback:
                                            self._fallback = True
                                    if idx == 0:
                                        self._stream_whole(f, resp)
                                    return
                                while True:
                                    chunk = resp.read(CHUNK_SIZE)
                                    if not chunk:
                                        break
                                    self._pause.wait()
                                    if self._cancel.is_set():
                                        return
                                    f.seek(pos)
                                    f.write(chunk)
                                    pos += len(chunk)
                                    with self._cond_lock:
                                        self.done_bytes += len(chunk)
                                    self._chunk_pos[idx] = pos
                                    self._maybe_save_state()
                            break   # 本分段下载完成，成功退出重试循环
                        except (urllib.error.HTTPError, urllib.error.URLError, OSError, socket.timeout, ValueError) as _e:
                            retry += 1
                            code = getattr(_e, "code", None) if isinstance(_e, urllib.error.HTTPError) else None
                            # 错误分类（借鉴 PCL-CE 容错思路）：403/404 等确定性失败无需重试；
                            # 5xx 只短重试一次；其余瞬断（超时/连接重置）走指数退避重试
                            fatal = code is not None and code in (401, 403, 404, 410)
                            limit = 1 if (code is not None and 500 <= code <= 599) else MAX_RETRY
                            if fatal or retry > limit:
                                raise
                            with self._cond_lock:
                                self.retries += 1
                            # 指数退避加随机抖动，避免多个分段同时重试打爆服务器
                            time.sleep(RETRY_BASE * (2 ** (retry - 1)) + 0.3 * random.random())
        except (urllib.error.URLError, OSError, socket.timeout, ValueError):
            with self._cond_lock:
                if not self.error:
                    self.error = "下载连接中断"

    def _stream_whole(self, f, resp):
        """单流下载整块内容写入文件（用于服务器不支持 Range 的场景）"""
        pos = 0
        f.seek(0)
        try:
            while True:
                self._pause.wait()
                if self._cancel.is_set():
                    return
                chunk = resp.read(CHUNK_SIZE)
                if not chunk:
                    break
                f.seek(pos)
                f.write(chunk)
                pos += len(chunk)
                with self._cond_lock:
                    self.done_bytes += len(chunk)
        except (urllib.error.URLError, OSError, socket.timeout):
            with self._cond_lock:
                if not self.error:
                    self.error = "下载连接中断，可点击继续续传"

    def _maybe_save_state(self):
        """多线程安全地限频保存进度（每段每秒最多触发一次落盘）。"""
        now = time.time()
        with self._state_lock:
            if now - self._state_timer < 1.0:
                return
            self._state_timer = now
            try:
                self._save_state()
            except Exception:
                pass

    def _save_state_quiet(self):
        try:
            self._save_state()
        except Exception:
            pass

    def _save_state(self):
        if not self.state_path:
            return
        data = {
            "url": self.url,
            "file": self.filepath,
            "total": self.total_size,
            "chunks": {str(k): v for k, v in self._chunk_pos.items()},
        }
        with self._state_lock:
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, self.state_path)

    def _finish_check(self):
        """下载结束后统一判定完成状态，完成则清理续传标记"""
        if self._cancel.is_set():
            return
        # done_bytes 严格累加了所有实际写入的字节，以是否写满为准最可靠
        self.completed = self.total_size > 0 and self.done_bytes >= self.total_size
        if self.completed:
            try:
                if self.state_path and os.path.exists(self.state_path):
                    os.remove(self.state_path)
            except OSError:
                pass

    # ---------- 控制 ----------
    def cancel(self):
        self._cancel.set()
        self._pause.set()

    def pause(self):
        self._pause.clear()

    def resume(self):
        self._pause.set()

    def is_paused(self):
        return not self._pause.is_set()

    def is_cancelled(self):
        return self._cancel.is_set()

    @property
    def percent(self):
        if self.total_size <= 0:
            return 0.0
        return min(100.0, self.done_bytes / self.total_size * 100)