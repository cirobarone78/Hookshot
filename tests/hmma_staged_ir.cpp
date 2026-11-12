// SPDX-License-Identifier: GPL-3.0-or-later
// Real Eden IR/pass/emitter check of HMMA_nx2's matrix routes (backend/spirv/mma_staged.h, mma_route.h); no game or GPU.
// One compute program with the program's own shared memory, exchanged between invocations over a barrier, and two HMMA_nx2
// (C = RZ, then C = the first's D), emitted on each route: native (16x8x16), software (the shuffle function), staged (16x16x16
// through shared memory), staged with the explicit workgroup layout, staged with 8- and 16-bit shared stores (the translator's
// compare-exchange functions), staged on programs it cannot take (the software function; native where the native route
// checks out too, mma_staged_native), and the staged self-test's module (gpu/vk/vk_mma_staged_test.h). Each module is
// written for spirv-val, with a line of what it holds.
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <map>
#include <stdexcept>
#include <string>
#include "shader_recompiler/backend/spirv/emit_spirv.h"
#include "shader_recompiler/backend/spirv/mma_layout.h"
#include "shader_recompiler/backend/spirv/mma_route.h"
#include "shader_recompiler/backend/spirv/mma_staged.h"
#include "shader_recompiler/frontend/ir/ir_emitter.h"
#include "shader_recompiler/object_pool.h"
#include "shader_recompiler/environment.h"
#include "shader_recompiler/ir_opt/passes.h"
#include "vk_mma_staged_test.h"
using namespace Shader;
namespace SB = Shader::Backend::SPIRV;
struct TestEnv : Environment {
    TestEnv() { stage = Stage::Compute; }
    u64 ReadInstruction(u32) override { return 0; }
    u32 ReadCbufValue(u32, u32) override { return 0; }
    TextureType ReadTextureType(u32) override { return TextureType::Color2D; }
    TexturePixelFormat ReadTexturePixelFormat(u32) override { return {}; }
    bool IsTexturePixelFormatInteger(u32) override { return false; }
    u32 ReadViewportTransformState() override { return 0; }
    u32 TextureBoundBuffer() const override { return 0; }
    u32 LocalMemorySize() const override { return 0; }
    u32 SharedMemorySize() const override { return 0; }
    std::array<u32, 3> WorkgroupSize() const override { return {1, 1, 1}; }
    bool HasHLEMacroState() const override { return false; }
    std::optional<ReplaceConstant> GetReplaceConstBuffer(u32, u32) override { return {}; }
    void Dump(u64, u64) override {}
};

static constexpr u32 kOwnShared = 284;   // (bytes of the program's own shared memory: not a multiple of 64)

static Profile test_profile(bool explicit_layout) {
    Profile profile{};
    profile.supported_spirv = 0x00010600;
    profile.supported_subgroup_stages = 0xffffffffu;
    profile.support_int64 = true;
    profile.support_explicit_workgroup_layout = explicit_layout;
    // (the float modes vk_shader.cpp's make_profile has the game's programs keep: the self-test's module declares the same)
    profile.support_float_controls = true;
    profile.support_fp16_signed_zero_nan_preserve = profile.support_fp32_signed_zero_nan_preserve = true;
    return profile;
}

static const char* emitted_route = "none";   // (the route PlanMatrixRoute gave the program emit() made last)

