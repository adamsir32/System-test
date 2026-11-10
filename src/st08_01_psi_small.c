#include "app_support.h"
#include "layout.h"
#include "bfv_apsi_concentrated_application.h"
int st_case_08_01_psi_small(void) {
    int rc = app_bind_lane();
    if (rc) return rc;
    rc = app_prepare("psi", IMAGE_LINES, WINDOW_LINES);
    if (!rc) rc = app_run(hpu_run_bfv_apsi_concentrated_application);
    if (!rc) rc = app_check("build/imported/psi/golden.u32.bin", outputs, OUTPUT_COUNT, IMAGE_LINES);
    return app_finish("psi", rc);
}
#ifdef ST_STANDALONE
ST_CASE_MAIN("08_01_psi_small", "PSI Small", st_case_08_01_psi_small)
#endif
