#include "app_support.h"
#include "layout.h"
#include "bfv_apsi_concentrated_application.h"
extern int psi_verify_intersection(const volatile uint32_t *);
int st_case_08_01_psi_small(void) {
    int rc = app_prepare("build/imported/psi/image.u32.bin", IMAGE_LINES, WINDOW_LINES);
    if (!rc) rc = app_run(hpu_run_bfv_apsi_concentrated_application);
    if (!rc) rc = app_check("build/imported/psi/golden.u32.bin", outputs, OUTPUT_COUNT, IMAGE_LINES);
    if (!rc) rc = app_export("psi-output", IMAGE_LINES);
    if (!rc && psi_verify_intersection(g_mem)) rc = ST_ERR_COMPARE;
    return rc;
}
#ifdef ST_STANDALONE
ST_CASE_MAIN("08_01_psi_small", "PSI Small", st_case_08_01_psi_small)
#endif
