#!/usr/bin/env python3
"""Prepare a pinned, host-only SEAL build; never generate recipient secret keys."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]
REV='5a0f7898da265a6c92e6f73331a540c8fc8d38a9'

def verify_source(source):
    expected=json.loads((ROOT/'config/seal-source.json').read_text())
    for name,digest in expected.items():
        if hashlib.sha256((source/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()!=digest:
            raise ValueError('SEAL source differs from pinned Producer: '+name)

def main():
    p=argparse.ArgumentParser(); p.add_argument('--source',type=Path,required=True); p.add_argument('--build',type=Path,required=True); a=p.parse_args()
    default_source=ROOT/'build/host-deps/producer/third_party/modified-SEAL'
    if not a.source.exists():
        if a.source.resolve()!=default_source.resolve(): raise ValueError('explicit SEAL_SOURCE does not exist')
        checkout=ROOT/'build/host-deps/producer'; checkout.parent.mkdir(parents=True,exist_ok=True)
        subprocess.run(['git','clone','--no-checkout','--filter=blob:none','https://github.com/adamsir32/inline-asm.git',str(checkout)],check=True)
        subprocess.run(['git','-C',str(checkout),'checkout','--detach',REV],check=True)
    verify_source(a.source)
    if a.build.resolve()==(ROOT/'build/host-deps/seal').resolve() or not (a.build/'lib/libseal-4.4.a').exists():
        subprocess.run(['cmake','-S',str(a.source),'-B',str(a.build),'-DCMAKE_BUILD_TYPE=Release',
                        '-DSEAL_BUILD_DEPS=OFF','-DSEAL_USE_MSGSL=OFF','-DSEAL_USE_ZLIB=OFF',
                        '-DSEAL_USE_ZSTD=OFF','-DSEAL_USE_INTEL_HEXL=OFF','-DBUILD_SHARED_LIBS=OFF',
                        '-DSEAL_BUILD_EXAMPLES=OFF','-DSEAL_BUILD_TESTS=OFF','-DSEAL_BUILD_BENCH=OFF'],check=True)
        subprocess.run(['cmake','--build',str(a.build),'--parallel',str(min(os.cpu_count() or 2,8))],check=True)
    print('Pinned SEAL source verified; host library ready')

if __name__=='__main__': main()
