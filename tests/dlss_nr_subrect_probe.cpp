// Optional Windows GPU probe, compiled manually with the user's own NGX SDK (not part of run_all).
// Synthetic inputs only; one feature at its maximum allocation, varying active subrects. No image files written.
// Usage: dlss_nr_subrect_probe.exe <runtime-directory> <writable-NGX-cache-directory>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#define VK_NO_PROTOTYPES
#include <windows.h>
#include <vulkan/vulkan.h>
#include <nvsdk_ngx_vk.h>
#include <nvsdk_ngx_helpers_vk.h>
#include <cstdio>
#include <cstring>
#include <vector>
#include <cmath>
#include <cstdint>
#include <string>
#include <cstdlib>
#include <utility>


static void NVSDK_CONV logger(const char* text, NVSDK_NGX_Logging_Level, NVSDK_NGX_Feature) {
    (void)text;
}
int wmain(int argc, wchar_t** argv) {
    if (argc != 3) { std::fprintf(stderr, "Usage: dlss_nr_subrect_probe <runtime-directory> <cache-directory>\n"); return 1; }
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    HMODULE module = LoadLibraryW(L"vulkan-1.dll");
    if (!module) return 1;
    auto gipa = (PFN_vkGetInstanceProcAddr)GetProcAddress(module, "vkGetInstanceProcAddr");
    auto create_instance = (PFN_vkCreateInstance)gipa(nullptr, "vkCreateInstance");
    VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO};
    app.pApplicationName = "Hookshot synthetic NR subrect probe", app.apiVersion = VK_API_VERSION_1_3;
    VkInstanceCreateInfo ic{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO}; ic.pApplicationInfo = &app;
    VkInstance instance{};
    if (create_instance(&ic, nullptr, &instance) != VK_SUCCESS) return 2;
#define IP(name) auto name = (PFN_##name)gipa(instance, #name)
    IP(vkEnumeratePhysicalDevices); IP(vkGetPhysicalDeviceProperties); IP(vkGetPhysicalDeviceQueueFamilyProperties);
    IP(vkEnumerateDeviceExtensionProperties); IP(vkGetPhysicalDeviceFeatures2); IP(vkCreateDevice);
    IP(vkDestroyInstance); IP(vkGetDeviceProcAddr);
    uint32_t n = 0; vkEnumeratePhysicalDevices(instance, &n, nullptr);
    std::vector<VkPhysicalDevice> physical(n); vkEnumeratePhysicalDevices(instance, &n, physical.data());
    VkPhysicalDevice pd{};
    for (auto p : physical) { VkPhysicalDeviceProperties prop{}; vkGetPhysicalDeviceProperties(p, &prop);
        if (prop.vendorID == 0x10de) { pd = p; std::printf("GPU: %s\n", prop.deviceName); break; } }
    if (!pd) return 3;
    vkGetPhysicalDeviceQueueFamilyProperties(pd, &n, nullptr);
    std::vector<VkQueueFamilyProperties> families(n); vkGetPhysicalDeviceQueueFamilyProperties(pd, &n, families.data());
    uint32_t family = 0; while (family < n && !(families[family].queueFlags & VK_QUEUE_GRAPHICS_BIT)) ++family;
    if (family == n) return 4;
    vkEnumerateDeviceExtensionProperties(pd, nullptr, &n, nullptr);
    std::vector<VkExtensionProperties> all(n); vkEnumerateDeviceExtensionProperties(pd, nullptr, &n, all.data());
    std::vector<const char*> extensions;
    for (const char* want : {"VK_NVX_binary_import", "VK_NVX_image_view_handle", "VK_KHR_push_descriptor"})
        for (const auto& e : all) if (!std::strcmp(want, e.extensionName)) { extensions.push_back(want); break; }
    VkPhysicalDeviceVulkan12Features f12{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES};
    VkPhysicalDeviceVulkan13Features f13{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES};
    VkPhysicalDeviceFeatures2 f{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2};
    f.pNext = &f12, f12.pNext = &f13; vkGetPhysicalDeviceFeatures2(pd, &f);
    const float priority = 1;
    VkDeviceQueueCreateInfo qi{VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};
    qi.queueFamilyIndex = family, qi.queueCount = 1, qi.pQueuePriorities = &priority;
    VkDeviceCreateInfo dc{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO}; dc.pNext = &f;
    dc.queueCreateInfoCount = 1, dc.pQueueCreateInfos = &qi;
    dc.enabledExtensionCount = (uint32_t)extensions.size(), dc.ppEnabledExtensionNames = extensions.data();
    VkDevice device{}; if (vkCreateDevice(pd, &dc, nullptr, &device) != VK_SUCCESS) return 5;
