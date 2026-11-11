#include "app_support.h"
#include "pir_cpu.h"
#include "pir_layout.h"
#include "bfv_sealpir_2d_small_stage0_concentrated_000.h"
#include "bfv_sealpir_2d_small_stage1_concentrated_000.h"
static uint32_t plaintexts[PIR_CPU_PLAINTEXTS * PIR_CPU_DEGREE];
static struct pir_cpu_encoder encoder;
static int check_cpu_inputs(void) {
    FILE *f = fopen("build/imported/stage1/image.u32.bin", "rb");
    if (!f) return ST_ERR_ARG;
    for (unsigned i = 0; i < PIR_CPU_INPUT_LIMBS; ++i) {
        const struct pir_cpu_input_limb *limb = &stage1_cpu_limbs[i];
        if (fseek(f, (long)limb->line * ST_LINE_BYTES, SEEK_SET)) { fclose(f); return ST_ERR_ARG; }
        for (unsigned j = 0; j < limb->words; ++j) {
            uint32_t expected;
            if (fread(&expected, sizeof(expected), 1, f) != 1 ||
                expected != g_mem[(size_t)limb->line * ST_WORDS_PER_LINE + j]) {
                fprintf(stderr, "[HPU][FAIL] CPU input limb=%u word=%u\n", i, j);
                fclose(f); return ST_ERR_COMPARE;
            }
        }
    }
    fclose(f); return ST_OK;
}
static int run_pir(void) {
    int rc = app_bind_lane();
    if (rc) return rc;
    rc = app_prepare("stage0", STAGE0_IMAGE_LINES, STAGE0_WINDOW_LINES);
    if (!rc) rc = app_run(hpu_run_bfv_sealpir_2d_small_stage0_concentrated_000);
    if (!rc) rc = app_check("build/imported/stage0/golden.u32.bin", stage0_outputs, STAGE0_OUTPUT_COUNT, STAGE0_IMAGE_LINES);
    rc = app_finish("pir-stage0", rc);
    if (rc) return rc;
    if (pir_cpu_decompose(g_mem, STAGE0_WINDOW_LINES, stage0_cpu_limbs, PIR_CPU_OUTPUT_LIMBS,
                          &pir_parameters, plaintexts, PIR_CPU_PLAINTEXTS * PIR_CPU_DEGREE)) return ST_ERR_COMPARE;
    rc = app_prepare("stage1", STAGE1_IMAGE_LINES, STAGE1_WINDOW_LINES);
    if (rc) return app_finish("pir-stage1", rc);
    /* Poison every declared CPU input so a missing or partial write cannot pass. */
    for (unsigned i = 0; i < PIR_CPU_INPUT_LIMBS; ++i) {
        const struct pir_cpu_input_limb *limb = &stage1_cpu_limbs[i];
        size_t start = (size_t)limb->line * ST_WORDS_PER_LINE;
        size_t total = (size_t)STAGE1_WINDOW_LINES * ST_WORDS_PER_LINE;
        if (start > total || limb->words > total - start)
            return app_finish("pir-stage1", ST_ERR_ARG);
        for (unsigned j = 0; j < limb->words; ++j) g_mem[start + j] = UINT32_MAX;
    }
    if (pir_cpu_encoder_init(&encoder, &pir_parameters) ||
        pir_cpu_encode(plaintexts, PIR_CPU_PLAINTEXTS * PIR_CPU_DEGREE, g_mem,
                       STAGE1_WINDOW_LINES, stage1_cpu_limbs, PIR_CPU_INPUT_LIMBS,
                       &pir_parameters, &encoder)) return app_finish("pir-stage1", ST_ERR_COMPARE);
    rc = check_cpu_inputs();
    if (!rc) rc = app_accept_cpu_inputs("build/imported/stage1/cpu-inputs.u8.bin");
    if (rc) return app_finish("pir-stage1", rc);
    st_cache_clean((void *)g_mem, (size_t)STAGE1_IMAGE_LINES * ST_LINE_BYTES);
    rc = app_run(hpu_run_bfv_sealpir_2d_small_stage1_concentrated_000);
    if (!rc) rc = app_check("build/imported/stage1/golden.u32.bin", stage1_outputs, STAGE1_OUTPUT_COUNT, STAGE1_IMAGE_LINES);
    return app_finish("pir-stage1", rc);
}
int st_case_08_02_pir_small(void) { return app_close(run_pir()); }
#ifdef ST_STANDALONE
ST_CASE_MAIN("08_02_pir_small", "PIR Small", st_case_08_02_pir_small)
#endif
