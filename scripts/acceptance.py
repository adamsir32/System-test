#!/usr/bin/env python3
"""Fresh upload -> board execution -> unconditional collection -> semantic acceptance."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import uuid
from verify_run import ROOT, CASES, local_receipts, verify_run
sys.path.insert(0,str(ROOT/'tools'))
from verify_inputs import sha256

def routing(path):
    data=json.loads(path.read_text())
    if data.get('schema')!=1 or data.get('status')!='confirmed' or not data.get('board_id'):
        raise ValueError('hardware routing is unconfirmed; obtain actual board/RTL evidence first')
    evidence=path.parent/data['evidence_file']
    digest=sha256(evidence)
    if digest!=data['evidence_sha256'] or data.get('evidence_kind') not in ('rtl','board_document','measurement'):
        raise ValueError('routing evidence missing/changed')
    rows=data['lanes']
    if len(rows)!=2 or len({r['cpu'] for r in rows})!=2 or len({r['hart'] for r in rows})!=2:
        raise ValueError('two distinct CPUs and harts required')
    for lane,r in enumerate(rows):
        if r['lane']!=lane or r['hpu']!=lane or type(r['cpu'])!=int or not 0<=r['cpu']<1024 or type(r['hart'])!=int or r['hart']<0:
            raise ValueError('invalid routing identity')
        if r['csr']!=hex(0x08000000+lane*0x1000) or r['ddr']!=hex(0x87000000+lane*0x04000000):
            raise ValueError('routing contradicts Runtime addresses')
    return rows,digest

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--host',required=True); p.add_argument('--user',default='root'); p.add_argument('--port',type=int,default=22)
    p.add_argument('--routing',type=Path,required=True); p.add_argument('--binary',choices=CASES,default='group_08')
    p.add_argument('--target-dir',default='/root/pir-psi-st'); p.add_argument('--output-root',type=Path,default=ROOT/'output')
    a=p.parse_args()
    board,_=local_receipts(); routes,digest=routing(a.routing)
    if not re.fullmatch(r'[A-Za-z0-9_.:@-]+',a.host) or a.host.startswith('-') or not re.fullmatch(r'[A-Za-z0-9_-]+',a.user):
        raise ValueError('invalid SSH target')
    if not re.fullmatch(r'/[A-Za-z0-9_./-]+',a.target_dir) or '..' in Path(a.target_dir).parts:
        raise ValueError('target-dir must be an absolute shell-safe path')
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:12]
    dest=a.output_root/run_id; dest.mkdir(parents=True,exist_ok=False)
    route=json.loads(a.routing.read_text()); evidence=a.routing.parent/route['evidence_file']
    shutil.copyfile(evidence,dest/'routing-evidence'); route['evidence_file']='routing-evidence'
    (dest/'routing.json').write_text(json.dumps(route,indent=2)+'\n')
    manifest=dict(schema=1,run_id=run_id,execution_kind='physical_hpu',binary=a.binary,build_id=board['build_id'],
                  board_receipt_sha256=sha256(ROOT/'build/board-receipt.json'),
                  offline_receipt_sha256=sha256(ROOT/'build/offline-receipt.json'),routing_evidence_sha256=digest,
                  host=a.host,port=a.port,hardware_verified=False)
    (dest/'run.json').write_text(json.dumps(manifest,indent=2)+'\n')
    selected={k:v for k,v in board['files'].items() if k.startswith('build/imported/') or k==a.binary}
    sums=''.join(v+'  '+k+'\n' for k,v in selected.items())
    (dest/'SHA256SUMS').write_text(sums)
    with tarfile.open(dest/'upload.tar.gz','w:gz') as tar:
        for name in selected: tar.add(ROOT/name,arcname=name)
        tar.add(dest/'SHA256SUMS',arcname='SHA256SUMS')
    target=f'{a.user}@{a.host}'; remote=a.target_dir+'/runs/'+run_id
    ssh=['ssh','-p',str(a.port),target]; scp=['scp','-P',str(a.port)]
    q=shlex.quote
    def call(cmd):
        proc=subprocess.run(cmd,text=True,capture_output=True)
        with (dest/'transport.log').open('a') as f: f.write(proc.stdout+proc.stderr)
        return proc
    try:
        call(ssh+[f'mkdir -p {q(a.target_dir+"/runs")} && mkdir -m 700 {q(remote)}']).check_returncode()
        call(scp+[str(dest/'upload.tar.gz'),target+':'+remote+'/upload.tar.gz']).check_returncode()
        env={'ST_RUN_ID':run_id,'ST_RUN_DIR':'results','ST_ROUTE_EVIDENCE_SHA256':digest}
        for i,r in enumerate(routes): env.update({f'ST_CPU_LANE{i}':str(r['cpu']),f'ST_HART_LANE{i}':str(r['hart'])})
        assignment=' '.join(k+'='+q(v) for k,v in env.items())
        command=(f'cd {q(remote)} && mkdir results && '
                 'tar -xzf upload.tar.gz && '
                 f'if sha256sum -c SHA256SUMS >results/preflight.log 2>&1; then chmod +x {q(a.binary)}; '
                 f'env {assignment} ./{q(a.binary)} >results/board.log 2>&1; rc=$?; '
                 'else rc=2; fi; printf "%s\\n" "$rc" >results/board.exit')
        # A nonzero board rc is retained in board.exit; collection still runs.
        remote_result=call(ssh+[command])
        collection=call(scp+['-r',target+':'+remote+'/results',str(dest)])
        if remote_result.returncode or collection.returncode: raise RuntimeError('remote execution/collection failed; see transport.log')
        result=verify_run(dest)
    except Exception as e:
        result=dict(status='FAIL',hardware_verified=False,run_id=run_id,error=str(e))
    (dest/'acceptance.json').write_text(json.dumps(result,indent=2)+'\n')
    print(str(dest)); print(json.dumps(result,indent=2))
    return int(result['status']!='HPU_ACCEPTANCE_PASS')

if __name__=='__main__': sys.exit(main())
