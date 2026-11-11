"""Build snapshots once from live gaps and shadow pages; preserve in-place overlays."""
import os
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
s = (root / 'gpu/vk/vk_memory.cpp').read_text()
a = s.index('const uint8_t* memory_as_submitted(')
function = s[a:s.index('\nvoid memory_drop_shadow', a)]
# Track explicit overlay copies and vector range copies in the production function.
function = function.replace('std::memcmp(', 'compare_shadow(').replace('std::memcpy(', 'copy_shadow(').replace('std::vector<uint8_t>& scratch', 'TrackingBuffer& scratch')
prefix = r'''
#include <algorithm>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <memory>
#include <mutex>
#include <unordered_map>
#include <vector>
using namespace std;
struct ShadowPage { unique_ptr<uint8_t[]> b; };
unordered_map<uint32_t,ShadowPage> shadow;
unordered_map<uint32_t,uint32_t> shadow_regions;
atomic<size_t> shadow_n{0};
struct Counter {
    int64_t value=0;
    size_t updates=0;
    Counter& operator=(int64_t v){value=v;updates=0;return *this;}
    operator int64_t() const{return value;}
    int64_t load() const{return value;}
    void operator++(int){++value;++updates;}
    void fetch_add(int64_t n,memory_order){value+=n;++updates;}
};
Counter st_overlaid,st_differed;
mutex shadow_mu;
vector<int> tex_spans;
uint64_t tex_merged_bytes=0;
bool off=false;
bool overlay_off(){return off;}
template<class... T> void logf(const char*,T...){}
size_t writes=0, copied_bytes=0, comparisons=0;
int compare_shadow(const void* a,const void* b,size_t n){++comparisons;return memcmp(a,b,n);}
struct TrackingBuffer : vector<uint8_t> {
    using vector<uint8_t>::vector;
    TrackingBuffer(vector<uint8_t> initial):vector<uint8_t>(std::move(initial)){}
    template<class It> void assign(It a,It b){copied_bytes+=size_t(b-a);vector<uint8_t>::assign(a,b);}
    template<class It> auto insert(const_iterator at,It a,It b){copied_bytes+=size_t(b-a);return vector<uint8_t>::insert(at,a,b);}
};
void* copy_shadow(void* dst,const void* src,size_t n){++writes;copied_bytes+=n;return memcpy(dst,src,n);}
'''
suffix = r'''
void check(uint64_t guest, size_t size, bool inplace, bool changed) {
    shadow.clear();shadow_regions.clear();shadow_n=0;
    st_overlaid=0;st_differed=0;writes=0;copied_bytes=0;comparisons=0;
    vector<uint8_t> live(size);
    for(size_t i=0;i<size;i++) live[i]=uint8_t(i*37+11);
    vector<uint8_t> expected=live;
    size_t pages=0,different=0,changed_bytes=0;
    for(uint64_t p=guest>>12;p<=(guest+size-1)>>12;p++) {
        if(p%3==1) continue; // Holes and region boundaries retain live bytes.
        auto& page=shadow[uint32_t(p)];page.b=make_unique<uint8_t[]>(4096);
        fill_n(page.b.get(),4096,0x55);
        auto lo=max(guest,p<<12),hi=min(guest+size,(p+1)<<12);
        for(uint64_t at=lo;at<hi;at++) page.b[at-(p<<12)]=live[at-guest];
        bool differ=changed && p%2==0;
        if(differ) {page.b[lo-(p<<12)]^=0x80;expected[lo-guest]^=0x80;++different;changed_bytes+=hi-lo;}
        ++shadow_regions[uint32_t(p>>9)];++pages;
    }
    shadow_n=shadow.size();
    TrackingBuffer scratch=inplace?live:vector<uint8_t>{0x33};
    const uint8_t* input=inplace?scratch.data():live.data();
    const uint8_t* result=memory_as_submitted(guest,input,size,scratch);
    assert(equal(expected.begin(),expected.end(),result));
    const bool compare=inplace || (getenv("RX_VK_SHADOW_COMPARE_STATS") && atoi(getenv("RX_VK_SHADOW_COMPARE_STATS")));
    assert(st_overlaid==pages && st_differed==(compare?different:0));
    assert(comparisons==(compare?pages:0));
    assert(copied_bytes==(inplace?changed_bytes:(pages?size:0)));
    assert(writes==(inplace?different:0));
    assert(st_overlaid.updates==(pages?1u:0u));
    assert(st_differed.updates==((compare && different)?1u:0u));
    if(pages) {
        assert(result==scratch.data() && scratch.size()==size);
        // Equal pages must still be owned snapshots, not a pointer to live memory.
        if(!inplace){fill(live.begin(),live.end(),0);assert(equal(expected.begin(),expected.end(),result));}
    } else assert(result==input);
}
int main(){
    for(uint64_t base:{uint64_t(0x4000),uint64_t(0x1ffff0),uint64_t(0x200013)})
    for(size_t size:{size_t(1),size_t(4096),size_t(20000)})
    for(bool inplace:{false,true}) for(bool changed:{false,true}) check(base,size,inplace,changed);
    shadow.clear();shadow_regions.clear();shadow_n=0;
    vector<uint8_t> live(64,7);TrackingBuffer scratch{8,9};
    assert(memory_as_submitted(0x4000,live.data(),64,scratch)==live.data());
    shadow_n=1;off=true;
    assert(memory_as_submitted(0x4000,live.data(),64,scratch)==live.data());
    off=false;
    assert(memory_as_submitted(0x4000,live.data(),0,scratch)==live.data());
    assert((scratch==vector<uint8_t>{8,9}));
}
'''
with tempfile.TemporaryDirectory() as tmp:
    cpp = Path(tmp) / 'test.cpp'
    exe = Path(tmp) / 'test'
    cpp.write_text(prefix + function + suffix)
    subprocess.run([os.environ.get('CXX', 'g++'), '-std=c++17', str(cpp), '-o', str(exe)], check=True)
    env = dict(os.environ)
    env.pop('RX_VK_SHADOW_COMPARE_STATS', None)
    subprocess.run([str(exe)], env=env, check=True)
    subprocess.run([str(exe)], env={**env, 'RX_VK_SHADOW_COMPARE_STATS':'1'}, check=True)
print('PASS: equal/changed pages, holes, partial pages, regions, aliasing and owned snapshots')
