// AMD FSR upscaling (FSR 3.1 and FSR 4) in place of OoT's gameplay upscale network (vk_ffx.cpp), through AMD's signed
// runtime for Vulkan (FSR SDK 2.4: amd_fidelityfx_loader_vk.dll and amd_fidelityfx_upscaler_vk.dll, fetched by
// scripts/ffx_sdk.py into the game folder's ffx folder). vk_dlss.cpp makes its inputs (the same as DLSS's: the scene's
// colour, depth and motion, the camera's jitter) and calls ffx::upscale where DLSS would evaluate.
// Windows only: AMD publishes the runtime for Windows alone. Elsewhere these say FSR is not there.
#pragma once

#include <cstddef>
#include <cstdint>
#include <functional>

#include "vk_internal.h"

#if defined(_WIN32)
#define HOOKSHOT_FFX 1
#endif

namespace mkwvk::ffx {

/// Why FSR cannot be chosen here (the Insert menu's Upscaler row says it), OK when it can or is not known yet
enum Why { OK, NOT_BUILT, ENV_OFF, NO_RUNTIME, NOT_LOADED, NO_DEVICE_SUPPORT, WHY_COUNT };
Why why();
/// Whether this build has FSR in it (Windows)
bool built();
/// Loads AMD's runtime once and asks it what it offers on this device, so why() knows before the first upscale (the menu)
void probe();

/// What FSR is asked for, from the FSR version and FSR 4 model rows (opts.fsr_version, opts.fsr_model): 0 AMD's own choice
/// (the newest it offers on this GPU), 1 FSR 3.1, 2 FSR 4 FP8 (made for RDNA 4), 3 FSR 4 INT8 (RDNA 3), 4 FSR 4 INT8 for
/// RDNA 2, 5 FSR 4 INT8 Lite (made for APUs and handhelds), 6 FSR 4 by AMD's choice of model (INT8 Lite where AMD offers no
/// FSR 4). 2 to 5 run that model whatever AMD's own check says (it may not run on every GPU); RX_VK_FSR_MODEL=<n> over both rows
enum { MODEL_AUTO = 0, MODEL_FSR3 = 1, MODEL_FP8 = 2, MODEL_INT8 = 3, MODEL_INT8_RDNA2 = 4, MODEL_LITE = 5, MODEL_FSR4_AUTO = 6,
       kModels = 7 };
/// The rows' values: the FSR version row (0 Auto, 1 FSR 4, 2 FSR 3.1) and the FSR 4 model row (0 Auto, 1 FP8 .. 4 INT8 Lite)
enum { kVersions = 3, kFsr4Models = 5 };
int wanted_model();

/// One image FSR reads or writes: a 2D colour image of one level, in VK_IMAGE_LAYOUT_GENERAL (left so after)
struct Image {
    VkImage image = VK_NULL_HANDLE;
    VkFormat format = VK_FORMAT_UNDEFINED;
    uint32_t width = 0, height = 0;   // (the image's own size: the render size may be smaller, renderSize)
};

struct Frame {
    VkCommandBuffer cmd = VK_NULL_HANDLE;
    Image color, depth, motion, output;   // (colour: the scene as the network samples it, non-linear; depth: R32F, not
                                          // reversed; motion: render pixels, from this frame to the one before, no jitter)
    uint32_t render_w = 0, render_h = 0;  // (this frame's render size, within color's)
    uint32_t max_w = 0, max_h = 0;        // (the largest render size this context is to take)
    uint32_t out_w = 0, out_h = 0;
    float jitter[2]{};                    // (in render pixels, x right and y down: as DLSS takes it)
    bool reset = false;
    float frame_ms = 16.7f;
    float near_plane = 0.1f, far_plane = 1000.0f, fov_y = 1.0f;
};

/// What vk_dlss.cpp gives for frees the GPU's work in flight may still use: run a few frames on
using Later = std::function<void(std::function<void()>)>;

/// Records FSR's upscale of f into f.cmd (its context made, or made again when the sizes or the model change; an old one
/// goes to later). false: not drawn (the reason logged); the game's network runs
bool upscale(const Frame& f, const Later& later);
/// Its context let go (DLSS's idle rule: after 120 frames unused), its video memory back
void release(const Later& later);
/// The FSR version drawing ("4.1.2", "3.1.6"), the model ("INT8 Lite"), or "" before the first context
const char* version_name();
const char* model_name();
/// Its GPU memory, in bytes (0 when not known)
uint64_t memory();

} // namespace mkwvk::ffx
