// SPDX-FileCopyrightText: Copyright 2021 yuzu Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#include "shader_recompiler/backend/spirv/emit_spirv_instructions.h"
#include "shader_recompiler/backend/spirv/spirv_emit_context.h"

namespace Shader::Backend::SPIRV {
namespace {
// (hookshot) On the Vulkan memory model (a program on the staged matrix route, EmitContext::DefineMatrixRoute) a barrier
// makes the shared memory written before it available, and visible after it, only when it says so: the GLSL450 model
// did that implicitly, and the program's own shared memory exchange between invocations relies on it. Every barrier the
// program has says so: BAR, the subgroup's (Ampere's LDSM after the warp's stores) and MEMBAR
spv::MemorySemanticsMask Visibility(const EmitContext& ctx) {
    return ctx.workgroup_non_private ? spv::MemorySemanticsMask::MakeAvailable | spv::MemorySemanticsMask::MakeVisible
                                     : spv::MemorySemanticsMask::MaskNone;
}

void MemoryBarrier(EmitContext& ctx, spv::Scope scope) {
    const auto semantics{
        spv::MemorySemanticsMask::AcquireRelease | spv::MemorySemanticsMask::UniformMemory |
        spv::MemorySemanticsMask::WorkgroupMemory | spv::MemorySemanticsMask::AtomicCounterMemory |
        spv::MemorySemanticsMask::ImageMemory | Visibility(ctx)};
    ctx.OpMemoryBarrier(ctx.Const(static_cast<u32>(scope)), ctx.Const(static_cast<u32>(semantics)));
}
} // Anonymous namespace

void EmitBarrier(EmitContext& ctx) {
    const auto execution{spv::Scope::Workgroup};
    const auto memory{spv::Scope::Workgroup};
    const auto memory_semantics{spv::MemorySemanticsMask::AcquireRelease |
                                spv::MemorySemanticsMask::WorkgroupMemory | Visibility(ctx)};
    ctx.OpControlBarrier(ctx.Const(static_cast<u32>(execution)),
                         ctx.Const(static_cast<u32>(memory)),
                         ctx.Const(static_cast<u32>(memory_semantics)));
}

// (hookshot) The subgroup's invocations meet, and their workgroup (shared) memory accesses before it are visible to the ones after:
// what the Switch's in-order warp gives a warp's stores and LDSM's reads of them without a BAR
void EmitSubgroupBarrier(EmitContext& ctx) {
    const auto scope{spv::Scope::Subgroup};
    const auto memory_semantics{spv::MemorySemanticsMask::AcquireRelease | spv::MemorySemanticsMask::WorkgroupMemory |
                                Visibility(ctx)};
    ctx.OpControlBarrier(ctx.Const(static_cast<u32>(scope)), ctx.Const(static_cast<u32>(scope)),
                         ctx.Const(static_cast<u32>(memory_semantics)));
}

void EmitWorkgroupMemoryBarrier(EmitContext& ctx) {
    MemoryBarrier(ctx, spv::Scope::Workgroup);
}

void EmitDeviceMemoryBarrier(EmitContext& ctx) {
    MemoryBarrier(ctx, spv::Scope::Device);
}

} // namespace Shader::Backend::SPIRV
