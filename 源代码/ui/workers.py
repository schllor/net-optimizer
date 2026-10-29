"""后台工作线程：把阻塞的系统/网络操作移出 GUI 线程。

统一约定（TaskWorker）：
  - 子类只实现 execute()，返回结果对象；
  - 结果通过 done 发出，异常通过 failed(用户提示, 技术细节) 发出，取消发出 cancelled；
  - 不使用 QThread 自带的 finished 作为业务信号，避免覆盖 Qt 的线程结束信号，
    主窗口才能用 finished 统一清理任务台账。
"""

import threading

from PySide6.QtCore import QThread, Signal

from core.diagnostic import NetworkDiagnostic
from core.repair import NetworkRepair
from core.settings import Settings
from core.speed_test import SpeedTest
from core.dns_optimizer import DNSOptimizer
from core.wifi_check import WiFiChecker


class TaskWorker(QThread):
    """后台任务基类：统一结果、异常与取消通道。"""

    done = Signal(object)
    failed = Signal(str, str)
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel_event = threading.Event()

    def cancel(self):
        """请求取消：子类在长循环里检查 is_cancelled()。"""
        self._cancel_event.set()

    def is_cancelled(self):
        return self._cancel_event.is_set()

    def execute(self):
        """子类实现具体任务并返回结果。"""
        return None

    def run(self):
        try:
            result = self.execute()
        except Exception as e:
            self.failed.emit(f"任务执行失败：{e}", repr(e))
            self.done.emit(None)
            return
        if self.is_cancelled():
            self.cancelled.emit()
        self.done.emit(result)


class DiagnosticWorker(TaskWorker):
    """诊断工作线程"""
    progress = Signal(int, str)
    item_done = Signal(dict)

    def execute(self):
        diag = NetworkDiagnostic()

        def progress_cb(percent, name):
            self.progress.emit(percent, name)

        return diag.run_all_tests(
            progress_cb, self.item_done.emit, cancel=self._cancel_event)


class RepairWorker(TaskWorker):
    """修复工作线程"""
    progress = Signal(int, str)
    item_done = Signal(dict)

    def execute(self):
        repair = NetworkRepair()

        def progress_cb(percent, name):
            self.progress.emit(percent, name)

        return repair.run_all_repairs(
            progress_cb, self.item_done.emit, cancel=self._cancel_event)


class SpeedTestWorker(TaskWorker):
    """测速工作线程"""
    progress = Signal(int)
    status = Signal(str)
    live = Signal(float)
    upline = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tester = SpeedTest()
        self.settings = Settings()

    def execute(self):
        def progress_cb(percent):
            self.progress.emit(percent)

        def status_cb(text):
            self.status.emit(text)

        def live_cb(mbps):
            if mbps > 0:
                self.live.emit(mbps)

        def uplive_cb(mbps):
            if mbps > 0:
                self.upline.emit(mbps)

        return self.tester.run_full_test(
            progress_cb, status_cb, live_cb, uplive_cb,
            duration=self.settings.get("speed_dl_seconds", 8),
            upload_duration=self.settings.get("speed_ul_seconds", 6))

    def cancel(self):
        """窗口关闭/用户取消时尽快结束测速，避免退出时长时间等待线程。"""
        super().cancel()
        self.tester.cancel()


class DnsTestWorker(TaskWorker):
    """DNS测试工作线程"""
    progress = Signal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.optimizer = DNSOptimizer()
        self.settings = Settings()

    def execute(self):
        def progress_cb(percent, name):
            self.progress.emit(percent, name)

        try:
            self.optimizer.ROUNDS = max(
                1, int(self.settings.get("dns_rounds", 3)))
        except (TypeError, ValueError):
            pass
        return self.optimizer.test_all_dns(progress_cb)

    def cancel(self):
        super().cancel()
        self.optimizer.cancel()


class DnsCurrentWorker(TaskWorker):
    """读取当前系统 DNS（原生 API 优先，ipconfig 兜底）"""

    def execute(self):
        return DNSOptimizer().get_current_dns()


class DnsApplyWorker(TaskWorker):
    """设置系统 DNS（管理员 netsh 写操作移出 GUI 线程）"""

    def __init__(self, primary, secondary="", parent=None):
        super().__init__(parent)
        self.optimizer = DNSOptimizer()
        self.primary = primary
        self.secondary = secondary

    def execute(self):
        return self.optimizer.set_dns(self.primary, self.secondary)


class DnsRestoreWorker(TaskWorker):
    """恢复为自动获取 DNS（DHCP）"""

    def execute(self):
        return DNSOptimizer().restore_dhcp()


class WifiCheckWorker(TaskWorker):
    """Wi-Fi检测工作线程"""

    def execute(self):
        return WiFiChecker().get_wifi_info()


class WifiScanWorker(TaskWorker):
    """附近 Wi-Fi 扫描工作线程（原生 BSS 列表 / netsh 回退）"""

    def execute(self):
        try:
            return WiFiChecker().scan_nearby_wifi()
        except Exception as e:
            return {"success": False, "networks": [], "advice": [],
                    "error": f"扫描失败: {e}"}


class WifiDiagWorker(TaskWorker):
    """收集 Wi-Fi 诊断文本（netsh/ipconfig 在后台执行，避免界面卡顿）"""

    def execute(self):
        from core.wifi_check import collect_wifi_diagnostics
        return collect_wifi_diagnostics()


class DeviceScanWorker(TaskWorker):
    """局域网设备扫描工作线程"""

    def execute(self):
        from core.lan_scan import scan_lan_devices
        return scan_lan_devices(cancel=self._cancel_event)


class DownloadWorker(TaskWorker):
    """下载工作线程：在后台运行阻塞式的 Downloader.start()"""

    def __init__(self, downloader, parent=None):
        super().__init__(parent)
        self.d = downloader

    def execute(self):
        try:
            self.d.start()
        except Exception as e:
            # 探测/启动阶段的异常也写入 error，便于 UI 呈现
            with self.d._cond_lock:
                if not self.d.error:
                    self.d.error = str(e)
        return None

    def cancel(self):
        super().cancel()
        self.d.cancel()


class TrafficSampler(QThread):
    """每秒采样一次网卡流量，把结果发回 GUI 线程更新标签。"""

    rates = Signal(object, object)

    def __init__(self, monitor, interval=1.0, parent=None):
        super().__init__(parent)
        self.monitor = monitor
        self.interval = interval
        self._stop_event = threading.Event()

    def run(self):
        while not self._stop_event.wait(self.interval):
            try:
                up, down = self.monitor.sample()
            except Exception:
                continue
            self.rates.emit(up, down)

    def stop(self):
        self._stop_event.set()
