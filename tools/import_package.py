"""新前端包接收器：保持native指令和布局，支持scratch allocation内的DMA子区间。"""
import csv
import json
from pathlib import Path
import re
import shutil
import struct

from performance_adapter import validate_source

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


def expected_operations(scheme, operation):
    return {
        "keyswitch": ["relinearize"], "hadd": ["add"],
        "hmul": ["multiply", "relinearize"], "reline": ["relinearize"],
        "modswitch": ["rescale" if scheme == "ckks" else "mod_switch"],
        "rotate": ["rotate" if scheme == "ckks" else "rotate_rows"],
    }[operation]


DEGREES = (128, 1024, 2048, 4096, 8192)
INSTRUCTIONS = {"padd": 4, "psub": 4, "pmul": 10, "pmac": 4, "pntt": 6,
                "pintt": 6, "pmodld": 4, "psync": 2, "pfree": 2}


def package_profile(spec):
    """所有参数来自唯一清单；原语、裸指令与密文库接口不能互相冒充。"""
    scheme, degree, level = spec["scheme"], int(spec["degree"]), int(spec["level"])
    kind, profile = spec.get("kind"), spec.get("profile")
    require(degree in DEGREES and 1 <= level <= 4, "unsupported degree/level")
    require(re.fullmatch(r"0[3-8]_\d{2}_[a-z0-9_]+", spec["case_id"]) is not None,
            "unsupported native case identity")
    if spec["case_id"][:2] in ("03", "04", "05"):
        require((degree, level) == (1024, 4), "03～05 require N1024/L4")
    stem = spec["program_stem"]
    require(re.fullmatch(r"[a-z][a-z0-9_]+", stem) is not None, "unsafe functional stem")
    if kind == "instruction":
        require(spec["case_id"].startswith("03_") and profile == "instruction" and scheme == "raw" and
                spec["operation"] in INSTRUCTIONS and
                stem == f'instruction_{spec["operation"]}_l{level}_n{degree}',
                "instruction identity/profile mismatch")
    elif kind == "native":
        require(spec["case_id"][:2] in ("04", "05", "06") and
                (scheme in ("ckks", "bfv", "bgv") or profile == "primitive" and scheme == "raw"),
                "unsupported functional group identity/parameters")
        require(not (level == 1 and spec["operation"] == "modswitch"),
                "rescale/modswitch requires input level >= 2")
        require(not (scheme == "bfv" and level == 1 and spec["operation"] == "hmul"),
                "BFV HMUL requires input level >= 2")
        if profile == "primitive":
            require(spec["case_id"].startswith("04_") and scheme == "raw" and
                    spec["operation"] in ("bconv", "ntt", "intt") and
                    stem == f'{spec["operation"]}_l{level}_n{degree}',
                    "primitive identity/parameters mismatch")
    elif kind == "performance":
        require(spec["case_id"].startswith("07_") and degree in (1024, 8192) and
                scheme in ("ckks", "bfv", "bgv"), "unsupported 07 scheme/degree")
        operation, variant = spec["operation"], spec["variant"]
        require(operation in ("keyswitch", "hadd", "hmul", "reline", "modswitch", "rotate"),
                "unsupported 07 operator")
        require(level == 4, "unsupported 07 level: requires L4 for every scheme")
        require(variant in ("optimized", "noopt"), "unsupported resource variant")
        require(stem == f"frontend_{scheme}_{operation}_l{level}_n{degree}", "explicit program stem mismatch")
    elif kind == "application":
        applications = {
            "08_01_psi_single": ("psi_single", "bfv_apsi_concentrated_application", 8192, 4),
            "08_02_pir_stage0": ("pir_stage0", "bfv_sealpir_2d_small_stage0_concentrated_000", 4096, 3),
            "08_03_pir_stage1": ("pir_stage1", "bfv_sealpir_2d_small_stage1_concentrated_000", 4096, 3),
        }
        require(scheme == "bfv" and profile == "application" and
                (spec.get("operation"), stem, degree, level) == applications.get(spec["case_id"]),
                "unsupported 08 application identity/parameters")
    else:
        raise ValueError("unsupported package kind")
    base, ram = int(spec["memory_base"], 0), int(spec["minimum_ram_bytes"])
    require((base, ram) == ((0x90000000, 536870912) if kind == "performance" else (0x87000000, 268435456)),
            "native memory contract mismatch")
    return stem, base, ram, kind == "performance"