static std::vector<u32> emit(u32 width, bool explicit_layout, bool bytes = false) {
    ObjectPool<IR::Inst> pool;
    IR::Block block{pool};
    IR::Program program;
    program.stage = Stage::Compute;
    program.workgroup_size = {width, 1, 1};
    program.shared_memory_size = kOwnShared;
    program.blocks.push_back(&block);
    program.post_order_blocks.push_back(&block);
    IR::AbstractSyntaxNode body{};
    body.type = IR::AbstractSyntaxNode::Type::Block;
    body.data.block = &block;
    program.syntax_list.push_back(body);
    IR::AbstractSyntaxNode ret{};
    ret.type = IR::AbstractSyntaxNode::Type::Return;
    program.syntax_list.push_back(ret);
    IR::IREmitter ir{block};
    ir.WriteShared(32, ir.Imm32(kOwnShared - 8), ir.Imm32(0x3c003c00u));   // (written, then read over a barrier: the exchange)
    if (bytes) {   // (8- and 16-bit stores: the compare-exchange functions, which load the word first)
        ir.WriteShared(8, ir.Imm32(kOwnShared - 12), ir.Imm32(1u));
        ir.WriteShared(16, ir.Imm32(kOwnShared - 10), ir.Imm32(2u));
    }
    ir.Barrier();
    ir.SubgroupBarrier();          // (the warp's own stores before its LDSM: Ampere's lowering)
    ir.WorkgroupMemoryBarrier();   // (MEMBAR.CTA)
    const IR::U32 own{ir.LoadShared(32, false, ir.Imm32(kOwnShared - 4))};   // (the program's own last word)
    const IR::Value a{ir.CompositeConstruct(own, ir.Imm32(0x3c003c00u), ir.Imm32(0x40004000u), ir.Imm32(0xbc00bc00u))};
    const IR::Value b{ir.CompositeConstruct(ir.Imm32(0x3c004000u), own)};
    const IR::Value rz{ir.CompositeConstruct(ir.Imm32(0u), ir.Imm32(0u))};
    const IR::Value d1{ir.MatrixMulAddF16(a, b, rz)};
    const IR::Value d2{ir.MatrixMulAddF16(a, b, d1)};
    ir.WriteShared(32, ir.Imm32(0), IR::U32{ir.CompositeExtract(d2, 0)});
    ir.WriteShared(32, ir.Imm32(4), IR::U32{ir.CompositeExtract(d2, 1)});
    ir.Epilogue();
    TestEnv env;
    Optimization::CollectShaderInfoPass(env, program);
    if (!program.info.uses_cooperative_matrix) throw std::runtime_error("no HMMA_nx2 seen");
    const Profile profile{test_profile(explicit_layout)};
    // (the route vk_shader.cpp logs and leaves networks out by: the translator's own, PlanMatrixRoute)
    const SB::MatrixRoutePlan plan{SB::PlanMatrixRoute(profile, program.stage, program.info, program.shared_memory_size,
                                                       program.workgroup_size)};
    emitted_route = SB::MatrixRouteName(plan.route);
    return SB::EmitSPIRV(profile, program);
}

// what a module holds: its memory model, the cooperative matrix instructions, the function calls, the shared words, SubgroupId;
// its Workgroup loads and stores (those NonPrivatePointer) and its control and memory barriers (those making memory available
// and visible); and which float modes it keeps (SignedZeroInfNanPreserve's widths)
static std::string inspect(const std::vector<u32>& code) {
    unsigned muladd = 0, load = 0, store = 0, calls = 0, functions = 0, subgroup_id = 0, model = 0;
    unsigned shared_access = 0, shared_nonprivate = 0, barriers = 0, barriers_visible = 0, signed_zero_inf_nan = 0;
    std::map<u32, u64> constants;
    std::map<u32, u32> array_length;   // (array type id: its length constant's value)
    u64 workgroup_words = 0;
    std::map<u32, u32> pointer_to;     // (pointer type id: pointee)
    std::map<u32, spv::StorageClass> pointer_class;
    std::map<u32, spv::StorageClass> value_class;   // (pointer value id: its storage class)
    const auto workgroup = [&](u32 pointer) {
        return value_class.count(pointer) && value_class[pointer] == spv::StorageClass::Workgroup;
    };
    const u32 nonprivate = static_cast<u32>(spv::MemoryAccessMask::NonPrivatePointer);
    const u32 visible = static_cast<u32>(spv::MemorySemanticsMask::MakeAvailable | spv::MemorySemanticsMask::MakeVisible);
    for (size_t at = 5; at < code.size();) {
        const u32 count = code[at] >> 16;
        const auto op = static_cast<spv::Op>(code[at] & 0xffffu);
        const u32* w = &code[at + 1];
        switch (op) {
        case spv::Op::OpAccessChain:
            if (pointer_class.count(w[0])) value_class[w[1]] = pointer_class[w[0]];
            break;
        case spv::Op::OpLoad:
            if (workgroup(w[2])) shared_access++, shared_nonprivate += count > 4 && (w[3] & nonprivate) ? 1 : 0;
            break;
        case spv::Op::OpStore:
            if (workgroup(w[0])) shared_access++, shared_nonprivate += count > 3 && (w[2] & nonprivate) ? 1 : 0;
            break;
        case spv::Op::OpControlBarrier:
            barriers++;
            if ((constants[w[2]] & visible) == visible) barriers_visible++;
            break;
        case spv::Op::OpMemoryBarrier:
            barriers++;
            if ((constants[w[1]] & visible) == visible) barriers_visible++;
            break;
        case spv::Op::OpExecutionMode:
            if (w[1] == static_cast<u32>(spv::ExecutionMode::SignedZeroInfNanPreserve)) signed_zero_inf_nan |= w[2];
            break;
        case spv::Op::OpMemoryModel: model = w[1]; break;
        case spv::Op::OpCooperativeMatrixMulAddKHR: muladd++; break;
        case spv::Op::OpCooperativeMatrixLoadKHR: load++; break;
        case spv::Op::OpCooperativeMatrixStoreKHR: store++; break;
        case spv::Op::OpFunctionCall: calls++; break;
        case spv::Op::OpFunction: functions++; break;
        case spv::Op::OpDecorate:
            if (w[1] == static_cast<u32>(spv::Decoration::BuiltIn) && w[2] == static_cast<u32>(spv::BuiltIn::SubgroupId)) subgroup_id++;
            break;
        case spv::Op::OpConstant: constants[w[1]] = w[2]; break;
        case spv::Op::OpTypeArray: array_length[w[0]] = (u32)constants[w[2]]; break;
        case spv::Op::OpTypeStruct: if (count == 3 && array_length.count(w[1])) array_length[w[0]] = array_length[w[1]]; break;
        case spv::Op::OpTypePointer: pointer_to[w[0]] = w[2], pointer_class[w[0]] = static_cast<spv::StorageClass>(w[1]); break;
        case spv::Op::OpVariable:
            value_class[w[1]] = static_cast<spv::StorageClass>(w[2]);
            if (static_cast<spv::StorageClass>(w[2]) == spv::StorageClass::Workgroup && array_length.count(pointer_to[w[0]]))
                workgroup_words = std::max<u64>(workgroup_words, array_length[pointer_to[w[0]]]);
            break;
        default: break;
        }
        at += count;
    }
    char line[384];
    std::snprintf(line, sizeof line, "model=%s muladd=%u load=%u store=%u calls=%u functions=%u subgroup_id=%u shared_elements=%llu "
                  "shared_access=%u shared_nonprivate=%u barriers=%u barriers_visible=%u preserve_bits=%u",
                  model == static_cast<u32>(spv::MemoryModel::VulkanKHR) ? "vulkan" : "glsl450", muladd, load, store, calls,
                  functions, subgroup_id, (unsigned long long)workgroup_words, shared_access, shared_nonprivate, barriers,
                  barriers_visible, signed_zero_inf_nan);
    return line;
}

