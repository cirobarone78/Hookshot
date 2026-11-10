/* The texture LOD bias for a scene a temporal upscaler scales up (NVIDIA DLSS, AMD FSR 3.1), as plain functions. No Vulkan:
   tests/test_upscale_lod_bias.cpp checks them.

   The GPU picks a texture's mip level from the size of a pixel of the 3D: drawn at half the picture's width, the scene samples
   mips one level smaller than the picture at full size would, and the upscaler, which rebuilds the picture's detail from the
   jittered frames, has only that blur to rebuild. Both NVIDIA's and AMD's guides ask for a bias of log2(render width /
   picture width) on the scene's textures, so they are sampled as the picture's size would sample them; the jitter and the
   upscaler's history then take away the shimmer a negative bias alone would bring.

   The bias is kept in steps of a quarter level: the scene's size follows the game's dynamic resolution, and every bias is
   a sampler of its own (vk_draw.cpp sampler_make). */
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>

namespace mkwvk::upscale_lod {

constexpr int kStepsPerLevel = 4;
/// Two levels at most: Ultra Performance's (a third of the picture's width) is 1.58
constexpr int kMaxSteps = 2 * kStepsPerLevel;

/// The bias's steps for a scene render_width wide scaled up to a picture picture_width wide, times strength
/// (RX_VK_UPSCALE_LOD_BIAS: 1 the guides' own, 0 none). 0 when the scene is not smaller than the picture (DLAA)
inline int steps(uint32_t render_width, uint32_t picture_width, float strength) {
    if (!render_width || picture_width <= render_width || !(strength > 0.0f)) return 0;
    const float levels = std::log2((float)picture_width / (float)render_width) * strength;
    return std::clamp((int)std::lround(levels * (float)kStepsPerLevel), 0, kMaxSteps);
}

/// The steps as a sampler's bias, in mip levels: negative, toward the larger mips
inline float bias(int steps) { return -(float)std::clamp(steps, 0, kMaxSteps) / (float)kStepsPerLevel; }

/// RX_VK_UPSCALE_LOD_BIAS's value as the strength: unset or not a number 1, else the number held to 0..2
inline float strength(const char* env) {
    if (!env || !*env) return 1.0f;
    char* end = nullptr;
    const float v = std::strtof(env, &end);
    if (end == env || !(v == v)) return 1.0f;
    return std::clamp(v, 0.0f, 2.0f);
}

} // namespace mkwvk::upscale_lod