def validate_capacity(spec, used):
    stem, base, ram, performance = package_profile(spec)
    require(type(used) is int and 0 < used < 1 << 32, "invalid actual image line count")
    size = (used + GUARD_LINES) * 256
    if performance:
        require(base + size <= 0x80000000 + ram, "image exceeds explicit 07 RAM contract")
    else:
        require(size < 0x07000000, "image exceeds workload memory budget")
    return stem, base, ram, performance


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def store_or_verify(path, data, existing):
    if not existing:
        path.write_bytes(data)
        return
    require(not path.is_symlink() and path.is_file() and path.stat().st_size == len(data),
            f"cached delivery missing/size mismatch: {path.name}")
    view = memoryview(data)
    with path.open("rb") as stream:
        for offset in range(0, len(data), 1024 * 1024):
            require(stream.read(1024 * 1024) == view[offset:offset + 1024 * 1024],
                    f"cached delivery content differs: {path.name}")


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


def validate_host(report):
    require(report.get("overall_status") == "pass" and all(report.get(k) is True for k in
            ("oracle_verified", "golden_matches_oracle", "model_verified", "raw_physical_words_equal",
             "host_instruction_model_verified", "optimization_equivalence_verified")),
            "frontend oracle/model/equivalence not verified")
    model = report.get("host_instruction_model", {})
    require(model.get("status") == "pass" and model.get("required") is True and
            model.get("verified") is True and model.get("ntt_contract") == "raw_bit_reversed_coefficients",
            "strict raw-stage bit-reversed instruction verification required")
    require(model.get("hardware_contract_verified") is False and all(report.get(k) is False for k in
            ("instruction_execution_verified", "rtl_verified", "hardware_verified")),
            "host package must not claim hardware execution")


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


def primitive_outputs(spec, parameters, operations):
    """QL→P3与逐Q分量NTT均无密文parms_id，不能伪造SEAL密文元数据。"""
    operation, level = spec["operation"], int(spec["level"])
    require(len(operations) == 1 and operations[0].get("id") == "tested" and
            operations[0].get("kind") == operation and operations[0].get("operation_index") == 0 and
            operations[0].get("golden_object_id") == "step_0", "primitive graph mismatch")
    levels, moduli = parameters["levels"], parameters["key_moduli"]
    require(len(levels) == 1 and len(moduli) >= level and levels[0]["moduli"] == moduli[:level] and
            all(type(q) is int and 65537 <= q < 1 << 32 for q in moduli) and
            len(set(moduli)) == len(moduli), "primitive modulus table/level mismatch")
    if operation == "bconv":
        expected = [50061313, 50077697, 50307073, 50552833][:level] + [90062849, 90095617, 90218497]
        require(moduli == expected, "04 BConv requires the declared Q-prefix to P3 bases")
        return {index: moduli[index] for index in range(level, level + 3)}, "coefficient"
    require(operation in ("ntt", "intt") and len(moduli) == level + 1,
            "04 transform requires its complete QL/P1 modulus table")
    return {index: moduli[index] for index in range(level)}, (
        "coefficient_bit_reversed" if operation == "intt" else "canonical_ntt_physical")


