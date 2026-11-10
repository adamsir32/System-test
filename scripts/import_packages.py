#!/usr/bin/env python3
"""Import the three fixed Small application packages for the ST build."""
import json
import re
import shutil
import sys
import tarfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from import_package import import_package
from pir_unified_layout import generate
from verify_inputs import verify
REV = '2622761537c7dcd73a89da3482da1d65c2b9c9b5'
SPECS = {
    'psi': ('08_01_psi_single', 'psi_single', 'bfv_apsi_concentrated_application', 8192, 4, 'hpu_query'),
    'stage0': ('08_02_pir_stage0', 'pir_stage0', 'bfv_sealpir_2d_small_stage0_concentrated_000', 4096, 3, 'stage0_concentrated_000'),
    'stage1': ('08_03_pir_stage1', 'pir_stage1', 'bfv_sealpir_2d_small_stage1_concentrated_000', 4096, 3, 'stage1_concentrated_000'),
}
def main():
    verify()
    build = ROOT / 'build'
    build.mkdir(exist_ok=True)
    meta, packages = {}, {}
    for name, (case, operation, stem, degree, level, directory) in SPECS.items():
        dest = build / 'packages' / name
        if dest.exists(): shutil.rmtree(dest)
        dest.mkdir(parents=True)
        with tarfile.open(ROOT / 'packages' / (name + '.tar.gz')) as archive:
            archive.extractall(dest, filter='data')
        package = dest / directory
        spec = dict(kind='application', profile='application', case_id=case, source='', operation=operation,
                    program_stem=stem, scheme='bfv', degree=degree, level=level,
                    memory_base='0x87000000', minimum_ram_bytes=268435456)
        target = build / 'imported' / name
        if target.exists(): shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        meta[name] = import_package(package, target, spec, REV)
        packages[name] = package
        source = (target / (stem + '.c')).read_text()
        marker = 'int hpu_run_' + stem + '(void) {'
        if source.count(marker) != 1: raise ValueError('fixed program entry missing')
        fixed = source[source.index(marker):]
        fixed = re.sub(r'^\s*\(void\)hpu_program_[a-z0-9_]+_resolved_spans;\s*$', '', fixed, flags=re.M)
        words = [int(x, 16) for x in re.findall(r'\.word (0x[0-9a-fA-F]+)', fixed)]
        expected = [int(x, 2) for x in (target / (stem + '.inst32')).read_text().split()]
        if words != expected: raise ValueError('fixed program words differ from package')
        (target / 'fixed.c').write_text('#include "' + stem + '.h"\n' + fixed)
    unified = build / 'unified'
    if unified.exists(): shutil.rmtree(unified)
    unified.mkdir()
    for stage in ('stage0', 'stage1'):
        shutil.copytree(build / 'imported' / stage, unified / stage)
    with tarfile.open(ROOT / 'packages/cpu-fixture.tar.gz') as archive:
        archive.extractall(build, filter='data')
    fixture = build / 'cpu-fixture'
    generate(unified, packages['stage0'], packages['stage1'], meta['stage0'], meta['stage1'],
             fixture / 'parameters.json', fixture / 'dynamic_inputs.tsv')
    (unified / 'pir_layout.h').write_text((unified / 'layout.h').read_text())
    (unified / 'pir_layout.c').write_text((unified / 'layout.c').read_text().replace('#include \"layout.h\"', '#include \"pir_layout.h\"'))
    hpu = (unified / 'stage1/writable.u8.bin').read_bytes()
    union = (unified / 'stage1/cpu_writable.u8.bin').read_bytes()
    cpu = bytes(int(bool(c) and not bool(h)) for h, c in zip(hpu, union))
    if len(cpu) != meta['stage1']['IMAGE_LINES'] or sum(cpu) != 96 * 64:
        raise ValueError('CPU-only writable coverage mismatch')
    (build / 'imported/stage1/cpu-inputs.u8.bin').write_bytes(cpu)
    sets = json.loads((ROOT / 'packages/psi-sets.json').read_text())
    locations = [tuple(map(int, line.split())) for line in (ROOT / 'packages/psi-receiver-layout.txt').read_text().splitlines()]
    if sorted(i for i, _ in locations) != sorted(sets['receiver']) or any(loc < 0 or loc >= 4096 for _, loc in locations):
        raise ValueError('PSI receiver layout mismatch')
    fixture = '#pragma once\n#include <stdint.h>\n'
    fixture += 'static const uint64_t psi_sender[] = {' + ','.join(str(x)+'ULL' for x in sets['sender']) + '};\n'
    fixture += 'static const uint64_t psi_receiver[] = {' + ','.join(str(x)+'ULL' for x,_ in locations) + '};\n'
    fixture += 'static const unsigned psi_location[] = {' + ','.join(str(loc)+'U' for _,loc in locations) + '};\n'
    (build / 'imported/psi/psi_fixture.h').write_text(fixture)
    print('Imported PSI, PIR Stage0 and Stage1; program words and DMA layouts checked')
if __name__ == '__main__': main()
