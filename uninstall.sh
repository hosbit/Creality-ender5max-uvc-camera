#!/bin/sh
set -eu
BASE=$(CDPATH= cd "$(dirname "$0")" && pwd)
exec /bin/sh "$BASE/install.sh" uninstall "$@"
