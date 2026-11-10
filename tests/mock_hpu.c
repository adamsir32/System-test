/* Test-only fixture writer: no HPU arithmetic, never linked into board ELF. */
#define _GNU_SOURCE
#include "app_support.h"
#include "pir_cpu.h"
#include "layout.h"
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
extern const struct output_span stage0_outputs[],stage1_outputs[];
static unsigned maps,unmaps;
static int issued;
void *st_map_phys(uintptr_t address,size_t bytes) {
    if (++maps>2 || (address==st_mem_base() && bytes!=(size_t)ST_WINDOW_LINES*256)) abort();
    void *p=mmap(NULL,bytes,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    return p==MAP_FAILED ? NULL : p;
}
int __real_munmap(void *,size_t);
int __wrap_munmap(void *p,size_t n) {
    if (p==(void *)g_mem || p==(void *)g_csr) {
        ++unmaps;
        if (p==(void *)g_mem && n!=(size_t)ST_WINDOW_LINES*256) abort();
        if (unmaps==2) printf("[MAPS] maps=%u unmaps=%u\n",maps,unmaps);
    }
    return __real_munmap(p,n);
}
void st_fence(void) {}
void st_cache_clean(void *p,size_t n) { (void)p;(void)n; }
void st_cache_invalidate(void *p,size_t n) { (void)p;(void)n; }
void st_psync(void) {}
uint32_t st_csr_read(uint32_t off) { return g_csr[off/4]; }
void st_csr_write(uint32_t off,uint32_t value) {
    if (off==ST_CSR_FAULT) g_csr[off/4]=0;
    else if (off==ST_CSR_COMMIT) g_csr[ST_CSR_STATUS/4]=ST_STATUS_VALID;
    else if (off==ST_CSR_IRQ) {
        g_csr[off/4]=0;
        const char *s=getenv("MOCK_TERMINAL");
        if (issued && s) {
            g_csr[ST_CSR_STATUS/4]=!strcmp(s,"busy") ? ST_STATUS_VALID|ST_STATUS_BUSY :
                !strcmp(s,"fault") ? ST_STATUS_VALID|ST_STATUS_FAULT : 0;
        }
    } else g_csr[off/4]=value;
}
int __wrap_app_bind_lane(void) {
    puts("[SOFTWARE MOCK] writes Golden; hardware NOT RUN");
    return getenv("MOCK_SKIP") ? ST_ERR_NOT_QUALIFIED : ST_OK;
}
static int fixture(const char *stage,const struct output_span *spans,unsigned count) {
    char path[160]; snprintf(path,sizeof(path),"build/imported/%s/golden.u32.bin",stage);
    FILE *f=fopen(path,"rb"); if(!f) return -1;
    for(unsigned i=0;i<count;++i) {
        if(fseek(f,(long)spans[i].golden_word*4,SEEK_SET) ||
           fread((void*)(g_mem+(size_t)spans[i].line*64),4,spans[i].words,f)!=spans[i].words) {
            fclose(f);return -1;
        }
    }
    fclose(f); issued=1;
    const char *wait=getenv("MOCK_WAIT");
    g_csr[ST_CSR_IRQ/4]=wait && !strcmp(wait,"timeout") ? 0 : ST_IRQ_LEVEL;
    g_csr[ST_CSR_STATUS/4]=ST_STATUS_VALID;
    if (wait && !strcmp(wait,"fault")) g_csr[ST_CSR_FAULT/4]=ST_FAULT_VALID;
    if (wait && !strcmp(wait,"busy")) g_csr[ST_CSR_STATUS/4]|=ST_STATUS_BUSY;
    const char *fault=getenv("MOCK_FAULT");
    if(fault && !strncmp(fault,stage,strlen(stage)) && fault[strlen(stage)]==':') {
        fault+=strlen(stage)+1;
        if(!strcmp(fault,"output")) g_mem[(size_t)spans[0].line*64]^=1;
        else if(!strcmp(fault,"guard")) {
            snprintf(path,sizeof(path),"build/imported/%s/writable.u8.bin",stage);
            f=fopen(path,"rb"); if(!f) return -1;
            if(fseek(f,0,SEEK_END)) { fclose(f);return -1; }
            long lines=ftell(f); fclose(f); if(lines<=0) return -1;
            g_mem[(size_t)lines*64-1]^=1;
        }
        else if(!strcmp(fault,"readonly")) g_mem[0]^=1;
        else {
            snprintf(path,sizeof(path),"build/imported/%s/%s",stage,
                !strcmp(fault,"cpu-input")?"cpu-inputs.u8.bin":"writable.u8.bin");
            f=fopen(path,"rb"); if(!f) return -1;
            size_t line=0; int b,found=0;
            while((b=fgetc(f))!=EOF) {
                int output=0;
                for(unsigned i=0;i<count;++i)
                    if(line>=spans[i].line && line<spans[i].line+spans[i].words/64) output=1;
                if(b && !output) { g_mem[line*64]^=1;found=1;break; } ++line;
            }
            fclose(f); if(!found) return -1;
        }
    }
    if (getenv("MOCK_PEER_FAIL") && st_lane==1) return -1;
    return 0;
}
int hpu_run_bfv_apsi_concentrated_application(void) { return fixture("psi",outputs,8); }
int hpu_run_bfv_sealpir_2d_small_stage0_concentrated_000(void) { return fixture("stage0",stage0_outputs,16); }
int hpu_run_bfv_sealpir_2d_small_stage1_concentrated_000(void) { return fixture("stage1",stage1_outputs,32); }
int __real_pir_cpu_encode(const uint32_t *,size_t,volatile uint32_t *,uint32_t,
    const struct pir_cpu_input_limb *,size_t,const struct pir_cpu_parameters *,struct pir_cpu_encoder *);
int __wrap_pir_cpu_encode(const uint32_t *p,size_t n,volatile uint32_t *m,uint32_t lines,
    const struct pir_cpu_input_limb *l,size_t count,const struct pir_cpu_parameters *par,struct pir_cpu_encoder *e) {
    int rc=__real_pir_cpu_encode(p,n,m,lines,l,count,par,e);
    if(getenv("MOCK_CPU_BAD")) m[0]^=1;
    if(getenv("MOCK_DELAY") && st_lane==1) sleep(6);
    return rc;
}
