// Geometry and thumbnail colors for authored images, including extreme and changing aspects.
#include <array>
#include <cstdio>
#include <vector>
#include "../gpu/vk/vk_capture_size.h"

static int failures;
static void check(bool ok, const char* name) {
    if (!ok) { std::fprintf(stderr, "FAIL: %s\n", name); ++failures; }
}
static void geometry(uint32_t w, uint32_t h, uint32_t want_w, uint32_t want_h, const int* crop = nullptr) {
    const auto size = mkwvk::capture_size(w, h, crop, 1280, 720);
    check(size.w == want_w && size.h == want_h, "capture preserves source/crop aspect");
    check(size.w && size.h && size.w <= 1280 && size.h <= 720, "capture fits allocated image/readback");
}
int main() {
    geometry(1920, 1080, 1280, 720);
    geometry(5120, 1440, 1280, 360);
    geometry(3440, 1440, 1280, 535);
    geometry(1024, 768, 960, 720);
    geometry(1080, 1920, 405, 720);
    geometry(8192, 1, 1280, 1);
    geometry(1, 8192, 1, 720);
    const int crop[] = {960, 0, 1920, 1080};
    geometry(3840, 1080, 1280, 720, crop);
    const int edge_crop[] = {99, 0, 10, 80};
    geometry(100, 80, 9, 720, edge_crop);
    geometry(0, 0, 1280, 720);
    const int dynamic_crop[] = {0, 0, 2560, 1152};
    const auto raw = mkwvk::capture_size(5120, 1440, dynamic_crop, 1280, 720);
    const auto wide = mkwvk::capture_size(5120, 1440, dynamic_crop, 1280, 720, {2560, 720});
    const auto resized = mkwvk::capture_size(5120, 1440, dynamic_crop, 1280, 720, {1600, 900});
    check(raw.w == 1280 && raw.h == 576, "unconfigured crop retains its own aspect");
    check(wide.w == 1280 && wide.h == 360, "anamorphic crop follows explicit widescreen presentation");
    check(resized.w == 1280 && resized.h == 720, "explicit stretch follows resized output");

    // Constant colors must stay constant, with no false brightness amplification for non-divisible cells.
    // A one-pixel input also exercises duplicated samples when the thumbnail is larger than its source.
    for (const auto size : {mkwvk::PresentContentSize{1280, 720}, {1280, 360}, {1280, 535}, {13, 7}, {1, 1}}) {
        std::vector<uint8_t> rgba(size_t(size.w) * size.h * 4);
        for (size_t p = 0; p < rgba.size(); p += 4) {
            rgba[p] = 251; rgba[p + 1] = 147; rgba[p + 2] = 63; rgba[p + 3] = 255;
        }
        std::array<uint8_t, 64 * 36 * 3 + 2> thumb;
        thumb.fill(0xa5);
        mkwvk::capture_thumbnail(rgba.data(), size.w, size.h, thumb.data() + 1, 64, 36);
        bool same = true;
        for (size_t p = 1; p < thumb.size() - 1; p += 3)
            same &= thumb[p] == 251 && thumb[p + 1] == 147 && thumb[p + 2] == 63;
        check(same, "constant thumbnail color unchanged");
        check(thumb.front() == 0xa5 && thumb.back() == 0xa5, "thumbnail output bounds");
    }
    std::array<uint8_t, 128 * 36 * 4> split{};
    for (unsigned y = 0; y < 36; ++y)
        for (unsigned x = 64; x < 128; ++x)
            for (unsigned c = 0; c < 3; ++c) split[(y * 128 + x) * 4 + c] = 255;
    std::array<uint8_t, 64 * 36 * 3> thumb{};
    mkwvk::capture_thumbnail(split.data(), 128, 36, thumb.data(), 64, 36);
    bool halves = true;
    for (unsigned y = 0; y < 36; ++y)
        for (unsigned x = 0; x < 64; ++x)
            for (unsigned c = 0; c < 3; ++c) halves &= thumb[(y * 64 + x) * 3 + c] == (x < 32 ? 0 : 255);
    check(halves, "thumbnail preserves left/right content positions");
    mkwvk::capture_thumbnail(nullptr, 0, 0, thumb.data(), 64, 36);
    check(std::all_of(thumb.begin(), thumb.end(), [](uint8_t v) { return !v; }), "empty input never read");
    std::printf("capture geometry/thumbnail: %d failures\n", failures);
    return failures ? 1 : 0;
}
