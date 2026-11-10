#ifndef APP_SUPPORT_H
#define APP_SUPPORT_H
#include <stdint.h>
#include "st_common.h"
int app_prepare(const char *image, unsigned image_lines, unsigned window_lines);
int app_run(int (*entry)(void));
int app_check(const char *golden, const void *outputs, unsigned count, unsigned image_lines);
int app_export(const char *name, unsigned image_lines);
struct app_span { unsigned line, words, golden_word, modulus, step, component, modulus_id; };
#endif
