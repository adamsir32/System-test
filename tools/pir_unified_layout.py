"""Generate namespaced metadata for a sequential, single-ELF PIR application."""

import csv
import json
from pathlib import Path
import re
import struct

from import_package import GUARD_LINES, read_json, read_rows, require, store_or_verify

N = 4096
LINE_WORDS = 64
STAGE0_STEM = "bfv_sealpir_2d_small_stage0_concentrated_000"
STAGE1_STEM = "bfv_sealpir_2d_small_stage1_concentrated_000"


def package_info(package):
    manifest = read_json(package / "package.json")
    return (manifest,
            read_rows(package / manifest["line_map"]),
            read_rows(package / manifest["golden_manifest"]),
            read_json(package / manifest["parameters"]))


def output_table(golden):
    result = []
    for row in golden:
        result.append((int(row["line_offset"]), int(row["payload_words"]),
                       len(result) * N, int(row["modulus"]),
                       int(row["object_id"].removeprefix("step_")),
                       int(row["component"]), int(row["modulus_id"])))
    return result


def emit_table(name, type_name, rows):
    return (f"const struct {type_name} {name}[{len(rows)}] = {{\n" +
            "".join("    { " + ", ".join(f"{value}U" for value in row) + " },\n"
                    for row in rows) + "};\n")


def compress_zero_lines(image):
    """Lossless line stream: PZL1, line count, then zero or literal runs."""
    require(len(image) % 256 == 0, "PIR image is not line aligned")
    lines = len(image) // 256
    result = bytearray(b"PZL1" + struct.pack("<I", lines))
    cursor = 0
    while cursor < lines:
        zero = not any(image[cursor * 256:(cursor + 1) * 256])
        end = cursor + 1
        while end < lines and (not any(image[end * 256:(end + 1) * 256])) == zero:
            end += 1
        count = end - cursor
        result.extend(struct.pack("<I", count | (0x80000000 if zero else 0)))
        if not zero:
            result.extend(image[cursor * 256:end * 256])
        cursor = end
    return bytes(result)


def write_generated(path, data, verify_existing):
    require(verify_existing or not path.exists(),
            f"refusing to overwrite generated layout: {path}")
    store_or_verify(path, data, path.exists())


def reverse_12(value):
    return int(f"{value:012b}"[::-1], 2)


def packed_pre_twist(psi, modulus):
    """HardwareNttModel K=8 online-PMUL parameter packing for N=4096."""
    physical = lambda index: pow(psi, reverse_12(index), modulus)
    result = [1] * 128
    for lane in range(64):
        result[lane] = physical(lane)
    for slot in range(1, 8):
        result[64 + slot - 1] = physical(64 * slot)
    for ratio in range(3):
        before = 512 * ((1 << ratio) - 1)
        after = 512 * (1 << ratio)
        result[71 + ratio] = physical(after) * pow(physical(before), -1, modulus) % modulus
    return result


def read_dynamic_input_map(path, plaintext_rows, physical_image, moduli):
    """Bind logical CPU plaintexts to package allocations from the producer map."""
    require(path.is_file() and not path.is_symlink(), "producer dynamic input map missing")
    by_id = {row["allocation_id"]: row for row in plaintext_rows}
    require(len(by_id) == 102, "stage1 physical plaintext allocations are not unique")
    with path.open(newline="", encoding="utf-8") as source:
        entries = list(csv.reader(source, delimiter="\t"))
    require(len(entries) == 96, "producer dynamic input map must have 96 limbs")
    result = {}
    allocations = set()
    for fields in entries:
        require(len(fields) == 2, "invalid producer dynamic input map row")
        allocation, filename = fields
        match = re.fullmatch(r"dynamic_(\d+)\.u32\.bin", filename)
        require(match is not None and allocation in by_id,
                "producer dynamic input map has an unknown binding")
        rank = int(match.group(1))
        require(rank < 96 and rank not in result and allocation not in allocations,
                "producer dynamic input map repeats a binding")
        row = by_id[allocation]
        basis_match = re.search(r"/mod(\d+)$", allocation)
        require(basis_match is not None and
                int(basis_match.group(1)) < len(moduli) and
                int(basis_match.group(1)) == rank % 3 and
                int(row["payload_words"]) == N and row["read_only"] == "true",
                "producer dynamic input map limb/modulus shape changed")
        limb_file = path.parent / filename
        require(limb_file.is_file() and not limb_file.is_symlink(),
                "producer dynamic input limb missing")
        offset = int(row["line_offset"]) * LINE_WORDS * 4
        require(limb_file.read_bytes() == physical_image[offset:offset + N * 4],
                "producer dynamic input bytes differ from package image")
        result[rank] = (row, rank, rank % 3)
        allocations.add(allocation)
    require(len(result) == 96 and len(plaintext_rows) - len(allocations) == 6,
            "producer dynamic map does not separate 96 dynamic and 6 fixed limbs")
    return [result[index] for index in range(96)]


