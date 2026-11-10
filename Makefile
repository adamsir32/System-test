.RECIPEPREFIX := >
SYSTEM_TEST ?= ../System-test
CROSS_COMPILE ?= riscv64-linux-gnu-
CC := $(CROSS_COMPILE)gcc
CFLAGS ?= -O1 -g -Wall -Wextra -march=rv64gc
LDFLAGS ?= -static
HOST_CXX ?= g++
HOST_CC ?= gcc
SEAL_SOURCE ?= $(CURDIR)/build/host-deps/producer/third_party/modified-SEAL
SEAL_BUILD ?= $(CURDIR)/build/host-deps/seal
.PHONY: all prepare check check-no-v st08_01_psi_small st08_02_pir_small group_08 offline test clean
all:
>python3 scripts/build_board.py --runtime '$(SYSTEM_TEST)' --cc '$(CC)' --objdump '$(CROSS_COMPILE)objdump' --cflags='$(CFLAGS)' --ldflags='$(LDFLAGS)'
st08_01_psi_small st08_02_pir_small group_08 check-no-v: all
prepare:
>python3 scripts/import_packages.py
check:
>python3 scripts/gen_cases.py --check
>python3 tools/verify_inputs.py
offline: prepare
>python3 scripts/prepare_offline.py --source '$(SEAL_SOURCE)' --build '$(SEAL_BUILD)'
>test -f "$(SEAL_SOURCE)/native/src/seal/seal.h" -a -f "$(SEAL_BUILD)/lib/libseal-4.4.a"
>$(HOST_CC) -Isrc -Ibuild/imported/psi -c build/imported/psi/layout.c -o build/psi_layout_host.o
>$(HOST_CC) -Isrc -Ibuild/unified -c build/unified/pir_layout.c -o build/pir_layout_host.o
>$(HOST_CXX) $(SEAL_CPPFLAGS) -std=c++17 -DVERIFY_PSI -Isrc -Ipackages/keys -Ibuild/imported/psi -I$(SEAL_SOURCE)/native/src -I$(SEAL_BUILD)/native/src src/offline_verify.cpp src/psi_client.cpp build/psi_layout_host.o $(SEAL_BUILD)/lib/libseal-4.4.a $(SEAL_LIBS) -pthread -o build/verify_psi
>$(HOST_CXX) $(SEAL_CPPFLAGS) -std=c++17 -Isrc -Ipackages/keys -Ibuild/unified -I$(SEAL_SOURCE)/native/src -I$(SEAL_BUILD)/native/src src/offline_verify.cpp src/pir_client.cpp build/pir_layout_host.o $(SEAL_BUILD)/lib/libseal-4.4.a $(SEAL_LIBS) -pthread -o build/verify_pir
>python3 scripts/offline_receipt.py '$(SEAL_SOURCE)' '$(SEAL_BUILD)'
test:
>SYSTEM_TEST='$(SYSTEM_TEST)' python3 -m unittest discover -s tests -v
clean:
>rm -f st08_01_psi_small st08_02_pir_small group_08 build/board-receipt.json build/offline-receipt.json
