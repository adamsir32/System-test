#!/usr/bin/env python3
"""Check a collected ST result and decrypt its real DDR outputs on the host.
No receipts or file hashes. The board exit code and stage completion are required.
"""
import argparse
from pathlib import Path
import re
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
CASES={'group_08':['psi','pir-stage0','pir-stage1'],
       'st08_01_psi_small':['psi'], 'st08_02_pir_small':['pir-stage0','pir-stage1']}

def verify(directory,binary):
    if (directory/'board.exit').read_text().strip()!='0':
        raise ValueError('board ST failed; keep DDR files for diagnosis')
    log=(directory/'board.log').read_text(errors='replace')
    if '[SOFTWARE MOCK]' in log:
        raise ValueError('software mock is not physical HPU acceptance')
    for stage in CASES[binary]:
        tag={'psi':'psi','pir-stage0':'stage0','pir-stage1':'stage1'}[stage]
        header=(ROOT/'build/imported'/tag/'layout.h').read_text()
        size=int(re.search(r'#define IMAGE_LINES (\d+)U',header)[1])*256
        for lane in range(2):
            marker=f'[SNAPSHOT] stage={stage} lane={lane} completed=1 result=0'
            if marker not in log: raise ValueError('missing successful stage: '+stage+f' lane{lane}')
            image=directory/f'{stage}-lane{lane}.u32.bin'
            if image.stat().st_size!=size: raise ValueError('incomplete DDR: '+image.name)
            if stage=='pir-stage0': continue
            app='psi' if stage=='psi' else 'pir'
            proc=subprocess.run([str(ROOT/'build'/('verify_'+app)),str(image),
                str(ROOT/'packages/keys'/(app+'.secretkey.seal'))],capture_output=True,text=True,timeout=120)
            (directory/f'{stage}-lane{lane}.semantic.log').write_text(proc.stdout+proc.stderr)
            if proc.returncode: raise ValueError('semantic comparison failed: '+image.name)
            print(f'[SEMANTIC][PASS] {stage} lane={lane}')
    print('[ACCEPT][PASS] board ST and offline semantics; actual hardware routing remains a board prerequisite')

def main():
    p=argparse.ArgumentParser();p.add_argument('results',type=Path)
    p.add_argument('--binary',choices=CASES,default='group_08');a=p.parse_args()
    try: verify(a.results,a.binary)
    except Exception as e:
        print('[ACCEPT][FAIL] '+str(e),file=sys.stderr);return 1
    return 0
if __name__=='__main__': sys.exit(main())
