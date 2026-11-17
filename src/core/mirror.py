"""
国内下载加速镜像模块 - 针对国外托管源（GitHub 等）自动选择国内可用镜像
只对"可镜像的国外 host"生效；国内直链/签名链接保持原样，不走这里，避免破坏签名与防盗链。

做法（参考 mirror-cn 等开源方案）：
  1. 判断 URL 是否属于可镜像的国外托管 host；
  2. 是则生成候选镜像地址（前缀模式 + 域名替换模式）；
  3. 并发对候选发 Range 请求，实际读一小段计时，按"支持 Range + 吞吐"排序；
  4. 下载器可同时使用前几名镜像，让不同分块分别连接不同主机，叠加吞吐。
"""

import time
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout

USER_AGENT = "Mozilla/5.0 NetHelper/1.0"
PROBE_TIMEOUT = 4.0        # 单个候选镜像探测超时（秒）
PROBE_BYTES = 64 * 1024    # 实测吞吐时最多读取的字节数
MAX_PROBE = 6              # 同时并发探测的候选上限
MAX_SOURCES = 3            # 返回给下载器的最优源数量
PROBE_RANGE = f"bytes=0-{PROBE_BYTES - 1}"

Source = namedtuple("Source", "url supports_range total speed_bps")

# 前缀加速镜像（在原始 URL 前加前缀）。顺序即优先级倾向，真正取舍以测速为准。
GH_PREFIX_MIRRORS = [
    "https://gh-proxy.org/",
    "https://gh-proxy.com/",
    "https://ghfast.top/",
    "https://mirror.ghproxy.com/",
    "https://ghproxy.net/",
]

# 域名替换镜像（把 github.com 相关 host 替换成这些域名）
GH_HOST_MIRRORS = [
    "hub.gitmirror.com",
    "github.moeyy.xyz",
    "ghproxy.net",
    "gh.llkk.cc",
]

# 判定"可镜像"的国外下载托管 host（含尾匹配，如 objects.githubusercontent.com）
MIRRORABLE_HOST_HINTS = (
    "github.com", "githubusercontent.com", "github.io",
    "modrinth.com", "curseforge.com",
)


def _host_of(url):
    from urllib.parse import urlparse
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def is_mirrorable(url):
    """判断该 URL 是否属于可镜像的国外托管源"""
    host = _host_of(url)
    if not host:
        return False
    return any(hint in host for hint in MIRRORABLE_HOST_HINTS)


def build_mirror_urls(url):
    """为国外托管 URL 生成候选镜像地址；不可镜像或异常则返回 [url]"""
    if not is_mirrorable(url):
        return [url]
    from urllib.parse import urlparse
    cands = [url]
    try:
        p = urlparse(url)
        for m in GH_PREFIX_MIRRORS:
            cands.append(m + url)
        # 域名替换模式仅对 github.com 系 host 生效
        net = p.netloc.lower()
        if "github.com" in net or "githubusercontent.com" in net:
            path_q = (p.path or "") + (("?" + p.query) if p.query else "")
            for m in GH_HOST_MIRRORS:
                cands.append(f"{p.scheme}://{m}{path_q}")
    except Exception:
        return [url]
    # 去重保序
    seen, result = set(), []
    for u in cands:
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result


def _parse_total(content_range):
    """从 Content-Range: bytes 0-65535/123456 中解析总大小"""
    try:
        tail = (content_range or "").rsplit("/", 1)[-1].strip()
        return int(tail)
    except (ValueError, AttributeError):
        return 0


def _probe_one(url, timeout=PROBE_TIMEOUT):
    """实测单个候选：读一小段，返回 Source；不可用时返回 None。"""
    import urllib.error
    import urllib.request
    # 延迟导入，避免与 downloader 形成顶层循环依赖
    from .downloader import open_url, validate_url
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Range": PROBE_RANGE,
            "Accept-Encoding": "identity",
        })
        t0 = time.perf_counter()
        with open_url(req, timeout) as resp:
            code = resp.status
            if code not in (200, 206):
                return None
            total = _parse_total(resp.headers.get("Content-Range"))
            final_url = resp.geturl() or url
            data = resp.read(PROBE_BYTES)
        elapsed = max(time.perf_counter() - t0, 1e-3)
        if validate_url(final_url):
            return None
        if not data:
            return None
        return Source(
            url=url,
            supports_range=(code == 206),
            total=total,
            speed_bps=len(data) / elapsed,
        )
    except (urllib.error.URLError, OSError, ValueError):
        return None


def probe_sources(url, timeout=PROBE_TIMEOUT):
    """
    并发探测候选镜像，按"支持 Range 优先、吞吐从高到低"返回可用源列表。
    不可镜像时返回 [Source(url, ...)] 由调用方决定是否使用。
    """
    cands = build_mirror_urls(url)
    if not cands:
        return []
    found = []
    workers = min(MAX_PROBE, len(cands))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_probe_one, c, timeout) for c in cands]
        try:
            for f in as_completed(futs, timeout=timeout + 1.5):
                try:
                    r = f.result()
                except Exception:
                    r = None
                if r is not None:
                    found.append(r)
        except FuturesTimeout:
            pass
    seen, uniq = set(), []
    for r in found:
        if r.url not in seen:
            seen.add(r.url)
            uniq.append(r)
    uniq.sort(key=lambda r: (not r.supports_range, -r.speed_bps))
    return uniq


def pick_fastest_url(url):
    """返回吞吐最高的可用地址；没有可用镜像时返回原始 url。"""
    if len(build_mirror_urls(url)) <= 1:
        return url
    ranked = probe_sources(url)
    return ranked[0].url if ranked else url
