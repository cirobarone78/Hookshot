"""A neighboring GPU import must not retain an unrelated freed guest range."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
root = Path(__file__).resolve().parents[1]
source = (root/'gpu/vk/vk_memory.cpp').read_text()
start = source.index('int memory_guest_imported(uint64_t lo, uint64_t hi) {')
end = source.index('\nbool mirror_make(', start)
body = source[start:end]
fixture = r'''
#include <cstdint>
#include <map>
#include <mutex>
#include <vector>
#include <cassert>
struct Pool { uint64_t lo, hi; bool memory = true; };
std::map<uint64_t, Pool> imported;
std::vector<decltype(imported)::node_type> retired_pools;
std::mutex pools_mu;
''' + body + r'''
int main() {
 imported.emplace(0x2000, Pool{0x2000,0x4000});
 assert(!memory_guest_imported(0x1000,0x2000)); // exactly adjacent on the right
 assert(!memory_guest_imported(0x4000,0x5000)); // exactly adjacent on the left
 assert(!memory_guest_imported(0x2000,0x2000));
 assert(!memory_guest_imported(0x3000,0x2000));
 assert(memory_guest_imported(0x1000,0x2001));
 assert(memory_guest_imported(0x3fff,0x5000));
 assert(memory_guest_imported(0x2000,0x4000));
 assert(memory_guest_imported(0x2800,0x3000));
 assert(memory_guest_imported(0x1000,0x5000));
 retired_pools.push_back(imported.extract(0x2000));
 assert(!memory_guest_imported(0x1000,0x2000));
 assert(!memory_guest_imported(0x4000,0x5000));
 assert(memory_guest_imported(0x2000,0x4000)); // still held by in-flight GPU work
 retired_pools[0].mapped().memory = false;
 assert(!memory_guest_imported(0x2000,0x4000));
}
'''
compiler = shutil.which('g++') or shutil.which('clang++')
if not compiler:
    raise SystemExit('SKIP: C++ compiler unavailable')
with tempfile.TemporaryDirectory() as tmp:
    p=Path(tmp); src=p/'test.cpp'; binary=p/('test.exe' if os.name=='nt' else 'test')
    src.write_text(fixture)
    subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror',str(src),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
print('PASS: active/retired import overlap, adjacency, containment and empty ranges')
