"""Host regressions for our ST only. No test here is hardware acceptance."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import unittest
ROOT=Path(__file__).resolve().parents[1]
def run(args,**kw):
    return subprocess.run(list(map(str,args)),cwd=ROOT,text=True,capture_output=True,timeout=90,**kw)
class SmallST(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=Path(tempfile.mkdtemp(prefix='software-',dir=ROOT/'build'))
        s=(ROOT/'build/runtime/st_common.c').read_text()
        # Real Runtime memory/completion code; mock only mapping, MMIO and cache.
        macros=s[s.index('#define CSR_BASE_LO'):s.index('#define OP_PADD')]
        globals_=s[s.index('volatile uint32_t *g_csr;'):s.index('void st_fence(void)')]
        memory=s[s.index('static uint32_t step_prng'):s.index('void st_dload(unsigned')]
        completion=s[s.index('int st_wait_window'):s.index('const uint32_t *st_ntt_seed(')]
        completion=completion.replace('csr_read(', 'st_csr_read(').replace('csr_write(', 'st_csr_write(')
        host=cls.tmp/'runtime_host.c'
        host.write_text('#include "st_common.h"\n#include <string.h>\n'+macros+globals_+memory+completion)
        cls.binary=cls.tmp/'group_mock'
        sources=['src/st_group_08.c','src/st08_01_psi_small.c','src/st08_02_pir_small.c',
                 'src/app_support.c','src/pir_cpu_decompose.c','src/pir_cpu_encode.c',
                 'build/imported/psi/layout.c','build/unified/pir_layout.c',
                 'build/runtime/st_dual.c','tests/mock_hpu.c',host]
        inc=['-Isrc','-Ibuild/runtime','-Ibuild/imported/psi','-Ibuild/imported/stage0',
             '-Ibuild/imported/stage1','-Ibuild/unified']
        p=run(['gcc','-O1','-g','-Wall','-Wextra',*inc,*sources,
               '-Wl,--wrap=app_bind_lane,--wrap=munmap,--wrap=pir_cpu_encode','-o',cls.binary])
        if p.returncode: raise RuntimeError(p.stdout+p.stderr)
    def mock(self,**settings):
        dest=Path(tempfile.mkdtemp(dir=self.tmp))
        env=dict(os.environ,ST_OUTPUT_DIR=str(dest),ST_DUAL_TIMEOUT_MS='30000',ST_HPU_TIMEOUT_MS='100')
        env.update(settings);p=run([self.binary],env=env)
        (dest/'board.log').write_text(p.stdout+p.stderr)
        (dest/'board.exit').write_text(str(p.returncode)+'\n')
        return dest,p
    def test_01_full_flow(self):
        d,p=self.mock();self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertEqual(p.stdout.count('[MAPS] maps=2 unmaps=2'),4)
        self.assertEqual(p.stdout.count('completed=1 result=0'),6)
        p=run(['python3','scripts/verify_results.py',d])
        self.assertNotEqual(p.returncode,0); self.assertIn('software mock',p.stderr)
        (self.tmp/'successful-run.txt').write_text(str(d))
    def test_02_readonly_guard_outputs(self):
        for stage in ('psi','stage0','stage1'):
            for fault in ('readonly','guard','output'):
                with self.subTest(stage=stage,fault=fault):
                    d,p=self.mock(MOCK_FAULT=stage+':'+fault)
                    self.assertNotEqual(p.returncode,0)
                    prefix={'stage0':'pir-stage0','stage1':'pir-stage1'}.get(stage,stage)
                    for lane in range(2):self.assertTrue((d/f'{prefix}-lane{lane}.u32.bin').is_file())
    def test_03_scratch_and_cpu_input_permissions(self):
        for stage in ('psi','stage0','stage1'):
            d,p=self.mock(MOCK_FAULT=stage+':scratch');self.assertEqual(p.returncode,0,p.stderr)
        d,p=self.mock(MOCK_FAULT='stage1:cpu-input');self.assertNotEqual(p.returncode,0)
        d,p=self.mock(MOCK_CPU_BAD='1');self.assertNotEqual(p.returncode,0)
        self.assertIn('CPU wrote fixed region',p.stdout+p.stderr)
    def test_04_poll_and_terminal_states(self):
        for setting,values in [('MOCK_WAIT',['timeout','busy','fault']),('MOCK_TERMINAL',['busy','invalid','fault'])]:
            for value in values:
                with self.subTest(setting=setting,value=value):
                    start=time.monotonic();d,p=self.mock(**{setting:value})
                    self.assertLess(time.monotonic()-start,10)
                    self.assertNotEqual(p.returncode,0)
                    self.assertIn('completed=0',p.stdout)
                    self.assertTrue((d/'pir-stage0-lane0.u32.bin').is_file())
    def test_05_slow_pir_handoff(self):
        start=time.monotonic();d,p=self.mock(MOCK_DELAY='1')
        self.assertGreater(time.monotonic()-start,6)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
    def test_06_peer_failure_and_case_timeout(self):
        d,p=self.mock(MOCK_PEER_FAIL='1');self.assertNotEqual(p.returncode,0)
        start=time.monotonic();d,p=self.mock(MOCK_DELAY='1',ST_DUAL_TIMEOUT_MS='1000')
        self.assertNotEqual(p.returncode,0);self.assertLess(time.monotonic()-start,5)
        self.assertTrue((d/'pir-stage0-lane0.u32.bin').is_file())
    def test_07_old_output_rejected(self):
        d,p=self.mock(); self.assertEqual(p.returncode,0)
        env=dict(os.environ,ST_OUTPUT_DIR=str(d),ST_DUAL_TIMEOUT_MS='10000')
        p=run([self.binary],env=env);self.assertNotEqual(p.returncode,0)
        self.assertIn('File exists',p.stdout+p.stderr)
    def test_09_failed_ssh_still_collects(self):
        fake=self.tmp/'fake-bin';fake.mkdir(exist_ok=True)
        marker=self.tmp/'collected'
        (fake/'ssh').write_text('#!/bin/sh\ncase "$*" in *tar\\ -xzf*) exit 124;; esac\nexit 0\n')
        (fake/'scp').write_text('#!/bin/sh\ncase "$*" in *" -r "*) touch "'+str(marker)+'"; exit 1;; esac\nexit 0\n')
        for name in ('ssh','scp'): (fake/name).chmod(0o755)
        env=dict(os.environ,TARGET_HOST='test.invalid',PATH=str(fake)+':'+os.environ['PATH'])
        p=run(['sh','scripts/deploy_run.sh'],env=env)
        self.assertNotEqual(p.returncode,0);self.assertTrue(marker.exists())
        self.assertIn('execute=124 collect=1',p.stderr)
    def test_10_skip_and_missing_results(self):
        stub=self.tmp/'group_stub.c'
        stub.write_text('#include "st_common.h"\n#include <stdlib.h>\n#include <string.h>\nint st_case_08_01_psi_small(void){return 0;}\nint st_case_08_02_pir_small(void){return 0;}\nint st_run_case_dual(st_case_fn f,const char *id,const char *subject,int expected){(void)f;(void)subject;(void)expected; const char *v=getenv(strstr(id,"psi")?"PSI_RC":"PIR_RC"); return v?atoi(v):0;}\n')
        binary=self.tmp/'group_stub'
        build=run(['gcc','-Ibuild/runtime','src/st_group_08.c',stub,'-o',binary]); self.assertEqual(build.returncode,0,build.stderr)
        for psi,pir,want in [(0,0,0),(1,0,1),(10,10,1),(0,10,1),(10,0,1)]:
            result=run([binary],env=dict(os.environ,PSI_RC=str(psi),PIR_RC=str(pir)))
            self.assertEqual(result.returncode,want,result.stdout)
        d,p=self.mock(MOCK_SKIP='1');self.assertNotEqual(p.returncode,0)
        self.assertIn('pass=0 fail=0 skip=2',p.stdout)
        self.assertEqual(len(list(d.glob('*.u32.bin'))),0)
        self.assertNotEqual(run(['python3','scripts/verify_results.py',d]).returncode,0)
    def test_12_cpu_encoder_must_write_every_word(self):
        for setting in ('MOCK_CPU_NO_WRITE', 'MOCK_CPU_PARTIAL'):
            d,p=self.mock(**{setting:'1'})
            self.assertNotEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertIn('CPU input limb=',p.stdout+p.stderr)
    def test_13_dual_hart_pass_required(self):
        d,p=self.mock(); self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        log=(d/'board.log').read_text().replace('[SOFTWARE MOCK]','[FIXTURE]')
        (d/'board.log').write_text(log)
        ok=run(['python3','scripts/verify_results.py',d]); self.assertEqual(ok.returncode,0,ok.stderr)
        for case in ('08_01_psi_small','08_02_pir_small'):
            bad=re.sub(r'^.*\[PASS\] both_harts_checked=1 case='+case+r'\s*$', '', log, flags=re.M)
            self.assertNotEqual(bad,log)
            (d/'board.log').write_text(bad)
            result=run(['python3','scripts/verify_results.py',d])
            self.assertNotEqual(result.returncode,0)
            self.assertIn('missing dual-hart PASS: '+case,result.stderr)
    def test_11_elf_instruction_streams(self):
        import shutil
        objdump=os.environ.get('CROSS_COMPILE','riscv64-linux-gnu-')+'objdump'
        if not shutil.which(objdump): self.skipTest('cross objdump not available')
        for binary,tags in [('st08_01_psi_small',['psi']),('st08_02_pir_small',['stage0','stage1']),
                            ('group_08',['psi','stage0','stage1'])]:
            for tag in tags:
                inst=next((ROOT/'build/imported'/tag).glob('*.inst32'))
                expected=[int(w,2) for w in inst.read_text().split()]
                p=run([objdump,'-d','--disassemble=hpu_run_'+inst.stem,binary])
                self.assertEqual(p.returncode,0,p.stderr)
                words=[int(w,16) for w in re.findall(r'^\s*[0-9a-f]+:\s+([0-9a-f]{8})\s',p.stdout,re.M)]
                self.assertEqual([w for w in words if w&127 in (0x2b,0x5b)],expected)
if __name__=='__main__':unittest.main()
