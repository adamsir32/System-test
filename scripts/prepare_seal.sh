#!/bin/sh
set -eu
revision=5a0f7898da265a6c92e6f73331a540c8fc8d38a9
source_dir=${SEAL_SOURCE:-}
if [ -z "$source_dir" ]; then
    source_dir="$(pwd)/build/producer/third_party/modified-SEAL"
    if [ ! -f "$source_dir/CMakeLists.txt" ]; then
        mkdir -p build/producer
        curl -fL "https://github.com/adamsir32/inline-asm/archive/$revision.tar.gz" -o build/producer-source.tar.gz
        tar -xzf build/producer-source.tar.gz --strip-components=1 -C build/producer "inline-asm-$revision/third_party/modified-SEAL"
    fi
fi
[ -f "$source_dir/CMakeLists.txt" ] || { echo "SEAL_SOURCE is missing: $source_dir" >&2; exit 1; }
printf '%s\n' "$source_dir" > build/seal-source.txt
cmake -S "$source_dir" -B build/seal-riscv -DCMAKE_SYSTEM_NAME=Linux -DCMAKE_SYSTEM_PROCESSOR=riscv64 \
    -DCMAKE_C_COMPILER="${CROSS_COMPILE:-riscv64-linux-gnu-}gcc" \
    -DCMAKE_CXX_COMPILER="${CROSS_COMPILE:-riscv64-linux-gnu-}g++" \
    -DCMAKE_BUILD_TYPE=Release -DSEAL_BUILD_DEPS=OFF -DSEAL_USE_MSGSL=OFF \
    -DSEAL_USE_ZLIB=OFF -DSEAL_USE_ZSTD=OFF -DSEAL_USE_INTRIN=OFF \
    -DSEAL_BUILD_TESTS=OFF -DSEAL_BUILD_EXAMPLES=OFF
cmake --build build/seal-riscv --parallel "${JOBS:-2}"