int main(int argc, char** argv) {
    try {
        if (argc != 2) return 2;
        std::filesystem::create_directories(argv[1]);
        const auto write = [&](const std::string& name, const std::vector<u32>& words) {
            std::ofstream file(std::filesystem::path(argv[1]) / (name + ".spv"), std::ios::binary);
            file.write(reinterpret_cast<const char*>(words.data()), words.size() * sizeof(u32));
            if (!file) std::exit(3);
            std::printf("%s %s route=%s\n", name.c_str(), inspect(words).c_str(), emitted_route);
            emitted_route = "none";
        };
        const auto route = [](bool software, bool staged, bool staged_native = false) {
            SB::mma_software = software;
            SB::mma_staged = staged;
            SB::mma_staged_native = staged_native;
            SB::mma_staged_shared_limit = staged ? 65536 : 0;
        };
        route(false, false);
        write("native", emit(128, false));
        route(true, false);
        write("software", emit(128, false));
        route(false, true);
        write("staged", emit(128, false));
        write("staged-explicit", emit(128, true));
        write("staged-bytes", emit(128, false, true));
        write("staged-narrow", emit(16, false));   // (16 lanes wide: not whole subgroups, the software function)
        SB::mma_staged_shared_limit = 4096;      // (no room for the scratch: the software function)
        write("staged-full", emit(128, false));
        route(false, true, true);                // (RX_VK_MMA_STAGED=1 where 16x8x16 checks out too: the others native)
        write("staged-narrow-native", emit(16, false));
        write("staged-native", emit(128, false));
        route(true, false);
        write("software-bytes", emit(128, false, true));
        route(false, false);
        const auto scratch = mma_staged_test::scratch_for(65536);
        write("selftest", mma_staged_test::build(scratch, 4));
        std::printf("scratch offset=%u size=%u words_per_subgroup=%u\n", SB::PlanStagedScratch(kOwnShared, {128, 1, 1}, 65536).offset,
                    SB::PlanStagedScratch(kOwnShared, {128, 1, 1}, 65536).size, SB::kStagedWords);
        return 0;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "%s\n", e.what());
        return 1;
    }
}
