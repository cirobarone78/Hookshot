// (hookshot) Active UI language detection for overlays and menus (vk_imgui.cpp, vk_menu.cpp).
// Mirrors host/nn_applet.c desired_language() across all 16 game languages:
//   RX_VK_UI_LANG (optional override) -> HOS_LANGUAGE -> language.txt beside the executable/game folder -> en-US.
// Plain C++, no Windows headers required when tested standalone.
#pragma once

#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

namespace mkwvk::i18n {

enum Lang {
    kEnUS = 0,
    kEnGB,
    kFr,
    kFrCA,
    kDe,
    kIt,
    kEs,
    kEs419,
    kPtBR,
    kNl,
    kPl,
    kRu,
    kJa,
    kKo,
    kZhHans,
    kZhHant,
    kLangCount
};

inline const char* lang_code(Lang l) {
    static const char* const kCodes[kLangCount] = {
        "en-US", "en-GB", "fr", "fr-CA", "de", "it", "es", "es-419",
        "pt-BR", "nl",    "pl", "ru",    "ja", "ko", "zh-Hans", "zh-Hant",
    };
    return (unsigned)l < (unsigned)kLangCount ? kCodes[l] : "en-US";
}

inline int ascii_icmp(const char* a, const char* b) {
    for (; *a && *b; ++a, ++b) {
        unsigned char ca = (unsigned char)*a;
        unsigned char cb = (unsigned char)*b;
        if (ca >= 'A' && ca <= 'Z') ca += 'a' - 'A';
        if (cb >= 'A' && cb <= 'Z') cb += 'a' - 'A';
        if (ca != cb) return (int)ca - (int)cb;
    }
    return (int)(unsigned char)*a - (int)(unsigned char)*b;
}

inline bool parse_lang_code(const char* raw, Lang* out) {
    if (!raw || !*raw) return false;
    while (*raw == ' ' || *raw == '\t') ++raw;
    char tok[32];
    size_t n = 0;
    while (raw[n] && raw[n] != ' ' && raw[n] != '\t' && raw[n] != '\r' && raw[n] != '\n') {
        if (n + 1 >= sizeof tok) return false;
        tok[n] = raw[n] == '_' ? '-' : raw[n];
        ++n;
    }
    tok[n] = 0;
    if (!n) return false;
    for (int i = 0; i < kLangCount; ++i) {
        if (ascii_icmp(tok, lang_code((Lang)i)) == 0) {
            if (out) *out = (Lang)i;
            return true;
        }
    }
    struct Alias { const char* code; Lang lang; };
    static constexpr Alias kAliases[] = {
        {"en", kEnUS}, {"en-AU", kEnGB}, {"en-NZ", kEnGB}, {"fr-FR", kFr},
        {"de-DE", kDe}, {"it-IT", kIt}, {"es-ES", kEs}, {"es-MX", kEs419},
        {"pt", kPtBR}, {"pt-PT", kPtBR}, {"nl-NL", kNl}, {"pl-PL", kPl},
        {"ru-RU", kRu}, {"ja-JP", kJa}, {"ko-KR", kKo},
        {"zh", kZhHans}, {"zh-CN", kZhHans}, {"zh-SG", kZhHans},
        {"zh-TW", kZhHant}, {"zh-HK", kZhHant}, {"zh-MO", kZhHant},
    };
    for (const auto& a : kAliases) {
        if (ascii_icmp(tok, a.code) == 0) {
            if (out) *out = a.lang;
            return true;
        }
    }
    return false;
}

/// Parses language.txt using the same rules as host/nn_applet.c desired_language().
inline bool resolve_lang_from_file(const char* path, Lang* out) {
    if (!path || !*path) return false;
    FILE* f = std::fopen(path, "r");
    if (!f) return false;
    char line[256];
    bool whole = true;
    bool found = false;
    while (std::fgets(line, sizeof line, f)) {
        const bool starts = whole;
        whole = std::strchr(line, '\n') != nullptr;
        if (!starts) continue;
        const char* p = line;
        if ((unsigned char)p[0] == 0xEF && (unsigned char)p[1] == 0xBB && (unsigned char)p[2] == 0xBF) p += 3;
        while (*p == ' ' || *p == '\t') ++p;
        if (*p == '#' || *p == '\r' || *p == '\n' || !*p) continue;
        if (parse_lang_code(p, out)) {
            found = true;
            break;
        }
    }
    std::fclose(f);
    return found;
}

/// Resolves the UI language from RX_VK_UI_LANG, HOS_LANGUAGE, or <dir>/language.txt.
inline Lang resolve_lang(const char* game_dir) {
    if (const char* ov = std::getenv("RX_VK_UI_LANG"); ov && *ov) {
        Lang l = kEnUS;
        return parse_lang_code(ov, &l) ? l : kEnUS;
    }
    if (const char* env = std::getenv("HOS_LANGUAGE"); env && *env) {
        Lang l = kEnUS;
        return parse_lang_code(env, &l) ? l : kEnUS;
    }
    std::string path = game_dir && *game_dir ? std::string(game_dir) : std::string();
    if (!path.empty() && path.back() != '/' && path.back() != '\\') path += '/';
    path += "language.txt";
    Lang l = kEnUS;
    if (resolve_lang_from_file(path.c_str(), &l)) return l;
    return kEnUS;
}

/// Representative non-ASCII glyph needed by the language so font loading can verify coverage
/// and merge a fallback font when the primary menu font lacks the script.
inline uint32_t script_probe_char(Lang l) {
    switch (l) {
    case kFr:
    case kFrCA:
    case kEs:
    case kEs419:
    case kPtBR:
    case kIt: return 0x00E9u; // 'é'
    case kDe: return 0x00FCu; // 'ü'
    case kPl: return 0x0142u; // 'ł'
    case kRu: return 0x0414u; // 'Д'
    case kJa: return 0x8A2Du; // '設'
    case kKo: return 0xC124u; // '설'
    case kZhHans: return 0x8BBEu; // '设'
    case kZhHant: return 0x8A2Du; // '設'
    default: return 0;
    }
}

inline bool is_cjk(Lang l) { return l == kJa || l == kKo || l == kZhHans || l == kZhHant; }

inline std::atomic<Lang>& state_lang() {
    static std::atomic<Lang> l{kEnUS};
    return l;
}

inline std::atomic<bool>& state_ready() {
    static std::atomic<bool> r{false};
    return r;
}

inline void init(const char* game_dir) {
    state_lang().store(resolve_lang(game_dir), std::memory_order_relaxed);
    state_ready().store(true, std::memory_order_release);
}

inline void set_active_lang(Lang l) {
    state_lang().store((unsigned)l < (unsigned)kLangCount ? l : kEnUS, std::memory_order_relaxed);
    state_ready().store(true, std::memory_order_release);
}

inline void set_lang_for_test(Lang l) { set_active_lang(l); }

inline Lang current_lang() {
    if (!state_ready().load(std::memory_order_acquire)) init(nullptr);
    return state_lang().load(std::memory_order_relaxed);
}

} // namespace mkwvk::i18n
