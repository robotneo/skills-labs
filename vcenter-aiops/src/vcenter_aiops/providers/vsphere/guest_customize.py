"""Declarative Guest customization spec validation (no SDK, no OS calls).

The spec is data, never shell. It declares hostname and exactly one IPv4 method
(static with address/prefix/gateway, or dhcp) plus optional DNS. Validation here
is the hard, offline-testable boundary; applying it inside the Guest is a
separate fixed program verified on a live host. A successful submission never
implies the guest configuration has completed (Tools/reboot may be required).
"""
import ipaddress
import re

from ...domain.models import fail


HOSTNAME = re.compile(r"^(?=.{1,63}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def validate_spec(data):
    if not isinstance(data, dict):
        fail("guest_spec_invalid", "定制规格必须是对象", 2)
    allowed = {"hostname", "adapter"}
    if set(data) - allowed:
        fail("guest_spec_invalid", f"规格含未知字段：{sorted(set(data) - allowed)}", 2)

    hostname = data.get("hostname")
    if hostname is not None:
        if not isinstance(hostname, str) or not HOSTNAME.match(hostname):
            fail("guest_spec_invalid", "hostname 须为 1–63 位标签（字母数字与连字符）", 2)

    adapter = data.get("adapter")
    if adapter is None:
        fail("guest_spec_invalid", "必须声明一个网络适配器 adapter", 2)
    adapter = _validate_adapter(adapter)

    return {"hostname": hostname, "adapter": adapter}


def _validate_adapter(adapter):
    if not isinstance(adapter, dict):
        fail("guest_spec_invalid", "adapter 必须是对象", 2)
    allowed = {"mac", "name", "ipv4", "dns_servers", "dns_search"}
    if set(adapter) - allowed:
        fail("guest_spec_invalid", f"adapter 含未知字段：{sorted(set(adapter) - allowed)}", 2)

    selector = [key for key in ("mac", "name") if key in adapter]
    if len(selector) != 1:
        fail("guest_spec_invalid", "适配器须且只能用 mac 或 name 之一精确定位", 2)
    if "mac" in adapter and not re.fullmatch(
            r"(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}", adapter["mac"]):
        fail("guest_spec_invalid", "mac 不是合法的 MAC 地址", 2)
    if "name" in adapter and (not isinstance(adapter["name"], str) or not adapter["name"]):
        fail("guest_spec_invalid", "适配器 name 不能为空", 2)

    ipv4 = adapter.get("ipv4")
    if not isinstance(ipv4, dict):
        fail("guest_spec_invalid", "必须声明 ipv4 配置", 2)
    ipv4 = _validate_ipv4(ipv4)

    dns_servers = adapter.get("dns_servers", [])
    if not isinstance(dns_servers, list) or len(dns_servers) > 4:
        fail("guest_spec_invalid", "dns_servers 须为最多 4 个地址的数组", 2)
    for server in dns_servers:
        try:
            ipaddress.ip_address(server)
        except ValueError:
            fail("guest_spec_invalid", f"DNS 地址非法：{server}", 2)

    dns_search = adapter.get("dns_search", [])
    if not isinstance(dns_search, list) or len(dns_search) > 8:
        fail("guest_spec_invalid", "dns_search 须为最多 8 个搜索域的数组", 2)
    for suffix in dns_search:
        if not isinstance(suffix, str) or not suffix or len(suffix) > 253 or " " in suffix:
            fail("guest_spec_invalid", f"DNS 搜索域非法：{suffix}", 2)

    return {**{k: adapter[k] for k in selector}, "ipv4": ipv4,
            "dns_servers": dns_servers, "dns_search": dns_search}


def _validate_ipv4(ipv4):
    method = ipv4.get("method")
    if method not in ("static", "dhcp"):
        fail("guest_spec_invalid", "ipv4.method 须为 static 或 dhcp", 2)
    allowed = {"method", "address", "prefix", "gateway"}
    if set(ipv4) - allowed:
        fail("guest_spec_invalid", f"ipv4 含未知字段：{sorted(set(ipv4) - allowed)}", 2)
    if method == "dhcp":
        if set(ipv4) - {"method"}:
            fail("guest_spec_invalid", "dhcp 模式不得提供 address/prefix/gateway", 2)
        return {"method": "dhcp"}

    address = ipv4.get("address")
    prefix = ipv4.get("prefix")
    gateway = ipv4.get("gateway")
    if address is None or prefix is None:
        fail("guest_spec_invalid", "static 模式须提供 address 与 prefix", 2)
    if type(prefix) is not int or not 1 <= prefix <= 32:
        fail("guest_spec_invalid", "prefix 须为 1–32 的整数", 2)
    try:
        if ipaddress.ip_address(address).version != 4:
            raise ValueError
    except ValueError:
        fail("guest_spec_invalid", f"address 不是合法 IPv4：{address}", 2)
    if gateway is not None:
        try:
            if ipaddress.ip_address(gateway).version != 4:
                raise ValueError
        except ValueError:
            fail("guest_spec_invalid", f"gateway 不是合法 IPv4：{gateway}", 2)
    return {"method": "static", "address": address, "prefix": prefix,
            "gateway": gateway}
