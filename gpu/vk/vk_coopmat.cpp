// (hookshot) Native matrix multiplies: OoT's networks (the movie upscaler, the gameplay TAAU) are HMMA.16816.F16
// programs, which the shuffle expansion in lower_to_maxwell.h runs at a fraction of the speed. With
// VK_KHR_cooperative_matrix offering 16x8x16 f16 on the subgroup, HMMA lowers to HMMA_nx2 and the SPIR-V back end
// emits one OpCooperativeMatrixMulAddKHR, moving each lane's fragment registers in and out of its elements.
//
// Which matrix positions a lane's elements are is the implementation's choice, so at start this measures it: a probe
// loads row-major matrices whose values are their positions and writes out every lane's elements in order. When each
// lane holds the same positions as the console's fragments do (PTX mma.m16n8k16's layout), only the order within the
// lane differs, and that order (mma_layout.h) is all the emitter needs. A multiply in the console's layout is then
// checked against the CPU's (exact: small integers). Anything else, or RX_VK_NATIVE_MMA=0, keeps the expansion.
//
// (hookshot) Cards whose cooperative matrices are 16x16x16 only (RDNA3/4 on RADV): their lanes hold other positions, which
// no reordering within a lane can make the console's. There the multiplies go through shared memory instead
// (eden/.../mma_staged.h), once a self-test of that route's own function on random problems matches the software
// function's arithmetic (vk_mma_staged_test.h); otherwise, or with RX_VK_MMA_STAGED=0, the software function as before.
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <string>
#include <vector>

#include "vk_internal.h"
#include "vk_mma_staged_test.h"
#include "shader_recompiler/backend/spirv/mma_layout.h"
#include "shader_recompiler/backend/spirv/mma_staged.h"
#include <sirit/sirit.h>
#ifndef HOOKSHOT_ENV_H   // (env_on: the switches' one rule)
#include "hookshot_env.h"
#endif

