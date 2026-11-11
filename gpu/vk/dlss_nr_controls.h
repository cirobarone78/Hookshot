#pragma once
#include "dlss_nr_settings.h"

namespace mkwvk::dlss_nr {
enum Profile { Original, Faithful, Balanced, Intense, Custom };
struct Look { Settings model{}; int color = 100; };
inline Look look(int profile) {
    Look r;
    if (profile == Faithful) { r.model.style = 1; r.color = 0; }
    if (profile == Intense) r.model.intensity = 100;
    return r;
}
inline int identify(const Settings& model, int color) {
    for (int p = Faithful; p <= Intense; ++p) {
        const auto v = look(p);
        if (model.clamped() == v.model.clamped() && color == v.color) return p;
    }
    return Custom;
}
inline const char* profile_name(int p) {
    constexpr const char* names[] = {"Original", "Faithful", "Balanced", "Intense", "Custom"};
    return names[std::clamp(p, 0, 4)];
}
// 310.9.16 fixed-input GPU validation found a distinct preset 1; hints 2/3 matched default.
// Retain legacy values on load, but only offer the two verified choices for new edits.
inline int step_preset(int current) { return current == 1 ? 0 : 1; }
// An ephemeral comparison never writes the persistent requested enable flag.
struct Comparison {
    bool active = false, on = false, was_held = false;
    void enter(bool requested) { active = true; on = requested; was_held = false; }
    void leave() { active = false; }
    void toggle() { if (active) on = !on; }
    void shortcut(bool held, bool pressed, bool hold_mode) {
        if (active && !hold_mode && !was_held && (held || pressed)) toggle();
        was_held = held;
    }
    int override_for(bool held, bool hold_mode) const { return !active ? -1 : on && !(hold_mode && held) ? 1 : 0; }
};
} // namespace mkwvk::dlss_nr
