#!/usr/bin/env python3
import re
import sys
import time
import json
import csv
import argparse
import platform
import subprocess
from urllib.request import urlopen

def run_cmd(cmd: str, timeout: int = 10) -> str:
    try:
        return subprocess.check_output(
            cmd, shell=True, text=True, stderr=subprocess.DEVNULL, timeout=timeout
        )
    except:
        return ""

def progress_bar(percent: int, width: int = 30):
    filled = int(width * percent / 100)
    bar = "[" + "=" * filled + " " * (width - filled) + "]"
    print(f"\r{bar} {percent}%", end="", flush=True)

def mask_sensitive(value: str, mask_char: str = "*") -> str:
    if not value or value == "未知":
        return value
    if re.match(r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$", value):
        sep = ":" if ":" in value else "-"
        parts = value.split(sep)
        return sep.join([parts[0], parts[1], mask_char * 2, mask_char * 2, parts[4], parts[5]])
    if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", value):
        parts = value.split(".")
        return f"{parts[0]}.{parts[1]}.{mask_char * len(parts[2])}.{parts[3]}"
    return value

def parse_ping_result(ping_out: str, system: str) -> tuple[float, float]:
    loss_match = re.search(r"([\d.]+)%\s+packet loss", ping_out, re.I)
    if not loss_match:
        loss_match = re.search(r"([\d.]+)%\s*(丢失|loss)", ping_out, re.I)
    loss = float(loss_match.group(1)) if loss_match else 100.0

    latency_patterns = [
        r"round-trip min/avg/max/stddev = [\d.]+/([\d.]+)/",
        r"rtt min/avg/max/(?:mdev|stddev) = [\d.]+/([\d.]+)/",
        r"平均\s*=\s*([\d.]+)ms",
        r"Average\s*=\s*([\d.]+)ms",
    ]
    latency = 999.0
    for pattern in latency_patterns:
        match = re.search(pattern, ping_out, re.I)
        if match:
            latency = float(match.group(1))
            break
    return loss, latency

def speed_test() -> float:
    test_urls = [
        "https://speed.aliyun.com/download?size=1048576",
        "https://dldir1.qq.com/qqfile/qq/QQ9.7.3/29949/QQ9.7.3.29949.exe.dl?start=0&end=1048575",
    ]
    for url in test_urls:
        try:
            start = time.time()
            with urlopen(url, timeout=5) as response:
                response.read(1048576)
            elapsed = max(time.time() - start, 0.001)
            return round(8 / elapsed, 1)
        except Exception:
            continue
    return 0.0

def collect_info(interface: str = "en0", run_speedtest: bool = False) -> dict:
    info = {}
    system = platform.system().lower()
    
    progress_bar(10)
    if system == "darwin":
        airport = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
        airport_out = run_cmd(f"{airport} -I")
        if not airport_out or "AirPort: Off" in airport_out or "SSID:" not in airport_out:
            raise Exception("未检测到无线网络连接，请先连接 WiFi")
        
        for line in airport_out.split("\n"):
            line = line.strip()
            if "SSID:" in line and "BSSID" not in line:
                info["ssid"] = line.split(":",1)[1].strip()
            elif "agrCtlRSSI:" in line:
                info["rssi"] = int(line.split(":",1)[1].strip())
            elif "channel:" in line:
                chan_part = line.split(":",1)[1].strip()
                info["channel"] = int(chan_part.split(",")[0])
                info["band"] = "5G" if info["channel"] >=36 else "2.4G"
                info["channel_width"] = int(chan_part.split(",")[1].strip()) if "," in chan_part else 20
            elif "lastTxRate:" in line:
                info["tx_rate"] = float(line.split(":",1)[1].strip())
        
        info["ip"] = run_cmd(f"ifconfig {interface} | grep 'inet ' | awk '{{print $2}}'").strip() or "未知"
        info["gateway"] = run_cmd(f"netstat -rn | grep default | grep {interface} | awk '{{print $2}}'").strip() or "未知"
        info["mac"] = run_cmd(f"ifconfig {interface} | grep ether | awk '{{print $2}}'").strip() or "未知"
        info["security"] = run_cmd(f"{airport} -I | grep 'Link Auth:' | awk '{{print $3}}'").strip() or "未知"
    elif system == "windows":
        netsh_out = run_cmd("netsh wlan show interfaces")
        if not netsh_out:
            raise Exception("未检测到无线网络连接，请先连接 WiFi")
        for line in netsh_out.split("\n"):
            line = line.strip()
            if "SSID" in line and "BSSID" not in line:
                info["ssid"] = line.split(":", 1)[1].strip()
            elif "BSSID" in line:
                info["bssid"] = line.split(":", 1)[1].strip()
            elif "信号" in line or "Signal" in line:
                match = re.search(r"(\d+)%", line)
                if match:
                    info["rssi"] = int((int(match.group(1)) / 2) - 100)
            elif "频道" in line or "Channel" in line:
                info["channel"] = int(line.split(":", 1)[1].strip())
                info["band"] = "5G" if info["channel"] >= 36 else "2.4G"
            elif "传输速率" in line or "Transmit rate" in line:
                info["tx_rate"] = float(line.split(":", 1)[1].strip().split(" ")[0])
            elif "物理地址" in line or "Physical address" in line:
                info["mac"] = line.split(":", 1)[1].strip()
        info.setdefault("channel_width", 20)
        info.setdefault("mac", "未知")
        ipconfig_out = run_cmd("ipconfig")
        ip_match = re.search(r"IPv4[^:]*:\s*([\d.]+)", ipconfig_out)
        gateway_match = re.search(r"(?:默认网关|Default Gateway)[^:]*:\s*([\d.]+)", ipconfig_out, re.I)
        info["ip"] = ip_match.group(1) if ip_match else "未知"
        info["gateway"] = gateway_match.group(1) if gateway_match else "未知"
        info["security"] = "未知"
    else:
        raise Exception("暂不支持当前系统，仅支持 macOS 和 Windows")
    
    progress_bar(50)
    # 网络质量检测
    ping_target = info["gateway"] if info["gateway"] != "未知" else "114.114.114.114"
    if system == "windows":
        ping_out = run_cmd(f"ping -n 3 -w 1000 {ping_target}")
    else:
        ping_out = run_cmd(f"ping -c 3 -W 1 {ping_target}")
    info["packet_loss"], info["latency"] = parse_ping_result(ping_out, system)
    
    # 同信道干扰
    if system == "darwin":
        nearby_out = run_cmd(f"/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport -s | grep ' {info['channel']},' | wc -l")
        try:
            info["same_channel_wifi"] = max(0, int(nearby_out.strip()) - 1)
        except ValueError:
            info["same_channel_wifi"] = 0
    else:
        info["same_channel_wifi"] = 0
    info["download_speed"] = speed_test() if run_speedtest else 0.0
    progress_bar(100)
    print("\n")
    
    # 健康评分
    info["health_score"] = 100
    if info["packet_loss"] > 1:
        info["health_score"] -= min(40, int(info["packet_loss"] * 4))
    if info["latency"] > 30:
        info["health_score"] -= min(20, int((info["latency"] - 30) // 10 * 2))
    if info["rssi"] < -50:
        info["health_score"] -= min(20, ((-50 - info["rssi"]) // 5) * 2)
    if info["channel_width"] == 20:
        info["health_score"] -= 10
    
    if info["health_score"] >= 85:
        info["health_status"] = "✅ 优秀"
    elif info["health_score"] >=70:
        info["health_status"] = "⚠️ 良好"
    elif info["health_score"] >=60:
        info["health_status"] = "⚡ 一般"
    else:
        info["health_status"] = "❌ 较差"
    return info

def print_result(info: dict, mask: bool = False):
    if mask:
        info = dict(info)
        for key in ("ip", "gateway", "mac", "bssid"):
            if key in info:
                info[key] = mask_sensitive(str(info[key]))
    print("📶 无线网络核心参数")
    print("| 参数 | 当前值 |")
    print("| --- | --- |")
    print(f"| IP地址 | {info.get('ip', '未知')} |")
    print(f"| 网关地址 | {info.get('gateway', '未知')} |")
    print(f"| SSID名称 | {info.get('ssid', '未知')} |")
    print(f"| 工作频段 | {info.get('band', '未知')} |")
    print(f"| 信号强度 | {info.get('rssi', '未知')} dBm |")
    print(f"| 协商速率 | {info.get('tx_rate', '未知')} Mbps |")
    print(f"| 信道频宽 | {info.get('channel_width', '未知')} MHz |")
    print(f"| 无线信道 | {info.get('channel', '未知')} |")
    print(f"| 同信道干扰数量 | {info.get('same_channel_wifi', 0)} 个 |")
    print(f"| MAC地址 | {info.get('mac', '未知')} |")
    print(f"| 网络时延 | {info.get('latency', '未知')} ms |")
    print(f"| 丢包率 | {info.get('packet_loss', '未知')} % |")
    if info.get("download_speed", 0):
        print(f"| 实际下载速度 | {info.get('download_speed')} Mbps |")
    print(f"| 安全类型 | {info.get('security', '未知')} |")
    
    print("\n")
    print("🌐 当前网络状态")
    print(f"健康评分: {info['health_score']}/100 {info['health_status']}")
    if info.get("latency", 999) <= 30 and info.get("packet_loss", 100) <= 1:
        print(f"稳定性: 非常优秀，网关时延 {info.get('latency')} ms，丢包率 {info.get('packet_loss')}%，日常办公、视频会议和游戏都不会因为本地 WiFi 链路明显卡顿。")
    elif info.get("latency", 999) <= 100 and info.get("packet_loss", 100) <= 3:
        print(f"稳定性: 基本稳定，网关时延 {info.get('latency')} ms，丢包率 {info.get('packet_loss')}%，视频会议可能偶尔波动。")
    else:
        print(f"稳定性: 较差，网关时延 {info.get('latency')} ms，丢包率 {info.get('packet_loss')}%，可能出现卡顿或断连。")
    print("优化建议:")
    suggestions = []
    if info["channel_width"] == 20 and info["band"] == "5G":
        suggestions.append("5G频宽仅20MHz，建议配置为80MHz可提升4倍速率")
    if info["rssi"] < -70:
        suggestions.append("信号强度偏弱，建议靠近路由器减少遮挡")
    if info["same_channel_wifi"] >=3:
        suggestions.append("同信道干扰较多，建议更换WiFi信道")
    if info.get("security") in {"Open", "未知"}:
        suggestions.append("建议确认并开启 WPA2/WPA3 加密，避免开放网络带来的隐私和蹭网风险")
    if not suggestions:
        suggestions.append("当前无线网络质量优秀，无需优化")
    for idx, sug in enumerate(suggestions, 1):
        print(f"  {idx}. {sug}")
    print("")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WiFi质量检测工具")
    parser.add_argument("--interface", type=str, default="en0", help="指定网卡")
    parser.add_argument("--speedtest", action="store_true", help="增加轻量下载测速")
    parser.add_argument("--mask", action="store_true", help="打码 IP、网关和 MAC 地址，方便截图分享")
    parser.add_argument("--json", type=str, help="输出 JSON 结果到指定路径")
    parser.add_argument("--csv", type=str, help="输出 CSV 结果到指定路径")
    args = parser.parse_args()
    
    try:
        print("🔍 正在检测无线网络质量...\n")
        info = collect_info(interface=args.interface, run_speedtest=args.speedtest)
        print_result(info, mask=args.mask)
        if args.json:
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump(info, f, ensure_ascii=False, indent=2)
            print(f"✅ JSON结果已保存到: {args.json}")
        if args.csv:
            with open(args.csv, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["参数", "值"])
                for key, value in info.items():
                    writer.writerow([key, value])
            print(f"✅ CSV结果已保存到: {args.csv}")
    except Exception as e:
        print(f"❌ 检测失败: {str(e)}")
        sys.exit(1)