namespace mkwvk {
VkResult guarded_compute_pipeline(VkPipelineCache cache, const VkComputePipelineCreateInfo* ci, VkPipeline* pl);   // (vk_draw.cpp)
namespace {

uint16_t to_half(float f) {   // (small integers only: exact)
    if (f == 0.0f) return 0;
    uint32_t x;
    std::memcpy(&x, &f, 4);
    const uint32_t sign = (x >> 16) & 0x8000;
    const int exp = (int)((x >> 23) & 0xff) - 127 + 15;
    return (uint16_t)(sign | (uint32_t)(exp << 10) | ((x >> 13) & 0x3ff));
}
float from_half(uint16_t h) {
    const uint32_t sign = (uint32_t)(h & 0x8000) << 16, exp = (h >> 10) & 0x1f, man = h & 0x3ff;
    uint32_t x;
    if (!exp && !man) x = sign;
    else if (!exp) { float f = std::ldexp((float)man, -24); return sign ? -f : f; }
    else if (exp == 31) x = sign | 0x7f800000 | (man << 13);
    else x = sign | ((exp - 15 + 127) << 23) | (man << 13);
    float f;
    std::memcpy(&f, &x, 4);
    return f;
}

// the console's fragment positions: lane t (g = t/4, i = t%4), element e (two a register, low half first)
void console_a(int t, int e, int& r, int& k) { const int g = t / 4, i = t % 4; r = g + ((e >> 1) & 1) * 8; k = 2 * i + (e & 1) + (e >> 2) * 8; }
void console_b(int t, int e, int& k, int& n) { const int g = t / 4, i = t % 4; k = 2 * i + (e & 1) + (e >> 1) * 8; n = g; }
void console_c(int t, int e, int& r, int& n) { const int g = t / 4, i = t % 4; r = g + (e >> 1) * 8; n = 2 * i + (e & 1); }

// a 32-lane compute shader over one storage buffer of u32 words, built by body(module, ...)
struct TestShader {
    Sirit::Module m{0x00010600};
    Sirit::Id u32, f16, f16x2, buf, u32_ptr, lane, ta, tb, tc, zero;
    Sirit::Id c32(uint32_t v) { return m.Constant(u32, v); }
    Sirit::Id word_ptr(Sirit::Id index) { return m.OpAccessChain(u32_ptr, buf, c32(0), index); }
    Sirit::Id word(Sirit::Id index) { return m.OpLoad(u32, word_ptr(index)); }
    void store(Sirit::Id index, Sirit::Id value) { m.OpStore(word_ptr(index), value); }
    Sirit::Id at(Sirit::Id base, uint32_t add) { return m.OpIAdd(u32, base, c32(add)); }
    Sirit::Id pack(Sirit::Id lo, Sirit::Id hi) { return m.OpBitcast(u32, m.OpCompositeConstruct(f16x2, lo, hi)); }
    Sirit::Id element(Sirit::Id matrix, uint32_t j) { return m.OpCompositeExtract(f16, matrix, j); }
};

std::vector<uint32_t> build_shader(const std::function<void(TestShader&)>& body) {
    using namespace Sirit;
    TestShader s;
    Module& m = s.m;
    m.AddCapability(spv::Capability::Shader);
    m.AddCapability(spv::Capability::Float16);
    m.AddCapability(spv::Capability::CooperativeMatrixKHR);
    m.AddExtension("SPV_KHR_cooperative_matrix");
    m.AddCapability(spv::Capability::VulkanMemoryModel);
    m.AddExtension("SPV_KHR_vulkan_memory_model");
    m.SetMemoryModel(spv::AddressingModel::Logical, spv::MemoryModel::VulkanKHR);
    const Id void_t = m.TypeVoid();
    s.u32 = m.TypeUInt(32);
    const Id uvec3 = m.TypeVector(s.u32, 3);
    s.f16 = m.TypeFloat(16);
    s.f16x2 = m.TypeVector(s.f16, 2);
    const Id runtime = m.TypeRuntimeArray(s.u32);
    m.Decorate(runtime, spv::Decoration::ArrayStride, 4U);
    const Id block = m.TypeStruct(runtime);
    m.Decorate(block, spv::Decoration::Block);
    m.MemberDecorate(block, 0U, spv::Decoration::Offset, 0U);
    s.buf = m.AddGlobalVariable(m.TypePointer(spv::StorageClass::StorageBuffer, block), spv::StorageClass::StorageBuffer);
    m.Decorate(s.buf, spv::Decoration::DescriptorSet, 0U);
    m.Decorate(s.buf, spv::Decoration::Binding, 0U);
    const Id lid = m.AddGlobalVariable(m.TypePointer(spv::StorageClass::Input, uvec3), spv::StorageClass::Input);
    m.Decorate(lid, spv::Decoration::BuiltIn, spv::BuiltIn::LocalInvocationId);
    s.u32_ptr = m.TypePointer(spv::StorageClass::StorageBuffer, s.u32);
    const Id scope = s.c32((uint32_t)spv::Scope::Subgroup);
    const auto mat = [&](uint32_t r, uint32_t c, spv::CooperativeMatrixUse use) {
        return m.TypeCooperativeMatrixKHR(s.f16, scope, s.c32(r), s.c32(c), s.c32((uint32_t)use));
    };
    s.ta = mat(16, 16, spv::CooperativeMatrixUse::MatrixAKHR);
    s.tb = mat(16, 8, spv::CooperativeMatrixUse::MatrixBKHR);
    s.tc = mat(16, 8, spv::CooperativeMatrixUse::MatrixAccumulatorKHR);
    s.zero = m.Constant(s.f16, 0U);
    const Id main = m.OpFunction(void_t, spv::FunctionControlMask::MaskNone, m.TypeFunction(void_t));
    m.AddLabel();
    s.lane = m.OpCompositeExtract(s.u32, m.OpLoad(uvec3, lid), 0U);
    body(s);
    m.OpReturn();
    m.OpFunctionEnd();
    m.AddEntryPoint(spv::ExecutionModel::GLCompute, main, "main", s.buf, lid);
    m.AddExecutionMode(main, spv::ExecutionMode::LocalSize, 32U, 1U, 1U);
    return m.Assemble();
}

// one dispatch of a 32-lane shader over words (in and out): groups workgroups, with whole subgroups when asked (a
// workgroup a multiple of 32 lanes wide, as vk_draw.cpp's pin_subgroup gives the game's programs)
bool run_shader(const std::vector<uint32_t>& code, std::vector<uint32_t>& data, uint32_t groups = 1, bool full_subgroups = false) {
    const VkDeviceSize size = data.size() * 4;
    VkBufferCreateInfo bi{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};
    bi.size = size;
    bi.usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT;
    VkBuffer buffer{};
    if (vkCreateBuffer(dev.device, &bi, nullptr, &buffer) != VK_SUCCESS) return false;
    VkMemoryRequirements req;
    vkGetBufferMemoryRequirements(dev.device, buffer, &req);
    VkPhysicalDeviceMemoryProperties mp;
    vkGetPhysicalDeviceMemoryProperties(dev.physical, &mp);
    uint32_t type = UINT32_MAX;
    const VkMemoryPropertyFlags want = VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
    for (uint32_t i = 0; i < mp.memoryTypeCount && type == UINT32_MAX; i++)
        if ((req.memoryTypeBits & (1u << i)) && (mp.memoryTypes[i].propertyFlags & want) == want) type = i;
    VkMemoryAllocateInfo ai{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
    ai.allocationSize = req.size;
    ai.memoryTypeIndex = type;
    VkDeviceMemory memory{};
    if (type == UINT32_MAX || vkAllocateMemory(dev.device, &ai, nullptr, &memory) != VK_SUCCESS) {
        vkDestroyBuffer(dev.device, buffer, nullptr);
        return false;
    }
    vkBindBufferMemory(dev.device, buffer, memory, 0);
    uint32_t* words = nullptr;
    vkMapMemory(dev.device, memory, 0, size, 0, (void**)&words);
    std::memcpy(words, data.data(), size);

    VkDescriptorSetLayoutBinding b{0, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr};
    VkDescriptorSetLayoutCreateInfo dli{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};
    dli.bindingCount = 1, dli.pBindings = &b;
    VkDescriptorSetLayout dsl{};
    vkCreateDescriptorSetLayout(dev.device, &dli, nullptr, &dsl);
    VkPipelineLayoutCreateInfo pli{VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
    pli.setLayoutCount = 1, pli.pSetLayouts = &dsl;
    VkPipelineLayout layout{};
    vkCreatePipelineLayout(dev.device, &pli, nullptr, &layout);
    VkShaderModuleCreateInfo smi{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
    smi.codeSize = code.size() * 4, smi.pCode = code.data();
    VkShaderModule module{};
    vkCreateShaderModule(dev.device, &smi, nullptr, &module);
    VkComputePipelineCreateInfo cpi{VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO};
    cpi.stage = {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, nullptr, 0, VK_SHADER_STAGE_COMPUTE_BIT, module, "main", nullptr};
    VkPipelineShaderStageRequiredSubgroupSizeCreateInfo lanes{VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_REQUIRED_SUBGROUP_SIZE_CREATE_INFO};
    lanes.requiredSubgroupSize = 32;   // (as the programs it stands for will run: vk_main.cpp)
    if (dev.sg32_stages & VK_SHADER_STAGE_COMPUTE_BIT) cpi.stage.pNext = &lanes;
    if (full_subgroups) cpi.stage.flags |= VK_PIPELINE_SHADER_STAGE_CREATE_REQUIRE_FULL_SUBGROUPS_BIT;
    cpi.layout = layout;
    VkPipeline pipeline{};
    // (behind vk_draw.cpp's fault guard, as the game's own compute pipelines: a driver that faults compiling a test fails
    // the test, -77, and the multiplies go as without that route)
    const VkResult pr = module ? guarded_compute_pipeline(VK_NULL_HANDLE, &cpi, &pipeline) : VK_ERROR_INITIALIZATION_FAILED;
    bool ok = false;
    if (pr == VK_SUCCESS) {
        VkDescriptorPoolSize ps{VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1};
        VkDescriptorPoolCreateInfo dpi{VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO};
        dpi.maxSets = 1, dpi.poolSizeCount = 1, dpi.pPoolSizes = &ps;
        VkDescriptorPool pool{};
        vkCreateDescriptorPool(dev.device, &dpi, nullptr, &pool);
        VkDescriptorSetAllocateInfo dsa{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO};
        dsa.descriptorPool = pool, dsa.descriptorSetCount = 1, dsa.pSetLayouts = &dsl;
        VkDescriptorSet set{};
        vkAllocateDescriptorSets(dev.device, &dsa, &set);
        VkDescriptorBufferInfo dbi{buffer, 0, size};
        VkWriteDescriptorSet wr{VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET};
        wr.dstSet = set, wr.descriptorCount = 1, wr.descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, wr.pBufferInfo = &dbi;
        vkUpdateDescriptorSets(dev.device, 1, &wr, 0, nullptr);
        VkCommandPoolCreateInfo cpci{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};
        cpci.queueFamilyIndex = dev.queue_family;
        VkCommandPool cmd_pool{};
        vkCreateCommandPool(dev.device, &cpci, nullptr, &cmd_pool);
        VkCommandBufferAllocateInfo cba{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};
        cba.commandPool = cmd_pool, cba.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, cba.commandBufferCount = 1;
        VkCommandBuffer cmd{};
        vkAllocateCommandBuffers(dev.device, &cba, &cmd);
        VkCommandBufferBeginInfo cbb{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
        cbb.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
        vkBeginCommandBuffer(cmd, &cbb);
        vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline);
        vkCmdBindDescriptorSets(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, layout, 0, 1, &set, 0, nullptr);
        vkCmdDispatch(cmd, groups, 1, 1);
        VkMemoryBarrier2 mb{VK_STRUCTURE_TYPE_MEMORY_BARRIER_2};
        mb.srcStageMask = VK_PIPELINE_STAGE_2_COMPUTE_SHADER_BIT, mb.srcAccessMask = VK_ACCESS_2_SHADER_WRITE_BIT;
        mb.dstStageMask = VK_PIPELINE_STAGE_2_HOST_BIT, mb.dstAccessMask = VK_ACCESS_2_HOST_READ_BIT;
        VkDependencyInfo di{VK_STRUCTURE_TYPE_DEPENDENCY_INFO};
        di.memoryBarrierCount = 1, di.pMemoryBarriers = &mb;
        vkCmdPipelineBarrier2(cmd, &di);
        vkEndCommandBuffer(cmd);
        VkFenceCreateInfo fci{VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
        VkFence fence{};
        vkCreateFence(dev.device, &fci, nullptr, &fence);
        VkCommandBufferSubmitInfo csi{VK_STRUCTURE_TYPE_COMMAND_BUFFER_SUBMIT_INFO};
        csi.commandBuffer = cmd;
        VkSubmitInfo2 si{VK_STRUCTURE_TYPE_SUBMIT_INFO_2};
        si.commandBufferInfoCount = 1, si.pCommandBufferInfos = &csi;
        ok = vkQueueSubmit2(dev.queue, 1, &si, fence) == VK_SUCCESS &&
             vkWaitForFences(dev.device, 1, &fence, VK_TRUE, 5000000000ull) == VK_SUCCESS;
        if (ok) std::memcpy(data.data(), words, size);
        else logf("vk: cooperative matrix test: the dispatch did not complete");
        vkDestroyFence(dev.device, fence, nullptr);
        vkDestroyCommandPool(dev.device, cmd_pool, nullptr);
        vkDestroyDescriptorPool(dev.device, pool, nullptr);
        vkDestroyPipeline(dev.device, pipeline, nullptr);
    } else {
        logf("vk: cooperative matrix test: pipeline creation failed (%d)", (int)pr);
    }
    if (module) vkDestroyShaderModule(dev.device, module, nullptr);
    vkDestroyPipelineLayout(dev.device, layout, nullptr);
    vkDestroyDescriptorSetLayout(dev.device, dsl, nullptr);
    vkDestroyBuffer(dev.device, buffer, nullptr);
    vkFreeMemory(dev.device, memory, nullptr);
    return ok;
}

// The probe: A (16x16), B (16x8) and C (16x8) loaded row major from words 0, 128 and 192, each element's value its
// position (row * columns + column); lane t writes its 8 A elements at 256 + 4t, its 4 B at 384 + 2t, its 4 C at
// 448 + 2t. Then each console element is found among the device's of the same lane: one order for all lanes or none.
bool measure_order() {
    std::vector<uint32_t> data(512, 0);
    const auto put = [&](uint32_t base, int rows, int cols) {
        for (int r = 0; r < rows; r++)
            for (int c = 0; c < cols; c += 2)
                data[base + (r * cols + c) / 2] = (uint32_t)to_half((float)(r * cols + c)) |
                                                  ((uint32_t)to_half((float)(r * cols + c + 1)) << 16);
    };
    put(0, 16, 16), put(128, 16, 8), put(192, 16, 8);
    const auto code = build_shader([](TestShader& s) {
        auto& m = s.m;
        const auto load = [&](Sirit::Id type, uint32_t base, uint32_t stride_words) {
            return m.OpCooperativeMatrixLoadKHR(type, s.word_ptr(s.c32(base)), s.c32(0) /* RowMajorKHR */,
                                                s.c32(stride_words));
        };
        const Sirit::Id a = load(s.ta, 0, 8), b = load(s.tb, 128, 4), c = load(s.tc, 192, 4);
        const auto out = [&](Sirit::Id matrix, uint32_t base, uint32_t words) {
            const Sirit::Id at = m.OpIAdd(s.u32, s.c32(base), m.OpIMul(s.u32, s.lane, s.c32(words)));
            for (uint32_t w = 0; w < words; w++) s.store(s.at(at, w), s.pack(s.element(matrix, 2 * w), s.element(matrix, 2 * w + 1)));
        };
        out(a, 256, 4), out(b, 384, 2), out(c, 448, 2);
    });
    if (!run_shader(code, data)) return false;
    const auto dev_value = [&](uint32_t base, uint32_t words, int t, int j) {
        const uint32_t w = data[base + t * words + j / 2];
        return (int)from_half((uint16_t)(j & 1 ? w >> 16 : w & 0xffff));
    };
    const auto find = [&](const char* name, uint32_t base, int count, int cols, auto console, auto& order) {
        for (int e = 0; e < count; e++) {
            int found = -1;
            for (int t = 0; t < 32; t++) {
                int r, c;
                console(t, e, r, c);
                int j = 0;
                while (j < count && dev_value(base, count / 2, t, j) != r * cols + c) j++;
                if (j == count || (found >= 0 && j != found)) {
                    std::string row;
                    for (int k = 0; k < count; k++) row += " " + std::to_string(dev_value(base, count / 2, t, k));
                    logf("vk: cooperative matrix %s: lane %d holds%s, the console's element %d is (%d, %d): not the same "
                         "positions in every lane", name, t, row.c_str(), e, r, c);
                    return false;
                }
                found = j;
            }
            order[e] = (uint32_t)found;
        }
        std::string s;
        for (int e = 0; e < count; e++) s += " " + std::to_string(order[e]);
        logf("vk: cooperative matrix %s: the console's elements are the device's%s", name, s.c_str());
        return true;
    };
    using namespace Shader::Backend::SPIRV;
    return find("A", 256, 8, 16, console_a, mma_order_a) && find("B", 384, 4, 8, console_b, mma_order_b) &&
           find("C", 448, 4, 8, console_c, mma_order_c);
}

// test values (small integers, every product and sum exact in f16)
float a_val(int r, int k) { return (float)(((r * 7 + k * 3 + 1) % 5) - 2); }
float b_val(int k, int n) { return (float)(((k * 5 + n * 11 + 2) % 4) - 1); }
float c_val(int r, int n) { return (float)(((r * 3 + n * 13) % 9) - 4); }

// The multiply as HMMA_nx2 emits it: lane t's fragment words at 8t (A 4, B 2, C 2), D's 2 out at 256 + 2t
bool test_multiply() {
    using namespace Shader::Backend::SPIRV;
    std::vector<uint32_t> data(320, 0xffffffffu);
    const auto pack = [](float lo, float hi) { return (uint32_t)to_half(lo) | ((uint32_t)to_half(hi) << 16); };
    for (int t = 0; t < 32; t++) {
        int r0, c0, r1, c1;
        for (int e = 0; e < 8; e += 2) console_a(t, e, r0, c0), console_a(t, e + 1, r1, c1), data[t * 8 + e / 2] = pack(a_val(r0, c0), a_val(r1, c1));
        for (int e = 0; e < 4; e += 2) console_b(t, e, r0, c0), console_b(t, e + 1, r1, c1), data[t * 8 + 4 + e / 2] = pack(b_val(r0, c0), b_val(r1, c1));
        for (int e = 0; e < 4; e += 2) console_c(t, e, r0, c0), console_c(t, e + 1, r1, c1), data[t * 8 + 6 + e / 2] = pack(c_val(r0, c0), c_val(r1, c1));
    }
    const auto code = build_shader([](TestShader& s) {
        auto& m = s.m;
        const Sirit::Id base = m.OpIMul(s.u32, s.lane, s.c32(8));
        const auto load = [&](Sirit::Id type, uint32_t first, uint32_t count, const auto& order) {
            Sirit::Id mx = m.OpCompositeConstruct(type, s.zero);
            for (uint32_t w = 0; w < count; w++) {
                const Sirit::Id pair = m.OpBitcast(s.f16x2, s.word(s.at(base, first + w)));
                for (uint32_t h = 0; h < 2; h++) mx = m.OpCompositeInsert(type, m.OpCompositeExtract(s.f16, pair, h), mx, order[w * 2 + h]);
            }
            return mx;
        };
        const Sirit::Id d = m.OpCooperativeMatrixMulAddKHR(s.tc, load(s.ta, 0, 4, mma_order_a), load(s.tb, 4, 2, mma_order_b),
                                                            load(s.tc, 6, 2, mma_order_c));
        const Sirit::Id out = m.OpIAdd(s.u32, s.c32(256), m.OpIMul(s.u32, s.lane, s.c32(2)));
        for (uint32_t w = 0; w < 2; w++)
            s.store(s.at(out, w), s.pack(s.element(d, mma_order_c[w * 2]), s.element(d, mma_order_c[w * 2 + 1])));
    });
    if (!run_shader(code, data)) return false;
    int bad = 0;
    for (int t = 0; t < 32; t++)
        for (int e = 0; e < 4; e++) {
            int r, n;
            console_c(t, e, r, n);
            float want_d = c_val(r, n);
            for (int k = 0; k < 16; k++) want_d += a_val(r, k) * b_val(k, n);
            const uint32_t w = data[256 + t * 2 + e / 2];
            const float got = from_half((uint16_t)(e & 1 ? w >> 16 : w & 0xffff));
            if (got != want_d && bad++ < 4)
                logf("vk: cooperative matrix test: lane %d element %d (D[%d][%d]) %g, the CPU %g", t, e, r, n, got, want_d);
        }
    if (bad) logf("vk: cooperative matrix test: %d of 128 elements differ", bad);
    return bad == 0;
}

/// (hookshot) The staged route (mma_staged.h) on this device: random HMMA problems through the route's own function in
/// workgroups of four subgroups, against the software function's arithmetic (vk_mma_staged_test.h). It passes when no
/// element is further from that than HMMA's two f16 roundings and the f32 sums allow, the small-integer problems are exact,
/// the program's own shared memory is untouched, and at most 2% of the elements differ by a rounding at all, 0.8% of a
/// kind of problem's and 2.4% of those at one place of D (an f32 summation order differs in a few in ten thousand; a wrong
/// rounding mode would show in half of them, a wrong lane at its places). False: why says why
bool test_staged(std::string& why) {
    namespace T = mma_staged_test;
    const Shader::Backend::SPIRV::StagedScratch scratch = T::scratch_for(dev.props.limits.maxComputeSharedMemorySize);
    if (!scratch.fits) {
        why = "no room for its scratch in shared memory";
        return false;
    }
    constexpr uint32_t groups = 16;
    T::Report total;
    for (const uint64_t seed : {0x5eed0f0a2c0ffee1ull, 0x9dc98871eb7fc101ull}) {
        std::vector<uint32_t> data = T::make_data(groups, seed);
        if (!run_shader(T::build(scratch, groups), data, groups, true)) {
            why = "its test dispatch did not run";
            return false;
        }
        total.add(T::check(data, groups, seed));
    }
    logf("vk: staged matrix self-test: %s", T::summary(total).c_str());
    if (!total.passed(20)) {
        why = total.worst.empty() ? "its results are not the software function's" : "its results are not the software function's: " + total.worst;
        return false;
    }
    return true;
}

} // namespace

// (vk_main.cpp, once the device is made: dev.coop_matrix says the extension and its feature are on)
namespace {
/// Without cooperative matrices (a GTX 1650, an RTX 2060 on some drivers, AMD and Intel cards): the same multiplies in a shader function on
/// subgroup shuffles. The lowering refuses a matrix multiply it has no way to run, and the game's upscaling networks were then left out:
/// the 3D scene came out black or as coloured noise, with the HUD over it (Hookshot issues 10 and 14)
void software_multiplies(const char* why) {
    Shader::Backend::SPIRV::mma_software = true;
    dev.native_mma = true;
    logf("vk: matrix multiplies in software (%s)", why);
}

/// (hookshot) Cooperative matrices of 16x16x16 only (RDNA3/4 on RADV): the multiplies staged through shared memory
/// (mma_staged.h), when the device has what the route needs and its self-test passes. False: not on, and logged why.
/// Asked (RX_VK_MMA_STAGED=1): on any driver; otherwise on Mesa RADV only, the driver it was tested on (AMD's own driver
/// lists 16x16x16 on RDNA2 too, without the matrix hardware, and has crashed building such pipelines there)
bool staged_multiplies(const std::vector<VkCooperativeMatrixPropertiesKHR>& props, const char* otherwise, bool asked) {
    bool shape = false;   // (f16 x f16 -> f32: the f32 sums HMMA's roundings are made from, mma_staged.h)
    for (const auto& p : props)
        shape |= p.MSize == 16 && p.NSize == 16 && p.KSize == 16 && p.AType == VK_COMPONENT_TYPE_FLOAT16_KHR &&
                 p.BType == VK_COMPONENT_TYPE_FLOAT16_KHR && p.CType == VK_COMPONENT_TYPE_FLOAT32_KHR &&
                 p.ResultType == VK_COMPONENT_TYPE_FLOAT32_KHR && p.scope == VK_SCOPE_SUBGROUP_KHR;
    VkPhysicalDeviceCooperativeMatrixPropertiesKHR stages{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_COOPERATIVE_MATRIX_PROPERTIES_KHR};
    VkPhysicalDeviceProperties2 p2{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2};
    p2.pNext = &stages;
    vkGetPhysicalDeviceProperties2(dev.physical, &p2);
    std::string why;
    if (!shape) why = "no 16x16x16 f16 -> f32 cooperative matrices";
    else if (!(stages.cooperativeMatrixSupportedStages & VK_SHADER_STAGE_COMPUTE_BIT)) why = "no cooperative matrices in compute shaders";
    else if (!dev.vk12.shaderFloat16) why = "no f16 shaders";
    else if (!(dev.sg32_stages & VK_SHADER_STAGE_COMPUTE_BIT) || !dev.vk13.computeFullSubgroups)
        why = "compute subgroups cannot be held to 32 lanes, whole";
    else if (!asked && dev.driver_id != VK_DRIVER_ID_MESA_RADV)
        why = "tested on Mesa RADV only so far (RX_VK_MMA_STAGED=1 tries it on this driver)";
    else {
        // (said before it runs: should the driver hang or fail the device in it, the log's last line says how to start without it)
        logf("vk: staged matrix self-test (RX_VK_MMA_STAGED=0 starts without it and without the route)");
        test_staged(why);
    }
    if (!why.empty()) {
        logf("vk: staged matrix multiplies not used: %s; %s instead", why.c_str(), otherwise);
        return false;
    }
    Shader::Backend::SPIRV::mma_staged = true;
    Shader::Backend::SPIRV::mma_staged_shared_limit = dev.props.limits.maxComputeSharedMemorySize;
    dev.native_mma = true;
    logf("vk: matrix multiplies on 16x16x16 cooperative matrices, staged through shared memory (%u bytes a subgroup; the "
         "self-test passed; RX_VK_MMA_STAGED=0: %s)", Shader::Backend::SPIRV::kStagedBytes, otherwise);
    return true;
}

/// (hookshot, mma_layout.h global_table_loop) Intel's Mesa driver only for now (Mesa inlines DontInline; Windows not tried); env is
/// RX_VK_GM_LOOP, 0 or 1 over the default. A table indexed by the loop's counter needs dynamic indexing of storage buffer arrays
/// (tests/test_global_table_loop.py)
bool table_loop_wanted(VkDriverId driver, bool dynamic_indexing, const char* env) {
    return (env ? !env_value_off(env) : driver == VK_DRIVER_ID_INTEL_OPEN_SOURCE_MESA) && dynamic_indexing;
}
} // namespace

void coopmat_init() {
    // (amd-fix) NaN guard on float colour outputs (mma_layout.h frag_nan_guard), on every card since v2.0.6 as NX2navi's patch 0027
    // has it: the neon plants were reported on NVIDIA cards too, and one NaN texel spreads through bloom and blur. RX_VK_NAN_GUARD=0:
    // off, with vk_shader.cpp's GuardFragmentOutputs (one switch for both guards; it replaces RX_VK_NO_NAN_GUARD)
    {
        const char* e = std::getenv("RX_VK_NAN_GUARD");
        Shader::Backend::SPIRV::frag_nan_guard = !e || std::atoi(e) != 0;
    }
    if (Shader::Backend::SPIRV::frag_nan_guard) logf("vk: colour outputs NaN-guarded");
    Shader::Backend::SPIRV::position_invariant = dev.props.vendorID != 0x10DE && !env_on("RX_VK_NO_INVARIANT");
    if (Shader::Backend::SPIRV::position_invariant) logf("vk: positions invariant (not an NVIDIA card)");
    Shader::Backend::SPIRV::global_table_loop = table_loop_wanted(dev.driver_id, dev.features.shaderStorageBufferArrayDynamicIndexing,
                                                                  std::getenv("RX_VK_GM_LOOP"));
    if (Shader::Backend::SPIRV::global_table_loop) logf("vk: storage buffer tables searched in loops (RX_VK_GM_LOOP=0: written out)");
    // (hookshot) the translation's vendor fixes (vk_vendor.h, dev.fixes): out-of-bounds texel fetches answer 0, NaN tests on bits
    Shader::Backend::SPIRV::fetch_bounds = dev.fixes.fetch_bounds;
    // (dev.features.robustBufferAccess: on exactly when robustBufferAccess2 is, vk_main.cpp create_device)
    Shader::Backend::SPIRV::fetch_bounds_buffers = dev.fixes.fetch_bounds && !dev.features.robustBufferAccess;
    Shader::Backend::SPIRV::nan_bits = dev.fixes.nan_bits;
    // (hookshot) RX_VK_MMA_SOFTWARE=1: HMMA_nx2 in a shader function on subgroup shuffles, no cooperative matrices
    // (emit_spirv_warp.cpp, from Lichii): the lowering still gives HMMA_nx2 (dev.native_mma)
    if (const char* sw = std::getenv("RX_VK_MMA_SOFTWARE"); sw && std::atoi(sw)) {
        Shader::Backend::SPIRV::mma_software = true;
        dev.native_mma = true;
        logf("vk: matrix multiplies in software (subgroup shuffles, RX_VK_MMA_SOFTWARE)");
        return;
    }
    const char* env = std::getenv("RX_VK_NATIVE_MMA");
    if (env && !std::atoi(env)) {
        logf("vk: native matrix multiplies off (RX_VK_NATIVE_MMA=0)");
        return;
    }
    if (!dev.coop_matrix || !vkGetPhysicalDeviceCooperativeMatrixPropertiesKHR || env_on("RX_VK_MMA_NO_COOP")) {
        software_multiplies("no cooperative matrices");
        return;
    }
    uint32_t n = 0;
    vkGetPhysicalDeviceCooperativeMatrixPropertiesKHR(dev.physical, &n, nullptr);
    std::vector<VkCooperativeMatrixPropertiesKHR> props(n, VkCooperativeMatrixPropertiesKHR{VK_STRUCTURE_TYPE_COOPERATIVE_MATRIX_PROPERTIES_KHR});
    vkGetPhysicalDeviceCooperativeMatrixPropertiesKHR(dev.physical, &n, props.data());
    bool shape = false;
    for (const auto& p : props)
        shape |= p.MSize == 16 && p.NSize == 8 && p.KSize == 16 && p.AType == VK_COMPONENT_TYPE_FLOAT16_KHR &&
                 p.BType == VK_COMPONENT_TYPE_FLOAT16_KHR && p.CType == VK_COMPONENT_TYPE_FLOAT16_KHR &&
                 p.ResultType == VK_COMPONENT_TYPE_FLOAT16_KHR && p.scope == VK_SCOPE_SUBGROUP_KHR;
    // (hookshot) Without 16x8x16, the staged route (mma_staged.h) when its self-test passes, on Mesa RADV. RX_VK_MMA_STAGED=0:
    // never (the software function, as before it); =1: on any driver, and tried first even where 16x8x16 is there (a test of
    // the route on NVIDIA's cards)
    const char* staged_env = std::getenv("RX_VK_MMA_STAGED");
    const bool staged_off = staged_env && *staged_env && !std::atoi(staged_env);
    const bool staged_first = staged_env && std::atoi(staged_env) == 1;
    if (staged_off && !shape) logf("vk: staged matrix multiplies off (RX_VK_MMA_STAGED=0)");
    const bool staged = !staged_off && (!shape || staged_first) &&
                        staged_multiplies(props, shape ? "the native route" : "the software function", staged_first);
    if (staged && !shape) return;
    if (!shape) {
        software_multiplies("the cooperative matrices lack 16x8x16 f16");
        return;
    }
    // (with the staged route first where 16x8x16 is there too: the native route is checked as below all the same, and takes the
    // programs the staged one cannot (mma_staged_native, mma_route.h); those keep the software function if it does not check out)
    if (!dev.vk12.shaderFloat16) {
        if (!staged) software_multiplies("no f16 shaders");
        return;
    }
    bool ok = measure_order() && test_multiply();
    // (hookshot, diagnosis) RX_VK_MMA_A_ORDER / _B_ORDER / _C_ORDER=<n,n,...>: the element orders given instead of the
    // measured ones (as if the console's fragments were laid out otherwise)
    const auto override_order = [&](const char* name, auto& order) {
        const char* e = std::getenv(name);
        if (!e) return;
        for (size_t k = 0; k < order.size() && *e; ++k) {
            order[k] = (uint32_t)std::strtoul(e, nullptr, 10);
            while (*e && *e != ',') e++;
            if (*e) e++;
        }
        ok = true;
        logf("vk: %s given: the cooperative matrix test is skipped", name);
    };
    override_order("RX_VK_MMA_A_ORDER", Shader::Backend::SPIRV::mma_order_a);
    override_order("RX_VK_MMA_B_ORDER", Shader::Backend::SPIRV::mma_order_b);
    override_order("RX_VK_MMA_C_ORDER", Shader::Backend::SPIRV::mma_order_c);
    if (!ok) {
        if (staged) {
            logf("vk: the programs the staged route cannot take: matrix multiplies in the software function (the cooperative "
                 "matrix layout is not the console's)");
            return;
        }
        software_multiplies("the cooperative matrix layout is not the console's");
        return;
    }
    dev.native_mma = true;
    if (staged) {
        Shader::Backend::SPIRV::mma_staged_native = true;
        logf("vk: native matrix multiplies for the programs the staged route cannot take (the console's fragment layout checked)");
        return;
    }
    logf("vk: native matrix multiplies on (cooperative matrices, the console's fragment layout checked)");
}

} // namespace mkwvk