def instruction_contract(spec, parameters, graph, report):
    """裸模指令的独立数学/单stage门禁；不要求或捏造SEAL和优化等价报告。"""
    level, operation = int(spec["level"]), spec["operation"]
    moduli = [2013265921, 1811939329, 469762049, 998244353][:level]
    require(parameters.get("test_layer") == "instruction" and parameters.get("encrypted") is False and
            parameters.get("plain_modulus") == 0 and parameters.get("input_rns_components") == level and
            parameters.get("context_moduli") == parameters.get("key_moduli") == moduli and
            parameters.get("levels") == [{"moduli": moduli}],
            "instruction parameters must declare raw modular, not encrypted SEAL")
    require(report.get("test_layer") == "instruction" and report.get("overall_status") == "pass" and
            report.get("oracle") == "independent_u64_modular_and_C_stage_golden" and
            all(report.get(key) is True for key in ("oracle_verified", "golden_matches_oracle",
                "model_verified", "raw_physical_words_equal", "readonly_and_guard_verified",
                "host_instruction_model_verified")), "independent instruction oracle/model not verified")
    model = report.get("host_instruction_model", {})
    require(model.get("required") is True and model.get("verified") is True and
            model.get("status") == "pass" and model.get("ntt_contract") == "legacy_raw_stage" and
            model.get("hardware_contract_verified") is False and
            all(report.get(key) is False for key in
                ("instruction_execution_verified", "rtl_verified", "hardware_verified")),
            "instruction host model cannot claim hardware verification")
    require("compiler_resources" not in report and "optimization_equivalence_verified" not in report,
            "instruction package must not fabricate resource compiler/SEAL equivalence")
    operations = graph.get("operations")
    count = INSTRUCTIONS[operation]
    require(graph.get("test_layer") == "instruction" and
            graph.get("component_semantics") == "scenario_not_ciphertext" and
            graph.get("component_count") == count and len(operations) == 1 and
            operations[0].get("kind") == operation and graph.get("terminal_psync_count") == 1 and
            graph.get("timing_verified") is False and graph.get("irq_rearm_verified") is False,
            "instruction graph/scenario contract mismatch")
    scenarios = graph.get("scenario_outputs")
    require(isinstance(scenarios, list) and len(scenarios) == count * level and
            all(isinstance(row.get("scenario"), str) and row["scenario"] for row in scenarios) and
            {(row.get("component"), row.get("modulus_id")) for row in scenarios} ==
                {(component, limb) for component in range(count) for limb in range(level)},
            "instruction scenario outputs must cover every RNS/context variant")
    require(model.get("compared_words") == int(spec["degree"]) * len(scenarios),
            "instruction model comparison coverage differs")
    return moduli, scenarios

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


def validate_operation_levels(spec, parameters, operations):
    """单算子的输出层由输入L和运算推导，不能仅相信包内任意parms_id。"""
    source = parameters["levels"][0]["moduli"]
    expected_level = int(spec["level"]) - int(spec["operation"] == "modswitch")
    contexts = {tuple(level["parms_id"]): level["moduli"] for level in parameters["levels"]}
    require(expected_level > 0 and all(contexts.get(tuple(op.get("parms_id", ()))) == source[:expected_level]
                                     for op in operations),
            "operator output Q-RNS context differs from the derived level")


