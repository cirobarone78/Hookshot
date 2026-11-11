"""Localization table, language detection and formatter checks for the Vulkan F1/Insert menu.

python -I -B tests/test_menu_i18n.py [--cxx clang++]
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"

SKIP_VALUE_LITERALS = {
    "Off", "On", "Native", "Auto", "Custom", "FSR 3", "DLSS", "TAAU", "MSAA",
    "FPS", "2x", "4x", "8x", "16x", "1x", "100%", "sRGB", "scRGB", "HDR10",
    "Windows", "WASAPI", "Audio", "Vulkan",
}


def decode_c_string(raw: str) -> str:
    """Unescape a single C string literal body (without surrounding quotes)."""
    out = bytearray()
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch != "\\":
            out.extend(ch.encode("utf-8"))
            i += 1
            continue
        i += 1
        if i >= len(raw):
            break
        esc = raw[i]
        i += 1
        if esc == "n":
            out.extend(b"\n")
        elif esc == "t":
            out.extend(b"\t")
        elif esc == "r":
            out.extend(b"\r")
        elif esc in ('\\', '"', "'"):
            out.extend(esc.encode("utf-8"))
        elif esc == "x":
            hex_digits = []
            while i < len(raw) and raw[i] in "0123456789abcdefABCDEF" and len(hex_digits) < 2:
                hex_digits.append(raw[i])
                i += 1
            out.append(int("".join(hex_digits), 16))
        elif esc in "01234567":
            oct_digits = [esc]
            while i < len(raw) and raw[i] in "01234567" and len(oct_digits) < 3:
                oct_digits.append(raw[i])
                i += 1
            out.append(int("".join(oct_digits), 8))
        else:
            out.extend(esc.encode("utf-8"))
    return out.decode("utf-8")


def parse_kentries(text: str) -> dict[str, list[str | None]]:
    m = re.search(r"inline constexpr LangEntry kEntries\[\]\s*=\s*\{(.*?)\n\};", text, re.S)
    assert m, "kEntries[] not found in vk_menu_i18n.h"
    body = m.group(1)
    entries: dict[str, list[str | None]] = {}
    i = 0
    n = len(body)
    while i < n:
        if body[i] == "/" and i + 1 < n and body[i + 1] == "/":
            nl = body.find("\n", i)
            i = n if nl < 0 else nl + 1
            continue
        if body[i] != "{":
            i += 1
            continue
        # Parse {"key", { ... }}
        end = body.find("}", body.find("{", i + 1) + 1)
        assert end != -1, f"unterminated entry at offset {i}"
        close = body.find("}", end + 1)
        assert close != -1, f"unterminated outer entry at offset {i}"
        chunk = body[i : close + 1]
        i = close + 1

        tokens: list[str | None] = []
        j = 0
        while j < len(chunk):
            if chunk[j] == '"':
                j += 1
                buf = []
                while j < len(chunk):
                    if chunk[j] == "\\":
                        buf.append(chunk[j : j + 2])
                        j += 2
                    elif chunk[j] == '"':
                        j += 1
                        break
                    else:
                        buf.append(chunk[j])
                        j += 1
                # Handle adjacent C string literals separated only by whitespace
                val = decode_c_string("".join(buf))
                while True:
                    k = j
                    while k < len(chunk) and chunk[k] in " \t\r\n":
                        k += 1
                    if k < len(chunk) and chunk[k] == '"':
                        k += 1
                        buf2 = []
                        while k < len(chunk):
                            if chunk[k] == "\\":
                                buf2.append(chunk[k : k + 2])
                                k += 2
                            elif chunk[k] == '"':
                                k += 1
                                break
                            else:
                                buf2.append(chunk[k])
                                k += 1
                        val += decode_c_string("".join(buf2))
                        j = k
                    else:
                        break
                tokens.append(val)
            elif chunk.startswith("nullptr", j):
                tokens.append(None)
                j += 7
            else:
                j += 1
        assert len(tokens) == 16, f"expected 16 strings/nullptrs in entry {tokens[:2]!r}, got {len(tokens)}"
        key = tokens[0]
        assert isinstance(key, str) and key, f"empty key in entry {tokens!r}"
        assert key not in entries, f"duplicate key in kEntries: {key!r}"
        entries[key] = tokens[1:]
    return entries


def check_static_sources(entries: dict[str, list[str | None]]) -> None:
    files = [
        VK / "vk_menu_lang.h",
        VK / "vk_menu_i18n.h",
        VK / "vk_imgui.h",
        VK / "vk_imgui.cpp",
        VK / "vk_menu.cpp",
        Path(__file__),
    ]
    for path in files:
        raw = path.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), f"{path.name}: UTF-8 BOM forbidden"
        raw.decode("utf-8")

    # Every non-variant base language must have a non-empty translation in every entry
    variant_slots = {0, 2, 6}  # en-GB, fr-CA, es-419
    for key, trans in entries.items():
        for idx, val in enumerate(trans):
            if val is None:
                assert idx in variant_slots, f"kEntries[{key!r}] slot {idx} is nullptr (only regional variants may fallback)"
            else:
                assert len(val) > 0, f"kEntries[{key!r}] slot {idx} is empty string"
                val.encode("utf-8").decode("utf-8")

    # Cheat items & sections from oot_cheat_items.h
    cheat_text = (VK / "oot_cheat_items.h").read_text(encoding="utf-8")
    sections = re.findall(r'\bOOT_SECTION\s*\(\s*"([^"]+)"\s*\)', cheat_text)
    items = re.findall(r'\bOOT_ITEM\s*\(\s*"([^"]+)"\s*,', cheat_text)
    assert sections and items, f"unexpected oot_cheat_items.h counts: {len(sections)}, {len(items)}"
    for sec in sections:
        assert sec in entries, f"oot_cheat_items.h section {sec!r} missing from kEntries"
    for item in items:
        assert item in entries, f"oot_cheat_items.h item {item!r} missing from kEntries"

    # FPS breakdown + startup strings
    for label in ("Game", "Renderer", "GPU wait", "Pacing", "GPU time", "Shaders built (4 s)", "Draws left out (4 s)"):
        assert label in entries, f"FPS breakdown label {label!r} missing from kEntries"
    prog_text = (VK / "vk_progress.h").read_text(encoding="utf-8")
    for s in ("Preparing shaders", "Building pipelines", "Loading pipelines",
              "Reading the game's shaders", "Reading the pipeline notes", "Loading the shader cache"):
        assert s in prog_text and s in entries, f"vk_progress.h literal {s!r} missing from kEntries"

    # Menu tabs, teleport sections/locations, controls bindings, and wiring checks
    menu_text = (VK / "vk_menu.cpp").read_text(encoding="utf-8")
    assert "ensure_i18n();" in menu_text and "i18n::prebake_utf8()" in menu_text
    imgui_text = (VK / "vk_imgui.cpp").read_text(encoding="utf-8")
    assert "merge_language_fallbacks" in imgui_text and "cjk_fallback_font" in imgui_text

    tabs_m = re.search(r"tab_titles\[TAB_COUNT\]\s*=\s*\{(.*?)\};", menu_text, re.S)
    assert tabs_m
    for tab in re.findall(r'"([^"]+)"', tabs_m.group(1)):
        assert tab in entries, f"tab_titles {tab!r} missing from kEntries"

    tp_sec_m = re.search(r"teleport_sections\[\]\s*=\s*\{(.*?)\};", menu_text, re.S)
    assert tp_sec_m
    for s in re.findall(r'\{\s*"([^"]+)"', tp_sec_m.group(1)):
        assert s in entries, f"teleport_sections {s!r} missing from kEntries"

    tp_names_m = re.search(r"teleport_names\[\]\s*=\s*\{(.*?)\};", menu_text, re.S)
    assert tp_names_m
    for s in re.findall(r'"([^"]+)"', tp_names_m.group(1)):
        assert s in entries, f"teleport_names {s!r} missing from kEntries"

    tp_notes_m = re.search(r"teleport_notes\[\]\s*=\s*\{(.*?)\};", menu_text, re.S)
    assert tp_notes_m
    for s in re.findall(r'"([^"]+)"', tp_notes_m.group(1)):
        assert s in entries, f"teleport_notes {s!r} missing from kEntries"

    ctrl_m = re.search(r"controls\[\]\s*=\s*\{(.*?)\};", menu_text, re.S)
    assert ctrl_m
    for s in re.findall(r',\s*"([^"]+)"\s*\}', ctrl_m.group(1)):
        if len(s) > 1 and s not in {"ZL", "ZR", "L3", "R3"}:
            assert s in entries, f"controls row {s!r} missing from kEntries"

    dbg_m = re.search(r"debug_groups\[\]\s*=\s*\{(.*?)\};", menu_text, re.S)
    assert dbg_m
    for s in re.findall(r'"([^"]+)"', dbg_m.group(1)):
        assert s in entries, f"debug_groups string {s!r} missing from kEntries"


CPP_FIXTURE = r'''
#define _CRT_SECURE_NO_WARNINGS 1
#include "vk_menu_lang.h"
#include "vk_menu_i18n.h"

#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <string_view>

namespace i18n = mkwvk::i18n;

static void set_env_var(const char* name, const char* val) {
#ifdef _WIN32
    _putenv_s(name, val ? val : "");
#else
    if (val && *val) setenv(name, val, 1);
    else unsetenv(name);
#endif
}

static bool valid_utf8(const char* s) {
    if (!s) return false;
    const unsigned char* p = reinterpret_cast<const unsigned char*>(s);
    while (*p) {
        unsigned char c = *p++;
        if (c < 0x80) continue;
        int cont = 0;
        uint32_t cp = 0;
        if ((c & 0xE0) == 0xC0) { cont = 1; cp = c & 0x1F; if (cp < 2) return false; }
        else if ((c & 0xF0) == 0xE0) { cont = 2; cp = c & 0x0F; }
        else if ((c & 0xF8) == 0xF0) { cont = 3; cp = c & 0x07; }
        else return false;
        while (cont--) {
            unsigned char x = *p++;
            if ((x & 0xC0) != 0x80) return false;
            cp = (cp << 6) | (x & 0x3F);
        }
        if (cp > 0x10FFFF || (cp >= 0xD800 && cp <= 0xDFFF)) return false;
    }
    return true;
}

int main(int argc, char** argv) {
    assert(argc == 2);
    const std::string dir = argv[1];

    // 1. Language code parsing across all 16 codes and common OS/region variants
    struct ParseCase { const char* s; i18n::Lang want; };
    const ParseCase cases[] = {
        {"en-US", i18n::kEnUS}, {"en_us", i18n::kEnUS}, {"en", i18n::kEnUS},
        {"en-GB", i18n::kEnGB}, {"en_AU", i18n::kEnGB},
        {"fr", i18n::kFr}, {"fr-FR", i18n::kFr}, {"fr-CA", i18n::kFrCA}, {"fr_ca", i18n::kFrCA},
        {"de", i18n::kDe}, {"it", i18n::kIt},
        {"es", i18n::kEs}, {"es-ES", i18n::kEs}, {"es-419", i18n::kEs419}, {"es-MX", i18n::kEs419},
        {"pt-BR", i18n::kPtBR}, {"pt", i18n::kPtBR},
        {"nl", i18n::kNl}, {"pl", i18n::kPl}, {"ru", i18n::kRu},
        {"ja", i18n::kJa}, {"ko", i18n::kKo},
        {"zh-Hans", i18n::kZhHans}, {"zh-CN", i18n::kZhHans}, {"zh-SG", i18n::kZhHans},
        {"zh-Hant", i18n::kZhHant}, {"zh-TW", i18n::kZhHant}, {"zh-HK", i18n::kZhHant},
    };
    for (const auto& c : cases) {
        i18n::Lang out = i18n::kLangCount;
        if (!i18n::parse_lang_code(c.s, &out) || out != c.want) {
            std::fprintf(stderr, "parse_lang_code mismatch for '%s': ok=%d got=%d want=%d\n",
                         c.s, (int)i18n::parse_lang_code(c.s, &out), (int)out, (int)c.want);
            return 2;
        }
    }
    i18n::Lang bad = i18n::kLangCount;
    assert(!i18n::parse_lang_code("", &bad));
    assert(!i18n::parse_lang_code("zz-ZZ", &bad));

    // 2. Priority: RX_VK_UI_LANG > HOS_LANGUAGE > language.txt > default
    const std::string lang_txt = dir + "/language.txt";
    {
        FILE* f = std::fopen(lang_txt.c_str(), "wb");
        assert(f);
        std::fputs("\xEF\xBB\xBF# comment\n  es-ES \r\n", f);
        std::fclose(f);
    }
    set_env_var("RX_VK_UI_LANG", "");
    set_env_var("HOS_LANGUAGE", "");
    assert(i18n::resolve_lang(dir.c_str()) == i18n::kEs);

    set_env_var("HOS_LANGUAGE", "ja");
    assert(i18n::resolve_lang(dir.c_str()) == i18n::kJa);

    set_env_var("RX_VK_UI_LANG", "ru");
    assert(i18n::resolve_lang(dir.c_str()) == i18n::kRu);

    set_env_var("RX_VK_UI_LANG", "");
    set_env_var("HOS_LANGUAGE", "");

    // 3. CJK & probe char metadata
    assert(!i18n::is_cjk(i18n::kEs));
    assert(i18n::is_cjk(i18n::kJa));
    assert(i18n::is_cjk(i18n::kKo));
    assert(i18n::is_cjk(i18n::kZhHans));
    assert(i18n::is_cjk(i18n::kZhHant));
    for (int li = 0; li < i18n::kLangCount; ++li) {
        auto l = static_cast<i18n::Lang>(li);
        assert(i18n::lang_code(l) && *i18n::lang_code(l));
        if (l != i18n::kEnUS && l != i18n::kEnGB && l != i18n::kNl) {
            assert(i18n::script_probe_char(l) > 0);
        }
    }

    // 4. All 16 languages: static translations, dynamic builders, restart list, prebake UTF-8
    const char* restart_items[] = {"HDR", "Resolution", "Aspect Ratio"};
    for (int li = 0; li < i18n::kLangCount; ++li) {
        const auto l = static_cast<i18n::Lang>(li);
        i18n::set_lang_for_test(l);
        assert(i18n::current_lang() == l);

        const char* static_probes[] = {
            "Graphics", "Audio", "Gameplay", "Controls", "Debug", "Motion",
            "Inventory", "Teleport", "Restart Needed", "Kokiri Sword",
            "Temple of Time", "Shaders built (4 s)", "Preparing shaders",
        };
        for (const char* s : static_probes) {
            const char* out = i18n::tr(s);
            assert(out && *out && valid_utf8(out));
        }

        const char* dyn_probes[] = {
            "200 nits",
            "Native (DLAA, 1920x1080)",
            "1920x1080 (native)",
            "1920x1080 (game's)",
            "0: Speakers (Realtek)",
            "Mic (not connected)",
            "0: DualSense",
            "Press a key...",
            "Press A / B to bind",
            "RX_VK_FIFO or RX_VK_IMMEDIATE is set: it chooses for this run.",
            "4x (1080p native)",
            "No upscaler selected",
            "Wait... 2 s",
        };
        for (const char* d : dyn_probes) {
            const char* out = i18n::tr_dyn(d);
            assert(out && *out && valid_utf8(out));
        }

        const std::string keys = i18n::tr_keys_text("Z / Right click / Space");
        assert(!keys.empty() && valid_utf8(keys.c_str()));

        const char* sub = i18n::tr_fps_sub("game 60");
        const char* low = i18n::tr_fps_low("1% low 58");
        const char* step = i18n::tr_startup_step("STEP 2 OF 2");
        const char* sleft = i18n::tr_startup_left("120 / 240 pipelines");
        const char* sleft2 = i18n::tr_startup_left("45 shaders");
        const char* sright = i18n::tr_startup_right("about 12 s left");
        const char* sright2 = i18n::tr_startup_right("a few seconds left");
        const char* icount = i18n::tr_items_count(68);
        const char* qty = i18n::tr_quantity(30);
        const char* page = i18n::tr_page_of(1, 3);
        const char* rng = i18n::tr_inv_range(1, 24, 68);
        const char* nm = i18n::tr_n_of_m(5, 31);
        for (const char* x : {sub, low, step, sleft, sleft2, sright, sright2, icount, qty, page, rng, nm}) {
            assert(x && *x && valid_utf8(x));
        }

        const std::string rline = i18n::tr_restart_line(restart_items, 3, 0b111u, 1, 2);
        const std::string rask = i18n::tr_restart_ask(restart_items, 3, 0b101u);
        assert(!rline.empty() && valid_utf8(rline.c_str()));
        assert(!rask.empty() && valid_utf8(rask.c_str()));

        const char* pre = i18n::prebake_utf8();
        assert(pre && *pre && valid_utf8(pre));
    }

    // 5. Spot-check expected localized strings on representative languages
    i18n::set_lang_for_test(i18n::kEs);
    assert(std::string_view(i18n::tr("Graphics")) == "Gr\xc3\xa1" "ficos");
    assert(std::string_view(i18n::tr("Restart Needed")) == "Reinicio necesario");
    assert(std::string_view(i18n::tr("Restart needed")) == "Requiere reinicio");
    assert(std::string_view(i18n::tr("Compact")) == "Compacto");
    assert(std::string_view(i18n::tr("Full menu")) == "Men\xc3\xba completo");
    assert(std::string_view(i18n::tr("VRAM budget")) == "L\xc3\xad" "mite de VRAM");
    assert(std::string_view(i18n::tr_dyn("Right Shift")) == "Shift derecho");
    assert(std::string_view(i18n::tr_dyn("2.2 GB (4GB preset)")) == "2,2 GB (4 GB)");
    assert(std::string_view(i18n::tr("Kokiri Sword")) == "Espada Kokiri");
    assert(std::string_view(i18n::tr_items_count(10)) == "10 objetos");
    assert(std::string_view(i18n::tr_fps_sub("game 60")) == "juego 60");
    // (regression: a number-led value is not "N nits", and minutes are not seconds)
    assert(std::string_view(i18n::tr_dyn("100%")) == "100%");
    assert(std::string_view(i18n::tr_dyn("1.25x")) == "1.25x");
    assert(std::string_view(i18n::tr_dyn("50")) == "50");
    assert(std::string_view(i18n::tr_dyn("800 nits")) == "800 nits");
    assert(std::string_view(i18n::tr_dyn("Num 5")) == "Num 5");
    assert(std::string_view(i18n::tr_dyn("Key 70")) == "Tecla 70");
    assert(std::string_view(i18n::tr_startup_right("about 10 s left")) == "unos 10 s restantes");
    assert(std::string_view(i18n::tr_startup_right("about 5 min left")) == "unos 5 min restantes");

    i18n::set_lang_for_test(i18n::kJa);
    assert(std::string_view(i18n::tr("Graphics")) == "\xe3\x82\xb0\xe3\x83\xa9\xe3\x83\x95\xe3\x82\xa3\xe3\x83\x83\xe3\x82\xaf");

    i18n::set_lang_for_test(i18n::kRu);
    assert(std::string_view(i18n::tr("Graphics")) == "\xd0\x93\xd1\x80\xd0\xb0\xd1\x84\xd0\xb8\xd0\xba\xd0\xb0");

    i18n::set_lang_for_test(i18n::kZhHans);
    assert(std::string_view(i18n::tr("Graphics")) == "\xe5\x9b\xbe\xe5\xbd\xa2");

    // 6. Active language fallback helper restores English cleanly (used when CJK glyphs are absent)
    i18n::set_active_lang(i18n::kJa);
    assert(i18n::current_lang() == i18n::kJa);
    i18n::set_active_lang(i18n::kEnUS);
    assert(i18n::current_lang() == i18n::kEnUS);
    assert(std::string_view(i18n::tr("Graphics")) == "Graphics");

    std::puts("test_menu_i18n OK (16 languages verified)");
    return 0;
}
'''


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cxx", default="g++")
    args = ap.parse_args()

    i18n_text = (VK / "vk_menu_i18n.h").read_text(encoding="utf-8")
    entries = parse_kentries(i18n_text)
    check_static_sources(entries)

    with tempfile.TemporaryDirectory(prefix="hookshot_i18n_") as tmp:
        tmp_path = Path(tmp)
        cpp = tmp_path / "test_menu_i18n.cpp"
        exe = tmp_path / ("test_menu_i18n.exe" if os.name == "nt" else "test_menu_i18n")
        cpp.write_text(CPP_FIXTURE, encoding="utf-8")
        subprocess.run(
            [args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I", str(VK), str(cpp), "-o", str(exe)],
            check=True,
        )
        run_env = os.environ.copy()
        cxx_path = Path(args.cxx)
        if cxx_path.is_absolute():
            run_env["PATH"] = f"{cxx_path.parent}{os.pathsep}{run_env.get('PATH', '')}"
        subprocess.run([str(exe), tmp], check=True, env=run_env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
