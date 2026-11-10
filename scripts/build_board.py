#!/usr/bin/env python3
"""Build only this extension, check every project object, and bind deployable bytes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from verify_inputs import sha256, verify

def run(cmd):
    print(shlex.join(map(str, cmd)), flush=True)
    subprocess.run(list(map(str, cmd)), cwd=ROOT, check=True)

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--runtime', required=True)
    p.add_argument('--cc', required=True)
    p.add_argument('--objdump', required=True)
    p.add_argument('--cflags', default='-O1 -g -Wall -Wextra -march=rv64gc')
    p.add_argument('--ldflags', default='-static')
    a = p.parse_args()
    os.chdir(ROOT)
    verify()
    run([sys.executable, 'scripts/gen_cases.py', '--check'])
    run([sys.executable, 'scripts/import_packages.py'])
    runtime = Path(a.runtime).resolve()
    contract = json.loads(Path('config/runtime-contract.json').read_text())
    for relative, expected in contract['text_sha256'].items():
        actual = hashlib.sha256((runtime / relative).read_text(encoding='utf-8').encode()).hexdigest()
        if actual != expected:
            raise ValueError('Runtime differs from reviewed contract: ' + relative +
                             '; review compatibility before updating config/runtime-contract.json')
    names = ['st_common.c', 'st_common.h', 'st_dual.c', 'st_insn.h', 'st_ntt_vectors.h']
    runtime_hashes = {name: sha256(runtime / 'src' / name) for name in names}
    if 'st_dual_barrier_generation' not in (runtime / 'src/st_dual.c').read_text():
        raise ValueError('Runtime must support repeated issue barriers')
    source_files = [ROOT / 'Makefile', ROOT / 'packages/inputs.lock.json', ROOT / 'config/runtime-contract.json']
    source_files += [f for folder in ('src', 'scripts', 'tools') for f in (ROOT / folder).rglob('*')
                     if f.is_file() and '__pycache__' not in f.parts]
    identity = dict(schema=1, source={f.relative_to(ROOT).as_posix(): sha256(f) for f in sorted(source_files)},
                    runtime=runtime_hashes, cflags=a.cflags, ldflags=a.ldflags,
                    compiler=subprocess.check_output([a.cc, '--version'], text=True).splitlines()[0])
    build_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    identity['build_id'] = build_id
    Path('build/identity.json').write_text(json.dumps(identity, indent=2) + '\n')
    Path('build/build_identity.h').write_text('#define ST_BUILD_ID "' + build_id + '"\n')
    inc = ['-Isrc', '-Ibuild', '-I' + str(runtime / 'src'), '-Ibuild/imported/psi',
           '-Ibuild/imported/stage0', '-Ibuild/imported/stage1', '-Ibuild/unified']
    flags = shlex.split(a.cflags)
    objects = []
    def compile_one(name, source, extra=()):
        obj = Path('build/objects') / (name + '.o')
        obj.parent.mkdir(exist_ok=True)
        run([a.cc, *flags, *inc, *extra, '-c', source, '-o', obj])
        objects.append(str(obj)); return str(obj)
    common = [compile_one('app_support', 'src/app_support.c')]
    common += [compile_one(n, runtime / 'src' / (n + '.c')) for n in ('st_common', 'st_dual')]
    psi = [compile_one('psi_layout', 'build/imported/psi/layout.c'),
           compile_one('psi_fixed', 'build/imported/psi/fixed.c')]
    pir = [compile_one(n, 'src/' + n + '.c') for n in ('pir_cpu_decompose', 'pir_cpu_encode')]
    pir += [compile_one('pir_layout', 'build/unified/pir_layout.c')]
    pir += [compile_one(stage + '_fixed', 'build/imported/' + stage + '/fixed.c') for stage in ('stage0', 'stage1')]
    entries, mains = [], []
    for name in ('st08_01_psi_small', 'st08_02_pir_small'):
        entries.append(compile_one(name, 'src/' + name + '.c'))
        mains.append(compile_one(name + '_main', 'src/' + name + '.c', ['-DST_STANDALONE']))
    group = compile_one('group_08', 'src/st_group_08.c')
    targets = {'st08_01_psi_small': [mains[0], *common, *psi],
               'st08_02_pir_small': [mains[1], *common, *pir],
               'group_08': [group, *entries, *common, *psi, *pir]}
    for binary, objs in targets.items():
        run([a.cc, *flags, *shlex.split(a.ldflags), '-o', binary, *objs])
    # Reuse the authorized Runtime's checker; never copy its implementation.
    env = dict(os.environ, OBJDUMP=a.objdump)
    check = subprocess.run(['bash', str(runtime / 'scripts/check_no_riscv_v.sh'), *objects],
                           env=env, text=True, capture_output=True)
    Path('build/no-v.log').write_text(check.stdout + check.stderr)
    print(check.stdout, end=''); check.check_returncode()
    counts = {}
    for binary, stages in [('st08_01_psi_small', ['psi']), ('st08_02_pir_small', ['stage0', 'stage1']),
                            ('group_08', ['psi', 'stage0', 'stage1'])]:
        for stage in stages:
            metadata = json.loads(Path('build/imported', stage, 'delivery.json').read_text())
            stem = metadata['program_stem']
            expected = [int(x, 2) for x in Path('build/imported', stage, stem + '.inst32').read_text().split()]
            assembly = subprocess.check_output([a.objdump, '-d', '--disassemble=hpu_run_' + stem, binary], text=True)
            words = [int(x, 16) for x in re.findall(r'^\s*[0-9a-f]+:\s+([0-9a-f]{8})\s', assembly, re.M)]
            actual = [x for x in words if x & 127 in (0x2b, 0x5b)]
            if actual != expected: raise ValueError('ELF instruction mismatch: ' + binary + '/' + stage)
            counts[binary + '/' + stage] = len(actual)
    paths = list(targets) + ['build/identity.json']
    for stage in ('psi', 'stage0', 'stage1'):
        paths += ['build/imported/' + stage + '/' + f for f in ('image.u32.bin', 'golden.u32.bin', 'writable.u8.bin')]
    paths += ['build/imported/stage1/cpu-inputs.u8.bin']
    receipt = dict(schema=1, build_id=build_id, hardware_verified=False,
                   files={s: sha256(s) for s in paths}, instruction_counts=counts,
                   checked_objects={s: sha256(s) for s in objects}, no_v='PASS',
                   inputs_lock_sha256=sha256('packages/inputs.lock.json'))
    Path('build/board-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('BOARD_BUILD_AND_STATIC_CHECK_PASS (hardware NOT RUN) build_id=' + build_id)

if __name__ == '__main__': main()
