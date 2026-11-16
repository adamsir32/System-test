/* Original System-test group runner pattern, restricted to our two cases. */
#include "st_common.h"
int st_case_08_03_psi_medium(void);
int st_case_08_04_pir_medium(void);
static const struct { st_case_fn fn; const char *id, *subject; } cases[] = {
    {st_case_08_03_psi_medium, "08_03_psi_medium", "PSI Medium"},
    {st_case_08_04_pir_medium, "08_04_pir_medium", "PIR Medium"}
};
int main(void) {
    unsigned pass=0, fail=0, skip=0;
    for (unsigned i=0;i<sizeof(cases)/sizeof(cases[0]);++i) {
        int rc=st_run_case_dual(cases[i].fn,cases[i].id,cases[i].subject,1);
        if (rc==ST_ERR_NOT_QUALIFIED) ++skip;
        else if (rc==ST_OK) ++pass;
        else ++fail;
    }
    printf("[HPU][SUMMARY] group=08_medium pass=%u fail=%u skip=%u\n",pass,fail,skip);
    return (fail || skip || pass != sizeof(cases)/sizeof(cases[0])) ? 1 : 0;
}
