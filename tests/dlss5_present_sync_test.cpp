#include <vulkan/vulkan.h>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <memory>
#include <mutex>
#include <unordered_map>
#include <vector>
#include <algorithm>
#include <unistd.h>

template<class T> T handle(uint64_t n) { return (T)(uintptr_t)n; }
bool modelOK=true, captureOK=true, composeOK=true, enabled=true;
int submitFail=0, submitCalls=0, semFail=0, semCalls=0;
std::unordered_map<VkSemaphore,bool> signaled;
struct Work { std::vector<VkSemaphore> waits, signals; VkFence fence; };
std::deque<Work> pending;
std::vector<VkSemaphore> presentedWaits;
const void* presentedNext=nullptr;
int presentCalls=0;
std::unordered_map<VkFence,bool> fences;
void progress() {
    assert(!pending.empty());auto w=pending.front();pending.pop_front();
    for(auto s:w.waits) {assert(signaled[s]);signaled[s]=false;}
    for(auto s:w.signals) {assert(!signaled[s]);signaled[s]=true;}
    fences[w.fence]=true;
}
VkResult submit(VkQueue,uint32_t,const VkSubmitInfo* si,VkFence f) {
    if(++submitCalls==submitFail) return VK_ERROR_OUT_OF_HOST_MEMORY;
    Work w;w.fence=f;
    if(si->waitSemaphoreCount) w.waits.assign(si->pWaitSemaphores,si->pWaitSemaphores+si->waitSemaphoreCount);
    if(si->signalSemaphoreCount) w.signals.assign(si->pSignalSemaphores,si->pSignalSemaphores+si->signalSemaphoreCount);
    pending.push_back(w);return VK_SUCCESS;
}
VkResult wait(VkDevice,uint32_t,const VkFence* f,VkBool32,uint64_t) {
    while(!fences[*f]) progress();return VK_SUCCESS;
}
VkResult reset(VkDevice,uint32_t,const VkFence* f) {fences[*f]=false;return VK_SUCCESS;}
VkResult begin(VkCommandBuffer,const VkCommandBufferBeginInfo*) {return VK_SUCCESS;}
VkResult end(VkCommandBuffer) {return VK_SUCCESS;}
VkResult createSem(VkDevice,const VkSemaphoreCreateInfo*,const VkAllocationCallbacks*,VkSemaphore* out) {
    if(++semCalls==semFail)return VK_ERROR_OUT_OF_HOST_MEMORY;
    *out=handle<VkSemaphore>(1000+semCalls);signaled[*out]=false;return VK_SUCCESS;
}
VkResult present(VkQueue,const VkPresentInfoKHR* p) {
    presentedWaits.clear();
    if(p->waitSemaphoreCount)presentedWaits.assign(p->pWaitSemaphores,p->pWaitSemaphores+p->waitSemaphoreCount);
    presentedNext=p->pNext;++presentCalls;return VK_SUCCESS;
}
void completePresentation() {
    while(!pending.empty())progress();
    for(auto s:presentedWaits){assert(signaled[s]);signaled[s]=false;}
}
struct Header {std::atomic<unsigned> seq_req{1};};
struct Shm {bool dead=false;Header* hdr=nullptr;};
struct Composition {
    bool RecordCapture(VkCommandBuffer,VkImage,int){return captureOK;}
    bool RecordCompose(VkCommandBuffer,VkImage,int){return composeOK;}
    bool RecordRestore(VkCommandBuffer,VkImage){return composeOK;}
    bool HasCapturedFrame(){return true;}
    int ModelWidth(){return 1;} int ModelHeight(){return 1;} int ModelBytes(){return 4;}
    void* ProxyPixels(){return nullptr;} void* ModelPixels(){return nullptr;}
    bool ProxyActive(){return false;} bool HdrProxyActive(){return false;}
    void ConsumeMeter(){} void MarkModelFrame(){}
};
struct SwapchainState {
    std::vector<VkImage> images;
    std::vector<VkSemaphore> presentReady;
    std::unique_ptr<Composition> comp=std::make_unique<Composition>();
    std::vector<VkPipelineStageFlags> waitStages;
    bool ready=true,passThrough=false,leg2Pending=false;
    unsigned width=640,height=480;VkQueue queue{};
    VkCommandBuffer cb=handle<VkCommandBuffer>(4);
    VkFence fenceLeg1=handle<VkFence>(5),fenceLeg2=handle<VkFence>(6);
};
struct DeviceChain {
    VkDevice self=handle<VkDevice>(1);bool inert=false;Shm shm;
    std::mutex lock;std::atomic<double> lastPresentMs{0};
    uint64_t framesPassedThrough=0,framesComposed=0;
    std::unordered_map<VkSwapchainKHR,SwapchainState> swapchains;
    std::unordered_map<VkQueue,uint32_t> queueFamilies;
    PFN_vkQueueSubmit vkQueueSubmit=submit;
    PFN_vkQueuePresentKHR vkQueuePresentKHR=present;
    PFN_vkWaitForFences vkWaitForFences=wait;
    PFN_vkResetFences vkResetFences=reset;
    PFN_vkBeginCommandBuffer vkBeginCommandBuffer=begin;
    PFN_vkEndCommandBuffer vkEndCommandBuffer=end;
    PFN_vkCreateSemaphore vkCreateSemaphore=createSem;
};
std::mutex g_stateMutex;
std::unordered_map<VkDevice,DeviceChain*> g_devices;
double NowMs(){return 0;}
bool TimeEnabled(){return false;}int TimeInterval(){return 30;}
bool LayerEnabled(){return enabled;}
bool VerboseEnabled(){return false;}
bool ShmNeuralEnabled(Shm&){return true;}
bool ClaimPrimary(VkDevice,VkSwapchainKHR,uint32_t,uint32_t){return true;}
void ReleasePrimary(VkDevice,VkSwapchainKHR){}
void PollHotkeys(DeviceChain*){}
void Log(const char*,...){}
bool NoteVk(DeviceChain*,VkResult r,const char*){return r==VK_SUCCESS;}
bool ShmProcessFrame(Shm&,int,int,int,void*,void*,bool,bool,bool){return modelOK;}
bool CreateResources(DeviceChain* dc,SwapchainState& sc,uint32_t) {
    VkDevice d=dc->self;
/* ALLOCATE */
    return true;
}
bool ProcessPresent(DeviceChain* dc,SwapchainState& sc,VkQueue queue,VkImage swapchainImage,
                    uint32_t waitCount,const VkSemaphore* waitSemaphores,bool,bool* waitsConsumed,VkSemaphore presentReady) {
    if(waitsConsumed)*waitsConsumed=false;
    VkDevice d=dc->self;VkCommandBuffer cb=sc.cb;bool time=false,answerViaFd=false;int fs=0;
    if(sc.leg2Pending){wait(d,1,&sc.fenceLeg2,VK_TRUE,UINT64_MAX);reset(d,1,&sc.fenceLeg2);sc.leg2Pending=false;}
/* PROCESS */
    return true;
}
/* RESTORE */
/* HOOK */
void idlePresent(DeviceChain* dc,SwapchainState* sc,VkSwapchainKHR swapchain,uint32_t index){
/* IDLE PRESENT */
}
int main(){
    DeviceChain dc;g_devices[dc.self]=&dc;
    auto scid=handle<VkSwapchainKHR>(8);auto queue=handle<VkQueue>(9);
    auto& sc=dc.swapchains[scid];
    for(unsigned i=0;i<4;++i)sc.images.push_back(handle<VkImage>(20+i));
    assert(CreateResources(&dc,sc,0));
    const VkSemaphore original=handle<VkSemaphore>(99);
    const int next=123;
    VkPresentInfoKHR pi{VK_STRUCTURE_TYPE_PRESENT_INFO_KHR};pi.pNext=&next;
    pi.swapchainCount=1;pi.pSwapchains=&scid;pi.waitSemaphoreCount=1;pi.pWaitSemaphores=&original;
    // Four images, acquired out of order: image identity, not a 2/3-frame ring, owns reuse.
    for(unsigned index:{0,2,1,3,2,0,3,1}){
        pi.pImageIndices=&index;signaled[original]=true;
        assert(Hook_QueuePresentKHR(queue,&pi)==VK_SUCCESS);
        assert(!signaled[original]);assert(presentedNext==&next);
        assert(presentedWaits==std::vector<VkSemaphore>{sc.presentReady[index]});
        assert(!signaled[presentedWaits[0]]); // compose GPU work is deliberately still pending
        completePresentation();assert(!signaled[sc.presentReady[index]]);
    }
    unsigned index=0;pi.pImageIndices=&index;
    // Even a caller that completed its own rendering on the CPU needs our compose wait.
    pi.waitSemaphoreCount=0;
    assert(Hook_QueuePresentKHR(queue,&pi)==VK_SUCCESS);
    assert(presentedWaits==std::vector<VkSemaphore>{sc.presentReady[index]});completePresentation();
    pi.waitSemaphoreCount=1;
    // Early failure keeps the application's wait; a model failure after capture does not double-wait.
    captureOK=false;signaled[original]=true;
    Hook_QueuePresentKHR(queue,&pi);assert(presentedWaits==std::vector<VkSemaphore>{original});completePresentation();captureOK=true;
    modelOK=false;signaled[original]=true;
    Hook_QueuePresentKHR(queue,&pi);assert(presentedWaits.empty()&&!signaled[original]);modelOK=true;
    submitFail=submitCalls+1;signaled[original]=true;
    Hook_QueuePresentKHR(queue,&pi);assert(presentedWaits==std::vector<VkSemaphore>{original});completePresentation();submitFail=0;
    // Restore follows a pending compose and signals the same image-owned wait.
    signaled[original]=true;Hook_QueuePresentKHR(queue,&pi);completePresentation();
    assert(sc.leg2Pending);
    assert(RestorePresent(&dc,sc,sc.images[0],sc.presentReady[0]));
    assert(sc.leg2Pending&&!signaled[sc.presentReady[0]]);
    idlePresent(&dc,&sc,scid,0);
    assert(presentedWaits==std::vector<VkSemaphore>{sc.presentReady[0]});completePresentation();
    // Multiple swapchains share the original wait only once, and retain each compose wait.
    auto secondID=handle<VkSwapchainKHR>(88);auto& second=dc.swapchains[secondID];
    second.images=sc.images;second.fenceLeg1=handle<VkFence>(55);second.fenceLeg2=handle<VkFence>(56);
    assert(CreateResources(&dc,second,0));
    VkSwapchainKHR chains[2]={scid,secondID};uint32_t indices[2]={2,3};
    pi.swapchainCount=2;pi.pSwapchains=chains;pi.pImageIndices=indices;signaled[original]=true;
    Hook_QueuePresentKHR(queue,&pi);
    assert(presentedWaits==std::vector<VkSemaphore>({sc.presentReady[2],second.presentReady[3]}));
    completePresentation();
    // Partial resource allocation leaves null slots, not bogus handles.
    SwapchainState partial;partial.images=sc.images;semFail=semCalls+3;
    assert(!CreateResources(&dc,partial,0));
    assert(partial.presentReady[0]&&partial.presentReady[1]&&!partial.presentReady[2]&&!partial.presentReady[3]);
    puts("PASS: delayed GPU, image-owned waits, zero original waits, failures, restore, allocation");
}
