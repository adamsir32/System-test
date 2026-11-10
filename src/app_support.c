#include "app_support.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static int read_exact(const char *path, void *dest, size_t bytes) {
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); return ST_ERR_ARG; }
    size_t n = fread(dest, 1, bytes, f);
    int extra = fgetc(f); int err = ferror(f); fclose(f);
    if (n != bytes || extra != EOF || err) { fprintf(stderr, "[HPU][FAIL] bad file %s\n", path); return ST_ERR_ARG; }
    return ST_OK;
}
int app_prepare(const char *image, unsigned image_lines, unsigned window_lines) {
    size_t bytes = (size_t)image_lines * ST_LINE_BYTES;
    volatile uint32_t *mapped = st_map_phys(st_mem_base(), bytes);
    if (!mapped) return ST_ERR_MAP;
    g_mem = mapped;
    int rc = read_exact(image, (void *)g_mem, bytes);
    if (rc) return rc;
    st_cache_clean((void *)g_mem, bytes);
    uint64_t base = st_mem_base();
    return st_config_window(window_lines, (uint32_t)base, (uint32_t)(base >> 32));
}
int app_run(int (*entry)(void)) {
    int rc = st_dual_issue_barrier();
    if (rc) return rc;
    if (entry() != 0) return ST_ERR_NOT_SUPPORTED;
    rc = st_wait_irq();
    if (!rc) rc = st_completion_clear();
    if (!rc) rc = st_check_status();
    return rc;
}
int app_check(const char *golden, const void *out, unsigned count, unsigned image_lines) {
    const unsigned char *spans = out;
    struct app_span span;
    size_t words = 0;
    for (unsigned i = 0; i < count; ++i) {
        memcpy(&span, spans + i * sizeof(span), sizeof(span));
        if ((size_t)span.line * ST_WORDS_PER_LINE + span.words > (size_t)image_lines * ST_WORDS_PER_LINE) return ST_ERR_ARG;
        size_t end = (size_t)span.golden_word + span.words;
        if (end > words) words = end;
    }
    uint32_t *expected = malloc(words * sizeof(*expected));
    if (!expected) return ST_ERR_ARG;
    int rc = read_exact(golden, expected, words * sizeof(*expected));
    st_cache_invalidate((void *)g_mem, (size_t)image_lines * ST_LINE_BYTES);
    for (unsigned i = 0; !rc && i < count; ++i) {
      memcpy(&span, spans + i * sizeof(span), sizeof(span));
      for (unsigned j = 0; j < span.words; ++j) {
        uint32_t actual = g_mem[(size_t)span.line * ST_WORDS_PER_LINE + j];
        uint32_t want = expected[span.golden_word + j];
        if (actual != want || actual >= span.modulus) {
            fprintf(stderr, "[HPU][FAIL] output=%u word=%u actual=%u golden=%u\n", i, j, actual, want);
            rc = ST_ERR_COMPARE; break;
        }
    }
    }
    free(expected); return rc;
}
int app_export(const char *name, unsigned image_lines) {
    char path[128]; snprintf(path, sizeof(path), "%s-lane%u.u32.bin", name, st_lane);
    FILE *f = fopen(path, "wb"); if (!f) { perror(path); return ST_ERR_ARG; }
    size_t bytes = (size_t)image_lines * ST_LINE_BYTES;
    st_cache_invalidate((void *)g_mem, bytes);
    size_t n = fwrite((const void *)g_mem, 1, bytes, f); int rc = fclose(f);
    return n == bytes && !rc ? ST_OK : ST_ERR_ARG;
}
