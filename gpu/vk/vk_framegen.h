// Frame interpolation (vk_framegen.cpp): made frames shown between the game's (in a window; RX_VK_FRAMEGEN=0: off).
#pragma once

#include "vk_internal.h"

namespace mkwvk {

// Cross-thread presentation traces share the host present CSV's performance-counter
// epoch. prof_now() is a calibrated TSC duration clock, not that absolute epoch.
inline int64_t present_trace_now() {
    LARGE_INTEGER now;
    QueryPerformanceCounter(&now);
    static const int64_t frequency = [] {
        LARGE_INTEGER value;
        QueryPerformanceFrequency(&value);
        return value.QuadPart;
    }();
    return perf_ticks_to_ns(now.QuadPart, frequency);
}

bool framegen_on();
// Each owned native image has one timeline: odd values publish the captured
// frame; the following even value releases the display read for reuse.
struct NativePresentSync {
    VkSemaphore timeline = VK_NULL_HANDLE;
    uint64_t ready = 0, consumed = 0;
    bool read_submitted = false;
    bool native_pq = false;
    bool shown = false;
    uint64_t source_frame = 0;
    int64_t source_ns = 0, queued_ns = 0, worker_ns = 0;
    int64_t present_begin_ns = 0, present_end_ns = 0, finished_ns = 0;
    VkResult present_result = VK_NOT_READY;
};
bool present_async_record(VkCommandBuffer cmd, VkImage src, VkFormat format, uint32_t w, uint32_t h, const int crop[4]);
NativePresentSync* present_async_pending();
void present_async_queue(bool submitted, uint64_t source_frame);
void present_async_release(NativePresentSync& sync);

/// Records the frame's processing into the present's recording (src: the window texture's view, sw x sh, the crop
/// x, y, w, h); false when interpolation cannot run (the present goes to the window as without it)
bool framegen_record(VkCommandBuffer cmd, VkImageView src, uint32_t sw, uint32_t sh, const int crop[4]);
/// The first frame the last framegen_record made (null when it made none), w x h, GENERAL
VkImage framegen_made_image(uint32_t* w, uint32_t* h);
/// After that recording's submit (value): the display thread shows its frames
void framegen_queue(uint64_t value);
/// The window's present of an image (GENERAL, w x h; crop as above or null), vk_replay.cpp: the display thread's
void present_image(VkImage src, uint32_t w, uint32_t h, const int crop[4], VkImageView view = VK_NULL_HANDLE, NativePresentSync* sync = nullptr);
/// (hookshot) Present ahead (vk_framegen.cpp display_main, #1702): while present_defer_into is set on a thread, present_image
/// submits the frame's copy into its swapchain image and stops there, with what present_commit needs to show it later. The
/// copy is then on the queue before the game's next frame, so its present at its time does not wait for that frame's rendering
struct PendingPresent {
    bool used = false;
    uint32_t index = 0;
    VkFence done = VK_NULL_HANDLE;           // (the copy's fence)
    VkSwapchainKHR swapchain = VK_NULL_HANDLE;
};
extern thread_local PendingPresent* present_defer_into;
bool present_commit(const PendingPresent& p);   // (false: not shown, nothing deferred or a swapchain made again since)
/// The Insert menu's upscaling of a frame to the window (dw x dh), recorded: the image to show, or null when it is off
VkImage framegen_scale(VkCommandBuffer cmd, VkImageView src, VkImage image, uint32_t sw, uint32_t sh, const int crop[4], uint32_t dw, uint32_t dh);
VkImageView framegen_scaled_view();   // (hookshot) the view of framegen_scale's last image
/// (hookshot) The HDR10 picture of src's crop at dw x dh (the Insert menu's HDR), GENERAL; null: none (the SDR picture then)
VkImage framegen_hdr(VkCommandBuffer cmd, VkImageView src, uint32_t sw, uint32_t sh, const int crop[4], uint32_t dw, uint32_t dh);
/// Each present: ultrawide's menus (the Insert menu's setting to the game's side, the sides blurred or black while a menu shows)
void wide_sides_tick();
/// Whether ultrawide's menu sides can show at all: Ultrawide with a margin and the Insert menu's setting on
bool wide_sides_possible();

} // namespace mkwvk
