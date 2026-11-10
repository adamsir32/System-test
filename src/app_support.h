#ifndef APP_SUPPORT_H
#define APP_SUPPORT_H
#include <stdint.h>
#include "st_common.h"
int app_prepare(const char *stage, unsigned image_lines, unsigned window_lines);
int app_bind_lane(void);
int app_accept_cpu_inputs(const char *cpu_mask);
int app_check_memory(void);
int app_finish(const char *name, int result);
int app_run(int (*entry)(void));
int app_check(const char *golden, const void *outputs, unsigned count, unsigned image_lines);
struct app_span { unsigned line, words, golden_word, modulus, step, component, modulus_id; };
#endif