def generate(destination, stage0_package, stage1_package, metadata0, metadata1,
             cpu_parameters, dynamic_input_map, verify_existing=False):
    _, _, golden0, parameters0 = package_info(stage0_package)
    manifest1, rows1, golden1, parameters1 = package_info(stage1_package)
    params = read_json(cpu_parameters)
    mod0 = parameters0["levels"][1]["moduli"]
    mod1 = parameters1["levels"][0]["moduli"]
    require(params["degree"] == N and params["plain_bits"] == 20 and
            params["plain_modulus"] == parameters0["plain_modulus"] == parameters1["plain_modulus"] and
            params["stage0_output_moduli"] == mod0 and params["stage1_input_moduli"] == mod1 and
            len(params["stage1_psi"]) == 3 and
            all(pow(psi, N, q) == q - 1 and pow(psi, 2 * N, q) == 1
                for psi, q in zip(params["stage1_psi"], mod1)),
            "CPU parameters disagree with either package")
    compressed_sizes = {}
    for stage, package in (("stage0", stage0_package), ("stage1", stage1_package)):
        original_image = (destination / stage / "image.u32.bin").read_bytes()
        compressed = compress_zero_lines(original_image)
        write_generated(destination / stage / "image.pzl.bin", compressed,
                        verify_existing)
        compressed_sizes[stage] = len(compressed)
    physical_image = (stage1_package / manifest1["image"]).read_bytes()
    for basis, (psi, modulus) in enumerate(zip(params["stage1_psi"], mod1)):
        name = f"constants/twiddle/canonical/mod{basis}/ntt/pre_twist"
        matches = [row for row in rows1 if row["allocation_id"] == name]
        require(len(matches) == 1 and matches[0]["kind"] == "twiddle" and
                int(matches[0]["payload_words"]) == 128,
                "missing package NTT pre-twist binding")
        offset = int(matches[0]["line_offset"]) * 256
        actual = struct.unpack_from("<128I", physical_image, offset)
        require(list(actual) == packed_pre_twist(psi, modulus),
                "CPU psi root differs from stage1 package pre-twist bytes")
    identities0 = list(dict.fromkeys(row["object_id"] for row in golden0))
    require(len(identities0) == 4 and len(golden0) == 16 and len(golden1) == 32,
            "unexpected stage output shape")
    limbs0 = []
    for row in golden0:
        reply = identities0.index(row["object_id"])
        component, basis = int(row["component"]), int(row["modulus_id"])
        require(component < 2 and basis < 2 and int(row["modulus"]) == mod0[basis],
                "stage0 limb identity/modulus mismatch")
        limbs0.append((int(row["line_offset"]), N, reply, component, basis,
                       mod0[basis]))
    plaintext_rows = [row for row in rows1 if row["kind"] == "plaintext"]
    require(len(plaintext_rows) == 102, "stage1 plaintext physical count changed")
    parsed = []
    for row in plaintext_rows:
        match = re.fullmatch(r"frontend/plains/plain_(\d+)/multiply/[^/]+/c0/mod(\d+)",
                             row["allocation_id"])
        require(match is not None, "stage1 plaintext naming changed")
        parsed.append((row, int(match.group(1)), int(match.group(2))))
    identities = {identity for _, identity, _ in parsed}
    require(len(identities) == 34 and
            all({basis for _, index, basis in parsed if index == identity} == {0, 1, 2}
                for identity in identities), "stage1 plaintext identity/modulus shape changed")
    dynamic_bindings = read_dynamic_input_map(
        dynamic_input_map, plaintext_rows, physical_image, mod1)
    limbs1 = []
    for row, rank, basis in dynamic_bindings:
        require(basis < len(mod1), "stage1 dynamic modulus index changed")
        limbs1.append((int(row["line_offset"]), N,
                       (rank // 3) // 4 + ((rank // 3) % 4) * 8,
                       basis, mod1[basis]))
    require(len(limbs1) == 96 and
            {tuple(row[2:4]) for row in limbs1} == {(p, q) for p in range(32) for q in range(3)},
            "stage1 dynamic limb coverage changed")
    window0, window1 = metadata0["WINDOW_LINES"], metadata1["WINDOW_LINES"]
    image0, image1 = metadata0["IMAGE_LINES"], metadata1["IMAGE_LINES"]
    require(window0 <= window1 and max(image0, image1) * 256 < 0x07000000,
            "combined sequential DDR window exceeds workload budget")
    writable = bytearray((destination / "stage1" / "writable.u8.bin").read_bytes())
    require(len(writable) == image1, "stage1 writable bitmap size")
    dynamic_lines = set()
    for line, words, _, _, _ in limbs1:
        require(words == N and line + words // LINE_WORDS <= window1 and
                all(writable[i] == 0 and i not in dynamic_lines
                    for i in range(line, line + words // LINE_WORDS)),
                "dynamic span conflicts with HPU writable or another CPU input")
        dynamic_lines.update(range(line, line + words // LINE_WORDS))
        writable[line:line + words // LINE_WORDS] = b"\x01" * (words // LINE_WORDS)
    write_generated(destination / "stage1" / "cpu_writable.u8.bin", bytes(writable),
                    verify_existing)

    header = f"""#ifndef PIR_UNIFIED_LAYOUT_H
#define PIR_UNIFIED_LAYOUT_H
#include <stdint.h>
#include <pir_cpu.h>
#define CASE_ID "08_04_pir_unified"
#define OUTPUT_COUNT 32U
#define IMAGE_LINES {max(image0, image1)}U
#define GOLDEN_WORDS {metadata1['GOLDEN_WORDS']}U
#define STAGE0_WINDOW_LINES {window0}U
#define STAGE1_WINDOW_LINES {window1}U
#define STAGE0_IMAGE_LINES {image0}U
#define STAGE1_IMAGE_LINES {image1}U
#define STAGE0_COMPRESSED_BYTES {compressed_sizes["stage0"]}U
#define STAGE1_COMPRESSED_BYTES {compressed_sizes["stage1"]}U
#define STAGE0_OUTPUT_COUNT 16U
#define STAGE1_OUTPUT_COUNT 32U
struct output_span {{ unsigned line, words, golden_word, modulus, step, component, modulus_id; }};
extern const uint8_t stage0_compressed_image[STAGE0_COMPRESSED_BYTES];
extern const uint8_t stage1_compressed_image[STAGE1_COMPRESSED_BYTES];
extern const uint32_t stage0_golden_words[16U * PIR_CPU_DEGREE];
extern const uint32_t stage1_golden_words[32U * PIR_CPU_DEGREE];
extern const uint8_t stage0_writable_lines[STAGE0_IMAGE_LINES];
extern const uint8_t stage1_writable_lines[STAGE1_IMAGE_LINES];
extern const uint8_t stage1_cpu_writable_lines[STAGE1_IMAGE_LINES];
extern const struct output_span stage0_outputs[STAGE0_OUTPUT_COUNT];
extern const struct output_span stage1_outputs[STAGE1_OUTPUT_COUNT];
extern const struct pir_cpu_output_limb stage0_cpu_limbs[PIR_CPU_OUTPUT_LIMBS];
extern const struct pir_cpu_input_limb stage1_cpu_limbs[PIR_CPU_INPUT_LIMBS];
extern const struct pir_cpu_parameters pir_parameters;
#endif
"""
    source = '#include "layout.h"\n'
    source += emit_table("stage0_outputs", "output_span", output_table(golden0))
    source += emit_table("stage1_outputs", "output_span", output_table(golden1))
    source += emit_table("stage0_cpu_limbs", "pir_cpu_output_limb", limbs0)
    source += emit_table("stage1_cpu_limbs", "pir_cpu_input_limb", limbs1)
    source += ("const struct pir_cpu_parameters pir_parameters = {\n"
               f"    {N}U, {params['plain_modulus']}U,\n"
               "    { " + ", ".join(f"{v}U" for v in mod0) + " },\n"
               "    { " + ", ".join(f"{v}U" for v in mod1) + " },\n"
               "    { " + ", ".join(f"{v}U" for v in params["stage1_psi"]) + " }\n};\n")
    write_generated(destination / "layout.h", header.encode(), verify_existing)
    write_generated(destination / "layout.c", source.encode(), verify_existing)
    return {"stage0_window_lines": window0, "stage1_window_lines": window1,
            "cpu_plaintext_words": 32 * N, "cpu_input_limbs": len(limbs1),
            "fixed_plaintext_limbs": 6, "combined_ddr_lines": max(image0, image1)}
