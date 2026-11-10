"""适配在线K=8生产者；固定发令入口及其单asm/x11复用保持原样。"""
import json
from pathlib import Path
import re


RETURN_BLOCK = "#if !defined(__riscv)\n    return -4;\n#else\n    return 0;\n#endif"


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


def preflight_source(original, stem):
    """保留dynamic校验及对象长度追踪，剥离明确的发令区；未知语句拒收。"""
    if original.count(RETURN_BLOCK) != 1 or "trace_issue" in original:
        raise ValueError("unexpected online producer instruction/return template")
    preflight = re.sub(r"^#if defined\(__riscv\)\n.*?^#endif\n", "", original, flags=re.M | re.S)
    preflight = preflight.replace(RETURN_BLOCK, "    return 0;")
    if "__asm__" in preflight or instruction_words(preflight):
        raise ValueError("preflight must not issue any instruction")
    # 确认剩余C正好是已知生产者的校验/长度追踪，不把未知调用移出计时来掩盖变化。
    checked = re.sub(r"    /\*[^\n]*\*/\n", "", preflight)
    checked, count = re.subn(
        r"^    if \(span_count != HPU_PROGRAM_[A-Z0-9_]+_DMA_COUNT \|\| \(span_count != 0 && spans == NULL\)\) return -1;\n",
        "", checked, flags=re.M)
    if count != 1:
        raise ValueError("producer span-count check changed")
    span_loop = ("    for (size_t i = 0; i < span_count; ++i) {\n"
                 "        if (spans[i].line_count == 0 ||\n"
                 "            spans[i].line_offset >= HPU_MEM_LINE_COUNT ||\n"
                 "            spans[i].line_count > HPU_MEM_LINE_COUNT - spans[i].line_offset)\n"
                 "            return -2;\n    }\n")
    if checked.count(span_loop) != 1:
        raise ValueError("producer span-range loop changed")
    checked = checked.replace(span_loop, "")
    checks = (
        r"^    if \(spans\[\d+\]\.line_count > (?:4|28|1024)\) return -3;\n",
        r"^    if \(hpu_obj_len\[(\d+)\] == 0 \|\| spans\[\d+\]\.line_count != hpu_obj_len\[\1\]\) return -5;\n",
        r"^    hpu_obj_len\[\d+\] = (?:0|spans\[\d+\]\.line_count|hpu_obj_len\[\d+\]);\n",
        r"^    if \(hpu_obj_len\[\d+\] == 0(?: \|\| hpu_obj_len\[\d+\] != hpu_obj_len\[\d+\]){0,2}\) return -6;\n",
        # 在线PMUL的数据长度与两行参数长度不同；精确保留上游的完整前置检查。
        r"^    if \((hpu_obj_len\[\d+\]) == 0 \|\| \1 < 2 \|\| \1 > 1024 \|\| \(\1 & \(\1 - 1\)\) != 0 \|\| hpu_obj_len\[\d+\] != 2\) return -6;\n",
        r"^    if \((hpu_obj_len\[\d+\]) < 2 \|\| \1 > 1024 \|\| \(\1 & \(\1 - 1\)\) != 0 \|\| hpu_obj_len\[\d+\] != 2 \|\| UINT32_C\(\d+\) >= \1 \* 64\) return -7;\n",
        r"^    if \(UINT32_C\(\d+\) >= hpu_obj_len\[\d+\]\) return -8;\n",
    )
    initialization = ("    volatile uint32_t hpu_obj_len[64];\n"
                      "    for (size_t i = 0; i < 64; ++i) hpu_obj_len[i] = 0;\n")
    if checked.count(initialization) != 1:
        raise ValueError("producer 64-object initialization changed")
    checked = checked.replace(initialization, "")
    for pattern in checks:
        checked = re.sub(pattern, "", checked, flags=re.M)
    expected = f"int hpu_program_{stem}(const hpu_dma_span_t *spans, size_t span_count) {{\n    return 0;\n}}"
    if checked != expected:
        raise ValueError("unexpected producer control/diagnostic code in preflight")
    return preflight.replace("int hpu_program_" + stem + "(",
                             "static int hpu_program_" + stem + "_preflight(", 1)


def adapt(code, stem):
    program = "hpu_program_" + stem
    begin, end = function_span(code, program)
    words, spans = instruction_words(code[begin:end]), resolved_spans(code)
    if not words:
        raise ValueError("missing producer instructions")
    validate_source(code, stem, words, spans)
    preflight = preflight_source(code[begin:end], stem)
    validator = (f"int hpu_validate_{stem}(void) {{\n"
                 f"    return {program}_preflight(\n"
                 f"        {program}_resolved_spans,\n"
                 f"        HPU_PROGRAM_{stem.upper()}_DMA_COUNT);\n}}\n")
    if not spans:
        validator = validator.replace(program + "_resolved_spans", "NULL")
    result = code[:begin] + preflight + code[end:] + "\n\n" + validator
    if instruction_words(result) != words or "trace_issue" in result:
        raise ValueError("performance adapter changed program or retained trace writes")
    validate_fixed_entry(result, stem, words, spans)
    return result, len(words)


def prepare(directory, stem):
    directory = Path(directory)
    code, count = adapt((directory / f"{stem}.c").read_text(), stem)
    expected = [int(word, 2) for word in (directory / f"{stem}.inst32").read_text().split()]
    if instruction_words(code) != expected:
        raise ValueError(f"{stem}: performance program differs from INST32")
    (directory / f"{stem}_perf.c").write_text(code)
    (directory / f"{stem}_perf.h").write_text(
        f'#include "{stem}.h"\n/* 必须在起始cycle前执行；只检查参数，不发HPU指令。 */\n'
        f'int hpu_validate_{stem}(void);\n')
    (directory / "PERF_ADAPTATION.json").write_text(json.dumps(dict(
        schema_version=1, metric="issue_to_irq_done_v1", completion="plic_irq", program_stem=stem,
        instruction_count=count, instruction_words_unchanged=True,
        native_fixed_entry_unchanged=True, dma_length_reuse="upstream_single_asm",
        preflight_emits_hpu=False, timed_parameter_checks=False,
        timed_trace_writes=False), indent=2) + "\n")
    return count
