"""新前端包接收器：保持native指令和布局，支持scratch allocation内的DMA子区间。"""

import csv

import json

from pathlib import Path

import re

import shutil

import struct

def function_span(code, name):
    matches = list(re.finditer(r"\bint " + re.escape(name) + r"\([^{};]*\) \{", code))
    if len(matches) != 1:
        raise ValueError(f"missing/duplicate producer entry: {name}")
    match = matches[0]
    depth = 0
    tokens = re.compile(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{}]', re.S)
    for token in tokens.finditer(code, match.end() - 1):
        if token[0] == "{":
            depth += 1
        elif token[0] == "}":
            depth -= 1
            if depth == 0:
                return match.start(), token.end()
    raise ValueError(f"unbalanced producer entry: {name}")

def instruction_words(code):
    return [int(word, 16) for word in re.findall(r'\.word (0x[0-9a-fA-F]+)', code)]

def resolved_spans(code):
    return [(int(first), int(count)) for first, count in re.findall(
        r'\{ UINT32_C\((\d+)\), UINT32_C\((\d+)\) \}', code)]

def validate_fixed_entry(code, stem, words, spans):
    """精确接受上游fixed模板；只读既有word，绝不重新编码HPU指令。"""
    begin, end = function_span(code, "hpu_run_" + stem)
    lines = [f"int hpu_run_{stem}(void) {{"]
    if spans:
        lines.append(f"    (void)hpu_program_{stem}_resolved_spans;")
    lines += ["#if defined(__riscv)", "    __asm__ volatile("]
    index, previous_count = 0, None
    for word in words:
        if word & 0x7f == 0x2b:
            if index >= len(spans):
                raise ValueError("fixed entry DMA span count differs")
            first, count = spans[index]
            index += 1
            lines.append(f'        "li x10, {first}\\n\\t"')
            if count != previous_count:
                lines.append(f'        "li x11, {count}\\n\\t"')
                previous_count = count
        lines.append(f'        ".word 0x{word:08X}\\n\\t"')
    lines += ['        : : : "x10", "x11", "memory");', "    return 0;",
              "#else", "    return -4;", "#endif", "}"]
    if index != len(spans) or code[begin:end] != "\n".join(lines):
        raise ValueError("fixed entry differs from native single-asm DMA/x11 template")
    return begin, end

def validate_source(code, stem, words, spans):
    begin, end = function_span(code, "hpu_program_" + stem)
    if instruction_words(code[begin:end]) != words or instruction_words(code) != words + words:
        raise ValueError("producer C/INST32 dynamic/fixed entries mismatch")
    if resolved_spans(code) != spans:
        raise ValueError("C resolved spans/DMA manifest mismatch")
    validate_fixed_entry(code, stem, words, spans)

GUARD_LINES = 64

NTT_ABI = {
    "version": 4, "coefficient_order": "bit_reversed", "external_coefficient_order": "natural",
    "pre_twist_order": "bit_reversed", "post_factor_order": "bit_reversed",
    "stage_twiddle_order": "reference_loader_batch_lane",
    "stage_twiddle_format": "hpu-twiddle-k8-v1", "twiddle_chains": 8,
    "stage_parameter_lines": 2,
    "online_pmul_format": "hpu-pmul-online-k8-v1", "online_pmul_parameter_lines": 2,
    "online_pmul_mode": 1, "online_pmul_parameter_bank_mask": 32,
    "canonical_ntt_layout": "reference_forward_layout",
    "normalization": "explicit_post_pmul", "twist_fused": False,
}

ISA_ABI = {
    "instruction_isa": "hpu-objects64-v1.2", "object_slots": 64,
    "allocation_granule_lines": 128, "mod_table_lines": 4,
    "stage_parameter_mod": 0, "stage_parameter_bank_mask": 32,
    "default_cp": 0, "dma_cache_policy": "twiddle_loads_only",
    "dma_format": "mod_rel_cp", "dload_mask_scope": "load_only",
    "dstore_rel0_retains": True,
}

DMA_COLUMNS = ["instruction_index", "dma_index", "operation_index", "operation_id",
               "operation_dma_index", "direction", "object_slot", "type_or_release", "flag",
               "allocation_id", "line_offset", "line_count", "word_hex", "normalized_asm", "cp"]

