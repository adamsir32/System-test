#include "app_support.h"
#include "layout.h"
#include "bfv_apsi_concentrated_application.h"
int st_case_08_03_psi_medium(void) {
    int rc = app_bind_lane();
    if (rc) return app_close(rc);
    rc = app_prepare("psi-medium", IMAGE_LINES, WINDOW_LINES);
    if (!rc) rc = app_run(hpu_run_bfv_apsi_concentrated_application);
    if (!rc) rc = app_check("build/imported/psi-medium/golden.u32.bin", outputs, OUTPUT_COUNT, IMAGE_LINES);
    return app_close(app_finish("psi-medium", rc));
}
#ifdef ST_STANDALONE
ST_CASE_MAIN("08_03_psi_medium", "PSI Medium", st_case_08_03_psi_medium)
#endif
