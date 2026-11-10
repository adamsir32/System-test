.RECIPEPREFIX := >
SYSTEM_TEST ?= ../System-test
CROSS_COMPILE ?= riscv64-linux-gnu-
CC := $(CROSS_COMPILE)gcc
CXX := $(CROSS_COMPILE)g++
CFLAGS ?= -O1 -g -Wall -Wextra -march=rv64gc
LDFLAGS ?= -static
INC := -Isrc -I$(SYSTEM_TEST)/src -Ibuild/imported/psi -Ibuild/imported/stage0 -Ibuild/imported/stage1 -Ibuild/unified
COMMON := src/app_support.c $(SYSTEM_TEST)/src/st_common.c $(SYSTEM_TEST)/src/st_dual.c
PSI := build/imported/psi/layout.c build/imported/psi/fixed.c build/psi_client.o
PIR := src/pir_cpu_decompose.c src/pir_cpu_encode.c build/unified/pir_layout.c build/imported/stage0/fixed.c build/imported/stage1/fixed.c build/pir_client.o
SEAL_LIB := build/seal-riscv/lib/libseal-4.4.a
.PHONY: all prepare seal clients check check-reference check-no-v clean
all: check check-reference st08_01_psi_small st08_02_pir_small group_08
prepare:
>python3 scripts/import_packages.py
seal:
>CROSS_COMPILE=$(CROSS_COMPILE) SEAL_SOURCE="$(SEAL_SOURCE)" ./scripts/prepare_seal.sh
check:
>python3 scripts/gen_cases.py --check
check-reference:
>$(MAKE) -C $(SYSTEM_TEST) check-it-cases
check-no-v: clients
>mkdir -p build/no-v
>for f in src/app_support.c src/st08_01_psi_small.c src/st08_02_pir_small.c src/pir_cpu_decompose.c src/pir_cpu_encode.c; do $(CC) $(CFLAGS) $(INC) -c $$f -o build/no-v/$$(basename $$f .c).o || exit $$?; done
>OBJDUMP=$(CROSS_COMPILE)objdump bash $(SYSTEM_TEST)/scripts/check_no_riscv_v.sh build/no-v/*.o build/psi_client.o build/pir_client.o
clients: prepare seal
>$(CXX) -std=c++17 $(CFLAGS) $(INC) -I"$$(cat build/seal-source.txt)/native/src" -Ibuild/seal-riscv/native/src -c src/psi_client.cpp -o build/psi_client.o
>$(CXX) -std=c++17 $(CFLAGS) $(INC) -I"$$(cat build/seal-source.txt)/native/src" -Ibuild/seal-riscv/native/src -c src/pir_client.cpp -o build/pir_client.o
st08_01_psi_small: clients
>$(CC) $(CFLAGS) $(INC) -DST_STANDALONE $(LDFLAGS) -o $@ src/st08_01_psi_small.c $(COMMON) $(PSI) $(SEAL_LIB) -lstdc++ -lm -pthread
st08_02_pir_small: clients
>$(CC) $(CFLAGS) $(INC) -DST_STANDALONE $(LDFLAGS) -o $@ src/st08_02_pir_small.c $(COMMON) $(PIR) $(SEAL_LIB) -lstdc++ -lm -pthread
group_08: clients
>$(CC) $(CFLAGS) $(INC) $(LDFLAGS) -o $@ src/st_group_08.c src/st08_01_psi_small.c src/st08_02_pir_small.c $(COMMON) $(PSI) $(PIR) $(SEAL_LIB) -lstdc++ -lm -pthread
clean:
>rm -f st08_01_psi_small st08_02_pir_small group_08
