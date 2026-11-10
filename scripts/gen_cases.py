#!/usr/bin/env python3
"""Generate the application group runner from the extension case list."""
import argparse
import csv
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def main():
    p = argparse.ArgumentParser(); p.add_argument('--check', action='store_true'); args = p.parse_args()
    with (ROOT / 'scripts/cases.tsv').open(encoding='utf-8', newline='') as f:
        rows = list(csv.DictReader(f, delimiter='\t'))
    if len(rows) != 2 or len({r['case_id'] for r in rows}) != len(rows): raise ValueError('invalid case list')
    text = '#include "st_common.h"\n'
    text += ''.join('int %s(void);\n' % r['function'] for r in rows)
    text += 'int main(void) { unsigned pass=0, fail=0, skip=0; int rc;\n'
    for r in rows:
        if not r['function'].replace('_','').isalnum() or not r['case_id'].replace('_','').isalnum(): raise ValueError('invalid identifier')
        text += 'rc=st_run_case_dual(%s,"%s","%s",1); if(rc==ST_ERR_NOT_QUALIFIED) ++skip; else if(rc==ST_OK) ++pass; else ++fail;\n' % (r['function'], r['case_id'], r['subject'])
    text += 'printf("[HPU][SUMMARY] group=08 pass=%u fail=%u skip=%u\\n",pass,fail,skip); return fail ? 1 : 0; }\n'
    files = {ROOT / 'src/st_group_08.c': text}
    files[ROOT / 'blocked.tsv'] = 'group\tcase_id\tstatus\treason\n' + ''.join('%s\t%s\t%s\t%s\n' % (r['group'],r['case_id'],r['status'],r['reason']) for r in rows if r['status'] != 'ready')
    files[ROOT / 'CASE_STATUS.md'] = '# PIR/PSI Small ST status\n\n| Case | Status | Reason |\n| --- | --- | --- |\n' + ''.join('| %s | %s | %s |\n' % (r['case_id'],r['status'],r['reason']) for r in rows)
    for path, value in files.items():
        if args.check:
            if not path.exists() or path.read_text() != value: raise SystemExit('generated file is stale: ' + str(path))
        else: path.write_text(value)

if __name__ == '__main__': main()
