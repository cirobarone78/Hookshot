"""Production collector: disabled overhead, exclusive intervals and CPU accounting."""
import csv, os, subprocess, tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
fixture=r'''
#include <cstdint>
static int reads=0;
static int64_t wall=0,cpu=0;
int64_t w(){++reads;return wall;}
int64_t c(){++reads;return cpu;}
#define MKWVK_TRACE_WALL() w()
#define MKWVK_TRACE_CPU() ::c()
#include "vk_stage_trace.h"
int main(int argc,char**) {
 {mkwvk::StageTrace trace("capture",42,3,2,1); trace.memory_flags=14;
 wall=100;cpu=10;trace.mark("wait");
 wall=250;cpu=160;trace.mark("copy");
 wall=300;cpu=170;trace.finish();
 wall=999;cpu=500;}
 return argc==1 && reads!=0 ? 1 : 0;
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d);(p/'test.cpp').write_text(fixture)
 subprocess.run(['g++','-std=c++20','-pthread','-I'+str(root/'gpu/vk'),str(p/'test.cpp'),'-o',str(p/'test')],check=True)
 env=dict(os.environ);env.pop('RX_VK_STAGE_TRACE',None);env.pop('RX_VK_STAGE_TRACE_ROWS',None)
 subprocess.run([str(p/'test')],env=env,check=True)
 subprocess.run([str(p/'test'),'trace'],env={**env,'RX_VK_STAGE_TRACE':str(p/'trace.csv')},check=True)
 rows=list(csv.DictReader((p/'trace.csv').open()))
 assert [r['stage'] for r in rows]==['wait','copy','tail']
 assert [int(r['wall_ns']) for r in rows]==[100,150,50]
 assert [int(r['cpu_ns']) for r in rows]==[10,150,10]
 assert all(r['submission']=='42' and r['dirty_pages']=='3' and r['copied_pages']=='2' and r['late_pages']=='1' for r in rows)
 assert all(r['source_memory_flags']=='14' for r in rows)
 assert all(r['trace_row_limit']=='1000000' for r in rows)
 subprocess.run([str(p/'test'),'trace'],env={**env,'RX_VK_STAGE_TRACE':str(p/'limited.csv'),'RX_VK_STAGE_TRACE_ROWS':'2'},check=True)
 limited=list(csv.DictReader((p/'limited.csv').open()))
 assert len(limited)==2 and all(r['trace_row_limit']=='2' for r in limited)
 assert rows[0]['end_ns']==rows[1]['start_ns'] and rows[1]['end_ns']==rows[2]['start_ns']
print('PASS: stage trace disabled path, adjacent wall/CPU intervals and work counts')
