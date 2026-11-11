/* Original System-test group runner pattern, restricted to our two cases. */
#include "st_common.h"
int st_case_08_01_psi_small(void);
int st_case_08_02_pir_small(void);
static const struct { st_case_fn fn; const char *id, *subject; } cases[] = {
    {st_case_08_01_psi_small, "08_01_psi_small", "PSI Small"},
    {st_case_08_02_pir_small, "08_02_pir_small", "PIR Small"}
};
int main(void) {
    unsigned pass=0, fail=0, skip=0;
    for (unsigned i=0;i<sizeof(cases)/sizeof(cases[0]);++i) {
        int rc=st_run_case_dual(cases[i].fn,cases[i].id,cases[i].subject,1);
        if (rc==ST_ERR_NOT_QUALIFIED) ++skip;
        else if (rc==ST_OK) ++pass;
        else ++fail;
    }
    printf("[HPU][SUMMARY] group=08 pass=%u fail=%u skip=%u\n",pass,fail,skip);
    return (fail || skip || pass != sizeof(cases)/sizeof(cases[0])) ? 1 : 0;
}
