// NVIDIA DLSS Frame Generation through NVIDIA Streamline (vk_dlssg.cpp): the Insert menu's DLSS Frame Gen row (opts.dlssg:
// 0 off, 1 2x, 2 3x, 3 4x), read from hookshot_options.ini at the start, before Vulkan is loaded. Built in only with
// Streamline's SDK (HOOKSHOT_SL_SDK at the build, scripts/sl_sdk.py; Windows); without it, or when Streamline does not start,
// these say it is not there and the renderer runs as before.
#pragma once

#include "vk_internal.h"

namespace mkwvk {

struct TemporalFrame;

/// Before Vulkan is loaded (vk_main.cpp load_global): Streamline's vkGetInstanceProcAddr when DLSS Frame Gen is set and
/// Streamline started (it then hooks the instance, the device, the swapchain and the present: manual hooking), null to load
/// vulkan-1.dll as without it
PFN_vkGetInstanceProcAddr dlssg_load();
/// Streamline runs in this process (dlssg_load gave its loader): Reflex goes through it, and the renderer's own frame
/// generation and Reflex are off
bool dlssg_active();
/// The Insert menu offers the row: a build with Streamline, on an NVIDIA GPU (or Streamline running already)
bool dlssg_available();
/// Why DLSS Frame Generation is not running (the row's help says it), DLSSG_OK when it runs
enum DlssgWhy { DLSSG_OK, DLSSG_NOT_BUILT, DLSSG_LATER, DLSSG_NO_FILES, DLSSG_NOT_SIGNED, DLSSG_FAILED, DLSSG_WHY_COUNT };
DlssgWhy dlssg_why();

/// Reflex through Streamline while it is active (vk_reflex.cpp's own Reflex is off then): the frame's latency markers and its
/// sleep
enum DlssgMarker { DLSSG_SIM_START, DLSSG_SIM_END, DLSSG_SUBMIT_START, DLSSG_SUBMIT_END, DLSSG_PRESENT_START, DLSSG_PRESENT_END };
void dlssg_marker(DlssgMarker m);
/// After a present: the next frame's token, Reflex's sleep, its simulation start
void dlssg_sleep();

/// The frame's inputs, from the temporal upscaler's frame chain (vk_temporal.cpp, recorded into cmd after its engine drew):
/// f's depth and motion (GENERAL, the render size at their top left), its jitter in render pixels; the scene camera's
/// projection and view-projection (row major, clip = M * position, both jittered) and its jitter in clip space. motion:
/// the motion vectors hold the camera's motion from the frame before (false: a new history)
void dlssg_inputs(VkCommandBuffer cmd, const TemporalFrame& f, const float projection[16], const float view_projection[16],
                  const float clip_jitter[2], bool motion);
/// Right before a present (vk_replay.cpp present_image): frame generation on for a game frame that gave its inputs, off
/// otherwise (the Insert menu open, the start-up screen, no inputs for a while)
void dlssg_before_present(bool game_frame);

/// The window is closing, before the host ends the process (vk_main.cpp mkwvk_close_asked: the window's close, Quit and the
/// Insert menu's Restart): Streamline shut down while the threads it needs still run. Left to the process's end, the DLSS-G
/// plugin tore its frame generation down in its DLL detach, after ExitProcess had ended them: an access violation at every
/// exit. In order: no dlssg_* call let in any more; a Reflex sleep under way waited for, with the present lock free (that
/// thread presents next); the present lock and the queue's taken; the device idle; DLSS-G off; slShutdown. Each wait is 2 s
/// at most: past that Streamline is left as it is and the exit goes on. Both locks stay held until the process ends, so
/// nothing reaches Streamline's hooks after it shut down. Once; nothing without Streamline
void dlssg_shutdown();

} // namespace mkwvk
