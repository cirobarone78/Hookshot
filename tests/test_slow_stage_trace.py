"""Production slow-operation tracing: opt-in clocks, inclusive threshold and whole stages."""
import csv
import os
from pathlib import Path
import subprocess
import tempfile

root=Path(__file__).resolve().parents[1]
fixture=r'''
#include <cstdint>
#include <cassert>
static int reads;
static int64_t wall,cpu;
static int64_t w(){++reads;return wall;}
static int64_t c(){++reads;return cpu;}
#define MKWVK_TRACE_WALL() w()
#define MKWVK_TRACE_CPU() ::c()
#include "vk_stage_trace.h"
int main(int argc,char**) {
 { mkwvk::SlowStageTrace trace("below"); wall=999999;cpu=10;trace.mark("work"); }
 wall=2000000;cpu=20;
 { mkwvk::SlowStageTrace trace("at_threshold"); wall=2400000;cpu=40;trace.mark("first");
   wall=3000000;cpu=50;trace.mark("second"); }
 if(argc==1) assert(reads==0);
}
'''
with tempfile.TemporaryDirectory() as tmp:
    p=Path(tmp);(p/'test.cpp').write_text(fixture)
    subprocess.run(['g++','-std=c++20','-pthread','-I'+str(root/'gpu/vk'),str(p/'test.cpp'),'-o',str(p/'test')],check=True)
    env={k:v for k,v in os.environ.items() if not k.startswith(('RX_VK_STAGE_TRACE','RX_VK_SLOW_STAGE'))}
    subprocess.run([str(p/'test')],env=env,check=True)
    subprocess.run([str(p/'test')],env={**env,'RX_VK_STAGE_TRACE':str(p/'disabled.csv')},check=True)
    assert not (p/'disabled.csv').exists()  # no sink creation when fine tracing is disabled
    for value in ['0','-1','garbage','10000001']:
        subprocess.run([str(p/'test')],env={**env,'RX_VK_STAGE_TRACE':str(p/'invalid.csv'),'RX_VK_SLOW_STAGE_US':value},check=True)
    subprocess.run([str(p/'test'),'trace'],env={**env,'RX_VK_STAGE_TRACE':str(p/'trace.csv'),'RX_VK_SLOW_STAGE_US':'1000'},check=True)
    rows=list(csv.DictReader((p/'trace.csv').open()))
    assert [r['operation'] for r in rows]==['at_threshold']*3
    assert [r['stage'] for r in rows]==['first','second','tail']
    assert [int(r['wall_ns']) for r in rows]==[400000,600000,0]
    assert [int(r['cpu_ns']) for r in rows]==[20,10,0]
print('PASS: slow trace disabled clocks, invalid thresholds, threshold equality and complete operation rows')
