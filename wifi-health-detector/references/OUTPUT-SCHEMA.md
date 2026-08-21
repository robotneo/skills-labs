# Output schema 2.0

The package version is 2.1; the machine-readable schema remains 2.0 because
the dashboard and `--view full|summary` only change Markdown presentation.
JSON and CSV always retain every field regardless of the selected view.

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
- `public_quality`: DNS/public reachability, latency, jitter, loss and optional throughput.

`diagnosis` contains the overall score, data confidence, verdict, category
scores, issue identifiers and evidence-based recommendations. CSV exports one
row per field with section, field, value, unit, availability, source and reason.
