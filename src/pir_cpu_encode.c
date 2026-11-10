#include "pir_cpu.h"

#include <stdint.h>

enum { PIR_BATCH_WORDS = 128U, PIR_BUTTERFLIES = 64U };

static uint32_t multiply_mod(uint32_t left, uint32_t right, uint32_t modulus) {
    return (uint32_t)(((uint64_t)left * right) % modulus);
}

static uint32_t power_mod(uint32_t base, uint32_t exponent, uint32_t modulus) {
    uint32_t result = 1U;
    while (exponent != 0U) {
        if (exponent & 1U) result = multiply_mod(result, base, modulus);
        exponent >>= 1U;
        if (exponent != 0U) base = multiply_mod(base, base, modulus);
    }
    return result;
}

static uint32_t reverse_12(uint32_t value) {
    uint32_t result = 0U;
    for (unsigned bit = 0U; bit < PIR_CPU_LOG_DEGREE; ++bit) {
        result = (result << 1U) | (value & 1U);
        value >>= 1U;
    }
    return result;
}

static void load_batch(const uint32_t *memory, uint32_t first, uint32_t second,
                       int interleaved, uint32_t registers[PIR_BATCH_WORDS],
                       uint32_t positions[PIR_BATCH_WORDS]) {
    if (!interleaved) {
        for (unsigned i = 0U; i < PIR_BATCH_WORDS; ++i) {
            positions[i] = first + i;
            registers[i] = memory[positions[i]];
        }
    } else {
        for (unsigned i = 0U; i < PIR_BUTTERFLIES; ++i) {
            positions[2U * i] = first + i;
            positions[2U * i + 1U] = second + i;
            registers[2U * i] = memory[positions[2U * i]];
            registers[2U * i + 1U] = memory[positions[2U * i + 1U]];
        }
    }
}

static void store_batch(uint32_t *memory,
                        const uint32_t registers[PIR_BATCH_WORDS],
                        const uint32_t positions[PIR_BATCH_WORDS]) {
    for (unsigned i = 0U; i < PIR_BATCH_WORDS; ++i)
        memory[positions[i]] = registers[i];
}

/* HardwareNttModel::apply_p: 128-lane right bit rotation, once per stage. */
static void permute(uint32_t registers[PIR_BATCH_WORDS]) {
    uint32_t shifted[PIR_BATCH_WORDS];
    for (unsigned old = 0U; old < PIR_BATCH_WORDS; ++old)
        shifted[(old >> 1U) | ((old & 1U) << 6U)] = registers[old];
    for (unsigned i = 0U; i < PIR_BATCH_WORDS; ++i)
        registers[i] = shifted[i];
}

static int prepare_twiddles(struct pir_cpu_encoder *encoder, unsigned basis) {
    const uint32_t q = encoder->moduli[basis];
    const uint32_t omega = multiply_mod(encoder->psi[basis], encoder->psi[basis], q);
    for (uint32_t i = 0U; i < PIR_CPU_DEGREE; ++i) encoder->labels[i] = i;
    for (unsigned stage = 0U; stage < PIR_CPU_LOG_DEGREE; ++stage) {
        const uint32_t m = 1U << stage;
        uint32_t twiddle_index = 0U;
        for (uint32_t group = 0U; group < PIR_CPU_DEGREE;
             group += m < PIR_BATCH_WORDS ? PIR_BATCH_WORDS : 2U * m) {
            for (uint32_t offset = 0U;
                 offset < (m < PIR_BATCH_WORDS ? PIR_BATCH_WORDS : m);
                 offset += m < PIR_BATCH_WORDS ? PIR_BATCH_WORDS : PIR_BUTTERFLIES) {
                uint32_t registers[PIR_BATCH_WORDS];
                uint32_t positions[PIR_BATCH_WORDS];
                load_batch(encoder->labels, group + offset,
                           group + m + offset, m >= PIR_BATCH_WORDS,
                           registers, positions);
                for (unsigned lane = 0U; lane < PIR_BUTTERFLIES; ++lane) {
                    const uint32_t lower = registers[2U * lane];
                    const uint32_t upper = registers[2U * lane + 1U];
                    if (upper != lower + m || twiddle_index >= PIR_CPU_DEGREE / 2U)
                        return -1;
                    const uint32_t exponent = (lower % m) * PIR_CPU_DEGREE / (2U * m);
                    encoder->twiddles[basis][stage][twiddle_index++] =
                        power_mod(omega, exponent, q);
                }
                permute(registers);
                store_batch(encoder->labels, registers, positions);
            }
        }
        if (twiddle_index != PIR_CPU_DEGREE / 2U) return -2;
    }
    return 0;
}

