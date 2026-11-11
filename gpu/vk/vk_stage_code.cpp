// (hookshot) Program stages' SPIR-V kept packed in memory, and made shader modules only while a pipeline is made with them
// (vk_shader.h StageCode, StageModule). Outside vk_shader.cpp, which is part of the translator's stamp (nx2/build.py): how the
// SPIR-V is kept says nothing about what it is.
#include <atomic>
#include <cstdint>
#include <new>
#include <vector>

#include <zstd.h>

#include "vk_internal.h"
#include "vk_shader.h"
// (no vk_work.h: no recorded command uses a shader module, so destroying one is no recorder boundary and drains nothing;
// tests/test_recorder_sync.py's BOUNDARY_OK)

namespace mkwvk {

bool stage_code(StageCode& c, const std::vector<uint32_t>& spirv) {
    c = {};
    if (spirv.empty()) return false;
    // (a context a thread, the fastest level: the game's SPIR-V packs about 3.8 times smaller at 0.14 ms a module; level 6 packs
    // 3% more at four times the time)
    thread_local struct Ctx {
        ZSTD_CCtx* z = ZSTD_createCCtx();
        ~Ctx() { ZSTD_freeCCtx(z); }
    } ctx;
    if (!ctx.z) return false;
    const size_t bytes = spirv.size() * sizeof(uint32_t);
    try {
        c.packed.resize(ZSTD_compressBound(bytes));
        const size_t n = ZSTD_compressCCtx(ctx.z, c.packed.data(), c.packed.size(), spirv.data(), bytes, 1);
        if (ZSTD_isError(n)) {
            c = {};
            return false;
        }
        c.packed.resize(n);
        c.packed.shrink_to_fit();
    } catch (const std::bad_alloc&) {
        c = {};
        return false;
    }
    c.words = (uint32_t)spirv.size();
    return true;
}

StageModule::StageModule(const Stage& st) {
    if (!st.code) return;
    // (the words unpacked into a buffer a thread, made a module from there: the driver takes its own copy)
    thread_local std::vector<uint32_t> words;
    try {
        words.resize(st.code.words);
    } catch (const std::bad_alloc&) {
        return;
    }
    static std::atomic<int> told{0};
    const size_t n = ZSTD_decompress(words.data(), words.size() * sizeof(uint32_t), st.code.packed.data(), st.code.packed.size());
    if (ZSTD_isError(n) || n != words.size() * sizeof(uint32_t)) {
        if (told++ < 8) logf("vk: a stage's packed SPIR-V did not unpack (%s): its pipeline is not made",
                             ZSTD_isError(n) ? ZSTD_getErrorName(n) : "short");
        return;
    }
    VkShaderModuleCreateInfo ci{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
    ci.codeSize = n;
    ci.pCode = words.data();
    if (const VkResult r = vkCreateShaderModule(dev.device, &ci, nullptr, &module_); r != VK_SUCCESS) {
        module_ = VK_NULL_HANDLE;
        if (told++ < 8) logf("vk: a stage's shader module was not made (%d): its pipeline is not made", (int)r);
    }
}

StageModule::~StageModule() {
    if (module_) vkDestroyShaderModule(dev.device, module_, nullptr);
}

} // namespace mkwvk
