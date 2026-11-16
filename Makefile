# Original System-test style: standalone STs + group runner, static RV64GC.
.DEFAULT_GOAL := all
SYSTEM_TEST ?= ../System-test-main
CROSS_COMPILE ?= riscv64-linux-gnu-
CC := $(CROSS_COMPILE)gcc
CFLAGS ?= -O2 -g -Wall -Wextra -march=rv64gc
LDFLAGS ?= -static
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

MED_OBJECTS := build/psi_medium_layout.o build/psi-medium_fixed.o build/stage0-medium_fixed.o build/stage1-medium_fixed.o build/pir_medium_layout.o build/pir_medium_decompose.o build/pir_medium_encode.o build/st08_03_psi_medium.o build/st08_04_pir_medium.o build/st08_03_psi_medium_main.o build/st08_04_pir_medium_main.o build/st_group_08_medium.o
.PHONY: all prepare check-no-v test clean
all: $(ST_TARGETS) group_08 st08_03_psi_medium st08_04_pir_medium group_08_medium
prepare: build/.imported build/.runtime

build/.imported: $(wildcard packages/*.gz packages/*.txt packages/*.json) scripts/import_packages.py scripts/import_medium.py $(wildcard tools/*.py)
	python3 scripts/import_packages.py
	python3 scripts/import_medium.py
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
check-no-v: $(OBJECTS) $(MED_OBJECTS)
	OBJDUMP=$(CROSS_COMPILE)objdump bash '$(SYSTEM_TEST)/scripts/check_no_riscv_v.sh' $(OBJECTS) $(MED_OBJECTS)

test: all
	python3 -m unittest discover -s tests -v
clean:
	rm -rf build
	rm -f $(ST_TARGETS) group_08 st08_03_psi_medium st08_04_pir_medium group_08_medium

# Medium uses package-derived counts and its own CPU objects; Small remains unchanged.
MED_INC := -Ibuild/imported/psi-medium -Ibuild/imported/stage0-medium -Ibuild/imported/stage1-medium -Ibuild/medium-unified $(INC)
MED_CFG := -include build/medium-unified/pir_config.h -Dpir_cpu_decompose=pir_medium_cpu_decompose -Dpir_cpu_encode=pir_medium_cpu_encode -Dpir_cpu_encoder_init=pir_medium_cpu_encoder_init
$(MED_OBJECTS): $(HEADERS) build/.imported
build/psi_medium_layout.o: build/.imported
	$(CC) $(CFLAGS) $(MED_INC) -c build/imported/psi-medium/layout.c -o $@
build/pir_medium_layout.o: build/.imported
	$(CC) $(CFLAGS) $(MED_INC) $(MED_CFG) -c build/medium-unified/pir_layout.c -o $@
build/pir_medium_decompose.o: src/pir_cpu_decompose.c
	$(CC) $(CFLAGS) $(MED_INC) $(MED_CFG) -c $< -o $@
build/pir_medium_encode.o: src/pir_cpu_encode.c
	$(CC) $(CFLAGS) $(MED_INC) $(MED_CFG) -c $< -o $@
build/st08_03_psi_medium.o: src/st08_03_psi_medium.c
	$(CC) $(CFLAGS) $(MED_INC) -c $< -o $@
build/st08_03_psi_medium_main.o: src/st08_03_psi_medium.c
	$(CC) $(CFLAGS) $(MED_INC) -DST_STANDALONE -c $< -o $@
build/st08_04_pir_medium.o: src/st08_04_pir_medium.c
	$(CC) $(CFLAGS) $(MED_INC) $(MED_CFG) -c $< -o $@
build/st08_04_pir_medium_main.o: src/st08_04_pir_medium.c
	$(CC) $(CFLAGS) $(MED_INC) $(MED_CFG) -DST_STANDALONE -c $< -o $@
MED_PSI := build/psi_medium_layout.o build/psi-medium_fixed.o
MED_PIR := build/pir_medium_layout.o build/pir_medium_decompose.o build/pir_medium_encode.o build/stage0-medium_fixed.o build/stage1-medium_fixed.o
st08_03_psi_medium: build/st08_03_psi_medium_main.o $(COMMON) $(MED_PSI)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $^
st08_04_pir_medium: build/st08_04_pir_medium_main.o $(COMMON) $(MED_PIR)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $^
group_08_medium: build/st_group_08_medium.o build/st08_03_psi_medium.o build/st08_04_pir_medium.o $(COMMON) $(MED_PSI) $(MED_PIR)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $^