int pir_cpu_encoder_init(struct pir_cpu_encoder *encoder,
                         const struct pir_cpu_parameters *parameters) {
    if (encoder == 0 || parameters == 0 ||
        parameters->degree != PIR_CPU_DEGREE ||
        parameters->plain_modulus <= (1U << PIR_CPU_PLAIN_BITS)) return -1;
    encoder->ready = 0U;
    encoder->plain_modulus = parameters->plain_modulus;
    for (unsigned basis = 0U; basis < PIR_CPU_STAGE1_MODULI; ++basis) {
        const uint32_t q = parameters->stage1_moduli[basis];
        const uint32_t psi = parameters->stage1_psi[basis];
        if (q < 65537U || parameters->plain_modulus >= q || psi == 0U || psi >= q ||
            power_mod(psi, PIR_CPU_DEGREE, q) != q - 1U ||
            power_mod(psi, 2U * PIR_CPU_DEGREE, q) != 1U) return -2;
        encoder->moduli[basis] = q;
        encoder->psi[basis] = psi;
        if (prepare_twiddles(encoder, basis) != 0) return -3;
    }
    encoder->ready = 1U;
    return 0;
}

static void encode_one(struct pir_cpu_encoder *encoder,
                       const uint32_t *plaintext, unsigned basis) {
    const uint32_t q = encoder->moduli[basis];
    const uint32_t t = encoder->plain_modulus;
    const uint32_t upper_half = (t + 1U) / 2U;
    uint32_t power = 1U;
    for (uint32_t i = 0U; i < PIR_CPU_DEGREE; ++i) {
        const uint32_t value = plaintext[i];
        const uint32_t lifted = value < upper_half ? value % q :
            (t - value == 0U ? 0U : q - (t - value) % q);
        encoder->values[i] = multiply_mod(lifted, power, q);
        power = multiply_mod(power, encoder->psi[basis], q);
    }
    /* DIT consumes bit-reversed twisted coefficients. */
    for (uint32_t i = 0U; i < PIR_CPU_DEGREE; ++i)
        encoder->labels[i] = encoder->values[reverse_12(i)];
    for (uint32_t i = 0U; i < PIR_CPU_DEGREE; ++i)
        encoder->values[i] = encoder->labels[i];
    for (unsigned stage = 0U; stage < PIR_CPU_LOG_DEGREE; ++stage) {
        const uint32_t m = 1U << stage;
        uint32_t twiddle_index = 0U;
        for (uint32_t group = 0U; group < PIR_CPU_DEGREE;
             group += m < PIR_BATCH_WORDS ? PIR_BATCH_WORDS : 2U * m) {
            for (uint32_t offset = 0U;
                 offset < (m < PIR_BATCH_WORDS ? PIR_BATCH_WORDS : m);
                 offset += m < PIR_BATCH_WORDS ? PIR_BATCH_WORDS : PIR_BUTTERFLIES) {
                uint32_t registers[PIR_BATCH_WORDS];
                uint32_t positions[PIR_BATCH_WORDS];
                load_batch(encoder->values, group + offset,
                           group + m + offset, m >= PIR_BATCH_WORDS,
                           registers, positions);
                for (unsigned lane = 0U; lane < PIR_BUTTERFLIES; ++lane) {
                    const uint32_t even = 2U * lane;
                    const uint32_t odd = even + 1U;
                    const uint32_t a = registers[even];
                    const uint32_t product = multiply_mod(
                        registers[odd], encoder->twiddles[basis][stage][twiddle_index++], q);
                    const uint64_t sum = (uint64_t)a + product;
                    registers[even] = (uint32_t)(sum >= q ? sum - q : sum);
                    registers[odd] = a >= product ? a - product :
                        (uint32_t)((uint64_t)a + q - product);
                }
                permute(registers);
                store_batch(encoder->values, registers, positions);
            }
        }
    }
}

