#include <cstdint>
#include <cstdio>
#include <vector>
#ifdef VERIFY_PSI
#include "layout.h"
extern "C" int psi_verify_intersection(const volatile uint32_t *);
#else
#include "pir_layout.h"
extern "C" int pir_verify_record(const volatile uint32_t *);
#endif
int main(int argc, char **argv) {
    if (argc != 2) { std::fprintf(stderr, "usage: %s output.u32.bin\n", argv[0]); return 2; }
    FILE *f = std::fopen(argv[1], "rb");
    if (!f) { std::perror(argv[1]); return 2; }
    std::vector<uint32_t> memory((size_t)IMAGE_LINES * 64);
    size_t n = std::fread(memory.data(), sizeof(uint32_t), memory.size(), f);
    int extra = std::fgetc(f), error = std::ferror(f); std::fclose(f);
    if (n != memory.size() || extra != EOF || error) { std::fprintf(stderr, "invalid DDR image size\n"); return 2; }
#ifdef VERIFY_PSI
    int rc = psi_verify_intersection(memory.data());
#else
    int rc = pir_verify_record(memory.data());
#endif
    std::printf("offline semantic verification: %s\n", rc ? "FAIL" : "PASS");
    return rc ? 1 : 0;
}
