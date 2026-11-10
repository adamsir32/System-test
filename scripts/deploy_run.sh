#!/bin/sh
# Adapted from original System-test SSH/SCP deployment for file-based packages.
set -eu
cd "$(dirname "$0")/.."
: "${TARGET_HOST:?Set TARGET_HOST to the real HPU board}"
TARGET_USER=${TARGET_USER:-root}
TARGET_PORT=${TARGET_PORT:-22}
TARGET_DIR=${TARGET_DIR:-/root/pir-psi-st}
BINARY=${BINARY:-group_08}
ST_DUAL_TIMEOUT_MS=${ST_DUAL_TIMEOUT_MS:-300000}
ST_HPU_TIMEOUT_MS=${ST_HPU_TIMEOUT_MS:-120000}
RUN_TIMEOUT=${RUN_TIMEOUT:-900}
ST_CPU0=${ST_CPU0:-0}
ST_CPU1=${ST_CPU1:-1}
case "$BINARY" in group_08|st08_01_psi_small|st08_02_pir_small) ;; *) echo 'invalid BINARY' >&2; exit 2;; esac
case "$TARGET_DIR" in /*) ;; *) echo 'TARGET_DIR must be absolute' >&2; exit 2;; esac
case "$TARGET_DIR" in *[!a-zA-Z0-9_./-]*|*/../*) echo 'invalid TARGET_DIR' >&2; exit 2;; esac
for n in "$TARGET_PORT" "$ST_DUAL_TIMEOUT_MS" "$ST_HPU_TIMEOUT_MS" "$RUN_TIMEOUT" "$ST_CPU0" "$ST_CPU1"; do
    case "$n" in ''|*[!0-9]*) echo 'invalid numeric option' >&2; exit 2;; esac
done
[ "$RUN_TIMEOUT" -gt 0 ] || exit 2
[ -x "./$BINARY" ] || { echo 'build the ST first' >&2; exit 2; }
mkdir -p output
run=$(mktemp -d output/run-XXXXXXXX)
remote="$TARGET_DIR/$(basename "$run")"
target="$TARGET_USER@$TARGET_HOST"
# Connection establishment, lost connections and whole SSH commands are bounded.
opts='-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=10 -o ServerAliveCountMax=3'
tar -czf "$run/input.tar.gz" "$BINARY" build/imported/*/*.bin
printf 'Results: %s\n' "$run"
timeout -k 5 60 ssh $opts -p "$TARGET_PORT" "$target" "mkdir -p '$TARGET_DIR' && mkdir '$remote' && mkdir '$remote/results'"
timeout -k 5 180 scp $opts -P "$TARGET_PORT" "$run/input.tar.gz" "$target:$remote/input.tar.gz"
set +e
timeout -k 5 "$((RUN_TIMEOUT + 60))" ssh $opts -p "$TARGET_PORT" "$target" \
    "cd '$remote' || exit 2; tar -xzf input.tar.gz && chmod +x '$BINARY'; prep=\$?; \
     if [ \$prep -eq 0 ]; then \
       timeout -k 5 '$RUN_TIMEOUT' env ST_OUTPUT_DIR=results \
       ST_DUAL_TIMEOUT_MS='$ST_DUAL_TIMEOUT_MS' ST_HPU_TIMEOUT_MS='$ST_HPU_TIMEOUT_MS' \
       ST_CPU0='$ST_CPU0' ST_CPU1='$ST_CPU1' './$BINARY' >results/board.log 2>&1; rc=\$?; \
     else rc=\$prep; fi; printf '%s\\n' \"\$rc\" >results/board.exit; exit \$rc" \
    >"$run/transport.log" 2>&1
remote_rc=$?
# Always collect available stage0/other snapshots after execution failure/timeout.
timeout -k 5 180 scp $opts -P "$TARGET_PORT" -r "$target:$remote/results" "$run/" >>"$run/transport.log" 2>&1
copy_rc=$?
set -e
[ ! -f "$run/results/board.log" ] || cat "$run/results/board.log"
if [ "$remote_rc" -ne 0 ] || [ "$copy_rc" -ne 0 ]; then
    echo "[ACCEPT][FAIL] execute=$remote_rc collect=$copy_rc; diagnostics in $run" >&2
    exit 1
fi
python3 scripts/verify_results.py "$run/results" --binary "$BINARY" >"$run/verification.log" 2>&1 || {
    cat "$run/verification.log"; exit 1;
}
cat "$run/verification.log"
