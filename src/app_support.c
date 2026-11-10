#define _GNU_SOURCE
#include "app_support.h"
#include "build_identity.h"
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <sched.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static uint32_t *snapshot;
static uint8_t *hpu_writable;
static unsigned mapped_lines;
static int completed;

static int read_exact(const char *path, void *dest, size_t bytes) {
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); return ST_ERR_ARG; }
    size_t n = fread(dest, 1, bytes, f);
    int extra = fgetc(f), err = ferror(f); fclose(f);
    if (n != bytes || extra != EOF || err) {
        fprintf(stderr, "[HPU][FAIL] bad file %s\n", path); return ST_ERR_ARG;
    }
    return ST_OK;
}
static int identifier(const char *s) {
    if (!s || !*s || strlen(s) > 96) return 0;
    for (; *s; ++s) if (!isalnum((unsigned char)*s) && *s != '-' && *s != '_') return 0;
    return 1;
}
static int env_number(const char *name, unsigned long *value) {
    const char *s = getenv(name); char *end;
    if (!s || !isdigit((unsigned char)*s)) return -1;
    errno = 0; *value = strtoul(s, &end, 10);
    return errno || *end ? -1 : 0;
}
int app_bind_lane(void) {
    char key[40], path[160]; unsigned long cpu, hart;
    const char *evidence = getenv("ST_ROUTE_EVIDENCE_SHA256");
    if (!identifier(getenv("ST_RUN_ID")) || !getenv("ST_RUN_DIR") ||
        !evidence || strlen(evidence) != 64 || st_lane >= 2) return ST_ERR_ARG;
    for (unsigned i = 0; i < 64; ++i) if (!isxdigit((unsigned char)evidence[i])) return ST_ERR_ARG;
    snprintf(key, sizeof(key), "ST_CPU_LANE%u", st_lane);
    if (env_number(key, &cpu) || cpu >= CPU_SETSIZE) return ST_ERR_ARG;
    snprintf(key, sizeof(key), "ST_HART_LANE%u", st_lane);
    if (env_number(key, &hart)) return ST_ERR_ARG;
    cpu_set_t set; CPU_ZERO(&set); CPU_SET(cpu, &set);
    if (sched_setaffinity(0, sizeof(set), &set) || sched_getcpu() != (int)cpu) {
        perror("lane CPU affinity"); return ST_ERR_ARG;
    }
    snprintf(path, sizeof(path), "/sys/devices/system/cpu/cpu%lu/of_node/reg", cpu);
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); return ST_ERR_ARG; }
    unsigned char bytes[9]; size_t count = fread(bytes, 1, sizeof(bytes), f);
    int err = ferror(f); fclose(f);
    if (err || (count != 4 && count != 8)) return ST_ERR_ARG;
    uint64_t observed = 0;
    for (size_t i = 0; i < count; ++i) observed = (observed << 8) | bytes[i];
    if (observed != hart) return ST_ERR_ARG;
    printf("[ROUTE] lane=%u cpu=%lu hart=%lu csr=0x%llx ddr=0x%llx evidence=%s\n",
           st_lane, cpu, hart, (unsigned long long)st_csr_base(),
           (unsigned long long)st_mem_base(), evidence);
    return ST_OK;
}
int app_prepare(const char *stage, unsigned image_lines, unsigned window_lines) {
    char path[160];
    completed = 0; mapped_lines = 0;
    free(snapshot); snapshot = NULL; free(hpu_writable); hpu_writable = NULL;
    if (!identifier(stage) || !window_lines || image_lines != window_lines + 64U ||
        (uint64_t)image_lines * ST_LINE_BYTES >= ST_DUAL_DDR_STRIDE) return ST_ERR_ARG;
    size_t bytes = (size_t)image_lines * ST_LINE_BYTES;
    snapshot = malloc(bytes); hpu_writable = malloc(image_lines);
    if (!snapshot || !hpu_writable) return ST_ERR_ARG;
    snprintf(path, sizeof(path), "build/imported/%s/image.u32.bin", stage);
    int rc = read_exact(path, snapshot, bytes);
    snprintf(path, sizeof(path), "build/imported/%s/writable.u8.bin", stage);
    if (!rc) rc = read_exact(path, hpu_writable, image_lines);
    if (rc) return rc;
    for (unsigned i = 0; i < image_lines; ++i)
        if (hpu_writable[i] > 1 || (i >= window_lines && hpu_writable[i])) return ST_ERR_ARG;
    volatile uint32_t *mapped = st_map_phys(st_mem_base(), bytes);
    if (!mapped) return ST_ERR_MAP;
    g_mem = mapped; mapped_lines = image_lines;
    memcpy((void *)g_mem, snapshot, bytes);
    st_cache_clean((void *)g_mem, bytes);
    uint64_t base = st_mem_base();
    return st_config_window(window_lines, (uint32_t)base, (uint32_t)(base >> 32));
}
/* CPU may change only declared inputs; those become read-only to HPU afterwards. */
int app_accept_cpu_inputs(const char *path) {
    uint8_t *mask = malloc(mapped_lines);
    if (!mapped_lines || !mask) { free(mask); return ST_ERR_ARG; }
    int rc = read_exact(path, mask, mapped_lines);
    for (unsigned line = 0; !rc && line < mapped_lines; ++line) {
        if (mask[line] > 1 || (mask[line] && hpu_writable[line])) { rc = ST_ERR_ARG; break; }
        for (unsigned j = 0; j < ST_WORDS_PER_LINE; ++j) {
            size_t word = (size_t)line * ST_WORDS_PER_LINE + j;
            if (!mask[line] && g_mem[word] != snapshot[word]) {
                fprintf(stderr, "[HPU][FAIL] CPU wrote fixed region line=%u word=%u\n", line, j);
                rc = ST_ERR_COMPARE; break;
            }
        }
    }
    if (!rc) for (unsigned line = 0; line < mapped_lines; ++line)
        if (mask[line]) for (unsigned j = 0; j < ST_WORDS_PER_LINE; ++j) {
            size_t word = (size_t)line * ST_WORDS_PER_LINE + j;
            snapshot[word] = g_mem[word];
        }
    free(mask); return rc;
}
int app_run(int (*entry)(void)) {
    int rc = st_dual_issue_barrier();
    if (rc) return rc;
    if (entry() != 0) return ST_ERR_NOT_SUPPORTED;
    rc = st_wait_irq();
    if (!rc) rc = st_completion_clear();
    if (!rc) rc = st_check_status();
    completed = rc == ST_OK;
    return rc;
}
int app_check_memory(void) {
    if (!mapped_lines || !snapshot || !hpu_writable) return ST_ERR_ARG;
    st_cache_invalidate((void *)g_mem, (size_t)mapped_lines * ST_LINE_BYTES);
    for (unsigned line = 0; line < mapped_lines; ++line) {
        if (hpu_writable[line]) continue;
        for (unsigned j = 0; j < ST_WORDS_PER_LINE; ++j) {
            size_t word = (size_t)line * ST_WORDS_PER_LINE + j;
            if (g_mem[word] != snapshot[word]) {
                fprintf(stderr, "[HPU][FAIL] readonly-or-guard line=%u word=%u actual=%u expected=%u\n",
                        line, j, g_mem[word], snapshot[word]); return ST_ERR_COMPARE;
            }
        }
    }
    return ST_OK;
}
int app_check(const char *golden, const void *out, unsigned count, unsigned image_lines) {
    const unsigned char *spans = out;
    struct app_span span; size_t words = 0;
    if (!out || !count || image_lines != mapped_lines) return ST_ERR_ARG;
    for (unsigned i = 0; i < count; ++i) {
        memcpy(&span, spans + i * sizeof(span), sizeof(span));
        if (!span.words || !span.modulus || (size_t)span.line * ST_WORDS_PER_LINE + span.words >
            (size_t)image_lines * ST_WORDS_PER_LINE) return ST_ERR_ARG;
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
    free(expected);
    int memory_rc = app_check_memory();
    return rc ? rc : memory_rc;
}
/* Incomplete snapshots are diagnostic only. O_EXCL rejects accidental reuse. */
int app_finish(const char *name, int result) {
    const char *dir = getenv("ST_RUN_DIR"), *run = getenv("ST_RUN_ID");
    if (!mapped_lines) return result ? result : ST_ERR_ARG;
    if (!dir || !identifier(run) || !identifier(name)) return result ? result : ST_ERR_ARG;
    char path[4096];
    int length = snprintf(path, sizeof(path), "%s/%s-lane%u.u32.bin", dir, name, st_lane);
    if (length < 0 || (size_t)length >= sizeof(path)) return result ? result : ST_ERR_ARG;
    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL, 0600);
    FILE *f = fd < 0 ? NULL : fdopen(fd, "wb");
    if (!f) { if (fd >= 0) close(fd); perror(path); return result ? result : ST_ERR_ARG; }
    size_t bytes = (size_t)mapped_lines * ST_LINE_BYTES;
    st_cache_invalidate((void *)g_mem, bytes);
    size_t n = fwrite((const void *)g_mem, 1, bytes, f);
    int io_error = n != bytes;
    if (fflush(f) || fsync(fileno(f))) io_error = 1;
    if (fclose(f)) io_error = 1;
    if (io_error) return result ? result : ST_ERR_ARG;
    length = snprintf(path, sizeof(path), "%s/%s-lane%u.json", dir, name, st_lane);
    if (length < 0 || (size_t)length >= sizeof(path)) return result ? result : ST_ERR_ARG;
    fd = open(path, O_WRONLY | O_CREAT | O_EXCL, 0600);
    f = fd < 0 ? NULL : fdopen(fd, "w");
    if (!f) { if (fd >= 0) close(fd); return result ? result : ST_ERR_ARG; }
    int written = fprintf(f, "{\"schema\":1,\"run_id\":\"%s\",\"build_id\":\"%s\",\"stage\":\"%s\","
                      "\"lane\":%u,\"bytes\":%zu,\"completed\":%s,\"result\":%d}\n",
                      run, ST_BUILD_ID, name, st_lane, bytes, completed ? "true" : "false", result);
    int close_rc = fclose(f);
    printf("[SNAPSHOT] stage=%s lane=%u completed=%d result=%d\n", name, st_lane, completed, result);
    return result ? result : (written < 0 || close_rc ? ST_ERR_ARG : ST_OK);
}
