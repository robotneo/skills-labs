from core.ip_allocator import allocate_ip
from core.host_scheduler import select_host

def plan_provision(args):
    return {
        "hostname": args["hostname"],
        "cpu": args.get("cpu", 4),
        "memory": args.get("memory", 8),
        "disk": args.get("disk", 100),
        "os": args.get("os", "ubuntu"),
        "ip": allocate_ip(),
        "host": args.get("host") or select_host()
    }