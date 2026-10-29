"""
网络修复模块 - 一键修复常见网络问题
面向新手小白，自动执行修复操作
"""

import subprocess
import os

from .cmd_utils import IS_WINDOWS, smart_run, run_cmd_bytes


def is_admin():
    """检测当前程序是否以管理员权限运行（Windows）"""
    if not IS_WINDOWS:
        return True
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin():
    """以管理员权限重新启动程序（Windows UAC 提权）"""
    if not IS_WINDOWS:
        return False
    try:
        import ctypes
        import sys
        exe_path = sys.executable if getattr(sys, "frozen", False) else sys.argv[0]
        # 透传命令行参数，避免提权重启后丢失运行参数
        params = subprocess.list2cmdline(sys.argv[1:]) if len(sys.argv) > 1 else ""
        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", exe_path, params, None, 1)
        # 返回值 > 32 表示提权启动成功
        return result > 32
    except Exception:
        return False


class NetworkRepair:
    """网络修复器 - 自动修复常见网络问题"""

    def __init__(self):
        self.is_windows = IS_WINDOWS
        self.is_admin = is_admin()
        self.logs = []

    def run_all_repairs(self, progress_callback=None, item_callback=None):
        """运行所有修复操作"""
        self.logs = []
        repairs = [
            ("刷新DNS缓存", self.flush_dns),
            ("重置Winsock目录", self.reset_winsock),
            ("重置TCP/IP协议", self.reset_tcpip),
            ("释放并重新获取IP", self.renew_ip),
            ("清除代理设置", self.clear_proxy),
        ]

        total = len(repairs)
        results = []

        for i, (name, repair_func) in enumerate(repairs):
            try:
                success, message = repair_func()
            except Exception as e:
                success = False
                message = f"执行异常: {str(e)}"

            result = {
                "name": name,
                "success": success,
                "message": message
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

    def clear_proxy(self):
        """清除代理设置"""
        try:
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