def validate_isa_contract(memory_abi):
    require(all(memory_abi.get(key) == value for key, value in ISA_ABI.items()),
            "64-object ISA v1.2/MOD-REL-CP/cache policy ABI mismatch")

def require(condition, message):
    if not condition:
        raise ValueError(message)

def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))

def read_rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))

def safe_file(root, relative):
    name = Path(relative)
    require(not name.is_absolute() and ".." not in name.parts, "unsafe package path")
    path = (root / name).resolve()
    require(path.is_relative_to(root.resolve()) and path.is_file(), f"missing file: {name}")
    return path

def validate_dma(words, dma, allocations, operations, used):
    """允许arena子区间，但禁止越界、写只读区和丢失指令/应用图来源。"""
    by_id = {row["allocation_id"]: row for row in allocations}
    require(len(by_id) == len(allocations), "duplicate allocation")
    require([int(row["instruction_index"]) for row in dma] ==
            [i for i, word in enumerate(words) if word & 0x7f == 0x2b], "DMA order mismatch")
    writable, first_access = set(), {}
    for index, row in enumerate(dma):
        allocation = by_id.get(row["allocation_id"])
        require(allocation is not None and int(row["dma_index"]) == index, "DMA allocation/index")
        first, count = int(row["line_offset"]), int(row["line_count"])
        base, size = int(allocation["line_offset"]), int(allocation["line_count"])
        require(count > 0 and base <= first and first + count <= base + size <= used,
                "DMA subspan outside allocation/window")
        inst = words[int(row["instruction_index"])]
        require(inst == int(row["word_hex"], 16) and (inst >> 15) & 31 == 10 and
                (inst >> 20) & 31 == 11, "DMA word/register ABI mismatch")
        direction = "dstore" if (inst >> 12) & 1 else "dload"
        flag = ((inst >> 7) & 31) | (((inst >> 25) & 1) << 5)
        require(row["direction"] == direction and int(row["object_slot"]) == (inst >> 26) & 63 and
                int(row["type_or_release"]) == (inst >> 14) & 1 and
                int(row["flag"]) == flag and int(row["cp"]) == (inst >> 13) & 1,
                "DMA v1.2 object/MOD-REL/CP/mask fields differ from instruction")
        require(direction != "dstore" or flag == 0, "DSTORE mask is reserved")
        expected_cp = int(direction == "dload" and allocation["kind"] == "twiddle")
        require(int(row["cp"]) == expected_cp, "DMA twiddle-only LLC cache policy mismatch")
        for line in range(first, first + count):
            first_access.setdefault(line, row["direction"])
        if row["direction"] == "dstore":
            require(allocation["read_only"] == "false", "DSTORE into readonly allocation")
            writable.update(range(first, first + count))
        op_index = row["operation_index"]
        require((not op_index and row["operation_id"] == "$application") or
                (op_index and 0 <= int(op_index) < len(operations) and
                 operations[int(op_index)]["id"] == row["operation_id"]), "DMA graph mismatch")
    return writable, first_access

def validate_ntt_contract(parameters, memory_abi, allocations, degree):
    require(parameters.get("ntt_table_abi") == NTT_ABI, "online K=8 NTT/PMUL table ABI v4 required")
    require(all(memory_abi.get(key) == NTT_ABI[key] for key in
                ("stage_twiddle_format", "twiddle_chains", "stage_parameter_lines",
                 "online_pmul_format", "online_pmul_parameter_lines", "online_pmul_mode",
                 "online_pmul_parameter_bank_mask")),
            "memory/parameters online twiddle ABI mismatch")
    for row in allocations:
        if re.search(r"/(ntt|intt)/stage\d+$", row["allocation_id"]):
            require(row["kind"] == "twiddle" and row["read_only"] == "true" and
                    int(row["payload_words"]) == int(row["padded_words"]) == 128 and
                    int(row["line_count"]) == 2, "stage twiddle must be a readonly two-line K=8 object")
        elif row["allocation_id"].endswith(("/pre_twist", "/post_untwist_scale")):
            require(row["kind"] == "twiddle" and row["read_only"] == "true" and
                    int(row["payload_words"]) == int(row["padded_words"]) == 128 and
                    int(row["line_count"]) == 2, "pre/post online PMUL must use readonly two-line templates")

