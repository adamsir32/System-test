/* Exercise CPU write permissions independently of HPU output fixture injection. */
#include "app_support.h"
#include "pir_layout.h"
int main(void) {
    if(app_bind_lane()!=ST_ERR_ARG) return 7; /* No hardware route configured in host probe. */
    if (app_prepare("stage1",STAGE1_IMAGE_LINES,STAGE1_WINDOW_LINES)) return 1;
    size_t dynamic=(size_t)stage1_cpu_limbs[0].line*64;
    g_mem[dynamic]^=1;
    if(app_accept_cpu_inputs("build/imported/stage1/cpu-inputs.u8.bin")) return 2;
    if(app_check_memory()) return 3; /* Must compare against new CPU snapshot. */
    g_mem[dynamic]^=1;
    if(app_check_memory()!=ST_ERR_COMPARE) return 4;
    if(app_prepare("stage1",STAGE1_IMAGE_LINES,STAGE1_WINDOW_LINES)) return 5;
    g_mem[0]^=1;
    if(app_accept_cpu_inputs("build/imported/stage1/cpu-inputs.u8.bin")!=ST_ERR_COMPARE) return 6;
    return 0;
}
