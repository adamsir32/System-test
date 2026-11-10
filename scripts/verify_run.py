#!/usr/bin/env python3
"""Validate one collected run, including both lanes, memory and client semantics."""
import argparse
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from verify_inputs import sha256, verify

CASES = {'st08_01_psi_small': ['psi'], 'st08_02_pir_small': ['pir-stage0','pir-stage1'],
         'group_08': ['psi','pir-stage0','pir-stage1']}

def check_files(receipt, root=ROOT):
    for relative, expected in receipt['files'].items():
        path = root / relative
        if not path.resolve().is_relative_to(root.resolve()) or sha256(path) != expected:
            raise ValueError('receipt mismatch: ' + relative)

def local_receipts():
    verify()
    board = json.loads((ROOT/'build/board-receipt.json').read_text())
    offline = json.loads((ROOT/'build/offline-receipt.json').read_text())
    check_files(board); check_files(offline)
    identity = json.loads((ROOT/'build/identity.json').read_text())
    check_files({'files':identity['source']})
    if board['inputs_lock_sha256'] != sha256(ROOT/'packages/inputs.lock.json'):
        raise ValueError('board package lock changed')
    return board, offline

def check_image(stage, path):
    tag = {'psi':'psi', 'pir-stage0':'stage0','pir-stage1':'stage1'}[stage]
    base = ROOT/'build/imported'/tag
    initial = (base/'image.u32.bin').read_bytes()
    actual = path.read_bytes()
    writable = (base/'writable.u8.bin').read_bytes()
    if len(actual) != len(initial): raise ValueError('DDR size mismatch: ' + path.name)
    for line, allowed in enumerate(writable):
        if not allowed and actual[line*256:(line+1)*256] != initial[line*256:(line+1)*256]:
            raise ValueError(f'readonly/guard mismatch {stage} line={line}')
    layout = (base/'layout.c').read_text()
    golden = (base/'golden.u32.bin').read_bytes()
    for row in re.findall(r'\{\s*([0-9U,\s]+)\}',layout):
        line, words, offset, q, *_ = map(int, re.findall(r'(\d+)U',row))
        data = actual[line*256:line*256+words*4]
        if data != golden[offset*4:(offset+words)*4] or any(v[0]>=q for v in struct.iter_unpack('<I',data)):
            raise ValueError('Golden mismatch: ' + path.name)

def verify_run(directory, allow_software=False):
    board, offline = local_receipts()
    manifest = json.loads((directory/'run.json').read_text())
    software = manifest['execution_kind'] == 'host_mock'
    if manifest['execution_kind'] not in ('physical_hpu','host_mock') or software and not allow_software:
        raise ValueError('software results are not board acceptance')
    if manifest['build_id'] != board['build_id'] or manifest['board_receipt_sha256'] != sha256(ROOT/'build/board-receipt.json'):
        raise ValueError('run/build mismatch')
    if manifest['offline_receipt_sha256'] != sha256(ROOT/'build/offline-receipt.json'):
        raise ValueError('offline verifier changed since run started')
    if not software:
        from acceptance import routing
        routes, digest = routing(directory/'routing.json')
        if digest != manifest['routing_evidence_sha256']: raise ValueError('routing evidence changed')
        log = (directory/'results/board.log').read_text(errors='replace')
        for lane, route in enumerate(routes):
            expected = f"[ROUTE] lane={lane} cpu={route['cpu']} hart={route['hart']} csr={route['csr']} ddr={route['ddr']} evidence={digest}"
            if expected not in log: raise ValueError('missing actual CPU/hart observation')
    results = directory/'results'
    if (results/'board.exit').read_text().strip() != '0': raise ValueError('board process failed')
    checks = []
    for stage in CASES[manifest['binary']]:
        for lane in range(2):
            path = results/f'{stage}-lane{lane}.u32.bin'
            meta = json.loads((results/f'{stage}-lane{lane}.json').read_text())
            if any(meta.get(k)!=v for k,v in dict(schema=1,run_id=manifest['run_id'],build_id=board['build_id'],
                       stage=stage,lane=lane,completed=True,result=0,bytes=path.stat().st_size).items()):
                raise ValueError('snapshot identity/completion mismatch: '+path.name)
            check_image(stage,path)
            checks.append(dict(stage=stage,lane=lane,sha256=sha256(path),memory='PASS'))
            if stage != 'pir-stage0':
                app = 'psi' if stage=='psi' else 'pir'
                proc=subprocess.run([str(ROOT/'build'/('verify_'+app)),str(path),
                    str(ROOT/'packages/keys'/(app+'.secretkey.seal'))],text=True,capture_output=True)
                (results/f'{stage}-lane{lane}.semantic.log').write_text(proc.stdout+proc.stderr)
                if proc.returncode: raise ValueError('offline semantic failure: '+path.name)
                checks[-1]['semantic']='PASS'
    return dict(schema=1,run_id=manifest['run_id'],status='SOFTWARE_FLOW_PASS' if software else 'HPU_ACCEPTANCE_PASS',
                hardware_verified=not software,build_id=board['build_id'],checks=checks)

def main():
    p=argparse.ArgumentParser(); p.add_argument('run',type=Path); p.add_argument('--allow-software',action='store_true'); a=p.parse_args()
    try: result=verify_run(a.run,a.allow_software)
    except Exception as e: result=dict(status='FAIL',hardware_verified=False,error=str(e))
    (a.run/'acceptance.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2)); return int(result['status']=='FAIL')

if __name__=='__main__': sys.exit(main())
