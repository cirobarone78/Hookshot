"""Overlapping uniform transfers keep last-writer semantics, including aliased bindings."""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ['--cxx', '{cxx}']
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cxx', default='g++')
    args = parser.parse_args()
    source = (ROOT / 'gpu/vk/vk_replay.cpp').read_text()
    body = source[source.index('struct PendingBufferWrites {'):source.index('// ---- uniform updates (UPDATE_UB)')]
    flush_start = source.index('void flush_ub_updates(VkCommandBuffer cmd) {')
    flush = source[flush_start:source.index('\n}\n', flush_start)+2]
    fixture = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <vector>
using VkBuffer=uint64_t;
using VkCommandBuffer=int;
constexpr int VK_STRUCTURE_TYPE_MEMORY_BARRIER_2=1, VK_STRUCTURE_TYPE_DEPENDENCY_INFO=2;
constexpr uint64_t VK_PIPELINE_STAGE_2_ALL_TRANSFER_BIT=4, VK_ACCESS_2_TRANSFER_WRITE_BIT=8;
struct VkMemoryBarrier2 { int type; uint64_t srcStageMask=0,dstStageMask=0,srcAccessMask=0,dstAccessMask=0; };
struct VkDependencyInfo { int type; unsigned memoryBarrierCount=0; const VkMemoryBarrier2* pMemoryBarriers=nullptr; };
struct BufferRef { uint64_t buffer,offset; explicit operator bool() const { return buffer!=0; } };
BufferRef gpu_buffer_bind(uint64_t gpu,uint64_t,bool) {
 if(gpu>=0x200000) return {2,gpu-0x200000};
 return {1,gpu>=0x100000 ? gpu-0x100000 : gpu};
}
struct Write { uint64_t buffer,offset; std::vector<uint8_t> bytes; };
std::vector<Write> queued;
std::vector<uint8_t> actual[3], expected[3];
int barriers=0, host_writes=0;
void drain() {
 // Without a dependency, transfer writes may execute in reverse order.
 for(auto i=queued.rbegin();i!=queued.rend();++i)
  std::memcpy(actual[i->buffer].data()+i->offset,i->bytes.data(),i->bytes.size());
 queued.clear();
}
void vkCmdPipelineBarrier2(int,const VkDependencyInfo* d) {
 assert(d->type==VK_STRUCTURE_TYPE_DEPENDENCY_INFO && d->memoryBarrierCount==1);
 const auto& b=*d->pMemoryBarriers;
 assert(b.type==VK_STRUCTURE_TYPE_MEMORY_BARRIER_2);
 assert(b.srcStageMask==4 && b.dstStageMask==4 && b.srcAccessMask==8 && b.dstAccessMask==8);
 ++barriers; drain();
}
void vkCmdUpdateBuffer(int,uint64_t b,uint64_t offset,uint64_t n,const uint8_t* data) {
 assert(n<=65536 && !(offset&3) && !(n&3));
 queued.push_back({b,offset,std::vector<uint8_t>(data,data+n)});
}
void guest_cpu_write(uint64_t,const void*,uint64_t) { ++host_writes; }
struct Host { void gpu_write(uint64_t,const void*,uint64_t) { ++host_writes; } } host_storage;
auto* host=&host_storage;
''' + body + r'''
struct UbUpdate { uint64_t dst; std::vector<uint8_t> bytes; };
std::vector<UbUpdate> ub_updates;
size_t ub_first_of_recording=0;
struct GprofSpan { int items=0; uint64_t bytes=0; GprofSpan(int,const char*) {} };
void full_barrier(int) { drain(); }
''' + flush + r'''
bool scenario(bool ordered) {
 barriers=0; queued.clear();
 for(int b=0;b<3;++b) { actual[b].assign(131072,0); expected[b]=actual[b]; }
 PendingBufferWrites pending;
 auto write=[&](uint64_t address,uint8_t value,size_t count) {
  std::vector<uint8_t> data(count,value);
  const auto b=gpu_buffer_bind(address,count,true);
  std::memcpy(expected[b.buffer].data()+b.offset,data.data(),count);
  gpu_write(1,address,data.data(),count,ordered?&pending:nullptr);
 };
 write(0,1,16); write(32,2,16); write(16,3,16);
 assert(barriers==0); // disjoint and adjacent ranges need no extra barrier
 write(8,4,8); write(0x100008,5,8); // partial overlap and a different GPU address alias
 write(0x200008,6,8); write(20,7,8); // another buffer and an already ordered old range
 if(ordered) assert(barriers==2);
 write(0,9,65544); // split at the Vulkan update limit, retaining the input bytes
 if(ordered) assert(barriers==3);
 drain();
 return actual[1]==expected[1] && actual[2]==expected[2];
}
int main() {
 assert(!scenario(false)); // the fixture exposes the pre-fix reordering bug
 assert(scenario(true));
 // Exercise the actual batch flush, including its integration with gpu_write.
 actual[1].assign(131072,0); barriers=0;
 ub_updates={{64,std::vector<uint8_t>(4,7)}, {0,std::vector<uint8_t>(16,1)}, {8,std::vector<uint8_t>(16,2)}};
 ub_first_of_recording=1;
 flush_ub_updates(1);
 assert(barriers==1 && queued.empty());
 for(unsigned i=0;i<24;++i) assert(actual[1][i]==(i<8?1:2));
 assert(actual[1][64]==0);
 ub_first_of_recording=ub_updates.size(); flush_ub_updates(1); assert(barriers==1);
 const uint32_t word=123;
 PendingBufferWrites pending;
 const int before=barriers;
 gpu_write(1,3,&word,4,&pending); // existing unaligned CPU fallback remains unchanged
 assert(host_writes==1 && queued.empty() && barriers==before && pending.ranges.empty());
 gpu_write(1,0,&word,0,&pending);
 assert(host_writes==1 && queued.empty());
}
'''
    with tempfile.TemporaryDirectory(prefix='uniform-write-order-') as tmp:
        folder=Path(tmp); (folder/'test.cpp').write_text(fixture); exe=folder/'test.exe'
        subprocess.run([args.cxx,'-std=c++17','-O2','-Wall','-Wextra','-Werror',str(folder/'test.cpp'),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)
    print('PASS: reordered transfers, overlap, aliases, adjacency, distinct buffers, 64 KiB split and fallback')


if __name__ == '__main__':
    main()
