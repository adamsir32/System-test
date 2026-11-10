# Original System-test style: standalone STs + group runner, static RV64GC.
.DEFAULT_GOAL := all
SYSTEM_TEST ?= ../System-test-main
CROSS_COMPILE ?= riscv64-linux-gnu-
CC := $(CROSS_COMPILE)gcc
CFLAGS ?= -O2 -g -Wall -Wextra -march=rv64gc
LDFLAGS ?= -static
HOST_CC ?= gcc
CXX ?= g++
SEAL_SOURCE ?= $(SYSTEM_TEST)/third_party/inline-asm/third_party/modified-SEAL
SEAL_BUILD ?= $(CURDIR)/build/seal
INC := -Isrc -Ibuild/runtime -Ibuild/imported/psi -Ibuild/imported/stage0 -Ibuild/imported/stage1 -Ibuild/unified
ST_TARGETS := st08_01_psi_small st08_02_pir_small
COMMON := build/app_support.o build/st_common.o build/st_dual.o
PSI := build/psi_layout.o build/psi_fixed.o
PIR := build/pir_cpu_decompose.o build/pir_cpu_encode.o build/pir_layout.o build/stage0_fixed.o build/stage1_fixed.o
ENTRIES := $(addprefix build/,$(addsuffix .o,$(ST_TARGETS)))
MAINS := $(addprefix build/,$(addsuffix _main.o,$(ST_TARGETS)))
OBJECTS := $(COMMON) $(PSI) $(PIR) $(ENTRIES) $(MAINS) build/st_group_08.o
RUNTIME := $(addprefix build/runtime/,st_common.c st_common.h st_dual.c st_insn.h st_ntt_vectors.h)
HEADERS := $(wildcard src/*.h) $(RUNTIME)

.PHONY: all prepare check-no-v offline test clean
all: $(ST_TARGETS) group_08
prepare: build/.imported build/.runtime

build/.imported: $(wildcard packages/*.gz packages/*.txt packages/*.json) scripts/import_packages.py $(wildcard tools/*.py)
	python3 scripts/import_packages.py
	touch $@
build/.runtime: build/.imported tools/prepare_runtime.py $(addprefix $(SYSTEM_TEST)/src/,st_common.c st_common.h st_dual.c st_insn.h st_ntt_vectors.h)
	python3 tools/prepare_runtime.py '$(SYSTEM_TEST)'
	touch $@
$(RUNTIME): build/.runtime
	@test -f $@
$(OBJECTS): $(HEADERS) build/.imported
build/%.o: src/%.c
	$(CC) $(CFLAGS) $(INC) -c $< -o $@
build/%_main.o: src/%.c
	$(CC) $(CFLAGS) $(INC) -DST_STANDALONE -c $< -o $@
build/st_common.o: build/runtime/st_common.c
	$(CC) $(CFLAGS) $(INC) -c $< -o $@
build/st_dual.o: build/runtime/st_dual.c
	$(CC) $(CFLAGS) $(INC) -c $< -o $@
build/psi_layout.o: build/.imported
	$(CC) $(CFLAGS) $(INC) -c build/imported/psi/layout.c -o $@
build/pir_layout.o: build/.imported
	$(CC) $(CFLAGS) $(INC) -c build/unified/pir_layout.c -o $@
build/%_fixed.o: build/.imported
	$(CC) $(CFLAGS) $(INC) -c build/imported/$*/fixed.c -o $@
st08_01_psi_small: build/st08_01_psi_small_main.o $(COMMON) $(PSI)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $^
st08_02_pir_small: build/st08_02_pir_small_main.o $(COMMON) $(PIR)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $^
group_08: build/st_group_08.o $(ENTRIES) $(COMMON) $(PSI) $(PIR)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $^
check-no-v: $(OBJECTS)
	OBJDUMP=$(CROSS_COMPILE)objdump bash '$(SYSTEM_TEST)/scripts/check_no_riscv_v.sh' $(OBJECTS)

offline: build/.imported
	cmake -S '$(SEAL_SOURCE)' -B '$(SEAL_BUILD)' -DCMAKE_BUILD_TYPE=Release -DSEAL_BUILD_DEPS=OFF -DSEAL_USE_MSGSL=OFF -DSEAL_USE_ZLIB=OFF -DSEAL_USE_ZSTD=OFF -DSEAL_USE_INTEL_HEXL=OFF -DBUILD_SHARED_LIBS=OFF -DSEAL_BUILD_EXAMPLES=OFF -DSEAL_BUILD_TESTS=OFF -DSEAL_BUILD_BENCH=OFF
	cmake --build '$(SEAL_BUILD)' --parallel 4
	$(HOST_CC) -Ibuild/imported/psi -c build/imported/psi/layout.c -o build/psi_layout_host.o
	$(HOST_CC) -Isrc -Ibuild/unified -c build/unified/pir_layout.c -o build/pir_layout_host.o
	$(CXX) -std=c++17 -DVERIFY_PSI -Isrc -Ibuild/imported/psi -I$(SEAL_SOURCE)/native/src -I$(SEAL_BUILD)/native/src src/offline_verify.cpp src/psi_client.cpp build/psi_layout_host.o $(SEAL_BUILD)/lib/libseal-4.4.a -pthread -o build/verify_psi
	$(CXX) -std=c++17 -Isrc -Ibuild/unified -I$(SEAL_SOURCE)/native/src -I$(SEAL_BUILD)/native/src src/offline_verify.cpp src/pir_client.cpp build/pir_layout_host.o $(SEAL_BUILD)/lib/libseal-4.4.a -pthread -o build/verify_pir

test: prepare
	python3 -m unittest discover -s tests -v
clean:
	rm -rf build
	rm -f $(ST_TARGETS) group_08
