#!/usr/bin/env python3
"""Build-local parameter adaptation of the recipient's original Runtime.
No private Runtime is committed or changed in place; no hash/version gate.
"""
import argparse
from pathlib import Path
import re

def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Runtime interface changed; review this adaptation: '+old[:70])
    return text.replace(old,new)

def main():
    p=argparse.ArgumentParser(); p.add_argument('runtime',type=Path); a=p.parse_args()
    out=Path('build/runtime'); out.mkdir(parents=True,exist_ok=True)
    lines=int(Path('build/app_lines.txt').read_text())
    if not 512 <= lines < 0x04000000//256: raise ValueError('invalid application window')
    header=(a.runtime/'src/st_common.h').read_text()
    header,n=re.subn(r'#define ST_WINDOW_LINES\s+512u',f'#define ST_WINDOW_LINES {lines}u',header)
    if n!=1: raise ValueError('expected original Runtime window declaration')
    (out/'st_common.h').write_text(header)
    for name in ('st_insn.h','st_ntt_vectors.h'):
        (out/name).write_bytes((a.runtime/'src'/name).read_bytes())
    common=(a.runtime/'src/st_common.c').read_text()
    # Preserve original IRQ/status/fault and clear semantics, use elapsed time.
    helper='''#include <stdlib.h>
#include <time.h>
static uint64_t st_app_now_ms(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts)) { perror("clock_gettime"); exit(ST_ERR_TIMEOUT); }
    return (uint64_t)ts.tv_sec * 1000u + (uint64_t)ts.tv_nsec / 1000000u;
}
static unsigned st_app_timeout_ms(void) {
    const char *s = getenv("ST_HPU_TIMEOUT_MS");
    if (s && *s) {
        char *end; unsigned long n = strtoul(s, &end, 10);
        if (!*end && n >= 100 && n <= 3600000) return (unsigned)n;
    }
    return 120000u;
}
'''
    start=common.index('int st_wait_irq(void) {')
    end=common.index('int st_completion_clear(void)',start)
    wait=common[start:end]
    wait=replace_once(wait,'    unsigned timeout;',
        '    const uint64_t start = st_app_now_ms();\n    const unsigned limit = st_app_timeout_ms();')
    wait=replace_once(wait,'for (timeout = 0u; timeout < ST_TIMEOUT; ++timeout)',
        'while (st_app_now_ms() - start < limit)')
    (out/'st_common.c').write_text(common[:start]+helper+wait+common[end:])
    dual=(a.runtime/'src/st_dual.c').read_text()
    if 'st_dual_barrier_generation' not in dual:
        raise ValueError('PIR requires original multi-generation issue barrier')
    dual=replace_once(dual,'#define ST_DUAL_BARRIER_TIMEOUT_NS  UINT64_C(5000000000)',
        'static unsigned st_dual_timeout_ms(void);\n'
        '#define ST_DUAL_BARRIER_TIMEOUT_NS ((uint64_t)st_dual_timeout_ms() * UINT64_C(1000000))')
    (out/'st_dual.c').write_text(dual)
    print('Original Runtime adapted: one DDR mapping, '+str(lines)+' lines; wall-clock IRQ and case-budget barrier')
if __name__=='__main__': main()
