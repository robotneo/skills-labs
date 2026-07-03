from scripts.ip_pool import parse_pool_spec, IPPool, reserve_ip, release_ip, cleanup_expired

def test_parse_cidr():
    ips = parse_pool_spec("10.0.0.0/29")
    assert len(ips) == 6  # /29 有 6 个可用主机
    assert "10.0.0.1" in ips

def test_parse_range():
    ips = parse_pool_spec("10.0.0.10-10.0.0.13")
    assert ips == ["10.0.0.10","10.0.0.11","10.0.0.12","10.0.0.13"]

def test_parse_combined():
    ips = parse_pool_spec("10.0.0.5,10.1.0.0/30")
    assert "10.0.0.5" in ips
    assert "10.1.0.1" in ips

def test_reserve_and_release():
    ip = "10.99.99.250"
    reserve_ip(ip, "tmp-vm")
    pool = IPPool("10.99.99.250", skip_alive=False)
    assert ip not in pool.available()
    release_ip(ip)
    assert ip in pool.available()