def exported_steps(graph):
    """SSA中间值可留在片上；所有显式导出结果仍必须完整校验。"""
    operations = graph.get("operations")
    require(isinstance(operations, list) and operations and
            all(type(op.get("exported")) is bool for op in operations),
            "every operation must declare a boolean exported flag")
    selected = {index for index, op in enumerate(operations) if op["exported"]}
    roots = {operations[index].get("output") for index in selected}
    require(selected and all(isinstance(root, str) and root for root in roots) and
            graph.get("final_output") in roots, "final output must be exported")
    for index, operation in enumerate(operations):
        require((operation.get("golden_object_id") == f"step_{index}") if index in selected
                else "golden_object_id" not in operation, "export/golden object metadata mismatch")
    if "marked_outputs" in graph:
        marked = graph["marked_outputs"]
        require(isinstance(marked, list) and marked and
                all(isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"] and
                    isinstance(row.get("physical_output"), str) for row in marked),
                "invalid marked outputs")
        require(len({row["id"] for row in marked}) == len(marked) and
                {row["physical_output"] for row in marked} == roots,
                "marked outputs differ from exported operations")
    return selected

def import_package(source, destination, spec):
    package = read_json(source / "package.json")
    scheme = "bfv"
    degree = int(spec["degree"])
    stem = spec["program_stem"]
    require(package.get("schema") == "hpu-application-package" and package.get("schema_version") == 1 and
            package.get("scheme") == scheme and package.get("case_name") == stem and
            [package.get(k) for k in ("word_bits", "line_words", "line_bytes", "byte_order")] ==
            [32, 64, 256, "little-endian"], "frontend package ABI/case mismatch")
    keys = ("parameters", "operation_graph", "program_source", "program_header", "program_inst32",
            "dma_relocation_manifest", "image", "line_map", "memory_manifest", "memory_config", "memory_abi",
            "golden_manifest")
    files = {key: safe_file(source, package[key]) for key in keys}
    parameters = read_json(files["parameters"])
    require(parameters.get("scheme") == scheme and parameters.get("poly_modulus_degree") == degree,
            "frontend parameters scheme/degree mismatch")
    config = read_json(files["memory_config"])
    used = config["used_lines"]
    require(type(used) is int and 0 < used == config["capacity_lines"] < 1 << 32,
            "image must be trimmed to actual lines")
    # ELF镜像从0x80000000加载，DDR从0x87000000起；构建后另做实际ELF段重叠检查。
    require((used + GUARD_LINES) * 256 < 0x04000000, "application exceeds lane DDR stride")
    image = bytearray(files["image"].read_bytes())
    require(len(image) == used * 256, "image length mismatch")
    graph = read_json(files["operation_graph"])
    operations = graph["operations"]
    selected_steps = exported_steps(graph)
    allocations = read_rows(files["line_map"])
    memory_abi = read_json(files["memory_abi"])
    validate_isa_contract(memory_abi)
    validate_ntt_contract(parameters, memory_abi, allocations, degree)
    fields = ("allocation_id", "kind", "read_only", "line_offset", "line_count",
              "payload_words", "padded_words", "initialization")
    require([{key: row[key] for key in fields} for row in allocations] ==
            [{key: row[key] for key in fields} for row in read_rows(files["memory_manifest"])],
            "memory manifests differ")
    end = 0
    for allocation in sorted(allocations, key=lambda row: int(row["line_offset"])):
        first, count = int(allocation["line_offset"]), int(allocation["line_count"])
        require(end <= first and count > 0 and first + count <= used and
                int(allocation["padded_words"]) == count * 64, "overlapping/malformed allocation")
        end = first + count
    words = [int(word, 2) for word in files["program_inst32"].read_text().split()]
    code = files["program_source"].read_text()
    require(words and words[-1] == 0x7000005b and words.count(0x7000005b) == 1 and
            all(word & 0x7f in (0x2b, 0x5b) for word in words), "opcode/terminal PSYNC mismatch")
    dma = read_rows(files["dma_relocation_manifest"])
    require(dma and list(dma[0]) == DMA_COLUMNS, "v1.2 resolved DMA manifest requires 15 columns")
    validate_source(code, stem, words, [(int(row["line_offset"]), int(row["line_count"])) for row in dma])
    writable, first_access = validate_dma(words, dma, allocations, operations, used)
    levels = {tuple(level["parms_id"]): level["moduli"] for level in parameters["levels"]}
    output_domain = "coefficient_bit_reversed"
    by_span = {(int(row["line_offset"]), int(row["line_count"])): row for row in allocations}
    golden, outputs, order = bytearray(), [], []
    for row in read_rows(files["golden_manifest"]):
        step, component, mod_id = int(row["object_id"].removeprefix("step_")), int(row["component"]), int(row["modulus_id"])
        require(step in selected_steps, "golden must belong to an exported operation")
        moduli = levels[tuple(operations[step]["parms_id"])]
        require(0 <= mod_id < len(moduli) and 0 <= component < operations[step]["component_count"],
                "invalid golden component/modulus")
        first, count, q = int(row["line_offset"]), int(row["line_count"]), moduli[mod_id]
        allocation = by_span.get((first, count))
        require(allocation is not None and allocation["kind"] == "output" and
                all(first_access.get(line) == "dstore" for line in range(first, first + count)),
                "golden must be a write-first pinned output")
        require(int(row["modulus"]) == q and 0 < q < 1 << 32 and
                int(row["payload_words"]) == int(row["padded_words"]) == count * 64 == degree and
                row["domain"] == output_domain,
                "golden shape/domain/modulus mismatch")
        data = safe_file(source, row["path"]).read_bytes()
        require(len(data) == degree * 4 and all(value < q for value, in struct.iter_unpack("<I", data)),
                "noncanonical/truncated golden")
        outputs.append((first, degree, len(golden) // 4, q, step, component, mod_id))
        order.append((step, component, mod_id))
        golden += data
        image[first * 256:(first + count) * 256] = b"\xff" * (count * 256)
    expected_order = [(step, component, mod_id) for step, op in enumerate(operations)
                      if step in selected_steps for component in range(op["component_count"])
                      for mod_id in range(len(levels[tuple(op["parms_id"])]))]
    require(order == expected_order, "incomplete golden coverage")
    # 只毒化写先输出；scratch、输入、twiddle和密钥保持原样，无旧BFV/CKKS重排补丁。
    image += struct.pack("<I", 0xa5a55a5a) * (64 * GUARD_LINES)
    destination.mkdir(parents=True)
    (destination / "image.u32.bin").write_bytes(image)
    (destination / "golden.u32.bin").write_bytes(golden)
    (destination / "writable.u8.bin").write_bytes(
        bytes(int(line in writable) for line in range(used + GUARD_LINES)))
    for key, suffix in (("program_source", "c"), ("program_header", "h")):
        shutil.copy2(files[key], destination / f"{stem}.{suffix}")
    (destination / f"{stem}.inst32").write_bytes(files["program_inst32"].read_bytes())
    constants = {"DEGREE": degree, "WINDOW_LINES": used, "IMAGE_LINES": used + GUARD_LINES,
                 "GOLDEN_WORDS": len(golden) // 4, "OUTPUT_COUNT": len(outputs),
                 "INSTRUCTION_COUNT": len(words), "DMA_COUNT": len(dma)}
    header = '#ifndef FRONTEND_LAYOUT_H\n#define FRONTEND_LAYOUT_H\n#include <stdint.h>\n'
    header += f'#define CASE_ID "{spec["case_id"]}"\n'
    header += f'#define LEVEL {int(spec["level"])}U\n'
    header += f'#define CASE_PURPOSE {json.dumps(spec.get("purpose", spec["operation"]), ensure_ascii=False)}\n'
    header += "\n".join(f"#define {name} {value}U" for name, value in constants.items())
    header += '\nstruct output_span { unsigned line, words, golden_word, modulus, step, component, modulus_id; };\n'
    header += 'extern const struct output_span outputs[OUTPUT_COUNT];\n#endif\n'
    (destination / "layout.h").write_text(header)
    table = '#include "layout.h"\nconst struct output_span outputs[OUTPUT_COUNT] = {\n'
    table += "\n".join("    { " + ", ".join(f"{value}U" for value in row) + " }," for row in outputs)
    (destination / "layout.c").write_text(table + "\n};\n")
    return constants
