#!/usr/bin/env python3
"""Import Medium applications using the same package importer as Small."""
import re, shutil, sys, tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from import_package import import_package
from pir_unified_layout import generate
SPECS={
 'psi-medium':('08_03_psi_medium','psi_medium','bfv_apsi_concentrated_application',4096,4,'hpu_query'),
 'stage0-medium':('08_04_pir_medium','pir_stage0','bfv_sealpir_2d_medium_stage0_concentrated_000',4096,3,'stage0_concentrated_000'),
 'stage1-medium':('08_04_pir_medium','pir_stage1','bfv_sealpir_2d_medium_stage1_concentrated_000',4096,3,'stage1_concentrated_000'),
}
def main():
 b=ROOT/'build'; meta={};packages={}
 for name,(case,op,stem,degree,level,dirname) in SPECS.items():
  dest=b/'packages'/name
  if dest.exists():shutil.rmtree(dest)
  dest.mkdir(parents=True)
  with tarfile.open(ROOT/'packages'/(name+'.tar.gz')) as t:t.extractall(dest,filter='data')
  package=dest/dirname; target=b/'imported'/name
  if target.exists():shutil.rmtree(target)
  target.parent.mkdir(parents=True,exist_ok=True)
  spec=dict(kind='application',profile='application',case_id=case,source='',operation=op,program_stem=stem,scheme='bfv',degree=degree,level=level,memory_base='0x87000000',minimum_ram_bytes=268435456)
  meta[name]=import_package(package,target,spec);packages[name]=package
  source=(target/(stem+'.c')).read_text();marker='int hpu_run_'+stem+'(void) {'
  if source.count(marker)!=1:raise ValueError('missing fixed program')
  fixed=re.sub(r'^\s*\(void\)hpu_program_[a-z0-9_]+_resolved_spans;\s*$','',source[source.index(marker):],flags=re.M)
  if [int(x,16) for x in re.findall(r'\.word (0x[0-9a-fA-F]+)',fixed)] != [int(x,2) for x in (target/(stem+'.inst32')).read_text().split()]:raise ValueError('fixed words mismatch')
  (target/'fixed.c').write_text('#include "'+stem+'.h"\n'+fixed)
 unified=b/'medium-unified'
 if unified.exists():shutil.rmtree(unified)
 unified.mkdir()
 for stage in ('stage0','stage1'):shutil.copytree(b/'imported'/(stage+'-medium'),unified/stage)
 fixture=b/'medium-fixture'
 if fixture.exists():shutil.rmtree(fixture)
 fixture.mkdir()
 with tarfile.open(ROOT/'packages/cpu-fixture-medium.tar.gz') as t:t.extractall(fixture,filter='data')
 fixture=fixture/'cpu-fixture'
 info=generate(unified,packages['stage0-medium'],packages['stage1-medium'],meta['stage0-medium'],meta['stage1-medium'],fixture/'parameters.json',fixture/'dynamic_inputs.tsv')
 (unified/'pir_config.h').write_text('#define PIR_CPU_STAGE0_REPLIES '+str(info['cpu_plaintext_words']//4096//8)+'U\n')
 (unified/'pir_layout.h').write_text((unified/'layout.h').read_text())
 (unified/'pir_layout.c').write_text((unified/'layout.c').read_text().replace('#include "layout.h"','#include "pir_layout.h"'))
 hpu=(unified/'stage1/writable.u8.bin').read_bytes(); union=(unified/'stage1/cpu_writable.u8.bin').read_bytes()
 cpu=bytes(int(bool(c) and not bool(h)) for h,c in zip(hpu,union))
 if sum(cpu)!=info['cpu_input_limbs']*64:raise ValueError('CPU input coverage mismatch')
 (b/'imported/stage1-medium/cpu-inputs.u8.bin').write_bytes(cpu)
 n=max(int((b/'app_lines.txt').read_text()),*(m['IMAGE_LINES'] for m in meta.values()))
 (b/'app_lines.txt').write_text(str(n)+'\n')
 print('Medium packages imported; maximum lines',n)
if __name__=='__main__':main()
