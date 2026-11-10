.RECIPEPREFIX := >
SYSTEM_TEST ?= ../System-test
CROSS_COMPILE ?= riscv64-linux-gnu-
CC := $(CROSS_COMPILE)gcc
CFLAGS ?= -O1 -g -Wall -Wextra -march=rv64gc
LDFLAGS ?= -static
INC := -Isrc -I$(SYSTEM_TEST)/src -Ibuild/imported/psi -Ibuild/imported/stage0 -Ibuild/imported/stage1 -Ibuild/unified
COMMON := src/app_support.c $(SYSTEM_TEST)/src/st_common.c $(SYSTEM_TEST)/src/st_dual.c
PSI := build/imported/psi/layout.c build/imported/psi/fixed.c
PIR := src/pir_cpu_decompose.c src/pir_cpu_encode.c build/unified/pir_layout.c build/imported/stage0/fixed.c build/imported/stage1/fixed.c
.PHONY: all prepare check check-no-v clean
all: check st08_01_psi_small st08_02_pir_small group_08
prepare:
>python3 scripts/import_packages.py
check:
>python3 scripts/gen_cases.py --check
check-no-v: prepare
>mkdir -p build/no-v
>for f in src/app_support.c src/st08_01_psi_small.c src/st08_02_pir_small.c src/pir_cpu_decompose.c src/pir_cpu_encode.c; do $(CC) $(CFLAGS) $(INC) -c $$f -o build/no-v/$$(basename $$f .c).o || exit $$?; done
>OBJDUMP=$(CROSS_COMPILE)objdump bash $(SYSTEM_TEST)/scripts/check_no_riscv_v.sh build/no-v/*.o
st08_01_psi_small: prepare
>$(CC) $(CFLAGS) $(INC) -DST_STANDALONE $(LDFLAGS) -o $@ src/st08_01_psi_small.c $(COMMON) $(PSI)
st08_02_pir_small: prepare
>$(CC) $(CFLAGS) $(INC) -DST_STANDALONE $(LDFLAGS) -o $@ src/st08_02_pir_small.c $(COMMON) $(PIR)
group_08: prepare
>$(CC) $(CFLAGS) $(INC) $(LDFLAGS) -o $@ src/st_group_08.c src/st08_01_psi_small.c src/st08_02_pir_small.c $(COMMON) $(PSI) $(PIR)
clean:
>rm -f st08_01_psi_small st08_02_pir_small group_08

# Optional host-only semantic recovery; never linked into the board binaries.
HOST_CXX ?= g++
HOST_CC ?= gcc
SEAL_SOURCE ?=
SEAL_BUILD ?=
.PHONY: offline
offline: prepare
>test -f "$(SEAL_SOURCE)/native/src/seal/seal.h" -a -f "$(SEAL_BUILD)/lib/libseal-4.4.a"
>$(HOST_CC) -Isrc -Ibuild/imported/psi -c build/imported/psi/layout.c -o build/psi_layout_host.o
>$(HOST_CC) -Isrc -Ibuild/unified -c build/unified/pir_layout.c -o build/pir_layout_host.o
>$(HOST_CXX) $(SEAL_CPPFLAGS) -std=c++17 -DVERIFY_PSI -Isrc -Ibuild/imported/psi -I$(SEAL_SOURCE)/native/src -I$(SEAL_BUILD)/native/src src/offline_verify.cpp src/psi_client.cpp build/psi_layout_host.o $(SEAL_BUILD)/lib/libseal-4.4.a $(SEAL_LIBS) -pthread -o build/verify_psi
>$(HOST_CXX) $(SEAL_CPPFLAGS) -std=c++17 -Isrc -Ibuild/unified -I$(SEAL_SOURCE)/native/src -I$(SEAL_BUILD)/native/src src/offline_verify.cpp src/pir_client.cpp build/pir_layout_host.o $(SEAL_BUILD)/lib/libseal-4.4.a $(SEAL_LIBS) -pthread -o build/verify_pir