#define DP(name) auto name = (PFN_##name)vkGetDeviceProcAddr(device, #name)
    DP(vkGetDeviceQueue); DP(vkCreateCommandPool); DP(vkAllocateCommandBuffers); DP(vkBeginCommandBuffer);
    DP(vkEndCommandBuffer); DP(vkQueueSubmit); DP(vkQueueWaitIdle); DP(vkDestroyCommandPool); DP(vkDestroyDevice);
    VkQueue queue{}; vkGetDeviceQueue(device, family, 0, &queue);
    VkCommandPoolCreateInfo pc{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO}; pc.queueFamilyIndex = family; pc.flags=VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
    VkCommandPool pool{}; vkCreateCommandPool(device, &pc, nullptr, &pool);
    VkCommandBufferAllocateInfo ca{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};
    ca.commandPool = pool, ca.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, ca.commandBufferCount = 1;
    VkCommandBuffer cmd{}; vkAllocateCommandBuffers(device, &ca, &cmd);
    VkCommandBufferBeginInfo begin{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO}; vkBeginCommandBuffer(cmd, &begin);
    const wchar_t* paths[] = {argv[1]};
    NVSDK_NGX_FeatureCommonInfo common{}; common.PathListInfo = {paths, 1};
    common.LoggingInfo.LoggingCallback = logger;
    common.LoggingInfo.MinimumLoggingLevel = NVSDK_NGX_LOGGING_LEVEL_ON;
    common.LoggingInfo.DisableOtherLoggingSinks = true;
    NVSDK_NGX_Result result = NVSDK_NGX_VULKAN_Init_with_ProjectID(
        "7b2f5d0c-6a1e-4c39-9f84-3d5e2a1b0c96", NVSDK_NGX_ENGINE_TYPE_CUSTOM, "1.0",
        argv[2], instance, pd, device, gipa, vkGetDeviceProcAddr, &common);
    std::printf("PROBE NGX init: %#x\n", (unsigned)result);
    if (NVSDK_NGX_FAILED(result)) return 6;
    NVSDK_NGX_Parameter* params{}; result = NVSDK_NGX_VULKAN_GetCapabilityParameters(&params);
    std::printf("PROBE capabilities: %#x\n", (unsigned)result);
    if (NVSDK_NGX_FAILED(result) || !params) return 7;
    for (const char* key : {"DLSSNR.Available", "NeuralRendering.Available", "DLSSNR.FeatureInitResult"}) {
        int value = 0; result = NVSDK_NGX_Parameter_GetI(params, key, &value);
        std::printf("PROBE capability %s: %#x, value %d\n", key, (unsigned)result, value);
    }

    DP(vkCreateImage); DP(vkGetImageMemoryRequirements); DP(vkAllocateMemory); DP(vkBindImageMemory);
    DP(vkCreateImageView); DP(vkCreateBuffer); DP(vkGetBufferMemoryRequirements); DP(vkBindBufferMemory);
    DP(vkMapMemory); DP(vkUnmapMemory); DP(vkCmdPipelineBarrier2); DP(vkCmdCopyBufferToImage);
    DP(vkCmdClearColorImage); DP(vkCmdCopyImageToBuffer); DP(vkResetCommandBuffer); DP(vkDestroyImageView); DP(vkDestroyImage);
    DP(vkDestroyBuffer); DP(vkFreeMemory);
        IP(vkGetPhysicalDeviceMemoryProperties);
    VkPhysicalDeviceMemoryProperties mp{}; vkGetPhysicalDeviceMemoryProperties(pd,&mp);
    auto memory_type=[&](uint32_t bits,VkMemoryPropertyFlags flags) {
        for(uint32_t i=0;i<mp.memoryTypeCount;i++) if((bits&(1u<<i)) && (mp.memoryTypes[i].propertyFlags&flags)==flags) return i;
        return UINT32_MAX;
    };
    constexpr uint32_t W=640,H=360;
    struct Image {VkImage image{};VkImageView view{};VkDeviceMemory mem{};VkFormat format{};};
    auto make_image=[&](VkFormat format) {
        Image out;out.format=format;
        VkImageCreateInfo c{VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO};c.imageType=VK_IMAGE_TYPE_2D;c.format=format;
        c.extent={W,H,1};c.mipLevels=c.arrayLayers=1;c.samples=VK_SAMPLE_COUNT_1_BIT;c.tiling=VK_IMAGE_TILING_OPTIMAL;
        c.usage=VK_IMAGE_USAGE_SAMPLED_BIT|VK_IMAGE_USAGE_STORAGE_BIT|VK_IMAGE_USAGE_TRANSFER_SRC_BIT|VK_IMAGE_USAGE_TRANSFER_DST_BIT;
        if(vkCreateImage(device,&c,nullptr,&out.image)!=VK_SUCCESS) std::exit(20);
        VkMemoryRequirements r{};vkGetImageMemoryRequirements(device,out.image,&r);
        VkMemoryAllocateInfo a{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};a.allocationSize=r.size;a.memoryTypeIndex=memory_type(r.memoryTypeBits,VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
        if(vkAllocateMemory(device,&a,nullptr,&out.mem)!=VK_SUCCESS) std::exit(21);
        vkBindImageMemory(device,out.image,out.mem,0);
        VkImageViewCreateInfo v{VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};v.image=out.image;v.viewType=VK_IMAGE_VIEW_TYPE_2D;v.format=format;
        v.subresourceRange={VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1};
        if(vkCreateImageView(device,&v,nullptr,&out.view)!=VK_SUCCESS)std::exit(22);
        return out;
    };
    struct Buffer {VkBuffer buffer{};VkDeviceMemory mem{};void* data{};};
    auto make_buffer=[&](size_t bytes) {
        Buffer out;VkBufferCreateInfo b{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};b.size=bytes;b.usage=VK_BUFFER_USAGE_TRANSFER_SRC_BIT|VK_BUFFER_USAGE_TRANSFER_DST_BIT;
        if(vkCreateBuffer(device,&b,nullptr,&out.buffer)!=VK_SUCCESS) std::exit(23);
        VkMemoryRequirements r{};vkGetBufferMemoryRequirements(device,out.buffer,&r);
        VkMemoryAllocateInfo a{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};a.allocationSize=r.size;
        a.memoryTypeIndex=memory_type(r.memoryTypeBits,VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
        if(vkAllocateMemory(device,&a,nullptr,&out.mem)!=VK_SUCCESS)std::exit(24);
        vkBindBufferMemory(device,out.buffer,out.mem,0);vkMapMemory(device,out.mem,0,VK_WHOLE_SIZE,0,&out.data);
        return out;
    };
    auto barrier=[&]() {VkMemoryBarrier2 b{VK_STRUCTURE_TYPE_MEMORY_BARRIER_2};b.srcStageMask=b.dstStageMask=VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT;
        b.srcAccessMask=b.dstAccessMask=VK_ACCESS_2_MEMORY_READ_BIT|VK_ACCESS_2_MEMORY_WRITE_BIT;
        VkDependencyInfo d{VK_STRUCTURE_TYPE_DEPENDENCY_INFO};d.memoryBarrierCount=1;d.pMemoryBarriers=&b;vkCmdPipelineBarrier2(cmd,&d);};
    auto submit_wait=[&]() {vkEndCommandBuffer(cmd);VkSubmitInfo q{VK_STRUCTURE_TYPE_SUBMIT_INFO};q.commandBufferCount=1;q.pCommandBuffers=&cmd;
        if(vkQueueSubmit(queue,1,&q,VK_NULL_HANDLE)!=VK_SUCCESS || vkQueueWaitIdle(queue)!=VK_SUCCESS)std::exit(25);
        vkResetCommandBuffer(cmd,0);vkBeginCommandBuffer(cmd,&begin);};
    auto color=make_image(VK_FORMAT_R16G16B16A16_SFLOAT),depth=make_image(VK_FORMAT_R32_SFLOAT),motion=make_image(VK_FORMAT_R16G16_SFLOAT),output=make_image(VK_FORMAT_R16G16B16A16_SFLOAT);
    auto composed=make_image(VK_FORMAT_R16G16B16A16_SFLOAT);
    auto upload=make_buffer(W*H*8),dep_upload=make_buffer(W*H*4),mv_upload=make_buffer(W*H*4),readback=make_buffer(W*H*8);
    auto half=[](float f) {uint32_t b;std::memcpy(&b,&f,4);return (uint16_t)(f==0?0:((b+0x1000)>>13)-(112u<<10));};
    for(uint32_t y=0;y<H;y++) for(uint32_t x=0;x<W;x++) {
        uint16_t* pixel=((uint16_t*)upload.data)+(y*W+x)*4;
        pixel[0]=half(.2f+.5f*x/W);pixel[1]=half(.3f+.4f*y/H);pixel[2]=half(.4f);pixel[3]=half(1);
    }
    for(size_t i=0;i<W*H;i++)((float*)dep_upload.data)[i]=0.5f;
    std::memset(mv_upload.data,0,W*H*4);
    for(auto im:{color,depth,motion,output,composed}) {VkImageMemoryBarrier2 b{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER_2};b.image=im.image;
        b.srcStageMask=VK_PIPELINE_STAGE_2_NONE;b.dstStageMask=VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT;b.dstAccessMask=VK_ACCESS_2_MEMORY_READ_BIT|VK_ACCESS_2_MEMORY_WRITE_BIT;
        b.oldLayout=VK_IMAGE_LAYOUT_UNDEFINED;b.newLayout=VK_IMAGE_LAYOUT_GENERAL;b.srcQueueFamilyIndex=b.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;b.subresourceRange={VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1};
        VkDependencyInfo d{VK_STRUCTURE_TYPE_DEPENDENCY_INFO};d.imageMemoryBarrierCount=1;d.pImageMemoryBarriers=&b;vkCmdPipelineBarrier2(cmd,&d);}
    VkBufferImageCopy copy{};copy.imageSubresource={VK_IMAGE_ASPECT_COLOR_BIT,0,0,1};copy.imageExtent={W,H,1};
    vkCmdCopyBufferToImage(cmd,upload.buffer,color.image,VK_IMAGE_LAYOUT_GENERAL,1,&copy);
    vkCmdCopyBufferToImage(cmd,dep_upload.buffer,depth.image,VK_IMAGE_LAYOUT_GENERAL,1,&copy);
    vkCmdCopyBufferToImage(cmd,mv_upload.buffer,motion.image,VK_IMAGE_LAYOUT_GENERAL,1,&copy);barrier();submit_wait();
    auto resource=[](Image im,bool write) {return NVSDK_NGX_Create_ImageView_Resource_VK(im.view,im.image,{VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1},im.format,W,H,write);};
    auto c=resource(color,false),d=resource(depth,false),m=resource(motion,false),o=resource(output,true);
    NVSDK_NGX_Parameter* p{}; NVSDK_NGX_VULKAN_GetCapabilityParameters(&p);
    auto ui=[&](const char* key,unsigned v){NVSDK_NGX_Parameter_SetUI(p,key,v);};
    auto fp=[&](const char* key,float v){NVSDK_NGX_Parameter_SetF(p,key,v);};
    ui("DLSSNR.Enabled",1);ui("DLSSNR.Width",W);ui("DLSSNR.Height",H);ui("CreationNodeMask",1);ui("VisibilityNodeMask",1);
    ui("DLSSNR.Hint.Render.Preset",0);ui("DLSSNR.Style",0);ui("DLSSNR.UseAutoMask",1);ui("DLSSNR.UICorrection",1);
    fp("DLSSNR.Intensity",.35f);fp("DLSSNR.LocalStructureStrength",1);fp("DLSSNR.LocalToneStrength",1);fp("DLSSNR.SkinStructureStrength",1);
    NVSDK_NGX_Handle* handle{};result=NVSDK_NGX_VULKAN_CreateFeature(cmd,(NVSDK_NGX_Feature)18,p,&handle);barrier();
    std::printf("DRS feature 640x360 create %#x\n",(unsigned)result);
    if(NVSDK_NGX_FAILED(result)||!handle)return 27;
    NVSDK_NGX_Parameter_SetVoidPointer(p,"DLSSNR.Color",&c);NVSDK_NGX_Parameter_SetVoidPointer(p,"DLSSNR.Depth",&d);
    NVSDK_NGX_Parameter_SetVoidPointer(p,"DLSSNR.MVec",&m);NVSDK_NGX_Parameter_SetVoidPointer(p,"DLSSNR.Output",&o);
    ui("DLSSNR.DepthInverted",0);fp("DLSSNR.MVecScaleX",1);fp("DLSSNR.MVecScaleY",1);
    uint64_t first_hash = 0; unsigned sample = 0; bool valid = true;
    for(auto size: {std::pair{640u,360u},std::pair{512u,288u},std::pair{432u,240u},std::pair{640u,360u}}) {
        for(const char* prefix:{"Color","Output","Depth","MVec"})for(const char* axis:{"BaseX","BaseY","Width","Height"}){
            char key[64];std::snprintf(key,sizeof key,"DLSSNR.%sSubrect%s",prefix,axis);ui(key,!std::strcmp(axis,"Width")?size.first:!std::strcmp(axis,"Height")?size.second:0);}
        const VkClearColorValue sentinel{{.125f,.125f,.125f,.25f}};
        const VkImageSubresourceRange range{VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1};
        vkCmdClearColorImage(cmd,output.image,VK_IMAGE_LAYOUT_GENERAL,&sentinel,1,&range);barrier();
        ui("DLSSNR.Reset",1);
        result=NVSDK_NGX_VULKAN_EvaluateFeature(cmd,handle,p,nullptr);barrier();
        if(NVSDK_NGX_FAILED(result)) {std::printf("DRS eval %ux%u failed %#x\n",size.first,size.second,(unsigned)result);return 28;}
        vkCmdCopyImageToBuffer(cmd,output.image,VK_IMAGE_LAYOUT_GENERAL,readback.buffer,1,&copy);barrier();submit_wait();
        unsigned outside=0,invalid=0,written=0; uint64_t hash=1469598103934665603ull;
        auto data=(const uint16_t*)readback.data;
        for(uint32_t y=0;y<H;y++)for(uint32_t x=0;x<W;x++) {
            auto pixel=data+(y*W+x)*4;
            if(x>=size.first||y>=size.second) {
                if(pixel[0]!=half(.125f)||pixel[1]!=half(.125f)||pixel[2]!=half(.125f)||pixel[3]!=half(.25f))outside++;
            } else {
                written += pixel[0]!=half(.125f)||pixel[1]!=half(.125f)||pixel[2]!=half(.125f)||pixel[3]!=half(.25f);
                for(int channel=0;channel<4;channel++) {invalid+=((pixel[channel]&0x7c00)==0x7c00);hash=(hash^pixel[channel])*1099511628211ull;}
            }
        }
        valid &= outside == 0 && invalid == 0 && written != 0;
        if (sample == 0) first_hash = hash;
        if (sample++ == 3) valid &= hash == first_hash;
        std::printf("DRS eval %ux%u: success; changed active pixels=%u; writes outside subrect=%u; nonfinite=%u; hash=%llx\n",size.first,size.second,written,outside,invalid,(unsigned long long)hash);
    }
    NVSDK_NGX_VULKAN_ReleaseFeature(handle); NVSDK_NGX_VULKAN_DestroyParameters(p);
    submit_wait();
    for(auto im:{color,depth,motion,output,composed}){vkDestroyImageView(device,im.view,nullptr);vkDestroyImage(device,im.image,nullptr);vkFreeMemory(device,im.mem,nullptr);}
    for(auto b:{upload,dep_upload,mv_upload,readback}){vkUnmapMemory(device,b.mem);vkDestroyBuffer(device,b.buffer,nullptr);vkFreeMemory(device,b.mem,nullptr);}
    NVSDK_NGX_VULKAN_DestroyParameters(params);NVSDK_NGX_VULKAN_Shutdown1(device);
    vkDestroyCommandPool(device,pool,nullptr);vkDestroyDevice(device,nullptr);vkDestroyInstance(instance,nullptr);
    return valid ? 0 : 29;
}
#else
#include <cstdio>
int main() { std::puts("This optional GPU probe needs Windows and a user-supplied native NR runtime."); return 77; }
#endif
