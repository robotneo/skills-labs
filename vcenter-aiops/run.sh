#!/bin/sh
set -eu
skill_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
runtime=${VCENTER_AIOPS_PYTHON:-python3}
"$runtime" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 2)' || {
  echo 'vCenter AIops requires Python 3.10+' >&2
  exit 3
}
export PYTHONPATH="$skill_root/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$runtime" -m vcenter_aiops "$@"
