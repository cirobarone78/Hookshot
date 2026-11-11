"""Run the production native-present queue with authored images and a gated display."""
import argparse
import csv
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cxx', default='g++')
    args = parser.parse_args()
    text = (ROOT / 'gpu/vk/vk_framegen.cpp').read_text()
    body = text[text.index('namespace {\nstruct NativeSlot'):text.index('// The Insert menu\'s Frame generation is off at 0.')]
    fixture = r'''
#include <atomic>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <cstring>
#include <cstdio>
#include <deque>
#include <future>
#include <mutex>
#include <thread>
#include <vector>
using VkCommandBuffer = int;
using VkImage = unsigned;
using VkFormat = unsigned;
using VkSemaphore = unsigned;
constexpr unsigned VK_NOT_READY=1, VK_SUCCESS=0, VK_SEMAPHORE_TYPE_TIMELINE=1,
 VK_FORMAT_A2B10G10R10_UNORM_PACK32=99, VK_STRUCTURE_TYPE_SEMAPHORE_TYPE_CREATE_INFO=1, VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO=2;
struct VkSemaphoreTypeCreateInfo { unsigned type; unsigned semaphoreType=0; };
struct VkSemaphoreCreateInfo { unsigned type; const void* pNext=nullptr; };
struct NativePresentSync { VkSemaphore timeline=0; uint64_t ready=0,consumed=0; bool read_submitted=false;bool native_pq=false;bool shown=false;uint64_t source_frame=0;int64_t source_ns=0,queued_ns=0,worker_ns=0,present_begin_ns=0,present_end_ns=0,finished_ns=0;int present_result=1; };
unsigned next_semaphore=0;
unsigned vkCreateSemaphore(int,const VkSemaphoreCreateInfo* ci,void*,VkSemaphore* out) {
 assert(ci->pNext); *out=++next_semaphore;return VK_SUCCESS;
}
void vkDestroySemaphore(int,VkSemaphore,void*){}
void present_async_release(NativePresentSync& sync) {
 assert(sync.timeline && sync.ready%2==1 && sync.consumed==sync.ready+1);
 sync.read_submitted=true;
}
constexpr unsigned VK_FORMAT_UNDEFINED=0, VK_IMAGE_USAGE_TRANSFER_SRC_BIT=1,
 VK_IMAGE_USAGE_TRANSFER_DST_BIT=2, VK_IMAGE_USAGE_SAMPLED_BIT=4,
 VK_IMAGE_ASPECT_COLOR_BIT=1, VK_IMAGE_LAYOUT_GENERAL=1;
struct Layers { unsigned a,b,c,d; };
struct Offset { int x,y,z; };
struct Extent { unsigned w,h,d; };
struct VkImageCopy { Layers a; Offset b; Layers c; Offset d; Extent extent; };
struct Img { unsigned image=0, view=0; };
struct { int hdr=0; } opts;
struct { bool hdr=false; bool offscreen=false; int device=1; std::mutex present_mu; } dev;
std::atomic<unsigned> present_kind{0};
bool interpolating=false;
struct {std::mutex mu;std::condition_variable cv;std::deque<int> jobs;struct {bool busy=false;} sets[3];} fg;
bool framegen_on() { return interpolating; }
unsigned next_image=0, live_images=0, copies=0, fail_at=0;
std::vector<unsigned> formats;
bool make_img(Img& i, unsigned, unsigned, unsigned format, unsigned usage) {
 assert(usage == 7); formats.push_back(format);
 if (++next_image == fail_at) return false;
 i.image=i.view=next_image; ++live_images; return true;
}
void drop_img(Img& i) { if(i.image) --live_images; i={}; }
void to_general(int,unsigned) {}
void queue_flush_locked() {}
void device_wait_idle_locked() {}
int64_t present_trace_now(){return std::chrono::steady_clock::now().time_since_epoch().count();}
void full_barrier(int) {}
void vkCmdCopyImage(int,unsigned src,unsigned,unsigned dst,unsigned,unsigned n,const VkImageCopy* c) {
 assert(src==99 && dst && n==1 && c->extent.w==640 && c->extent.h==360); ++copies;
}
void logf(const char*,...) {}
int GetCurrentThread(){return 0;}
void SetThreadDescription(int,const wchar_t*) {}
void menu_note_frame(bool native_frame) { assert(native_frame); }
std::mutex gate_mu;
std::condition_variable gate_cv;
bool entered=false, release_display=false;
std::vector<unsigned> displayed;
std::vector<uint64_t> ready_values;
void present_image(unsigned image,unsigned w,unsigned h,const int* crop,unsigned view,NativePresentSync* sync) {
 assert(sync && sync->timeline && sync->ready%2==1 && sync->consumed==sync->ready+1);
 sync->shown=!std::getenv("RX_TEST_HIDDEN");
 sync->present_begin_ns=present_trace_now();sync->present_end_ns=present_trace_now();
 sync->present_result=sync->shown?0:1;
 assert(w==640 && h==360 && image==view);
 assert(crop && crop[0]==10 && crop[1]==20 && crop[2]==600 && crop[3]==300);
 std::unique_lock lk(gate_mu); entered=true; gate_cv.notify_all();
 gate_cv.wait(lk,[]{return release_display;}); displayed.push_back(image);ready_values.push_back(sync->ready);
}
''' + body + r'''
int main() {
 const int crop[4]={10,20,600,300};
 if (std::atoi(std::getenv("RX_VK_ASYNC_PRESENT"))==0) {
  assert(!present_async_record(1,99,77,640,360,crop));
  assert(live_images==0 && copies==0); return 0;
 }
 if(std::getenv("RX_TEST_FAILED_CAPTURE")) {
  assert(present_async_record(1,99,77,640,360,crop));
  assert(present_async_pending());present_async_queue(false);native_drain();
  assert(native.failed && native.attempted==0 && native.queued==0 && !present_async_pending());
  std::quick_exit(0);
 }
 for(int i=0;i<3;++i) { assert(present_async_record(1,99,77,640,360,crop)); present_async_queue(true); }
 {
  std::unique_lock lk(gate_mu); gate_cv.wait(lk,[]{return entered;});
 }
 assert(live_images==3 && copies==3);
 for(auto f:formats) assert(f==77); // source format is retained, never quantized to RGBA8
 auto fourth=std::async(std::launch::async,[&]{return present_async_record(1,99,77,640,360,crop);});
 assert(fourth.wait_for(std::chrono::milliseconds(30))==std::future_status::timeout);
 {
  std::lock_guard lk(gate_mu); release_display=true;
 }
 gate_cv.notify_all(); assert(fourth.get()); present_async_queue(true); native_drain();
 assert(copies==4 && displayed.size()==4);
 assert(native.slots[0].sync.source_ns <= native.slots[0].sync.queued_ns);
 assert(native.slots[0].sync.queued_ns <= native.slots[0].sync.worker_ns);
 assert(native.slots[0].sync.worker_ns <= native.slots[0].sync.present_begin_ns);
 assert(native.slots[0].sync.present_end_ns <= native.slots[0].sync.finished_ns);
 assert(native.queued==4 && native.attempted==4);
 assert(native.shown==(std::getenv("RX_TEST_HIDDEN")?0:4));
 assert(ready_values==std::vector<uint64_t>({1,1,1,3}));
 assert(displayed[0]==1 && displayed[1]==2 && displayed[2]==3 && displayed[3]==1);
 interpolating=true;
 assert(!present_async_record(1,99,77,640,360,crop));
 interpolating=false;
 {std::lock_guard lock(fg.mu);fg.sets[0].busy=true;}
 auto transition=std::async(std::launch::async,[&]{return present_async_record(1,99,88,640,360,crop);});
 assert(transition.wait_for(std::chrono::milliseconds(30))==std::future_status::timeout);
 {std::lock_guard lock(fg.mu);fg.sets[0].busy=false;}fg.cv.notify_all();
 assert(transition.get());
 present_async_queue(true, 1234); native_drain();
 assert(live_images==3 && formats.back()==88 && native.attempted==5);
 assert(displayed.back()==5);
 fail_at=next_image+2; // partial replacement must be cleaned up and fall back
 assert(!present_async_record(1,99,89,640,360,crop));
 assert(live_images==0 && native.failed);
 assert(!present_async_record(1,99,77,640,360,crop));
 // The production worker lives until process exit; do not destroy its condition variable.
 std::quick_exit(0);
}
'''
    with tempfile.TemporaryDirectory(prefix='async-present-') as tmp:
        folder = Path(tmp)
        (folder / 'test.cpp').write_text(fixture)
        exe = folder / 'test.exe'
        subprocess.run([args.cxx, '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-pthread',
                        str(folder / 'test.cpp'), '-o', str(exe)], check=True)
        for enabled in ('0','1'):
            subprocess.run([str(exe)], env=dict(os.environ, RX_VK_ASYNC_PRESENT=enabled), check=True, timeout=15)
        trace=folder/'accepted.csv'
        subprocess.run([str(exe)], env=dict(os.environ, RX_VK_ASYNC_PRESENT='1',RX_VK_ASYNC_PRESENT_LOG=str(trace)), check=True, timeout=15)
        rows=list(csv.DictReader(trace.open()))
        assert len(rows)==5 and rows[-1]['source_frame']=='1234'
        for row in rows:
            times=[int(row[key]) for key in ('source_ns','queued_ns','worker_ns','present_begin_ns','present_end_ns','finished_ns')]
            assert times==sorted(times) and row['accepted']=='1' and row['result']=='0'
        subprocess.run([str(exe)], env=dict(os.environ, RX_VK_ASYNC_PRESENT='1',RX_TEST_FAILED_CAPTURE='1'), check=True, timeout=15)
        subprocess.run([str(exe)], env=dict(os.environ, RX_VK_ASYNC_PRESENT='1',RX_TEST_HIDDEN='1'), check=True, timeout=15)
    print('PASS: disabled mode, bounded queue, ordered reuse, source format/crop, drain and allocation fallback')


if __name__ == '__main__':
    main()
