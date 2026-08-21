#!/bin/sh
set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

python_works() {
  candidate=$1
  [ -n "$candidate" ] || return 1
  [ -x "$candidate" ] || command -v "$candidate" >/dev/null 2>&1 || return 1
  version_output=$($candidate -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 7) else 3)' 2>&1)
  status=$?
  if [ "$status" -eq 0 ]; then
    PYTHON_BIN=$candidate
    return 0
  fi
  case "$version_output" in
    *xcrun*|*"developer path"*) PYTHON_ERROR="Apple Command Line Tools Python proxy is broken: $version_output" ;;
    *) PYTHON_ERROR="Python candidate failed ($candidate): $version_output" ;;
  esac
  return 1
}

PYTHON_BIN=""
PYTHON_ERROR=""

if [ -n "${WIFI_HEALTH_PYTHON:-}" ]; then
  python_works "$WIFI_HEALTH_PYTHON" || true
fi

if [ -z "$PYTHON_BIN" ]; then
  for candidate in \
    /opt/homebrew/bin/python3 \
    /usr/local/bin/python3 \
    "$HOME/Library/Python/3.12/bin/python3" \
    "$HOME/Library/Python/3.11/bin/python3" \
    "$HOME/Library/Python/3.10/bin/python3" \
    "$HOME/Library/Python/3.9/bin/python3" \
    "$HOME/Library/Python/3.8/bin/python3" \
    python3
  do
    python_works "$candidate" && break
  done
fi

if [ -z "$PYTHON_BIN" ]; then
  echo "Wi-Fi Health Detector cannot start: a working Python 3.7+ runtime was not found." >&2
  if [ -n "$PYTHON_ERROR" ]; then echo "$PYTHON_ERROR" >&2; fi
  echo "Install Python from python.org or Homebrew, then rerun this script." >&2
  echo "This is a Python runtime problem, not a Wi-Fi disconnected diagnosis." >&2
  exit 3
fi

exec "$PYTHON_BIN" "$SCRIPT_DIR/main.py" "$@"
