/* Producer images use original st_v2_* shadow/permission checks.
 * Mapping, barriers, CSR completion and PASS/FAIL remain owned by Runtime.
 */
#define _GNU_SOURCE
#include "app_support.h"
#include <errno.h>
#include <fcntl.h>
#include <sched.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

static unsigned image_lines;
static int completed;
static int read_exact(const char *path, void *dest, size_t bytes) {
    FILE *f=fopen(path,"rb");
    if (!f) { perror(path); return ST_ERR_ARG; }
    size_t n=fread(dest,1,bytes,f);
    int extra=fgetc(f),err=ferror(f); fclose(f);
    if (n!=bytes || extra!=EOF || err) {
        fprintf(stderr,"[HPU][FAIL] invalid size/read: %s\n",path);
        return ST_ERR_ARG;
    }
    return ST_OK;
}
int app_bind_lane(void) {
    const char *s=getenv(st_lane ? "ST_CPU1" : "ST_CPU0");
    unsigned long cpu=st_lane;
    if (s) {
        char *end; errno=0; cpu=strtoul(s,&end,10);
        if (!*s || *end || errno) return ST_ERR_ARG;
    }
    if (cpu>=CPU_SETSIZE) return ST_ERR_ARG;
    cpu_set_t set; CPU_ZERO(&set); CPU_SET(cpu,&set);
    if (sched_setaffinity(0,sizeof(set),&set) || sched_getcpu()!=(int)cpu) {
        perror("lane affinity (set ST_CPU0/ST_CPU1 if board CPU numbering differs)");
        return ST_ERR_ARG;
    }
    printf("[CPU] lane=%u linux_cpu=%lu (hardware routing must match board)\n",st_lane,cpu);
    return ST_OK;
}
int app_prepare(const char *stage,unsigned lines,unsigned window) {
    char path[160]; completed=0; image_lines=0;
    if (!g_mem || !g_csr || !window || lines!=window+64u || lines>ST_WINDOW_LINES)
        return ST_ERR_ARG;
    size_t bytes=(size_t)lines*ST_LINE_BYTES;
    uint32_t *image=malloc(bytes); uint8_t *mask=malloc(lines);
    if (!image || !mask) { free(image); free(mask); return ST_ERR_ARG; }
    snprintf(path,sizeof(path),"build/imported/%s/image.u32.bin",stage);
    int rc=read_exact(path,image,bytes);
    snprintf(path,sizeof(path),"build/imported/%s/writable.u8.bin",stage);
    if (!rc) rc=read_exact(path,mask,lines);
    for (unsigned i=0; !rc && i<lines; ++i)
        if (mask[i]>1 || (i>=window && mask[i])) rc=ST_ERR_ARG;
    if (!rc) rc=st_v2_prepare(0u,ST_MOD_Q0,ST_MOD_Q1);
    if (!rc) rc=st_v2_copy(0u,image,lines*ST_WORDS_PER_LINE);
    for (unsigned i=0; !rc && i<lines; ++i)
        if (mask[i]) rc=st_v2_allow_output(i,1u);
    free(image); free(mask);
    if (rc) return rc;
    image_lines=lines;
    return st_config_window(window,(uint32_t)st_mem_base(),(uint32_t)(st_mem_base()>>32));
}
int app_accept_cpu_inputs(const char *path) {
    uint8_t *mask=malloc(image_lines);
    if (!image_lines || !mask) { free(mask); return ST_ERR_ARG; }
    int rc=read_exact(path,mask,image_lines);
    /* CPU writes may touch only the declared dynamic inputs, even in scratch. */
    for (unsigned line=0; !rc && line<ST_WINDOW_LINES; ++line) {
        if (line<image_lines && mask[line]) {
            if (mask[line]!=1 || line>=image_lines-64u) rc=ST_ERR_ARG;
            continue;
        }
        const uint32_t *expected=st_v2_expected(line);
        if (!expected) { rc=ST_ERR_ARG; break; }
        for (unsigned j=0;j<ST_WORDS_PER_LINE;++j)
            if (g_mem[(size_t)line*ST_WORDS_PER_LINE+j]!=expected[j]) {
                fprintf(stderr,"[HPU][FAIL] CPU wrote fixed region line=%u word=%u\n",line,j);
                rc=ST_ERR_COMPARE; break;
            }
    }
    for (unsigned line=0; !rc && line<image_lines; ++line)
        if (mask[line]) rc=st_v2_copy(line,(const uint32_t *)(g_mem+(size_t)line*64),64);
    free(mask); return rc;
}
int app_run(int (*entry)(void)) {
    int rc=st_dual_issue_barrier();
    if (!rc && entry()) rc=ST_ERR_NOT_SUPPORTED;
    if (!rc) rc=st_wait_irq();
    if (!rc) rc=st_completion_clear();
    if (!rc) rc=st_check_status();
    completed=rc==ST_OK;
    return rc;
}
int app_check(const char *golden,const void *out,unsigned count,unsigned lines) {
    struct app_span span; size_t words=0;
    if (!out || !count || lines!=image_lines) return ST_ERR_ARG;
    for (unsigned i=0;i<count;++i) {
        memcpy(&span,(const char *)out+i*sizeof(span),sizeof(span));
        size_t end=(size_t)span.golden_word+span.words;
        if (end>words) words=end;
    }
    uint32_t *expected=malloc(words*4);
    if (!expected) return ST_ERR_ARG;
    int rc=read_exact(golden,expected,words*4);
    for (unsigned i=0; !rc && i<count;++i) {
        memcpy(&span,(const char *)out+i*sizeof(span),sizeof(span));
        rc=st_v2_check_words("application-golden",span.line,
                             expected+span.golden_word,span.words,span.modulus);
    }
    free(expected);
    int memory_rc=st_v2_check_memory("readonly-and-guard");
    return rc ? rc : memory_rc;
}
int app_finish(const char *stage,int result) {
    if (!image_lines) return result ? result : ST_ERR_ARG;
    const char *dir=getenv("ST_OUTPUT_DIR"); if (!dir) dir=".";
    char path[4096];
    int n=snprintf(path,sizeof(path),"%s/%s-lane%u.u32.bin",dir,stage,st_lane);
    if (n<0 || (size_t)n>=sizeof(path)) return result ? result : ST_ERR_ARG;
    int fd=open(path,O_WRONLY|O_CREAT|O_EXCL,0600);
    FILE *f=fd<0 ? NULL : fdopen(fd,"wb");
    if (!f) { if(fd>=0)close(fd); perror(path); return result ? result : ST_ERR_ARG; }
    size_t bytes=(size_t)image_lines*ST_LINE_BYTES;
    st_cache_invalidate((void *)g_mem,bytes);
    int bad=fwrite((const void *)g_mem,1,bytes,f)!=bytes;
    if (fflush(f) || fsync(fileno(f))) bad=1;
    if (fclose(f)) bad=1;
    if (bad && !result) result=ST_ERR_ARG;
    printf("[SNAPSHOT] stage=%s lane=%u completed=%d result=%d\n",stage,st_lane,completed,result);
    return result;
}
static int unmap(volatile uint32_t **pointer,size_t bytes) {
    if (!*pointer) return 0;
    long page=sysconf(_SC_PAGESIZE); if (page<=0) page=4096;
    uintptr_t address=(uintptr_t)*pointer, base=address&~((uintptr_t)page-1);
    int rc=munmap((void *)base,bytes+(size_t)(address-base));
    *pointer=NULL; return rc;
}
int app_close(int result) {
    int a=unmap(&g_mem,(size_t)ST_WINDOW_LINES*ST_LINE_BYTES);
    int b=unmap(&g_csr,0x20u);
    return result ? result : (a || b ? ST_ERR_MAP : ST_OK);
}
