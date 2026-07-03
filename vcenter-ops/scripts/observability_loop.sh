#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

mkdir -p logs reports
TS="$(date '+%Y-%m-%d %H:%M:%S %z')"
DAY="$(date '+%F')"

{
  echo "[$TS] observability loop start"

  echo "[$TS] collect metrics"
  python3 scripts/handler.py --action metrics --metrics-action collect

  echo "[$TS] healthcheck"
  python3 scripts/healthcheck.py > reports/healthcheck-latest.md

  echo "[$TS] anomaly detection"
  python3 scripts/handler.py --action anomaly --metric-days 7 > reports/anomaly-latest.json

  echo "[$TS] capacity forecast"
  python3 scripts/handler.py --action forecast --metric-days 60 --forecast-threshold 0.9 > reports/forecast-latest.json

  echo "[$TS] observability loop success"
} >> "logs/observability_loop-${DAY}.log" 2>&1
