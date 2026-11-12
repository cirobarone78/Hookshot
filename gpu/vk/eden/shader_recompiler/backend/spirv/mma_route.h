// (hookshot) Which route a program's HMMA_nx2 takes on this device: the one test the translator emits by
// (EmitContext::DefineMatrixRoute) and the renderer decides by (vk_shader.cpp: which networks are left out and the line
// each logs; vk_draw.cpp: whether the 3/4 TAAU network is stood in for), so that the two never disagree.
//
//   Native    16x8x16 cooperative matrices, each lane's elements reordered (emit_spirv_warp.cpp; NVIDIA)
//   Software  the subgroup-shuffle function (emit_spirv_warp.cpp DefineSoftwareMatrixFunction): the device's route
//             (mma_software), or the staged route's fallback for a program it cannot take
//   Staged    16x16x16 cooperative matrices through the shared block's scratch (mma_staged.h): a compute program with
//             subgroup operations, whole subgroups and room for the scratch (PlanStagedScratch)
//   None      no HMMA_nx2 in the program
#pragma once

#include <array>
#include <cstdint>

#include "shader_recompiler/backend/spirv/mma_layout.h"
#include "shader_recompiler/backend/spirv/mma_staged.h"
#include "shader_recompiler/profile.h"
#include "shader_recompiler/shader_info.h"
#include "shader_recompiler/stage.h"

namespace Shader::Backend::SPIRV {

enum class MatrixRoute : uint32_t { None, Native, Software, Staged };

struct MatrixRoutePlan {
    MatrixRoute route = MatrixRoute::None;
    StagedScratch scratch;   // (Staged: where the scratch goes in the shared block)
};

inline const char* MatrixRouteName(MatrixRoute route) {
    switch (route) {
    case MatrixRoute::Native: return "native";
    case MatrixRoute::Software: return "software";
    case MatrixRoute::Staged: return "staged";
    default: return "none";
    }
}

/// The route of a program of this stage and info, with shared_memory_size bytes of its own shared memory and this
/// workgroup. The staged function needs the lane id and SubgroupId (subgroup operations in the stage: HMMA_nx2 programs
/// use the lane id and f16, collect_shader_info_pass.cpp, and EmitContext defines both for them then), whole subgroups and
/// room for its scratch. A program it cannot take goes native where the native route checks out too (mma_staged_native:
/// RX_VK_MMA_STAGED=1 on a card with 16x8x16), else to the software function
inline MatrixRoutePlan PlanMatrixRoute(const Profile& profile, Stage stage, const Info& info, uint32_t shared_memory_size,
                                       const std::array<uint32_t, 3>& workgroup_size) {
    MatrixRoutePlan plan;
    if (!info.uses_cooperative_matrix) return plan;
    if (mma_software) {
        plan.route = MatrixRoute::Software;
        return plan;
    }
    if (!mma_staged) {
        plan.route = MatrixRoute::Native;
        return plan;
    }
    if (stage == Stage::Compute && profile.SupportsSubgroupStage(stage) && info.uses_subgroup_invocation_id &&
        info.uses_fp16) {
        plan.scratch = PlanStagedScratch(shared_memory_size, workgroup_size, mma_staged_shared_limit);
        if (plan.scratch.fits) {
            plan.route = MatrixRoute::Staged;
            return plan;
        }
    }
    plan.scratch = {};
    plan.route = mma_staged_native ? MatrixRoute::Native : MatrixRoute::Software;
    return plan;
}

} // namespace Shader::Backend::SPIRV
