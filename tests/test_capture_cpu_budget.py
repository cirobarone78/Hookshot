"""Real snapshot storage: per-capture/global limits, reuse and concurrent admission."""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ['--cxx', '{cxx}']
root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--cxx',default='g++');args=parser.parse_args()
source=r'''
#include "vk_capture_cpu.h"
#include <cassert>
#include <thread>
#include <barrier>
#include <vector>
#include <atomic>
using mkwvk::CaptureCpuSnapshot;
int main() {
 const auto cap=CaptureCpuSnapshot::max_capture;
 {
  CaptureCpuSnapshot a,b,c;
  assert(!a.allocate(0) && !a.allocate(cap+1));
  assert(a.allocate(cap) && b.allocate(cap));
  assert(CaptureCpuSnapshot::live_bytes()==2*cap);
  assert(!c.allocate(1));
  a.reset();assert(c.allocate(4096));
  assert(c.allocate(8192));
  assert(CaptureCpuSnapshot::live_bytes()==cap+8192);
 }
 assert(CaptureCpuSnapshot::live_bytes()==0);
 std::barrier ready(8), admitted(8), release(8);
 std::atomic<int> successes{0};
 std::vector<std::thread> workers;
 for(int i=0;i<8;++i) workers.emplace_back([&]{
  CaptureCpuSnapshot value;ready.arrive_and_wait();
  if(value.allocate(cap)) ++successes;
  admitted.arrive_and_wait();
  assert(CaptureCpuSnapshot::live_bytes()<=CaptureCpuSnapshot::max_total);
  release.arrive_and_wait();
 });
 for(auto& t:workers)t.join();
 assert(successes==2 && CaptureCpuSnapshot::live_bytes()==0);
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d);(p/'test.cpp').write_text(source)
 subprocess.run([args.cxx,'-std=c++20','-pthread','-O2','-I'+str(root/'gpu/vk'),str(p/'test.cpp'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
print('PASS: per-capture and global budgets, replacement, concurrent admission and destruction')
