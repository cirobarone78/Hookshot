// Optional Linux/XCB smoke test for the external DLSS layer. No game data.
// Real initially minimized window, 4 swapchain images, repeated recreation,
// synchronization validation and a bounded run. The launcher supplies DLSS.
#define VK_USE_PLATFORM_XCB_KHR
#include <vulkan/vulkan.h>
#include <xcb/xcb.h>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <thread>
#include <vector>
static std::atomic<unsigned> errors{0};
static VKAPI_ATTR VkBool32 VKAPI_CALL report(VkDebugUtilsMessageSeverityFlagBitsEXT severity,
    VkDebugUtilsMessageTypeFlagsEXT,const VkDebugUtilsMessengerCallbackDataEXT* data,void*) {
    if(severity&VK_DEBUG_UTILS_MESSAGE_SEVERITY_ERROR_BIT_EXT)++errors;
    fprintf(stderr,"VALIDATION[%s][%s]: %s\n", severity&VK_DEBUG_UTILS_MESSAGE_SEVERITY_ERROR_BIT_EXT ? "error" : "warning",data->pMessageIdName,data->pMessage);return VK_FALSE;
}
static void check(VkResult r) {if(r!=VK_SUCCESS){fprintf(stderr,"Vulkan result %d\n",r);std::exit(2);}}
int main(){
    int screenNo=0;auto* connection=xcb_connect(nullptr,&screenNo);
    if(xcb_connection_has_error(connection))return 2;
    auto screen=xcb_setup_roots_iterator(xcb_get_setup(connection));
    for(int i=0;i<screenNo;++i)xcb_screen_next(&screen);
    auto window=xcb_generate_id(connection);
    uint32_t mask=XCB_EVENT_MASK_STRUCTURE_NOTIFY;
    xcb_create_window(connection,XCB_COPY_FROM_PARENT,window,screen.data->root,0,0,480,270,0,
        XCB_WINDOW_CLASS_INPUT_OUTPUT,screen.data->root_visual,XCB_CW_EVENT_MASK,&mask);
    const char title[]="Hookshot DLSS synchronization test";
    xcb_change_property(connection,XCB_PROP_MODE_REPLACE,window,XCB_ATOM_WM_NAME,XCB_ATOM_STRING,8,sizeof(title)-1,title);
    uint32_t hints[9]={2,0,3}; // StateHint, IconicState: initially minimized, restorable window.
    xcb_change_property(connection,XCB_PROP_MODE_REPLACE,window,XCB_ATOM_WM_HINTS,XCB_ATOM_WM_HINTS,32,9,hints);
    xcb_map_window(connection,window);xcb_flush(connection);
    auto atomCookie=xcb_intern_atom(connection,0,8,"WM_STATE");
    auto* atom=xcb_intern_atom_reply(connection,atomCookie,nullptr);bool iconic=false;
    for(int retry=0;atom&&retry<20&&!iconic;++retry){
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        auto cookie=xcb_get_property(connection,0,window,atom->atom,atom->atom,0,2);
        auto* state=xcb_get_property_reply(connection,cookie,nullptr);
        if(state&&xcb_get_property_value_length(state)>=4)iconic=*(uint32_t*)xcb_get_property_value(state)==3;
        std::free(state);
    }
    std::free(atom);
    if(!iconic){xcb_destroy_window(connection,window);xcb_disconnect(connection);fprintf(stderr,"Window did not become iconic\n");return 4;}
    fprintf(stderr,"WINDOW_ICONIC=1\n");
    const char* ext[]={VK_KHR_SURFACE_EXTENSION_NAME,VK_KHR_XCB_SURFACE_EXTENSION_NAME,VK_EXT_DEBUG_UTILS_EXTENSION_NAME};
    VkValidationFeatureEnableEXT enable=VK_VALIDATION_FEATURE_ENABLE_SYNCHRONIZATION_VALIDATION_EXT;
    VkValidationFeaturesEXT validation{VK_STRUCTURE_TYPE_VALIDATION_FEATURES_EXT};
    validation.enabledValidationFeatureCount=1;validation.pEnabledValidationFeatures=&enable;
    VkDebugUtilsMessengerCreateInfoEXT debug{VK_STRUCTURE_TYPE_DEBUG_UTILS_MESSENGER_CREATE_INFO_EXT};
    debug.pNext=&validation;debug.messageSeverity=VK_DEBUG_UTILS_MESSAGE_SEVERITY_ERROR_BIT_EXT|VK_DEBUG_UTILS_MESSAGE_SEVERITY_WARNING_BIT_EXT;
    debug.messageType=VK_DEBUG_UTILS_MESSAGE_TYPE_GENERAL_BIT_EXT|VK_DEBUG_UTILS_MESSAGE_TYPE_VALIDATION_BIT_EXT|VK_DEBUG_UTILS_MESSAGE_TYPE_PERFORMANCE_BIT_EXT;
    debug.pfnUserCallback=report;
    VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO};app.pApplicationName=title;app.apiVersion=VK_API_VERSION_1_3;
    VkInstanceCreateInfo ici{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};ici.pNext=&debug;ici.pApplicationInfo=&app;
    ici.enabledExtensionCount=3;ici.ppEnabledExtensionNames=ext;
    VkInstance instance;check(vkCreateInstance(&ici,nullptr,&instance));
    debug.pNext=nullptr;VkDebugUtilsMessengerEXT messenger;
    auto createDebug=(PFN_vkCreateDebugUtilsMessengerEXT)vkGetInstanceProcAddr(instance,"vkCreateDebugUtilsMessengerEXT");
    check(createDebug(instance,&debug,nullptr,&messenger));
    VkXcbSurfaceCreateInfoKHR sci{VK_STRUCTURE_TYPE_XCB_SURFACE_CREATE_INFO_KHR};sci.connection=connection;sci.window=window;
    VkSurfaceKHR surface;check(vkCreateXcbSurfaceKHR(instance,&sci,nullptr,&surface));
    uint32_t count=0;check(vkEnumeratePhysicalDevices(instance,&count,nullptr));std::vector<VkPhysicalDevice> physicals(count);
    check(vkEnumeratePhysicalDevices(instance,&count,physicals.data()));
    VkPhysicalDevice physical=VK_NULL_HANDLE;uint32_t family=0;
    for(auto p:physicals){VkPhysicalDeviceProperties props;vkGetPhysicalDeviceProperties(p,&props);if(props.vendorID!=0x10de)continue;
        uint32_t n=0;vkGetPhysicalDeviceQueueFamilyProperties(p,&n,nullptr);std::vector<VkQueueFamilyProperties> queues(n);vkGetPhysicalDeviceQueueFamilyProperties(p,&n,queues.data());
        for(uint32_t i=0;i<n;++i){VkBool32 yes=0;check(vkGetPhysicalDeviceSurfaceSupportKHR(p,i,surface,&yes));if(yes&&(queues[i].queueFlags&VK_QUEUE_GRAPHICS_BIT)){physical=p;family=i;break;}}
    }
    if(!physical)return 3;
    float priority=1;VkDeviceQueueCreateInfo qci{VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};qci.queueFamilyIndex=family;qci.queueCount=1;qci.pQueuePriorities=&priority;
    const char* swapExt=VK_KHR_SWAPCHAIN_EXTENSION_NAME;
    VkDeviceCreateInfo dci{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};dci.queueCreateInfoCount=1;dci.pQueueCreateInfos=&qci;dci.enabledExtensionCount=1;dci.ppEnabledExtensionNames=&swapExt;
    VkDevice device;check(vkCreateDevice(physical,&dci,nullptr,&device));VkQueue queue;vkGetDeviceQueue(device,family,0,&queue);
    VkCommandPoolCreateInfo pci{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};pci.queueFamilyIndex=family;pci.flags=VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
    VkCommandPool pool;check(vkCreateCommandPool(device,&pci,nullptr,&pool));
    VkCommandBufferAllocateInfo cai{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};cai.commandPool=pool;cai.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY;cai.commandBufferCount=1;
    VkCommandBuffer cmd;check(vkAllocateCommandBuffers(device,&cai,&cmd));
    VkFenceCreateInfo fci{VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};VkFence fence;check(vkCreateFence(device,&fci,nullptr,&fence));
    VkSemaphoreCreateInfo semci{VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO};VkSemaphore acquire;check(vkCreateSemaphore(device,&semci,nullptr,&acquire));
    for(unsigned epoch=0;epoch<2;++epoch){
        uint32_t dims[2]={480+epoch*160,270+epoch*90};xcb_configure_window(connection,window,XCB_CONFIG_WINDOW_WIDTH|XCB_CONFIG_WINDOW_HEIGHT,dims);xcb_flush(connection);
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
        VkSurfaceCapabilitiesKHR caps;check(vkGetPhysicalDeviceSurfaceCapabilitiesKHR(physical,surface,&caps));
        uint32_t nf=0;check(vkGetPhysicalDeviceSurfaceFormatsKHR(physical,surface,&nf,nullptr));std::vector<VkSurfaceFormatKHR> formats(nf);check(vkGetPhysicalDeviceSurfaceFormatsKHR(physical,surface,&nf,formats.data()));
        auto format=formats.front();for(auto f:formats)if(f.format==VK_FORMAT_B8G8R8A8_UNORM)format=f;
        VkSwapchainCreateInfoKHR ci{VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR};ci.surface=surface;ci.minImageCount=std::max(4u,caps.minImageCount);if(caps.maxImageCount)ci.minImageCount=std::min(ci.minImageCount,caps.maxImageCount);
        ci.imageFormat=format.format;ci.imageColorSpace=format.colorSpace;ci.imageExtent=caps.currentExtent;
        if(ci.imageExtent.width==UINT32_MAX)ci.imageExtent={dims[0],dims[1]};
        ci.imageArrayLayers=1;ci.imageUsage=VK_IMAGE_USAGE_TRANSFER_DST_BIT;ci.imageSharingMode=VK_SHARING_MODE_EXCLUSIVE;
        ci.preTransform=caps.currentTransform;ci.compositeAlpha=VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR;ci.presentMode=VK_PRESENT_MODE_FIFO_KHR;ci.clipped=VK_TRUE;
        VkSwapchainKHR swap;check(vkCreateSwapchainKHR(device,&ci,nullptr,&swap));
        uint32_t n=0;check(vkGetSwapchainImagesKHR(device,swap,&n,nullptr));std::vector<VkImage> images(n);check(vkGetSwapchainImagesKHR(device,swap,&n,images.data()));
        std::vector<VkSemaphore> ready(n);for(auto& s:ready)check(vkCreateSemaphore(device,&semci,nullptr,&s));
        for(unsigned frame=0;frame<120;++frame){
            uint32_t index=0;check(vkAcquireNextImageKHR(device,swap,UINT64_MAX,acquire,VK_NULL_HANDLE,&index));
            check(vkResetCommandBuffer(cmd,0));VkCommandBufferBeginInfo bi{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};check(vkBeginCommandBuffer(cmd,&bi));
            VkImageMemoryBarrier barrier{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER};barrier.srcQueueFamilyIndex=barrier.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;
            barrier.oldLayout=VK_IMAGE_LAYOUT_UNDEFINED;barrier.newLayout=VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;barrier.dstAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT;
            barrier.image=images[index];barrier.subresourceRange={VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1};
            vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_TRANSFER_BIT,0,0,nullptr,0,nullptr,1,&barrier);
            VkClearColorValue colour{{float(frame%30)/30,0.2f,0.5f,1.0f}};vkCmdClearColorImage(cmd,images[index],VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,&colour,1,&barrier.subresourceRange);
            barrier.oldLayout=barrier.newLayout;barrier.newLayout=VK_IMAGE_LAYOUT_PRESENT_SRC_KHR;barrier.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT;barrier.dstAccessMask=0;
            vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,0,0,nullptr,0,nullptr,1,&barrier);check(vkEndCommandBuffer(cmd));
            VkPipelineStageFlags stage=VK_PIPELINE_STAGE_TRANSFER_BIT;VkSubmitInfo si{VK_STRUCTURE_TYPE_SUBMIT_INFO};si.waitSemaphoreCount=1;si.pWaitSemaphores=&acquire;si.pWaitDstStageMask=&stage;si.commandBufferCount=1;si.pCommandBuffers=&cmd;si.signalSemaphoreCount=1;si.pSignalSemaphores=&ready[index];
            check(vkQueueSubmit(queue,1,&si,fence));
            VkPresentInfoKHR pi{VK_STRUCTURE_TYPE_PRESENT_INFO_KHR};pi.swapchainCount=1;pi.pSwapchains=&swap;pi.pImageIndices=&index;pi.waitSemaphoreCount=1;pi.pWaitSemaphores=&ready[index];
            check(vkQueuePresentKHR(queue,&pi));check(vkWaitForFences(device,1,&fence,VK_TRUE,UINT64_MAX));check(vkResetFences(device,1,&fence));
            std::this_thread::sleep_for(std::chrono::milliseconds(16));
        }
        check(vkDeviceWaitIdle(device));for(auto s:ready)vkDestroySemaphore(device,s,nullptr);vkDestroySwapchainKHR(device,swap,nullptr);
        fprintf(stderr,"EPOCH %u complete, images=%u\n",epoch,n);
    }
    check(vkDeviceWaitIdle(device));vkDestroySemaphore(device,acquire,nullptr);vkDestroyFence(device,fence,nullptr);vkDestroyCommandPool(device,pool,nullptr);vkDestroyDevice(device,nullptr);vkDestroySurfaceKHR(instance,surface,nullptr);
    auto destroyDebug=(PFN_vkDestroyDebugUtilsMessengerEXT)vkGetInstanceProcAddr(instance,"vkDestroyDebugUtilsMessengerEXT");destroyDebug(instance,messenger,nullptr);vkDestroyInstance(instance,nullptr);
    xcb_destroy_window(connection,window);xcb_disconnect(connection);
    fprintf(stderr,"VALIDATION_ERRORS=%u\n",errors.load());return errors?1:0;
}
