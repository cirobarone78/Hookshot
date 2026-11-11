"""Refresh real pool capture ranges without invalidating unchanged unions."""
import os
from pathlib import Path
import subprocess
import tempfile

root=Path(__file__).resolve().parents[1]
source=(root/'gpu/vk/vk_memory.cpp').read_text()
a=source.index('void refresh_pool_ranges_locked()')
function=source[a:source.index('\nbool capture_on()',a)]
prefix=r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <unordered_map>
#include <vector>
#include <utility>
using Range=std::pair<uint64_t,uint64_t>;
std::vector<Range> pool_cap_ranges;
std::unordered_map<uint64_t,uint64_t> pool_first_seen;
uint32_t pool_cap_gen=0;
uint64_t captures_made=0, pool_cap_built=0, cap_ranges_ver=1, eager=0, maximum=1<<20;
uint64_t capture_pool_max(){return maximum;}
uint64_t eager_captures(){return eager;}
struct Host {
 uint32_t gen=1; int reads=0; std::vector<Range> pools;
 uint32_t maps_generation(){return gen;}
 int gpu_pools(uint64_t (*out)[2],int capacity){
  ++reads;int n=std::min<int>(capacity,pools.size());
  for(int i=0;i<n;++i){out[i][0]=pools[i].first;out[i][1]=pools[i].second;}
  return n;
 }
} instance,*host=&instance;
'''
suffix=r'''
int main(){
 host->pools={{0x1001,4096},{0x2000,4096}};
 refresh_pool_ranges_locked();
 assert((pool_cap_ranges==std::vector<Range>{{0x1000,0x3000}}));
 auto version=cap_ranges_ver; auto reads=host->reads;
 refresh_pool_ranges_locked();assert(host->reads==reads);
 captures_made=64; refresh_pool_ranges_locked();
 assert(host->reads==reads+1 && cap_ranges_ver==version);
 std::reverse(host->pools.begin(),host->pools.end());++host->gen;
 refresh_pool_ranges_locked();assert(cap_ranges_ver==version);
 host->pools.push_back({0x8000,4096});++host->gen;
 refresh_pool_ranges_locked();assert(cap_ranges_ver==++version && pool_cap_ranges.size()==2);
 host->pools.erase(host->pools.begin(),host->pools.begin()+2);++host->gen;
 refresh_pool_ranges_locked();assert(cap_ranges_ver==++version);
 assert((pool_cap_ranges==std::vector<Range>{{0x8000,0x9000}}));
 eager=64; captures_made=128;refresh_pool_ranges_locked();
 assert(pool_cap_ranges.empty() && cap_ranges_ver==++version);
 host->pools.clear();++host->gen;refresh_pool_ranges_locked();
 assert(pool_first_seen.empty() && cap_ranges_ver==version);
 host->pools={{0x8000,4096}};++host->gen;refresh_pool_ranges_locked();
 assert(pool_cap_ranges.size()==1 && cap_ranges_ver==++version);
 assert(pool_first_seen.at(0x8000)==128);
 maximum=0;host->pools.clear();++host->gen;refresh_pool_ranges_locked();
 assert(pool_cap_ranges.size()==1 && cap_ranges_ver==version);
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d)/'ranges.cpp';exe=p.with_suffix('.exe' if os.name=='nt' else '')
 p.write_text(prefix+function+suffix)
 subprocess.run([os.environ.get('CXX','g++'),'-std=c++20','-Wall','-Wextra','-Werror',str(p),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
print('PASS: unchanged unions, new/removed pools, eager expiry and reappearance')
