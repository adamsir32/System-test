#!/bin/sh
set -eu
TARGET_HOST=${TARGET_HOST:-192.168.1.100}
TARGET_USER=${TARGET_USER:-root}
TARGET_DIR=${TARGET_DIR:-/root/pir-psi-st}
BINARY=${BINARY:-group_08}
case "$BINARY" in group_08|st08_01_psi_small|st08_02_pir_small) ;; *) echo 'unsupported BINARY' >&2; exit 1;; esac
[ -x "./$BINARY" ] || { echo "build $BINARY first" >&2; exit 1; }
ssh "$TARGET_USER@$TARGET_HOST" "mkdir -p '$TARGET_DIR/build/imported/psi' '$TARGET_DIR/build/imported/stage0' '$TARGET_DIR/build/imported/stage1'"
scp "./$BINARY" "$TARGET_USER@$TARGET_HOST:$TARGET_DIR/"
for stage in psi stage0 stage1; do
    scp "build/imported/$stage/image.u32.bin" "build/imported/$stage/golden.u32.bin" "$TARGET_USER@$TARGET_HOST:$TARGET_DIR/build/imported/$stage/"
done
ssh "$TARGET_USER@$TARGET_HOST" "cd '$TARGET_DIR' && rm -f psi-output-lane*.u32.bin pir-output-lane*.u32.bin && chmod +x './$BINARY' && './$BINARY'"
mkdir -p output
case "$BINARY" in
  group_08) prefixes="psi pir" ;;
  st08_01_psi_small) prefixes="psi" ;;
  st08_02_pir_small) prefixes="pir" ;;
esac
for prefix in $prefixes; do
  for lane in 0 1; do
    scp "$TARGET_USER@$TARGET_HOST:$TARGET_DIR/$prefix-output-lane$lane.u32.bin" "output/"
  done
done
