#ifndef HPU_PIR_CPU_H
#define HPU_PIR_CPU_H

#include <stddef.h>
#include <stdint.h>

/* Small fixed-query two-dimensional SealPIR package contract. */
#define PIR_CPU_DEGREE 4096U
#define PIR_CPU_LOG_DEGREE 12U
#define PIR_CPU_STAGE0_REPLIES 4U
#define PIR_CPU_STAGE0_COMPONENTS 2U
#define PIR_CPU_STAGE0_MODULI 2U
#define PIR_CPU_STAGE1_MODULI 3U
#define PIR_CPU_PLAINTEXTS 32U
#define PIR_CPU_OUTPUT_LIMBS 16U
#define PIR_CPU_INPUT_LIMBS 96U
#define PIR_CPU_PLAIN_BITS 20U

struct pir_cpu_output_limb {
    uint32_t line;
    uint32_t words;
    uint32_t reply;
    uint32_t component;
    uint32_t modulus_id;
    uint32_t modulus;
};

struct pir_cpu_input_limb {
    uint32_t line;
    uint32_t words;
    uint32_t plaintext_index;
    uint32_t modulus_id;
    uint32_t modulus;
};

struct pir_cpu_parameters {
    uint32_t degree;
    uint32_t plain_modulus;
    uint32_t stage0_moduli[PIR_CPU_STAGE0_MODULI];
    uint32_t stage1_moduli[PIR_CPU_STAGE1_MODULI];
    uint32_t stage1_psi[PIR_CPU_STAGE1_MODULI];
};

/* Output order is reply, ciphertext component, Q limb, 20-bit chunk, coefficient. */
int pir_cpu_decompose(const volatile uint32_t *stage0_ddr,
                      uint32_t stage0_lines,
                      const struct pir_cpu_output_limb *limbs,
                      size_t limb_count,
                      const struct pir_cpu_parameters *parameters,
                      uint32_t *plaintexts,
                      size_t plaintext_words);

/* Scratch and twiddle tables are caller-owned BSS, never a large stack frame. */
struct pir_cpu_encoder {
    uint32_t twiddles[PIR_CPU_STAGE1_MODULI][PIR_CPU_LOG_DEGREE][PIR_CPU_DEGREE / 2U];
    uint32_t values[PIR_CPU_DEGREE];
    uint32_t labels[PIR_CPU_DEGREE];
    uint32_t moduli[PIR_CPU_STAGE1_MODULI];
    uint32_t psi[PIR_CPU_STAGE1_MODULI];
    uint32_t plain_modulus;
    uint32_t ready;
};

int pir_cpu_encoder_init(struct pir_cpu_encoder *encoder,
                         const struct pir_cpu_parameters *parameters);

/* Only the 96 declared dynamic limbs are written. No fixed query/key/twiddle data. */
int pir_cpu_encode(const uint32_t *plaintexts,
                   size_t plaintext_words,
                   volatile uint32_t *stage1_ddr,
                   uint32_t stage1_lines,
                   const struct pir_cpu_input_limb *limbs,
                   size_t limb_count,
                   const struct pir_cpu_parameters *parameters,
                   struct pir_cpu_encoder *encoder);

#endif