int pir_cpu_encode(const uint32_t *plaintexts,
                   size_t plaintext_words,
                   volatile uint32_t *stage1_ddr,
                   uint32_t stage1_lines,
                   const struct pir_cpu_input_limb *limbs,
                   size_t limb_count,
                   const struct pir_cpu_parameters *parameters,
                   struct pir_cpu_encoder *encoder) {
    uint8_t seen[PIR_CPU_PLAINTEXTS][PIR_CPU_STAGE1_MODULI] = {{0}};
    if (plaintexts == 0 || stage1_ddr == 0 || limbs == 0 || parameters == 0 ||
        encoder == 0 || encoder->ready != 1U ||
        parameters->degree != PIR_CPU_DEGREE ||
        encoder->plain_modulus != parameters->plain_modulus ||
        plaintext_words != PIR_CPU_PLAINTEXTS * PIR_CPU_DEGREE ||
        limb_count != PIR_CPU_INPUT_LIMBS) return -1;
    for (unsigned basis = 0U; basis < PIR_CPU_STAGE1_MODULI; ++basis)
        if (encoder->moduli[basis] != parameters->stage1_moduli[basis] ||
            encoder->psi[basis] != parameters->stage1_psi[basis]) return -2;
    for (size_t i = 0U; i < plaintext_words; ++i)
        if (plaintexts[i] >= parameters->plain_modulus) return -3;
    for (size_t i = 0U; i < limb_count; ++i) {
        const struct pir_cpu_input_limb *limb = &limbs[i];
        if (limb->plaintext_index >= PIR_CPU_PLAINTEXTS ||
            limb->modulus_id >= PIR_CPU_STAGE1_MODULI ||
            limb->modulus != encoder->moduli[limb->modulus_id] ||
            limb->words != PIR_CPU_DEGREE || limb->line > stage1_lines ||
            PIR_CPU_DEGREE / 64U > stage1_lines - limb->line ||
            seen[limb->plaintext_index][limb->modulus_id]) return -4;
        seen[limb->plaintext_index][limb->modulus_id] = 1U;
    }
    for (unsigned plain = 0U; plain < PIR_CPU_PLAINTEXTS; ++plain)
        for (unsigned basis = 0U; basis < PIR_CPU_STAGE1_MODULI; ++basis)
            if (!seen[plain][basis]) return -5;
    for (size_t i = 0U; i < limb_count; ++i)
        for (size_t j = i + 1U; j < limb_count; ++j)
            if (limbs[i].line < limbs[j].line + PIR_CPU_DEGREE / 64U &&
                limbs[j].line < limbs[i].line + PIR_CPU_DEGREE / 64U) return -6;
    for (size_t i = 0U; i < limb_count; ++i) {
        const struct pir_cpu_input_limb *limb = &limbs[i];
        encode_one(encoder, plaintexts +
            (size_t)limb->plaintext_index * PIR_CPU_DEGREE, limb->modulus_id);
        volatile uint32_t *destination = stage1_ddr + (size_t)limb->line * 64U;
        for (uint32_t word = 0U; word < PIR_CPU_DEGREE; ++word)
            destination[word] = encoder->values[word];
    }
    return 0;
}
