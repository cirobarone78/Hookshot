// Instrument the stage code, not the loader: the runner compiles the actual StageCode/Stage/Program
// declarations, serializer, Reader and program_cache_load functions. stage_code (vk_stage_code.cpp) is a
// stand-in that keeps the words as they are and fails when told to; Info is a minimal stand-in with the
// cache's separately serialized containers. This test covers which records are taken and what their
// stages keep, not Shader::Info layout, SPIR-V validity or zstd.
#include <array>
#include <atomic>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>
#ifdef _WIN32
#include <io.h>
#else
#define _fseeki64 fseeko
#define _ftelli64 ftello
#endif

#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)
using VkDescriptorSetLayout = uintptr_t;
using VkPipelineLayout = uintptr_t;
using VkPipeline = uintptr_t;
using VkDescriptorType = uint32_t;
using VkShaderStageFlagBits = uint32_t;
using VkShaderStageFlags = uint32_t;
using VkPrimitiveTopology = uint32_t;
constexpr uintptr_t VK_NULL_HANDLE = 0;
constexpr uint32_t VK_SHADER_STAGE_VERTEX_BIT = 1, VK_SHADER_STAGE_FRAGMENT_BIT = 16;
constexpr uint32_t VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST = 3;
constexpr size_t kIdxEntry = 20;
namespace Shader {
namespace IR { enum class Attribute : uint64_t {}; }
struct Descriptor {   // (a descriptor's array size, which get_info checks)
    uint32_t count;
    Descriptor(uint32_t c = 1) : count(c) {}
};
struct Info {
    uint32_t marker = 0;
    std::vector<Descriptor> constant_buffer_descriptors, storage_buffers_descriptors,
        texture_buffer_descriptors, image_buffer_descriptors, texture_descriptors, image_descriptors;
    std::map<IR::Attribute, IR::Attribute> legacy_stores_mapping;
    std::vector<std::vector<uint32_t>> handle_programs;
};
}
#include "cache_types.inc"

unsigned attempts = 0, kept = 0, fail_at = 0;
bool stage_code(StageCode& c, const std::vector<uint32_t>& spirv) {
    c = {};
    CHECK(!spirv.empty());   // (an empty stage is refused before it is kept)
    if (++attempts == fail_at) return false;
    const auto* bytes = reinterpret_cast<const uint8_t*>(spirv.data());
    c.packed.assign(bytes, bytes + spirv.size() * sizeof(uint32_t));
    c.words = (uint32_t)spirv.size();
    ++kept;
    return true;
}
void disk_init() {}
void logf(const char*, ...) {}
bool disk_on = true, disk_listing = true;
FILE* disk_in = nullptr;
FILE* disk_out = nullptr;
FILE* disk_idx = nullptr;
std::mutex disk_mu;
std::unordered_map<uint64_t, std::vector<DiskRecord>> disk_records;
std::unordered_map<uint64_t, std::vector<DiskRecord>> disk_taken;   // (vk_shader.cpp: the records read in, for the prediction)
std::atomic<int64_t> st_cache_hits{0};
#define PROF_EXACT()   // (vk_prof.h's exact-timing scope, since #989: nothing to time here)
#include "cache_functions.inc"

constexpr uint32_t kVertexWord = 0x07230203, kFragmentWord = 0x07230204;
void save(uint64_t key, bool empty_second = false, int bad_answer = 0) {
    Program program;
    program.key = key;
    program.stages.emplace_back();
    program.stages.emplace_back();
    program.stages[0].nvn_stage = 0;
    program.stages[0].vk_stage = VK_SHADER_STAGE_VERTEX_BIT;
    program.stages[1].nvn_stage = 1;
    program.stages[1].vk_stage = VK_SHADER_STAGE_FRAGMENT_BIT;
    program.stages[1].info.handle_programs = {{1, 2}};
    program.stages[1].info.texture_descriptors = {0};
    program.answers.push_back({1, 0, 1, false});   // (a fitting answer: stage 1's one texture)
    // (the file is passed around: an answer naming a stage or slot the program does not have is refused)
    if (bad_answer == 1) program.answers.push_back({7, 0, 1, false});
    if (bad_answer == 2) program.answers.push_back({1, 3, 1, false});
    std::vector<std::vector<uint32_t>> code{{kVertexWord}, {kFragmentWord, kFragmentWord}};
    if (empty_second) code[1].clear();
    program_cache_save(program, code);
    CHECK(disk_records.at(key).size() > 0);
}
// (each stage of a program taken keeps its own SPIR-V, whole)
void check_taken(const std::vector<std::unique_ptr<Program>>& programs) {
    for (const auto& p : programs) {
        CHECK(p->ready.load() && p->stages.size() == 2);
        for (size_t k = 0; k < 2; k++) {
            const StageCode& c = p->stages[k].code;
            const std::vector<uint32_t> want = k ? std::vector<uint32_t>{kFragmentWord, kFragmentWord} : std::vector<uint32_t>{kVertexWord};
            CHECK(c && c.words == want.size() && c.packed.size() == want.size() * sizeof(uint32_t));
            CHECK(std::memcmp(c.packed.data(), want.data(), c.packed.size()) == 0);
        }
    }
}
int main(int argc, char** argv) {
    CHECK(argc == 2);
    disk_in = disk_out = std::tmpfile();
    CHECK(disk_in);
    const std::string scenario = argv[1];
    save(7, scenario == "empty", scenario == "answer_stage" ? 1 : scenario == "answer_desc" ? 2 : 0);
    if (scenario == "first") fail_at = 1;
    if (scenario == "second" || scenario == "mixed") fail_at = 2;
    if (scenario == "truncated") --disk_records.at(7).back().size;
    if (scenario == "mixed") {
        save(7); // A valid variant after the failing variant, under the same key.
        save(9); // An independent key must also remain usable.
    }
    std::vector<std::unique_ptr<Program>> programs;
    program_cache_load(7, programs);
    unsigned accepted = scenario == "valid" || scenario == "mixed" ? 1 : 0;
    CHECK(programs.size() == accepted && st_cache_hits == accepted);
    std::printf("%s: attempts=%u kept=%u accepted=%u\n", scenario.c_str(), attempts, kept, accepted);
    if (scenario == "first") CHECK(attempts == 1 && kept == 0);   // (the record left at its first stage)
    if (scenario == "second") CHECK(attempts == 2 && kept == 1);
    if (scenario == "empty") CHECK(attempts == 1 && kept == 1);
    if (scenario == "truncated") CHECK(attempts == 0 && kept == 0);
    if (scenario == "answer_stage" || scenario == "answer_desc") CHECK(attempts == 2 && kept == 2);
    if (scenario == "valid") CHECK(attempts == 2 && kept == 2);
    if (scenario == "mixed") {
        CHECK(attempts == 4 && kept == 3);
        program_cache_load(9, programs);
        CHECK(programs.size() == 2 && st_cache_hits == 2 && attempts == 6 && kept == 5);
        program_cache_load(7, programs); // Consumed records are not read twice.
        CHECK(programs.size() == 2 && attempts == 6 && kept == 5);
    }
    check_taken(programs);
    CHECK(std::fclose(disk_in) == 0);
    std::puts("PASS: refused records left out, each stage of those taken keeps its code");
}
