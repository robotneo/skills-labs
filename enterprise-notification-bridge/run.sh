#!/bin/sh
set -u
set -f

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON_BIN=""
PYTHON_ERROR=""

python_works() {
  candidate=$1
  [ -n "$candidate" ] || return 1
  [ -x "$candidate" ] || command -v "$candidate" >/dev/null 2>&1 || return 1
  version_output=$("$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 7) else 3)' 2>&1)
  status=$?
  if [ "$status" -eq 0 ]; then
    PYTHON_BIN=$candidate
    return 0
  fi
  PYTHON_ERROR="Python candidate failed ($candidate): $version_output"
  return 1
}

if [ -n "${ENTERPRISE_NOTIFICATION_BRIDGE_PYTHON:-}" ]; then
  python_works "$ENTERPRISE_NOTIFICATION_BRIDGE_PYTHON" || true
fi

if [ -z "$PYTHON_BIN" ] && [ -n "${WIFI_HEALTH_PYTHON:-}" ]; then
  python_works "$WIFI_HEALTH_PYTHON" || true
fi

if [ -z "$PYTHON_BIN" ]; then
  for candidate in \
    /opt/homebrew/bin/python3 \
    /usr/local/bin/python3 \
    /usr/bin/python3 \
    python3
  do
    python_works "$candidate" && break
  done
fi

if [ -z "$PYTHON_BIN" ]; then
  echo "Enterprise Notification Bridge cannot start: a working Python 3.7+ runtime was not found." >&2
  if [ -n "$PYTHON_ERROR" ]; then echo "$PYTHON_ERROR" >&2; fi
  exit 3
fi

PYTHONUTF8=1
export PYTHONUTF8
exec "$PYTHON_BIN" "$SCRIPT_DIR/main.py" "$@"
