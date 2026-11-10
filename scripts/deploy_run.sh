#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
: "${TARGET_HOST:?Set TARGET_HOST to the actual HPU board}"
: "${ROUTING_FILE:?Set ROUTING_FILE to confirmed board routing evidence JSON}"
exec python3 scripts/acceptance.py --host "$TARGET_HOST" --user "${TARGET_USER:-root}" --port "${TARGET_PORT:-22}" --target-dir "${TARGET_DIR:-/root/pir-psi-st}" --binary "${BINARY:-group_08}" --routing "$ROUTING_FILE"
