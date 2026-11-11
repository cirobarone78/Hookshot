// Diagnostic capture geometry and thumbnails, independent of Vulkan.
#pragma once
#include <algorithm>
#include <cstddef>
#include "vk_present_rect.h"

namespace mkwvk {

constexpr PresentContentSize capture_size(uint32_t sw, uint32_t sh, const int crop[4],
                                          uint32_t max_w, uint32_t max_h,
                                          PresentContentSize stretched_output = {}) noexcept {
    // Explicit widescreen uses anamorphic dynamic-resolution crops and stretches them at presentation.
    // Match that output shape; the raw crop ratio alone can squeeze a 32:9 scene into 20:9.
    const auto fit = stretched_output.w && stretched_output.h
                   ? present_rect(stretched_output.w, stretched_output.h, nullptr, max_w, max_h)
                   : present_rect(sw, sh, crop, max_w, max_h);
    return {fit.w, fit.h}; // tightly packed image; no letterbox pixels for the glitch detectors
}

// Sample each thumbnail cell at a four-pixel stride, averaging by its actual sample count. Cells in a
// small/odd-sized capture can have different sizes; never divide by a rounded-down, possibly zero count.
inline void capture_thumbnail(const uint8_t* rgba, uint32_t w, uint32_t h,
                              uint8_t* rgb, uint32_t tw, uint32_t th) {
    if (!tw || !th) return;
    if (!w || !h) { std::fill_n(rgb, size_t(tw) * th * 3, uint8_t{0}); return; }
    for (uint32_t y = 0; y < th; ++y) {
        const uint32_t y0 = uint64_t(y) * h / th;
        const uint32_t y1 = std::max(y0 + 1, uint32_t(uint64_t(y + 1) * h / th));
        for (uint32_t x = 0; x < tw; ++x) {
            const uint32_t x0 = uint64_t(x) * w / tw;
            const uint32_t x1 = std::max(x0 + 1, uint32_t(uint64_t(x + 1) * w / tw));
            uint64_t sum[3] = {}, count = 0;
            for (uint32_t yy = y0; yy < y1; yy += 4)
                for (uint32_t xx = x0; xx < x1; xx += 4) {
                    const auto* p = rgba + (size_t(yy) * w + xx) * 4;
                    for (int c = 0; c < 3; ++c) sum[c] += p[c];
                    ++count;
                }
            for (int c = 0; c < 3; ++c) rgb[(size_t(y) * tw + x) * 3 + c] = uint8_t(sum[c] / count);
        }
    }
}
} // namespace mkwvk
