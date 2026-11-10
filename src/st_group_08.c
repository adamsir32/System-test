#include "st_common.h"
int st_case_08_01_psi_small(void);
int st_case_08_02_pir_small(void);
int main(void) { unsigned pass=0, fail=0, skip=0; int rc;
rc=st_run_case_dual(st_case_08_01_psi_small,"08_01_psi_small","PSI Small",1); if(rc==ST_ERR_NOT_QUALIFIED) ++skip; else if(rc==ST_OK) ++pass; else ++fail;
rc=st_run_case_dual(st_case_08_02_pir_small,"08_02_pir_small","PIR Small",1); if(rc==ST_ERR_NOT_QUALIFIED) ++skip; else if(rc==ST_OK) ++pass; else ++fail;
printf("[HPU][SUMMARY] group=08 pass=%u fail=%u skip=%u\n",pass,fail,skip); return fail ? 1 : 0; }
