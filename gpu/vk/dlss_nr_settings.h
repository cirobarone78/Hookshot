// NR model controls are latched at feature creation. Coalesce edits before rebuilding it.
#pragma once

#include <algorithm>
#include <cstdint>

namespace mkwvk::dlss_nr {
struct Settings {
    int intensity = 35, structure = 100, tone = 100, skin = 100;
    int style = 0, preset = 0, mask = 1, ui = 1;
    bool operator==(const Settings&) const = default;
    Settings clamped() const {
        return {std::clamp(intensity, 0, 200), std::clamp(structure, 0, 200),
                std::clamp(tone, 0, 200), skin < 0 ? -100 : std::clamp(skin, 0, 200),
                std::clamp(style, 0, 2), std::clamp(preset, 0, 3), mask != 0, ui != 0};
    }
};

struct Edits {
    Settings pending{}, applied{};
    int64_t changed_ms = 0, applied_ms = -2000;
    bool observe(Settings wanted, int64_t now, bool dragging) {
        wanted = wanted.clamped();
        if (!(pending == wanted)) pending = wanted, changed_ms = now;
        return !(applied == wanted) && !dragging && now - changed_ms >= 350 && now - applied_ms >= 2000;
    }
    void commit(int64_t now) { applied = pending; applied_ms = now; }
};
} // namespace mkwvk::dlss_nr
