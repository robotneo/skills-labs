#!/bin/sh
# Select once before collection; never rerun failed diagnostics or notifications.
set -u
SCRIPT_DIR=$(CDPATH= cd -- "$(/usr/bin/dirname -- "$0")" && pwd)
ENGINE=${WIFI_HEALTH_ENGINE:-auto}
previous=''
for argument in "$@"; do
  if [ "$previous" = '--engine' ]; then ENGINE=$argument; fi
  case "$argument" in --engine=*) ENGINE=${argument#--engine=} ;; esac
  previous=$argument
done
case "$ENGINE" in auto|python|native|node) ;; *) echo 'Invalid --engine; use auto, python, native, or node.' >&2; exit 2 ;; esac
probe() {
  "$@" >/dev/null 2>&1 & probe_pid=$!
  ( /bin/sleep 2; /bin/kill -TERM "$probe_pid" 2>/dev/null; /bin/sleep 1; /bin/kill -KILL "$probe_pid" 2>/dev/null ) & watchdog=$!
  wait "$probe_pid" 2>/dev/null; result=$?
  /bin/kill "$watchdog" 2>/dev/null || true
  wait "$watchdog" 2>/dev/null || true
  return "$result"
}
python_works() {
  [ -n "$1" ] || return 1
  command -v "$1" >/dev/null 2>&1 || [ -x "$1" ] || return 1
  probe "$1" -c 'import sys, json, ctypes, concurrent.futures; raise SystemExit(0 if sys.version_info >= (3,7) else 3)'
}
if [ "$ENGINE" = auto ] || [ "$ENGINE" = python ]; then
  for candidate in "${WIFI_HEALTH_PYTHON:-}" "${VIRTUAL_ENV:+$VIRTUAL_ENV/bin/python}" "${CONDA_PREFIX:+$CONDA_PREFIX/bin/python}" python3 python /opt/homebrew/bin/python3 /usr/local/bin/python3 "$HOME"/.pyenv/shims/python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3; do
    if python_works "$candidate"; then
      export PYTHONUTF8=1
      exec "$candidate" "$SCRIPT_DIR/main.py" "$@"
    fi
  done
fi
if [ "$ENGINE" = auto ] || [ "$ENGINE" = native ]; then
  if [ -x /usr/bin/osascript ] && probe /usr/bin/osascript -l JavaScript -e 'ObjC.import("Foundation"); $.NSTask.alloc.init; JSON.stringify({ok:true});'; then
    exec /usr/bin/osascript -l JavaScript "$SCRIPT_DIR/portable/macos.js" "$@"
  fi
fi
if [ "$ENGINE" = auto ] || [ "$ENGINE" = node ]; then
  for candidate in "${WIFI_HEALTH_NODE:-}" node /opt/homebrew/bin/node /usr/local/bin/node; do
    [ -n "$candidate" ] || continue
    if command -v "$candidate" >/dev/null 2>&1 || [ -x "$candidate" ]; then
      if probe "$candidate" -e 'if(Number(process.versions.node.split(".")[0])<16)process.exit(3);require("child_process");require("fs");'; then
        exec "$candidate" "$SCRIPT_DIR/portable/node.cjs" "$@"
      fi
    fi
  done
fi
echo "Wi-Fi Health Detector cannot start: no usable $ENGINE engine (Python 3.7+, macOS native JXA, or Node.js 16+)." >&2
echo 'This is a runtime/capability problem, not a Wi-Fi disconnected diagnosis. Set WIFI_HEALTH_PYTHON or WIFI_HEALTH_NODE to an executable path.' >&2
exit 3
