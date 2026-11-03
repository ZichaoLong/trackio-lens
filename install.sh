#!/bin/sh
set -eu
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
selected_python=${TRACKIO_LENS_PYTHON:-}
if [ -z "$selected_python" ]; then
    previous=
    for argument do
        if [ "$previous" = --python ]; then selected_python=$argument; break; fi
        case "$argument" in --python=*) selected_python=${argument#--python=}; break;; esac
        previous=$argument
    done
fi
if [ -z "$selected_python" ]; then
    for candidate in python3.13 python3.12 python3.11 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3,11))' 2>/dev/null; then
            selected_python=$candidate; break
        fi
    done
fi
if [ -z "$selected_python" ]; then
    echo 'Python 3.11+ is required. Use --python /absolute/stable/python.' >&2
    exit 1
fi
exec "$selected_python" "$source_dir/scripts/install.py" "$@"
