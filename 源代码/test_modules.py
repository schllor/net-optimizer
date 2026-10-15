"""
测试脚本 - 验证所有功能模块
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.speed_test import SpeedTest
from core.dns_optimizer import DNSOptimizer
from core.wifi_check import WiFiChecker

print("=== 测试网速延迟 ===")
speed = SpeedTest()
result = speed.ping_test(count=3)
print("延迟测试: {}ms, 丢包率: {}%".format(result["avg_latency"], result["loss_rate"]))

print()
print("=== 测试DNS优化 ===")
dns = DNSOptimizer()
current_dns = dns.get_current_dns()
print("当前DNS: {}".format(current_dns))

print()
print("=== 测试Wi-Fi检测 ===")
wifi = WiFiChecker()
info = wifi.get_wifi_info()
if info.get("success") and info.get("connected"):
    ssid = info.get("ssid", "未知")
    signal = info.get("signal_strength", 0)
    print("Wi-Fi: {}, 信号: {}%".format(ssid, signal))
else:
    print("Wi-Fi状态: {}".format(info.get("error", "未连接")))

print()
print("所有功能测试完成！")
