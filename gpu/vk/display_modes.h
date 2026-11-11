/* The Insert menu's Aspect ratio and Output resolution rows (vk_menu.cpp): the sizes the screen offers, as the game can use
   them, and the shape each one has. Plain code, no Vulkan, no Windows: tests/test_display_modes.py checks it.

   The screen's modes (Windows' display settings, or HOS_DISPLAY_MODES=1920x1080,2560x1080,... for a run) become the sizes
   offered: each side rounded down to a multiple of 8, as host/nn_applet.c takes an output size, only those it accepts
   (hos_output_size_valid: 640 x 360 up to 5120 x 2880's pixels, 5:4 to 48:9), each once, by width then height. Their shapes
   are named as screens are sold (16:9, 21:9, 16:10, 4:3...) so the Aspect ratio row groups them. */
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

#include "../../host/hos_wide_size.h"   // (hos_output_size_valid: the sizes the game accepts)

namespace mkwvk::display_modes {

struct Size {
    uint32_t w, h;
};
inline bool operator==(Size a, Size b) { return a.w == b.w && a.h == b.h; }

/// The screen's modes as the game can take them: each side rounded down to 8, the ones it accepts, each size once, by
/// width then height
inline std::vector<Size> offered(const std::vector<Size>& modes) {
    std::vector<Size> v;
    for (Size m : modes) {
        const Size s{m.w & ~7u, m.h & ~7u};
        if (hos_output_size_valid(s.w, s.h) && std::find(v.begin(), v.end(), s) == v.end()) v.push_back(s);
    }
    std::sort(v.begin(), v.end(), [](Size a, Size b) { return a.w != b.w ? a.w < b.w : a.h < b.h; });
    return v;
}

/// "1920x1080,2560x1080" (HOS_DISPLAY_MODES): the sizes in it, as a screen's modes (anything else between them skipped)
inline std::vector<Size> parse_list(const char* text) {
    std::vector<Size> v;
    for (const char* p = text; p && *p;) {
        unsigned w = 0, h = 0;
        if (sscanf(p, "%u%*[xX]%u", &w, &h) == 2) v.push_back({w, h});
        while (*p && *p != ',' && *p != ';' && *p != ' ') p++;
        while (*p == ',' || *p == ';' || *p == ' ') p++;
    }
    return v;
}

inline double ratio(Size s) { return s.h ? (double)s.w / s.h : 0.0; }

/// The shape's name, as screens are sold: 5:4, 4:3, 3:2, 16:10, 5:3, 16:9, 21:9 (64:27, 43:18 and 12:5 all are), 32:9, 48:9;
/// within 2 % (sizes rounded to 8 come out a little off: 1360x768 is 16:9). Another shape by its smallest whole numbers when
/// they are small (1600x1024: 25:16), else as its ratio to 1 ("1.85:1")
inline std::string ratio_name(Size s) {
    const double r = ratio(s);
    if (r >= 2.30 && r <= 2.45) return "21:9";
    static const struct {
        const char* name;
        double r;
    } named[] = {{"5:4", 5.0 / 4}, {"4:3", 4.0 / 3}, {"3:2", 3.0 / 2},  {"16:10", 16.0 / 10}, {"5:3", 5.0 / 3},
                 {"16:9", 16.0 / 9}, {"32:9", 32.0 / 9}, {"48:9", 48.0 / 9}};
    const char* best = nullptr;
    double off = 0.02;
    for (const auto& n : named)
        if (std::fabs(r / n.r - 1.0) <= off) off = std::fabs(r / n.r - 1.0), best = n.name;
    if (best) return best;
    uint32_t a = s.w, b = s.h;
    while (b) {   // (their greatest common divisor)
        const uint32_t t = a % b;
        a = b, b = t;
    }
    char text[24];
    if (a && s.w / a <= 64 && s.h / a <= 64) snprintf(text, sizeof text, "%u:%u", s.w / a, s.h / a);
    else snprintf(text, sizeof text, "%.2f:1", r);
    return text;
}

/// A shape the Aspect ratio row lists: its name and the ratio it is ordered by (the first size of it that was seen)
struct Shape {
    std::string name;
    double r;
};
/// The shapes of sizes, each once, narrowest first
inline std::vector<Shape> shapes(const std::vector<Size>& sizes) {
    std::vector<Shape> v;
    for (Size s : sizes) {
        const std::string n = ratio_name(s);
        if (std::none_of(v.begin(), v.end(), [&](const Shape& x) { return x.name == n; })) v.push_back({n, ratio(s)});
    }
    std::sort(v.begin(), v.end(), [](const Shape& a, const Shape& b) { return a.r < b.r; });
    return v;
}
/// The place of s's shape in shapes, 0 when it is not there
inline int shape_index(const std::vector<Shape>& shapes, Size s) {
    const std::string n = ratio_name(s);
    for (int i = 0; i < (int)shapes.size(); i++)
        if (shapes[i].name == n) return i;
    return 0;
}
/// Of the sizes with shape name, the one to take when that shape is chosen: the screen's own size if it is one; else the
/// largest no taller than the screen (DSR's larger sizes are a choice, not where a shape starts); else the smallest; with no
/// screen size known, the largest. -1 when none has it
inline int pick(const std::vector<Size>& sizes, const std::string& name, Size screen) {
    int fits = -1, small = -1, large = -1;
    const auto px = [&](int i) { return (uint64_t)sizes[i].w * sizes[i].h; };
    for (int i = 0; i < (int)sizes.size(); i++) {
        if (ratio_name(sizes[i]) != name) continue;
        if (sizes[i] == screen) return i;
        if (screen.h && sizes[i].h <= screen.h && (fits < 0 || px(i) > px(fits))) fits = i;
        if (small < 0 || px(i) < px(small)) small = i;
        if (large < 0 || px(i) > px(large)) large = i;
    }
    return !screen.h ? large : fits >= 0 ? fits : small;
}

}  // namespace mkwvk::display_modes
