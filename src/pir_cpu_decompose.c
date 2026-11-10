#include "pir_cpu.h"

#include <stdint.h>

static uint32_t reverse_12(uint32_t value) {
    uint32_t result = 0U;
    for (unsigned bit = 0U; bit < PIR_CPU_LOG_DEGREE; ++bit) {
        result = (result << 1U) | (value & 1U);
        value >>= 1U;
    }
    return result;
}

int pir_cpu_decompose(const volatile uint32_t *stage0_ddr,
                      uint32_t stage0_lines,
                      const struct pir_cpu_output_limb *limbs,
                      size_t limb_count,
                      const struct pir_cpu_parameters *parameters,
                      uint32_t *plaintexts,
                      size_t plaintext_words) {
    uint8_t seen[PIR_CPU_STAGE0_REPLIES][PIR_CPU_STAGE0_COMPONENTS]
                [PIR_CPU_STAGE0_MODULI] = {{{0}}};
    if (stage0_ddr == 0 || limbs == 0 || parameters == 0 || plaintexts == 0 ||
        parameters->degree != PIR_CPU_DEGREE ||
        limb_count != PIR_CPU_OUTPUT_LIMBS ||
        plaintext_words != PIR_CPU_PLAINTEXTS * PIR_CPU_DEGREE ||
        parameters->plain_modulus <= (1U << PIR_CPU_PLAIN_BITS)) return -1;
    for (size_t index = 0U; index < limb_count; ++index) {
        const struct pir_cpu_output_limb *limb = &limbs[index];
        if (limb->reply >= PIR_CPU_STAGE0_REPLIES ||
            limb->component >= PIR_CPU_STAGE0_COMPONENTS ||
            limb->modulus_id >= PIR_CPU_STAGE0_MODULI ||
            limb->words != PIR_CPU_DEGREE || limb->line > stage0_lines ||
            PIR_CPU_DEGREE / 64U > stage0_lines - limb->line ||
            limb->modulus != parameters->stage0_moduli[limb->modulus_id] ||
            seen[limb->reply][limb->component][limb->modulus_id]) return -2;
        seen[limb->reply][limb->component][limb->modulus_id] = 1U;
    }
    for (unsigned reply = 0U; reply < PIR_CPU_STAGE0_REPLIES; ++reply)
        for (unsigned component = 0U; component < PIR_CPU_STAGE0_COMPONENTS; ++component)
            for (unsigned modulus = 0U; modulus < PIR_CPU_STAGE0_MODULI; ++modulus)
                if (!seen[reply][component][modulus]) return -4;
    for (size_t left = 0U; left < limb_count; ++left)
        for (size_t right = left + 1U; right < limb_count; ++right)
            if ((uint64_t)limbs[left].line <
                    (uint64_t)limbs[right].line + PIR_CPU_DEGREE / 64U &&
                (uint64_t)limbs[right].line <
                    (uint64_t)limbs[left].line + PIR_CPU_DEGREE / 64U)
                return -5;
    for (size_t index = 0U; index < limb_count; ++index) {
        const struct pir_cpu_output_limb *limb = &limbs[index];
        const volatile uint32_t *source = stage0_ddr + (size_t)limb->line * 64U;
        const size_t plain_base = (size_t)limb->reply * 8U +
            (size_t)limb->component * 4U + (size_t)limb->modulus_id * 2U;
        for (uint32_t physical = 0U; physical < PIR_CPU_DEGREE; ++physical) {
            const uint32_t value = source[physical];
            if (value >= limb->modulus) return -3;
            const uint32_t natural = reverse_12(physical);
            plaintexts[plain_base * PIR_CPU_DEGREE + natural] =
                value & ((1U << PIR_CPU_PLAIN_BITS) - 1U);
            plaintexts[(plain_base + 1U) * PIR_CPU_DEGREE + natural] =
                value >> PIR_CPU_PLAIN_BITS;
        }
    }
    return 0;
}
