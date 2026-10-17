#!/bin/sh
set -eu
BASE=$(CDPATH= cd "$(dirname "$0")" && pwd)
PY=/usr/share/klippy-env/bin/python
if [ ! -x "$PY" ]; then
    printf '%s\n' "Missing printer Python: $PY" >&2
    exit 1
fi
exec "$PY" "$BASE/tools/manage.py" "$@"
