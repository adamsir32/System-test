import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
sys.path.insert(0,str(ROOT/'tools'))
from acceptance import routing
from verify_run import verify_run, check_image
from verify_inputs import sha256, verify

class AcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime=Path(os.environ['SYSTEM_TEST']).resolve()
        cls.tmp=Path(tempfile.mkdtemp(prefix='software-',dir=ROOT/'build'))
        inc=['-Isrc','-Ibuild','-I'+str(cls.runtime/'src'),'-Ibuild/imported/psi',
             '-Ibuild/imported/stage0','-Ibuild/imported/stage1','-Ibuild/unified']
        cls.binary=cls.tmp/'host_mock'
        sources=['src/st_group_08.c','src/st08_01_psi_small.c','src/st08_02_pir_small.c',
                 'src/app_support.c','src/pir_cpu_decompose.c','src/pir_cpu_encode.c',
                 'build/imported/psi/layout.c','build/unified/pir_layout.c','tests/mock_hpu.c',
                 str(cls.runtime/'src/st_dual.c')]
        subprocess.run(['gcc','-O1','-g','-Wall','-Wextra',*inc,*sources,'-Wl,--wrap=app_bind_lane',
                        '-o',str(cls.binary)],cwd=ROOT,check=True)

    def run_mock(self,fault=None,timeout=False):
        dest=Path(tempfile.mkdtemp(dir=self.tmp)); (dest/'results').mkdir()
        board=json.loads((ROOT/'build/board-receipt.json').read_text())
        manifest=dict(schema=1,execution_kind='host_mock',run_id=dest.name,binary='group_08',build_id=board['build_id'],
                      board_receipt_sha256=sha256(ROOT/'build/board-receipt.json'),
                      offline_receipt_sha256=sha256(ROOT/'build/offline-receipt.json'))
        (dest/'run.json').write_text(json.dumps(manifest))
        env=dict(os.environ,ST_RUN_DIR=str(dest/'results'),ST_RUN_ID=dest.name)
        if fault: env['MOCK_FAULT']=fault
        if timeout: env['MOCK_TIMEOUT']='1'
        proc=subprocess.run([str(self.binary)],cwd=ROOT,env=env,text=True,capture_output=True,timeout=90)
        (dest/'results/board.log').write_text(proc.stdout+proc.stderr)
        (dest/'results/board.exit').write_text(str(proc.returncode)+'\n')
        return dest,proc

    def test_01_full_software_flow(self):
        dest,proc=self.run_mock(); self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
        report=verify_run(dest,True)
        self.assertEqual(report['status'],'SOFTWARE_FLOW_PASS'); self.assertFalse(report['hardware_verified'])
        self.assertEqual(len(report['checks']),6)
        (self.tmp/'successful-run.txt').write_text(str(dest))
        with self.assertRaises(ValueError): verify_run(dest)

    def test_02_protected_regions_and_failure_snapshots(self):
        for stage in ('psi','stage0','stage1'):
            for fault in ('readonly','guard','output'):
                with self.subTest(stage=stage,fault=fault):
                    dest,proc=self.run_mock(stage+':'+fault)
                    self.assertNotEqual(proc.returncode,0)
                    prefix={'psi':'psi','stage0':'pir-stage0','stage1':'pir-stage1'}[stage]
                    for lane in range(2):
                        self.assertTrue((dest/f'results/{prefix}-lane{lane}.u32.bin').is_file())
                    with self.assertRaises(ValueError): verify_run(dest,True)

    def test_03_cpu_inputs_protected_and_scratch_allowed(self):
        dest,proc=self.run_mock('stage1:cpu-input'); self.assertNotEqual(proc.returncode,0)
        self.assertIn('readonly-or-guard',proc.stderr+proc.stdout)
        for stage in ('psi','stage0','stage1'):
            dest,proc=self.run_mock(stage+':scratch')
            self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
            self.assertFalse(verify_run(dest,True)['hardware_verified'])

    def test_04_timeout_preserves_incomplete_image(self):
        dest,proc=self.run_mock(timeout=True); self.assertNotEqual(proc.returncode,0)
        meta=json.loads((dest/'results/pir-stage0-lane0.json').read_text())
        self.assertFalse(meta['completed']); self.assertEqual(meta['result'],6)

    def test_05_stale_and_incomplete_runs_rejected(self):
        dest,proc=self.run_mock(); self.assertEqual(proc.returncode,0)
        path=dest/'results/psi-lane0.json'; original=path.read_text(); meta=json.loads(original)
        meta['run_id']='older-run'; path.write_text(json.dumps(meta))
        with self.assertRaises(ValueError): verify_run(dest,True)
        path.write_text(original); (dest/'results/pir-stage1-lane1.u32.bin').unlink()
        with self.assertRaises(FileNotFoundError): verify_run(dest,True)

    def test_06_wrong_key_corruption_and_size_rejected(self):
        dest,proc=self.run_mock(); self.assertEqual(proc.returncode,0)
        image=dest/'results/psi-lane0.u32.bin'; verifier=ROOT/'build/verify_psi'
        wrong=ROOT/'packages/keys/pir.secretkey.seal'
        self.assertNotEqual(subprocess.run([str(verifier),str(image),str(wrong)],capture_output=True).returncode,0)
        key=dest/'corrupt.seal'; data=bytearray((ROOT/'packages/keys/psi.secretkey.seal').read_bytes()); data[-8]^=1; key.write_bytes(data)
        self.assertNotEqual(subprocess.run([str(verifier),str(image),str(key)],capture_output=True).returncode,0)
        image.write_bytes(image.read_bytes()[:-4])
        self.assertNotEqual(subprocess.run([str(verifier),str(image),str(ROOT/'packages/keys/psi.secretkey.seal')],capture_output=True).returncode,0)

    def test_07_unconfirmed_routing_rejected(self):
        with self.assertRaises(ValueError): routing(ROOT/'config/routing.example.json')

    def test_08_fixture_lock(self): verify()

    def test_09_cpu_write_boundary_and_snapshot(self):
        binary=self.tmp/'cpu_guard_probe'
        subprocess.run(['gcc','-O1','-Isrc','-Ibuild','-I'+str(self.runtime/'src'),
            '-Ibuild/imported/psi','-Ibuild/unified','tests/cpu_guard_probe.c',
            'src/app_support.c','tests/mock_hpu.c','build/imported/psi/layout.c',
            'build/unified/pir_layout.c',str(self.runtime/'src/st_dual.c'),'-o',str(binary)],cwd=ROOT,check=True)
        proc=subprocess.run([str(binary)],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)

    def test_10_package_content_corruption_rejected(self):
        from import_package import import_package
        from import_packages import SPECS, REV
        source=ROOT/'build/packages/psi/hpu_query'; dest=self.tmp/'corrupt-package'
        shutil.copytree(source,dest)
        path=dest/'memory/hpu_mem_image.u32.bin'; data=bytearray(path.read_bytes()); data[0]^=1;path.write_bytes(data)
        case,operation,stem,degree,level,_=SPECS['psi']
        spec=dict(kind='application',profile='application',case_id=case,operation=operation,program_stem=stem,
                  scheme='bfv',degree=degree,level=level,memory_base='0x87000000',minimum_ram_bytes=268435456)
        with self.assertRaisesRegex(ValueError,'provenance content mismatch'):
            import_package(dest,self.tmp/'bad-import',spec,REV)

    def test_11_failed_collection_cannot_pass(self):
        from unittest.mock import patch
        import acceptance
        d=self.tmp/'transport-test'; d.mkdir()
        (d/'evidence').write_text('TEST-ONLY synthetic transport fixture, not actual routing evidence')
        config=json.loads((ROOT/'config/routing.example.json').read_text())
        config.update(status='confirmed',board_id='TEST-ONLY',evidence_file='evidence',evidence_sha256=sha256(d/'evidence'))
        (d/'routing.json').write_text(json.dumps(config)); calls=[]
        def transport(cmd,**kwargs):
            calls.append(cmd)
            # Simulate nonzero SSH execution and failed collection. No HPU result is created.
            rc=1 if len(calls)>=3 else 0
            return subprocess.CompletedProcess(cmd,rc,'','simulated transport failure')
        argv=['acceptance.py','--host','test-only','--routing',str(d/'routing.json'),'--output-root',str(d/'runs')]
        with patch.object(sys,'argv',argv),patch.object(acceptance.subprocess,'run',side_effect=transport):
            self.assertEqual(acceptance.main(),1)
        self.assertEqual(len(calls),4)
        self.assertEqual(calls[-1][0],'scp') # Collection attempted despite execution failure.
        result=json.loads(next((d/'runs').glob('*/acceptance.json')).read_text())
        self.assertFalse(result['hardware_verified']); self.assertEqual(result['status'],'FAIL')

    def test_12_route_alias_and_evidence_changes_rejected(self):
        d=self.tmp/'route-negative'; d.mkdir(); (d/'evidence').write_text('TEST-ONLY')
        config=json.loads((ROOT/'config/routing.example.json').read_text())
        config.update(status='confirmed',board_id='TEST-ONLY',evidence_file='evidence',evidence_sha256=sha256(d/'evidence'))
        config['lanes'][1]['cpu']=config['lanes'][0]['cpu']
        p=d/'routing.json'; p.write_text(json.dumps(config))
        with self.assertRaises(ValueError): routing(p)
        config['lanes'][1]['cpu']=1; p.write_text(json.dumps(config)); (d/'evidence').write_text('changed')
        with self.assertRaises(ValueError): routing(p)

if __name__=='__main__': unittest.main()
