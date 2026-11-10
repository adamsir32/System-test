#!/usr/bin/env python3
"""Bind offline verifiers to their source, generated layouts and pinned test keys."""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from verify_inputs import sha256, verify

def inputs():
    return ['src/offline_verify.cpp', 'src/pir_client.cpp', 'src/psi_client.cpp', 'src/test_key.hpp',
            'packages/inputs.lock.json', 'packages/keys/fingerprints.h',
            'build/imported/psi/layout.c', 'build/imported/psi/layout.h',
            'build/imported/psi/psi_fixture.h', 'build/unified/pir_layout.c', 'build/unified/pir_layout.h']

if __name__ == '__main__':
    verify()
    files = inputs() + ['build/verify_pir', 'build/verify_psi']
    files += ['config/seal-source.json']
    (ROOT / 'build/offline-receipt.json').write_text(json.dumps(
        dict(schema=1, hardware_verified=False, files={s:sha256(ROOT/s) for s in files},
             seal_library_sha256=sha256(Path(sys.argv[2])/'lib/libseal-4.4.a'),
             seal_config_sha256=sha256(Path(sys.argv[2])/'native/src/seal/util/config.h')), indent=2)+'\n')
