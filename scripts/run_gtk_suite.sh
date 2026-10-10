#!/usr/bin/env bash
# Real GTK windows in an isolated display, with critical warnings treated as errors.
set -euo pipefail
canellia_repo=$(cd -- "$(dirname -- "$0")/.." && pwd)
if command -v xvfb-run >/dev/null 2>&1; then
    exec xvfb-run -a env NO_AT_BRIDGE=1 PYTHONFAULTHANDLER=1 CANELLIA_REAL_WINDOWS=1 G_DEBUG=fatal-criticals python3 "$canellia_repo/tests/gtk_menu_editor_smoke.py"
fi
if ! command -v Xephyr >/dev/null 2>&1; then
    echo 'Install Xvfb or Xephyr to run strict GTK integration tests.' >&2
    exit 1
fi
canellia_display=''
for canellia_number in {90..150}; do
    if [[ ! -e /tmp/.X11-unix/X$canellia_number && ! -e /tmp/.X$canellia_number-lock ]]; then
        canellia_display=:$canellia_number
        break
    fi
done
[[ -n $canellia_display ]] || { echo 'No free nested X display.' >&2; exit 1; }
canellia_log=$(mktemp)
Xephyr "$canellia_display" -screen 1280x900 -ac -br -no-host-grab >"$canellia_log" 2>&1 &
canellia_display_pid=$!
trap 'kill "$canellia_display_pid" 2>/dev/null || true; rm -f "$canellia_log"' EXIT
for canellia_attempt in {1..50}; do
    if [[ -S /tmp/.X11-unix/X${canellia_display#:} ]]; then
        DISPLAY="$canellia_display" env NO_AT_BRIDGE=1 PYTHONFAULTHANDLER=1 CANELLIA_REAL_WINDOWS=1 G_DEBUG=fatal-criticals python3 "$canellia_repo/tests/gtk_menu_editor_smoke.py"
        exit 0
    fi
    if ! kill -0 "$canellia_display_pid" 2>/dev/null; then
        cat "$canellia_log" >&2
        exit 1
    fi
    sleep 0.1
done
echo 'Nested X server did not become ready.' >&2
exit 1
