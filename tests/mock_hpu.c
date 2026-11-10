/* Host-only fixture writer. It does NOT execute HPU arithmetic. Never board-linked. */
#include "app_support.h"
#include "layout.h"
#include <stdlib.h>
#include <string.h>
volatile uint32_t *g_csr, *g_mem;
extern const struct output_span stage0_outputs[], stage1_outputs[];
static size_t mapped_bytes;
void *st_map_phys(uintptr_t address, size_t bytes) {
    (void)address; mapped_bytes=bytes; return calloc(1,bytes);
}
void st_cache_clean(void *p, size_t n) { (void)p; (void)n; }
void st_cache_invalidate(void *p, size_t n) { (void)p; (void)n; }
int st_config_window(uint32_t n,uint32_t lo,uint32_t hi) { (void)n;(void)lo;(void)hi;return 0; }
int st_wait_irq(void) { return getenv("MOCK_TIMEOUT") ? ST_ERR_TIMEOUT : 0; }
int st_completion_clear(void) { return 0; }
int st_check_status(void) { return 0; }
int __wrap_app_bind_lane(void) { return 0; }

static int fixture(const char *stage,const struct output_span *spans,unsigned count) {
    char path[160]; snprintf(path,sizeof(path),"build/imported/%s/golden.u32.bin",stage);
    FILE *f=fopen(path,"rb"); if(!f) return -1;
    for(unsigned i=0;i<count;++i) {
        if(fseek(f,(long)spans[i].golden_word*4,SEEK_SET) ||
           fread((void*)(g_mem+(size_t)spans[i].line*64),4,spans[i].words,f)!=spans[i].words) { fclose(f);return -1; }
    }
    fclose(f);
    const char *fault=getenv("MOCK_FAULT");
    if(fault && !strncmp(fault,stage,strlen(stage)) && fault[strlen(stage)]==':') {
        fault+=strlen(stage)+1;
        if(!strcmp(fault,"output")) g_mem[(size_t)spans[0].line*64]^=1;
        else if(!strcmp(fault,"guard")) g_mem[mapped_bytes/4-1]^=1;
        else if(!strcmp(fault,"readonly")) g_mem[0]^=1;
        else {
            snprintf(path,sizeof(path),"build/imported/%s/%s",stage,
                     !strcmp(fault,"cpu-input")?"cpu-inputs.u8.bin":"writable.u8.bin");
            f=fopen(path,"rb"); if(!f) return -1;
            size_t line=0; int b,found=0;
            while((b=fgetc(f))!=EOF) {
                int output=0;
                for(unsigned i=0;i<count;++i) if(line>=spans[i].line && line<spans[i].line+spans[i].words/64) output=1;
                if(b && !output) { g_mem[line*64]^=1;found=1;break; } ++line;
            }
            fclose(f); if(!found) return -1;
        }
    }
    return 0;
}
int hpu_run_bfv_apsi_concentrated_application(void) { return fixture("psi",outputs,8); }
int hpu_run_bfv_sealpir_2d_small_stage0_concentrated_000(void) { return fixture("stage0",stage0_outputs,16); }
int hpu_run_bfv_sealpir_2d_small_stage1_concentrated_000(void) { return fixture("stage1",stage1_outputs,32); }
