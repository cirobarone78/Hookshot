"""Exercise production queue creation/retrieval and surface fallback without a GPU."""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}", "--headers", "{vulkan_headers}"]
p = argparse.ArgumentParser()
p.add_argument('--cxx', required=True)
p.add_argument('--headers', required=True)
a = p.parse_args()
root = Path(__file__).resolve().parents[1]
source = (root / 'gpu/vk/vk_main.cpp').read_text()
setup = source[source.index('    const int present_queue_mode ='):source.index('    // features: what the hardware')]
get = source[source.index('    vkGetDeviceQueue(dev.device, dev.queue_family, 0, &dev.queue);'):source.index('    if (dev.buffer_marker) buffer_markers_init();')]
start = source.index('static void choose_present_queue()')
end = source.index('{', start) + 1
depth = 1
while depth:
    depth += (source[end] == '{') - (source[end] == '}')
    end += 1
choose = source[start:end]
fixture = r'''
#define VK_NO_PROTOTYPES
#include <vulkan/vulkan.h>
#include <vector>
#include <cassert>
#include <cstdlib>
struct {
 VkPhysicalDevice physical{}; VkDevice device{}; VkSurfaceKHR surface{};
 uint32_t queue_family=0,present_family=0;
 VkQueue queue{},present_queue{};
} dev;
const char* option=nullptr;
char* test_getenv(const char*) {return const_cast<char*>(option);}
#define getenv test_getenv
void vkGetPhysicalDeviceProperties2(VkPhysicalDevice,VkPhysicalDeviceProperties2*){}
void vkGetDeviceQueue(VkDevice,uint32_t family,uint32_t index,VkQueue* out) {
 *out=reinterpret_cast<VkQueue>(uintptr_t(1+family*16+index));
}
bool surface_supported=true;
VkResult surface_result=VK_SUCCESS;
VkResult vkGetPhysicalDeviceSurfaceSupportKHR(VkPhysicalDevice,uint32_t,VkSurfaceKHR,VkBool32* out) {
 *out=surface_supported;return surface_result;
}
void logf(const char*,...){}
@@CHOOSE@@
void check(const char* requested,uint32_t graphics_count,bool compute,uint32_t expected_count,
           uint32_t expected_family,uint32_t expected_index) {
 option=requested;dev.queue_family=1;
 std::vector<VkQueueFamilyProperties> families(3);
 families[0].queueFlags=VK_QUEUE_TRANSFER_BIT;families[0].queueCount=1;
 families[1].queueFlags=VK_QUEUE_GRAPHICS_BIT|VK_QUEUE_COMPUTE_BIT;families[1].queueCount=graphics_count;
 families[2].queueFlags=compute?VK_QUEUE_COMPUTE_BIT:VK_QUEUE_TRANSFER_BIT;families[2].queueCount=1;
 uint32_t n=uint32_t(families.size());
 @@SETUP@@
 assert(qs[0].queueFamilyIndex==dev.queue_family&&qs[0].queueCount==expected_count);
 for(uint32_t i=0;i<qs[0].queueCount;++i)assert(qs[0].pQueuePriorities[i]==1.0f);
 if(compute_family!=UINT32_MAX){
  assert(compute_family==2&&qs[1].queueFamilyIndex!=qs[0].queueFamilyIndex);
  assert(qs[1].queueCount==1&&qs[1].pQueuePriorities[0]==1.0f);
 }
 @@GET@@
 assert(dev.queue==reinterpret_cast<VkQueue>(uintptr_t(17)));
 if(expected_family==UINT32_MAX){assert(!dev.present_queue&&dev.present_family==dev.queue_family);return;}
 assert(dev.present_family==expected_family);
 assert(dev.present_queue==reinterpret_cast<VkQueue>(uintptr_t(1+expected_family*16+expected_index)));
 assert(dev.present_queue!=dev.queue);
 surface_supported=true;surface_result=VK_SUCCESS;choose_present_queue();assert(dev.present_queue);
 surface_supported=false;choose_present_queue();assert(!dev.present_queue&&dev.present_family==dev.queue_family);
}
int main(){
 check(nullptr,4,true,1,UINT32_MAX,0);
 check("0",4,true,1,UINT32_MAX,0);
 check("1",4,true,1,2,0);
 check("1",4,false,1,UINT32_MAX,0);
 check("2",4,true,2,1,1);
 check("2",2,false,2,1,1);
 check("2",1,true,1,UINT32_MAX,0); // no uncreated queue or silent compute fallback
 check("-1",4,true,1,2,0); // retain legacy nonzero compute selection
}
'''
with tempfile.TemporaryDirectory() as t:
    cpp = Path(t) / 'test.cpp'
    exe = Path(t) / 'test'
    cpp.write_text(fixture.replace('@@CHOOSE@@', choose).replace('@@SETUP@@', setup).replace('@@GET@@', get))
    subprocess.run([a.cxx, '-std=c++20', '-O1', '-I'+a.headers, str(cpp), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('Present queue creation, distinct handles and surface fallback: PASS')
