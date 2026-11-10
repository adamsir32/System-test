"""Verify public, fixed test fixtures before import or deployment."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def verify():
    lock = json.loads((ROOT / 'packages/inputs.lock.json').read_text())
    for relative, expected in lock['files'].items():
        path = ROOT / relative
        if not path.resolve().is_relative_to((ROOT / 'packages').resolve()):
            raise ValueError('invalid fixture path')
        if path.is_symlink() or sha256(path) != expected:
            raise ValueError('fixture SHA256 mismatch: ' + relative)
    return lock

if __name__ == '__main__':
    verify()
    print('Pinned package and test-key SHA256: PASS')
