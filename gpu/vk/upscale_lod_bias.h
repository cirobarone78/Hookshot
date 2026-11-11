/* The upscalers' texture LOD bias at Auto (vk_draw.cpp upscale_lod_bias), as plain functions. No Vulkan:
   tests/test_upscale_lod_bias.cpp checks them.

   The GPU picks a texture's mip level from the size of a pixel of the 3D, so a 3D drawn smaller samples smaller mips than the
   picture it is scaled up to would. OoT draws its 3D at 3/4 of the output and already gives its world's materials a bias of
   -0.5 for that; under DLSS, FSR 3.1 or FSR 4 a smaller 3D wants log2(share / 0.75) more. At a fixed Render resolution the
   share is the menu's. At Auto it is the game's dynamic resolution's, known only from what the upscaler drew: the width it
   drew from over the width it scaled to.

   That bias is kept in steps of a quarter level: the 3D's size moves from frame to frame, every bias is a sampler of its
   own, and samplers are never destroyed (vk_draw.cpp sampler_make). A step is left only once the size is an eighth of a
   level past its edge: another step makes every sampler anew, and a size that hovers at an edge would do so every frame. */
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace mkwvk::upscale_lod {

constexpr int kStepsPerLevel = 4;
/// Two levels at most (a 3D of 3/16 of the picture's width; Ultra Performance's third is 1.17)
constexpr int kMaxSteps = 2 * kStepsPerLevel;

/// The bias's steps for a 3D scene_width wide scaled up to a picture picture_width wide: log2 of the game's 3/4 over that
/// share, to the nearest quarter level. 0 from 3/4 up (the game's own bias covers it), and with nothing drawn
inline int steps(uint32_t scene_width, uint32_t picture_width) {
    if (!scene_width || !picture_width) return 0;
    const float levels = std::log2(0.75f * (float)picture_width / (float)scene_width);
    return std::clamp((int)std::lround(levels * (float)kStepsPerLevel), 0, kMaxSteps);
}

/// The same from the steps there are now: they stay until the size is an eighth of a level past their edge (half a step
/// past the half step where steps() rounds the other way), so a size that hovers between two steps keeps one. The bias is
/// then at most a quarter level from the exact one, not an eighth
inline int steps(uint32_t scene_width, uint32_t picture_width, int current) {
    if (!scene_width || !picture_width) return 0;
    current = std::clamp(current, 0, kMaxSteps);
    const float exact = std::log2(0.75f * (float)picture_width / (float)scene_width) * (float)kStepsPerLevel;
    return std::fabs(exact - (float)current) < 1.0f ? current : steps(scene_width, picture_width);
}

/// The steps as a sampler's bias, in mip levels: negative, toward the larger mips
inline float bias(int steps) { return -(float)std::clamp(steps, 0, kMaxSteps) / (float)kStepsPerLevel; }

} // namespace mkwvk::upscale_lod
