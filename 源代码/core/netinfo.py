"""
本机网络信息统一模块 - 探测本机 IP 与默认网关。

设计要点：
  - 语言无关优先：以 `route print` 的路由表为主策略。路由表的数据行是纯数字列，
    不受系统语言（中文 / 英文 / 其他）影响；而 ipconfig 的字段标签是本地化的，
    在不同区域设置的机器上会变成 `默认网关` 或 `Default Gateway`，只靠它极易失配。
  - 文本解析兜底：路由表取不到时，回退解析 `ipconfig`，同时兼容中英文标签。
  - 排除虚拟网卡：候选网关中优先选择与本机 IP 同 /24 网段者，
    避免误取 VMware / VirtualBox 等虚拟网卡网关（如 192.168.x.1）。
  - 永不抛错：任何异常都安全返回 None，交由上层做兜底判断。

面向新手，接口保持简单：
    get_local_ip()            -> "192.0.2.107" | None
    get_default_gateway()     -> "192.0.2.1"   | None
    get_default_gateway_info()-> {"gateway","interface","metric","source"} | None
"""

import re
import socket

from .cmd_utils import smart_run


# 默认网关字段标签：中文「默认网关」/ 英文「Default Gateway」（大小写不敏感）
_GW_LABEL_RE = re.compile(r"(?:默认网关|Default\s+Gateway)", re.IGNORECASE)

# 形如 192.0.2.1 的候选片段
_IPV4_FRAGMENT_RE = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}")


def _is_valid_ipv4(text):
    """判断是否为合法且非 0.0.0.0 的 IPv4 字符串。"""
    if not text:
        return False
    frag = _IPV4_FRAGMENT_RE.fullmatch(text)
    if not frag:
        return False
    if text == "0.0.0.0":
        return False
    try:
        return all(0 <= int(p) <= 255 for p in text.split("."))
    except ValueError:
        return False


def _same_subnet(ip_a, ip_b):
    """判断两个 IPv4 是否处于同一 /24 网段（用于排除虚拟网卡网关）。"""
    try:
        return ip_a.split(".")[:3] == ip_b.split(".")[:3]
    except Exception:
        return False


# ---------------------------------------------------------------- 纯解析函数
def parse_route_table_info(text):
    """从 `route print` 文本解析默认路由，返回 {'gateway','interface','metric'} 或 None。

    路由数据行形如：
        0.0.0.0          0.0.0.0     192.0.2.1      192.0.2.208     45
    即「目标 掩码 网关 接口 跃点数」。仅目标与掩码均为 0.0.0.0 的才是默认路由；
    存在多条时取跃点数（metric）最小者。表头虽本地化，数据行却是纯数字，
    因此本函数与系统语言无关。
    """
    if not text:
        return None
    best = None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        if parts[0] != "0.0.0.0" or parts[1] != "0.0.0.0":
            continue
        gateway, interface = parts[2], parts[3]
        if not _is_valid_ipv4(gateway):
            continue
        try:
            metric = int(parts[4])
        except (ValueError, IndexError):
            metric = 9999
        if best is None or metric < best["metric"]:
            best = {"gateway": gateway, "interface": interface, "metric": metric}
    return best


def parse_route_table(text):
    """从 `route print` 文本解析默认网关字符串；无则返回 None。"""
    info = parse_route_table_info(text)
    return info["gateway"] if info else None


def parse_gateway_from_ipconfig(text, local_ip=None):
    """解析 ipconfig 文本中的默认网关（同时兼容中英文标签）。

    做法：逐行定位带网关标签的行，取冒号之后的部分提取 IPv4，收集全部候选。
    选择规则：
      1) 若提供 local_ip，优先返回与其同 /24 网段的候选（排除虚拟网卡网关）；
      2) 否则返回第一个有效候选。
    网关为空的行（如 VMware 虚拟网卡的 `Default Gateway . . . :`）会被自然跳过。
    """
    if not text:
        return None

    candidates = []
    for raw_line in text.splitlines():
        line = raw_line.replace("：", ":")  # 兼容全角冒号
        if not _GW_LABEL_RE.search(line):
            continue
        tail = line.split(":", 1)[1] if ":" in line else line
        match = _IPV4_FRAGMENT_RE.search(tail)
        if not match:
            continue
        gateway = match.group(0)
        if _is_valid_ipv4(gateway) and gateway not in candidates:
            candidates.append(gateway)

    if not candidates:
        return None
    if local_ip:
        for gateway in candidates:
            if _same_subnet(gateway, local_ip):
                return gateway
    return candidates[0]


# ---------------------------------------------------------------- 命令执行层
def get_local_ip():
    """UDP connect 探测本机主 IP（不真正向外部发包）。失败返回 None。"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("223.5.5.5", 80))
            return sock.getsockname()[0]
        finally:
            sock.close()
    except Exception:
        return None


def get_default_gateway(local_ip=None):
    """获取默认网关；取不到返回 None。

    策略一：`route print -4` 路由表（语言无关，最稳）
    策略二：`ipconfig` 文本解析（中英文标签兼容）
    """
    # 策略一：路由表
    try:
        output = smart_run(["route", "print", "-4"], timeout=8).stdout
        gateway = parse_route_table(output)
        if gateway:
            return gateway
    except Exception:
        pass

    # 策略二：ipconfig
    try:
        if local_ip is None:
            local_ip = get_local_ip()
        output = smart_run(["ipconfig"], timeout=8).stdout
        return parse_gateway_from_ipconfig(output, local_ip)
    except Exception:
        return None


def get_default_gateway_info():
    """获取默认路由详情，返回 {'gateway','interface','metric','source'}；取不到返回 None。"""
    try:
        output = smart_run(["route", "print", "-4"], timeout=8).stdout
        info = parse_route_table_info(output)
        if info:
            info = dict(info)
            info["source"] = "route"
            return info
    except Exception:
        pass

    gateway = get_default_gateway()
    if gateway:
        return {"gateway": gateway, "interface": None, "metric": None, "source": "ipconfig"}
    return None
