# Output schema 2.0

The package version is 2.6; the machine-readable schema remains 2.0. Markdown
has one validated standard view with five fixed top-level sections; JSON and
CSV are explicit machine-data exports that retain every field.

JSON reports contain `schema_version`, `sections`, `diagnosis`, and `warnings`.
Every entry inside `sections` has the same shape:

```json
{
  "value": -57,
  "unit": "dBm",
  "availability": "available",
  "source": "airport -I",
  "reason": ""
}
```

Unavailable values use `value: null`, `availability: "unavailable"`, and a
non-empty `reason`. Consumers must not treat unavailable values as zero.

Sections and stable fields:

- `system`: OS, version/build, architecture, timestamp, privilege, Python.
- `adapter`: interface, description/status, MAC, driver/firmware, country and PHY.
- `connection`: SSID/BSSID, state/security, band, channel and width.
- `radio`: RSSI, noise, SNR, percentage/level, same/adjacent-channel counts.
- `link`: Tx/Rx/max rate, MCS, NSS and guard interval.
- `ip`: IPv4/IPv6, subnet, gateway, DNS and DHCP details.
- `local_quality`: gateway target, reachability, latency, jitter and loss.
- `public_quality`: aggregated mainland-China DNS/public reachability, latency,
  jitter, loss and optional throughput. Default targets are AliDNS
  `223.5.5.5`/`223.6.6.6`, Tencent Public DNS `119.29.29.29`, Baidu
  `www.baidu.com`, and Taobao `www.taobao.com`.

`diagnosis` contains the overall score, data confidence, verdict, category
scores, issue identifiers and evidence-based recommendations. CSV exports one
row per field with section, field, value, unit, availability, source and reason.

The standard Markdown keeps both Tx and Rx rate rows. Windows may provide both
association PHY rates. When macOS does not expose a current Rx PHY rate, the Rx
field remains unavailable with a platform-specific reason. Current channel
width is collected from full macOS System Profiler output or Windows `netsh` /
Native Wi-Fi BSS operation information elements; configured adapter maxima are
not reported as current width.
