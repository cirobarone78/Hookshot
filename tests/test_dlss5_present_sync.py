"""Optional production-path DLSS layer synchronization regression; no GPU/game."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get('DLSS5_LAYER_SOURCE', ROOT / 'work/dlss5/source/layer_linux/src/layer.cpp'))
HEADERS = ROOT / 'work/dlss5/source/standalone_runner/third_party'


class PresentSyncTest(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'linux' and SOURCE.is_file() and (HEADERS/'vulkan/vulkan.h').is_file() and shutil.which('g++'),
                         'requires pinned local DLSS layer checkout, Vulkan headers and g++')
    def test_delayed_compose_and_image_owned_waits(self):
        s = SOURCE.read_text()
        a = s.index('static bool ProcessPresent(', s.index('// Returns true if the swapchain image'))
        b = s.index('static VKAPI_ATTR VkResult VKAPI_CALL Hook_QueuePresentKHR(', a)
        process = s[a:b]
        core = process[process.index('    VkCommandBufferBeginInfo bi{};'):process.index('    const double tReturn')]
        a = b
        b = s.index('static DeviceChain* DeviceForQueue(', a)
        hook = s[a:b]
        a = s.index('    VkSemaphoreCreateInfo sci{', s.index('static bool CreateResources('))
        allocation = s[a:s.index('    if (!dc->instance)', a)]
        a = s.index('static bool RestorePresent(')
        restore = s[a:s.index('static VKAPI_ATTR VkResult VKAPI_CALL Hook_CreateDevice(', a)]
        a = s.index('                    VkPresentInfoKHR pi{', s.index('                if (drew) {'))
        b = s.index('                    dc->repaintSeenCtrl', a)
        idle = s[a:b]
        fixture = (ROOT/'tests/dlss5_present_sync_test.cpp').read_text()
        fixture = fixture.replace('/* ALLOCATE */', allocation).replace('/* PROCESS */', core)
        fixture = fixture.replace('/* HOOK */', hook).replace('/* RESTORE */', restore)
        fixture = fixture.replace('/* IDLE PRESENT */', idle)
        with tempfile.TemporaryDirectory() as tmp:
            cpp, exe = Path(tmp)/'check.cpp', Path(tmp)/'check'
            cpp.write_text(fixture)
            subprocess.run(['g++','-std=c++17','-O2','-pthread','-I'+str(HEADERS),str(cpp),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True,timeout=10)


    @unittest.skipUnless(sys.platform == 'linux' and (ROOT/'work/dlss5/source/layer_linux/src/composition.cpp').is_file() and shutil.which('g++'),
                         'requires pinned local DLSS source and g++')
    def test_swapchain_copy_barriers(self):
        source = (ROOT/'work/dlss5/source/layer_linux/src/composition.cpp').read_text()
        start = source.index('void Composition::TransitionSwapchain(')
        end = source.index('// One step in or out of the swapchain.', start)
        code = source[start:end]
        fixture = r'''#include <vulkan/vulkan.h>
#include <cassert>
VkImageMemoryBarrier got{}; VkPipelineStageFlags src{},dst{};
void barrier(VkCommandBuffer,VkPipelineStageFlags s,VkPipelineStageFlags d,VkDependencyFlags,
 uint32_t,const VkMemoryBarrier*,uint32_t,const VkBufferMemoryBarrier*,uint32_t n,const VkImageMemoryBarrier* b){
 assert(n==1);got=*b;src=s;dst=d;}
struct Table{PFN_vkCmdPipelineBarrier vkCmdPipelineBarrier=barrier;} table;
struct Composition {Table* _vk=&table;void TransitionSwapchain(VkCommandBuffer,VkImage,VkImageLayout,VkImageLayout);};
/* CODE */
int main(){Composition c;
 for(auto layout:{VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL}){
  auto access=layout==VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL?VK_ACCESS_TRANSFER_READ_BIT:VK_ACCESS_TRANSFER_WRITE_BIT;
  c.TransitionSwapchain({}, {},VK_IMAGE_LAYOUT_PRESENT_SRC_KHR,layout);
  assert(got.dstAccessMask==access&&src==VK_PIPELINE_STAGE_TRANSFER_BIT&&dst==VK_PIPELINE_STAGE_TRANSFER_BIT);
  c.TransitionSwapchain({}, {},layout,VK_IMAGE_LAYOUT_PRESENT_SRC_KHR);
  assert(got.srcAccessMask==access&&src==VK_PIPELINE_STAGE_TRANSFER_BIT);
  assert(got.srcQueueFamilyIndex==VK_QUEUE_FAMILY_IGNORED&&got.dstQueueFamilyIndex==VK_QUEUE_FAMILY_IGNORED);
 }
}'''
        fixture = '#include <initializer_list>\n' + fixture.replace('/* CODE */', code)
        with tempfile.TemporaryDirectory() as tmp:
            cpp,exe=Path(tmp)/'barrier.cpp',Path(tmp)/'barrier'
            cpp.write_text(fixture)
            subprocess.run(['g++','-std=c++17','-I'+str(HEADERS),str(cpp),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)


if __name__ == '__main__':
    unittest.main()
