"""后台工作线程：把阻塞的系统/网络操作移出 GUI 线程。"""

from PySide6.QtCore import QThread, Signal

from core.diagnostic import NetworkDiagnostic
from core.repair import NetworkRepair
from core.speed_test import SpeedTest
from core.dns_optimizer import DNSOptimizer
from core.wifi_check import WiFiChecker

class DiagnosticWorker(QThread):
    """诊断工作线程"""
    progress = Signal(int, str)
    item_done = Signal(dict)
    finished = Signal(list)

    def run(self):
        diag = NetworkDiagnostic()
        def progress_cb(percent, name):
            self.progress.emit(percent, name)
        def item_cb(result):
            self.item_done.emit(result)
        results = diag.run_all_tests(progress_cb, item_cb)
        self.finished.emit(results)


class RepairWorker(QThread):
    """修复工作线程"""
    progress = Signal(int, str)
    item_done = Signal(dict)
    finished = Signal(list)

    def run(self):
        repair = NetworkRepair()
        def progress_cb(percent, name):
            self.progress.emit(percent, name)
        def item_cb(result):
            self.item_done.emit(result)
        results = repair.run_all_repairs(progress_cb, item_cb)
        self.finished.emit(results)


class SpeedTestWorker(QThread):
    """测速工作线程""" 
    progress = Signal(int)
    status = Signal(str)
    live = Signal(float)
    upline = Signal(float)
    finished = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tester = SpeedTest()

    def run(self):
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
        results = self.tester.run_full_test(progress_cb, status_cb, live_cb, uplive_cb)
        self.finished.emit(results)

    def cancel(self):
        """窗口关闭/用户取消时尽快结束测速，避免退出时长时间等待线程。"""
        self.tester.cancel()


class DnsTestWorker(QThread):
    """DNS测试工作线程"""
    progress = Signal(int, str)
    finished = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.optimizer = DNSOptimizer()

    def run(self):
        def progress_cb(percent, name):
            self.progress.emit(percent, name)
        results = self.optimizer.test_all_dns(progress_cb)
        self.finished.emit(results)

    def cancel(self):
        self.optimizer.cancel()


class WifiCheckWorker(QThread):
    """Wi-Fi检测工作线程"""
    finished = Signal(dict)

    def run(self):
        wifi = WiFiChecker()
        info = wifi.get_wifi_info()
        self.finished.emit(info)


class DeviceScanWorker(QThread):
    """局域网设备扫描工作线程"""
    finished = Signal(list)

    def run(self):
        from core.lan_scan import scan_lan_devices
        try:
            devs = scan_lan_devices()
        except Exception:
            devs = []
        self.finished.emit(devs)


class DownloadWorker(QThread):
    """下载工作线程：在后台运行阻塞式的 Downloader.start()"""
    finished = Signal()

    def __init__(self, downloader, parent=None):
        super().__init__(parent)
        self.d = downloader

    def run(self):
        try:
            self.d.start()
        except Exception as e:
            # 探测/启动阶段的异常也写入 error，便于 UI 呈现
            with self.d._cond_lock:
                if not self.d.error:
                    self.d.error = str(e)
        finally:
            self.finished.emit()
