"""
网络修复模块 - 一键修复常见网络问题
面向新手小白，自动执行修复操作
"""

import json
import os
from datetime import datetime

from .admin import is_admin, relaunch_as_admin
from .cmd_utils import IS_WINDOWS, smart_run, run_cmd_bytes
from .paths import get_cache_dir


class NetworkRepair:
    """网络修复器 - 自动修复常见网络故障"""

    # 名称 -> 元信息（是否需要管理员 / 是否需重启 / 是否可回滚）
    SPECS = {
        "刷新DNS缓存": {"requires_admin": False, "needs_reboot": False,
                       "reversible": False, "title": "刷新 DNS 缓存"},
        "重置Winsock目录": {"requires_admin": True, "needs_reboot": True,
                           "reversible": False, "title": "重置 Winsock"},
        "重置TCP/IP协议": {"requires_admin": True, "needs_reboot": True,
                          "reversible": False, "title": "重置 TCP/IP 堆栈"},
        "释放并重新获取IP": {"requires_admin": True, "needs_reboot": False,
                            "reversible": False, "title": "释放并重获 IP"},
        "清除代理设置": {"requires_admin": False, "needs_reboot": False,
                        "reversible": True, "title": "清除代理设置"},
    }

    def __init__(self, path=None):
        self.is_windows = IS_WINDOWS
        self.is_admin = is_admin()
        self.logs = []

    def preview(self):
        """返回修复项预览，供界面在开始前如实告知权限/重启/回滚范围。"""
        rows = []
        for name, meta in self.SPECS.items():
            info = dict(meta)
            info["name"] = name
            info["requires_admin"] = bool(
                meta["requires_admin"] and self.is_windows)
            info["available"] = self.is_windows
            rows.append(info)
        return rows

    def run_all_repairs(self, progress_callback=None, item_callback=None,
                        cancel=None, only=None):
        """运行修复操作（支持在两项之间取消，已执行的结果保留）。

        only: 可选名称集合；为空时执行全部。
        """
        self.logs = []
        repairs = [
            ("刷新DNS缓存", self.flush_dns),
            ("重置Winsock目录", self.reset_winsock),
            ("重置TCP/IP协议", self.reset_tcpip),
            ("释放并重新获取IP", self.renew_ip),
            ("清除代理设置", self.clear_proxy),
        ]
        selected = None
        if only is not None:
            selected = {str(name) for name in only}
            repairs = [(name, func) for name, func in repairs
                       if name in selected]
        if not repairs:
            return []

        total = len(repairs)
        results = []

        for i, (name, repair_func) in enumerate(repairs):
            if cancel is not None and cancel.is_set():
                break
            try:
                success, message = repair_func()
            except Exception as e:
                success = False
                message = f"执行异常: {str(e)}"

            meta = self.SPECS.get(name, {})
            result = {
                "name": name,
                "success": success,
                "message": message,
                "requires_admin": bool(meta.get("requires_admin")),
                "needs_reboot": bool(meta.get("needs_reboot")),
                "reversible": bool(meta.get("reversible")),
            }
            results.append(result)
            self.logs.append(f"[{name}] {message}")

            if item_callback:
                item_callback(result)
            if progress_callback:
                progress_callback(int((i + 1) / total * 100), name)

        return results

    def flush_dns(self):
        """刷新DNS缓存"""
        try:
            if self.is_windows:
                result = smart_run(["ipconfig", "/flushdns"], timeout=10)
                combined = (result.stdout + "\n" + result.stderr).lower()
                if "成功刷新" in result.stdout or "successfully" in result.stdout.lower():
                    return True, "DNS缓存刷新成功"
                elif "提升" in combined or "denied" in combined or "拒绝" in combined or "require" in combined:
                    return False, "需要管理员权限才能刷新DNS缓存"
                elif result.returncode != 0:
                    return False, f"DNS缓存刷新失败（返回码: {result.returncode}）"
                else:
                    return True, "DNS缓存刷新完成"
            else:
                return True, "非Windows系统，跳过DNS刷新"
        except Exception as e:
            return False, f"DNS刷新失败: {str(e)}"

    def reset_winsock(self):
        """重置Winsock目录"""
        try:
            if self.is_windows:
                result = smart_run(["netsh", "winsock", "reset"], timeout=10)
                combined = (result.stdout + "\n" + result.stderr).lower()
                if "成功" in result.stdout or "successfully" in result.stdout.lower():
                    return True, "Winsock重置成功（需重启电脑生效）"
                elif "提升" in combined or "denied" in combined or "拒绝" in combined:
                    return False, "需要管理员权限才能重置Winsock"
                elif result.returncode != 0:
                    return False, f"Winsock重置失败（返回码: {result.returncode}）"
                else:
                    return True, "Winsock重置完成"
            else:
                return True, "非Windows系统，跳过Winsock重置"
        except Exception as e:
            return False, f"Winsock重置失败: {str(e)}"

    def reset_tcpip(self):
        """重置TCP/IP协议栈"""
        try:
            if self.is_windows:
                result = smart_run(["netsh", "int", "ip", "reset"], timeout=15)
                combined = (result.stdout + "\n" + result.stderr).lower()
                if "重置" in result.stdout or "reset" in result.stdout.lower():
                    return True, "TCP/IP协议重置成功（需重启电脑生效）"
                elif "提升" in combined or "denied" in combined or "拒绝" in combined:
                    return False, "需要管理员权限才能重置TCP/IP"
                elif result.returncode != 0:
                    return False, f"TCP/IP重置失败（返回码: {result.returncode}）"
                else:
                    return True, "TCP/IP协议重置完成"
            else:
                return True, "非Windows系统，跳过TCP/IP重置"
        except Exception as e:
            return False, f"TCP/IP重置失败: {str(e)}"

    def renew_ip(self):
        """释放并重新获取IP地址"""
        try:
            if self.is_windows:
                # 无管理员权限时不释放IP，避免释放后无法续订造成断网
                if not self.is_admin:
                    return False, "需要管理员权限。为避免断网，本次未执行IP释放/续订。请右键以管理员身份运行后再试"
                # 释放IP：失败时不要继续 renew，否则用户可能直接断网
                release_result = smart_run(["ipconfig", "/release"], timeout=10)
                if release_result.returncode != 0:
                    return False, (
                        f"IP释放失败（返回码: {release_result.returncode}），"
                        "已跳过续订以避免断网。请确认以管理员身份运行后重试")
                # 重新获取
                result = smart_run(["ipconfig", "/renew"], timeout=15)
                combined = (result.stdout + "\n" + result.stderr).lower()
                if "提升" in combined or "denied" in combined or "拒绝" in combined:
                    return False, "需要管理员权限才能续订IP地址"
                if "IP 地址" in result.stdout or "IP Address" in result.stdout:
                    return True, "IP地址重新获取成功"
                elif result.returncode != 0:
                    return False, f"IP地址获取失败（返回码: {result.returncode}）"
                else:
                    return False, "IP地址获取失败，请检查网络连接"
            else:
                return True, "非Windows系统，跳过IP续订"
        except Exception as e:
            return False, f"IP续订失败: {str(e)}"

    @staticmethod
    def backup_path():
        return os.path.join(get_cache_dir(), "proxy_backup.json")

    def _read_proxy_settings(self):
        """读取当前代理注册表值；失败返回空 dict。"""
        values = {}
        if not self.is_windows:
            values["HTTP_PROXY"] = os.environ.get("HTTP_PROXY", "")
            values["HTTPS_PROXY"] = os.environ.get("HTTPS_PROXY", "")
            return values
        try:
            import winreg  # type: ignore
            key_path = (r"Software\Microsoft\Windows\CurrentVersion"
                        r"\Internet Settings")
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                for name in ("ProxyEnable", "ProxyServer", "AutoConfigURL"):
                    try:
                        values[name] = winreg.QueryValueEx(key, name)[0]
                    except OSError:
                        continue
        except Exception:
            pass
        return values

    def backup_proxy(self):
        """清除代理前备份当前代理设置；返回备份路径，失败返回空串。"""
        payload = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "values": self._read_proxy_settings(),
        }
        path = self.backup_path()
        tmp = f"{path}.{os.getpid()}.tmp"
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            return path
        except OSError:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            return ""

    def restore_proxy(self):
        """把代理恢复为备份值；没有备份或写入失败返回 (False, 原因)。"""
        path = self.backup_path()
        if not os.path.exists(path):
            return False, "没有找到代理备份，无法自动恢复"
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            return False, "代理备份文件损坏，无法恢复"

        values = (payload or {}).get("values") or {}
        if not self.is_windows:
            if values.get("HTTP_PROXY"):
                os.environ["HTTP_PROXY"] = str(values["HTTP_PROXY"])
            else:
                os.environ.pop("HTTP_PROXY", None)
            return True, "环境变量代理已恢复"

        key_path = (r"HKCU\Software\Microsoft\Windows\CurrentVersion"
                    r"\Internet Settings")
        failed = []
        if "ProxyEnable" in values:
            code, _ = run_cmd_bytes(
                ["reg", "add", key_path, "/v", "ProxyEnable",
                 "/t", "REG_DWORD", "/d", str(int(values["ProxyEnable"])), "/f"],
                timeout=5)
            if code != 0:
                failed.append("ProxyEnable")
        if "ProxyServer" in values:
            code, _ = run_cmd_bytes(
                ["reg", "add", key_path, "/v", "ProxyServer",
                 "/t", "REG_SZ", "/d", str(values["ProxyServer"]), "/f"],
                timeout=5)
            if code != 0:
                failed.append("ProxyServer")
        if "AutoConfigURL" in values:
            code, _ = run_cmd_bytes(
                ["reg", "add", key_path, "/v", "AutoConfigURL",
                 "/t", "REG_SZ", "/d", str(values["AutoConfigURL"]), "/f"],
                timeout=5)
            if code != 0:
                failed.append("AutoConfigURL")
        if failed:
            return False, f"代理恢复部分失败：{', '.join(failed)}"
        return True, "代理设置已恢复到备份值"

    def clear_proxy(self):
        """清除代理设置（修改前自动备份，供 restore_proxy 恢复）"""
        try:
            self.backup_proxy()
            if self.is_windows:
                # 禁用代理（统一走 run_cmd_bytes：隐藏控制台窗口）
                code1, _ = run_cmd_bytes(
                    ["reg", "add",
                     r"HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                     "/v", "ProxyEnable", "/t", "REG_DWORD", "/d", "0", "/f"], timeout=5)
                # 清除代理服务器地址
                code2, _ = run_cmd_bytes(
                    ["reg", "add",
                     r"HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                     "/v", "ProxyServer", "/t", "REG_SZ", "/d", "", "/f"], timeout=5)
                if code1 == 0 and code2 == 0:
                    return True, "代理设置已清除"
                else:
                    errors = []
                    if code1 != 0:
                        errors.append(f"禁用代理(返回码:{code1})")
                    if code2 != 0:
                        errors.append(f"清除代理地址(返回码:{code2})")
                    return False, f"代理清除部分失败: {', '.join(errors)}"
            else:
                os.environ.pop("HTTP_PROXY", None)
                os.environ.pop("HTTPS_PROXY", None)
                return True, "环境变量代理已清除"
        except Exception as e:
            return False, f"代理清除失败: {str(e)}"

    def get_summary(self, results):
        """获取修复摘要"""
        success_count = sum(1 for r in results if r["success"])
        fail_count = sum(1 for r in results if not r["success"])

        if fail_count == 0:
            return f"全部修复成功（{success_count}项），建议重启电脑使设置完全生效", "ok"
        elif success_count > 0:
            return f"成功修复 {success_count} 项，{fail_count} 项失败（部分功能需要管理员权限）", "warning"
        else:
            return "修复全部失败，请尝试以管理员身份运行本软件", "error"