def import_package(source, destination, spec, commit, verify_existing=False):
    package = read_json(source / "package.json")
    scheme = "ckks" if spec.get("kind") == "instruction" or spec.get("profile") == "primitive" else spec["scheme"]
    degree = int(spec["degree"])
    stem, memory_base, minimum_ram, performance = package_profile(spec)
    require(package.get("schema") == "hpu-application-package" and package.get("schema_version") == 1 and
            package.get("scheme") == scheme and package.get("case_name") == stem and
            [package.get(k) for k in ("word_bits", "line_words", "line_bytes", "byte_order")] ==
            [32, 64, 256, "little-endian"], "frontend package ABI/case mismatch")
    keys = ("parameters", "operation_graph", "program_source", "program_header", "program_inst32",
            "dma_relocation_manifest", "image", "line_map", "memory_manifest", "memory_config", "memory_abi",
            "golden_manifest", "oracle_report")
    files = {key: safe_file(source, package[key]) for key in keys}
    provenance = read_json(source / "provenance/build.json")
    require(provenance.get("commit") == commit and
            provenance.get("worktree_state") == "clean-at-configure", "producer revision/cleanliness mismatch")
    parameters, report = read_json(files["parameters"]), read_json(files["oracle_report"])
    require(parameters.get("scheme") == scheme and parameters.get("poly_modulus_degree") == degree,
            "frontend parameters scheme/degree mismatch")
    instruction = spec.get("kind") == "instruction"
    if not instruction:
        validate_host(report)
    config = read_json(files["memory_config"])
    used = config["used_lines"]
    require(type(used) is int and 0 < used == config["capacity_lines"] < 1 << 32,
            "image must be trimmed to actual lines")
    # ELF镜像从0x80000000加载，DDR从0x87000000起；构建后另做实际ELF段重叠检查。
    validate_capacity(spec, used)
    image = bytearray(files["image"].read_bytes())
    require(len(image) == used * 256, "image length mismatch")
    graph = read_json(files["operation_graph"])
    operations = graph["operations"]
    selected_steps = exported_steps(graph)
    if spec.get("kind") == "native":
        require(len(parameters["levels"][0]["moduli"]) == int(spec["level"]),
                "functional input Q-RNS count differs from its catalog")
        if spec.get("profile") in ("kernel", "library", "regression"):
            require([row["kind"] for row in operations] == expected_operations(scheme, spec["operation"]),
                    "functional operation graph differs from the requested operator")
            validate_operation_levels(spec, parameters, operations)
        if spec.get("expected_operations"):
            require([row["kind"] for row in operations] == spec["expected_operations"],
                    "functional graph differs from its declared coverage")
    if performance:
        require([row["kind"] for row in operations] == expected_operations(scheme, spec["operation"]),
                "07 operation graph differs from the requested operator")
        require(len(parameters["levels"][0]["moduli"]) == int(spec["level"]),
                "07 input Q-RNS count differs from level")
        validate_operation_levels(spec, parameters, operations)
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
    primitive = spec.get("profile") == "primitive"
    if instruction:
        instruction_moduli, scenarios = instruction_contract(spec, parameters, graph, report)
        output_domain = "canonical_ntt_physical" if spec["operation"] in ("pntt", "pintt") else "coefficient"
        levels = {}
    elif primitive:
        primitive_moduli, output_domain = primitive_outputs(spec, parameters, operations)
        levels = {}
    else:
        levels = {tuple(level["parms_id"]): level["moduli"] for level in parameters["levels"]}
        output_domain = "coefficient_bit_reversed" if scheme == "bfv" else "canonical_ntt_physical"
    by_span = {(int(row["line_offset"]), int(row["line_count"])): row for row in allocations}
    golden, outputs, order = bytearray(), [], []
    for row in read_rows(files["golden_manifest"]):
        step, component, mod_id = int(row["object_id"].removeprefix("step_")), int(row["component"]), int(row["modulus_id"])
        require(step in selected_steps, "golden must belong to an exported operation")
        if instruction:
            moduli = instruction_moduli
            require(step == 0 and 0 <= mod_id < len(moduli) and
                    0 <= component < graph["component_count"], "invalid instruction scenario/modulus")
        elif primitive:
            moduli = primitive_moduli
            require(step == 0 and component == 0 and mod_id in moduli, "invalid primitive golden component/modulus")
        else:
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
    expected_order = ([(0, item["component"], item["modulus_id"]) for item in scenarios] if instruction else
                      [(0, 0, mod_id) for mod_id in primitive_moduli] if primitive else
                      [(step, component, mod_id) for step, op in enumerate(operations) if step in selected_steps
                       for component in range(op["component_count"])
                       for mod_id in range(len(levels[tuple(op["parms_id"])]))])
    require(order == expected_order and (instruction or len(order) == report["verified_limb_count"]),
            "incomplete golden coverage")
    if instruction:
        for item, output in zip(scenarios, outputs):
            first, words_count, _, modulus, step, component, mod_id = output
            require((item.get("line_offset"), item.get("line_count"), item.get("words"), item.get("modulus")) ==
                    (first, degree // 64, words_count, modulus), "instruction scenario span/modulus mismatch")
    # 只毒化写先输出；scratch、输入、twiddle和密钥保持原样，无旧BFV/CKKS重排补丁。
    image += struct.pack("<I", 0xa5a55a5a) * (64 * GUARD_LINES)
    existing = destination.exists()
    require(not existing or verify_existing,
            "refusing to overwrite imported delivery")
    require(not destination.is_symlink(), "imported delivery cannot be a symlink")
    if not existing:
        destination.mkdir(parents=True)
    store_or_verify(destination / "image.u32.bin", image, existing)
    store_or_verify(destination / "golden.u32.bin", golden, existing)
    store_or_verify(destination / "writable.u8.bin", bytes(int(line in writable) for line in range(used + GUARD_LINES)), existing)
    for key, suffix in (("program_source", "c"), ("program_header", "h")):
        if existing:
            store_or_verify(destination / f"{stem}.{suffix}", files[key].read_bytes(), True)
        else:
            shutil.copy2(files[key], destination / f"{stem}.{suffix}")
    store_or_verify(destination / f"{stem}.inst32", files["program_inst32"].read_bytes(), existing)
    program_header = stem + ("_perf.h" if performance else ".h")
    store_or_verify(destination / "program.h", f'#include "{program_header}"\n'.encode(), existing)
    constants = {"DEGREE": degree, "WINDOW_LINES": used, "IMAGE_LINES": used + GUARD_LINES,
                 "GOLDEN_WORDS": len(golden) // 4, "OUTPUT_COUNT": len(outputs),
                 "INSTRUCTION_COUNT": len(words), "DMA_COUNT": len(dma)}
    header = '#ifndef FRONTEND_LAYOUT_H\n#define FRONTEND_LAYOUT_H\n#include <stdint.h>\n'
    header += f'#define CASE_ID "{spec["case_id"]}"\n'
    header += f'#define LEVEL {int(spec["level"])}U\n'
    header += f'#define CASE_PURPOSE {json.dumps(spec.get("purpose", spec["operation"]), ensure_ascii=False)}\n'
    if performance:
        header += f'#define SCHEDULE_PROFILE "{spec["variant"]}"\n'
    header += "\n".join(f"#define {name} {value}U" for name, value in constants.items())
    header += '\nstruct output_span { unsigned line, words, golden_word, modulus, step, component, modulus_id; };\n'
    header += 'extern const struct output_span outputs[OUTPUT_COUNT];\n#endif\n'
    store_or_verify(destination / "layout.h", header.encode(), existing)
    table = '#include "layout.h"\nconst struct output_span outputs[OUTPUT_COUNT] = {\n'
    table += "\n".join("    { " + ", ".join(f"{value}U" for value in row) + " }," for row in outputs)
    store_or_verify(destination / "layout.c", (table + "\n};\n").encode(), existing)
    metadata = {**spec, **constants, "program_stem": stem, "producer_commit": commit,
                "ntt_table_abi": NTT_ABI, "instruction_abi": ISA_ABI, "hardware_verified": False,
                "status": "BUILD_READY_NOT_IT_PASS", "layout_adaptation": "none",
                "test_layer": "instruction" if instruction else "native",
                "encrypted": False if instruction else spec.get("profile") != "primitive"}
    if not instruction:
        metadata["compiler_resources"] = {key: value for key, value in report["compiler_resources"].items()
                                          if key != "logical_buffers"}
    if performance:
        metadata.update(memory_base=hex(memory_base), minimum_ram_bytes=minimum_ram,
                        level=int(spec["level"]), node_operations=[row["kind"] for row in operations])
    store_or_verify(destination / "delivery.json", (json.dumps(metadata, indent=2) + "\n").encode(), existing)
    return metadata
