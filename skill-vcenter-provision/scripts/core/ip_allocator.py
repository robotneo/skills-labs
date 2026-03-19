import yaml
from scripts.integrations.ping import ping_check

def allocate_ip():
    with open("assets/ip_pool.yaml") as f:
        ip_pool = yaml.safe_load(f)

    for item in ip_pool:
        ip = item["address"]
        status = item["status"]

        is_alive = ping_check(ip)

        # 未使用 + 不通 = 可用
        if status == "unused" and not is_alive:
            return ip

    raise Exception("IP 池中无可用的 IP 地址")