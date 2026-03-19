import yaml

def select_host():
    with open("assets/hosts.yaml") as f:
        hosts = yaml.safe_load(f)

    # 按评分选择宿主机
    hosts = sorted(
        hosts,
        key=lambda h: h["cpu_free"] * 0.5 + h["mem_free"] * 0.4,
        reverse=True
    )

    return hosts[0]["name"]