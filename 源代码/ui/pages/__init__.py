"""按功能拆分的界面页面（mixin，由 MainWindow 组合）。"""

from .home import HomePageMixin
from .diagnose import DiagnosePageMixin
from .repair import RepairPageMixin
from .speed import SpeedPageMixin
from .devices import DevicesPageMixin
from .dns import DnsPageMixin
from .wifi import WifiPageMixin
from .downloader import DownloaderPageMixin
from .history import HistoryPageMixin

__all__ = [
    "HomePageMixin",
    "DiagnosePageMixin",
    "RepairPageMixin",
    "SpeedPageMixin",
    "DevicesPageMixin",
    "DnsPageMixin",
    "WifiPageMixin",
    "DownloaderPageMixin",
    "HistoryPageMixin",
]
