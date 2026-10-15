"""
国内下载加速镜像模块 - 针对国外托管源（GitHub 等）自动选择国内可用镜像
只对"可镜像的国外 host"生效；国内直链/签名链接保持原样，不走这里，避免破坏签名与防盗链。

做法（参考 mirror-cn 等开源方案）：
  1. 判断 URL 是否属于可镜像的国外托管 host；
  2. 是则生成候选镜像地址（前缀模式 + 域名替换模式）；
  3. 并发对候选发 HEAD/Range:0-0 测速，选"可用且支持 Range、耗时最短"的镜像；
  4. 若全部镜像不可用，退回原始直连地址。
"""

import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

USER_AGENT = "Mozilla/5.0 NetHelper/1.0"
PROBE_TIMEOUT = 3.5     # 单个候选镜像探测超时（秒），避免拖慢下载启动
PROBE_RANGE = "bytes=0-0"   # 只取 1 字节即可判定可用性 + 是否支持 Range
MAX_PROBE = 6           # 同时并发探测的候选上限，控制资源占用

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


def _probe_one(url):
    """探测单个候选可用性，返回可用则 (elapsed, status, url)，否则 None"""
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Range": PROBE_RANGE})
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as resp:
            code = resp.status
        if code in (200, 206):
            return (time.time() - t0, code, url)
    except (urllib.error.URLError, urllib.error.HTTPError,
            OSError, ValueError, TimeoutError):
        pass
    return None


def _extract_host(url):
    h = _host_of(url).replace("www.", "") or url
    return h[:28]


def pick_fastest_url(url):
    """
    返回最优下载地址：可用且支持 Range、耗时最短的候选镜像；
    不可镜像 / 全部镜像不可用 / 无候选时，返回原始 url。
    """
    cands = build_mirror_urls(url)
    if len(cands) <= 1:
        return url
    found = []
    workers = min(MAX_PROBE, len(cands))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_probe_one, c) for c in cands]
        for f in futs:
            r = f.result()
            if r:
                found.append(r)
    if not found:
        return url
    # 优先支持 Range(206) 的镜像，其次耗时最短
    range_ok = [x for x in found if x[1] == 206]
    pool = range_ok if range_ok else found
    pool.sort(key=lambda x: x[0])
    return pool[0][2]