"""The bake at the build (nx2/bake.py live, nx2/make_game.py start_bake / finish_bake) and its handshake with the game's prepare.

The bake runs the back end's own prepare (gpu/vk/vk_draw.cpp prepare_run with bake_workers), translation only, in a folder of its
own, and leaves a program cache and the prepare's record there; live_install moves them into the game folder after the build.
The game's prepare then reads the record: translated (the stamp and the seed are the same) with warmed = kWarmedBaked, so it keeps
every program the cache has and translates only what it lacks. Checked here, with no GPU and no game:

- the handshake, with the record's helpers and the decision as they are in vk_draw.cpp: a baked record is taken (baked), a
  record for another translator or GPU (another stamp) prepares from the start, a missing record too, a record the game's own
  prepare wrote is not taken for a bake, and the bake itself never takes its own record for one;
- program_cache_file_stamp (vk_progcache.cpp), which the bake reads to keep a game folder's current cache: the stamp of a cache file,
  0 for a missing, short or foreign file;
- the source: a baked prepare passes kept compute programs over (seed_compute's kept_whole) and still notes the state list; a bake
  makes no pipeline cache, no compute pipelines and no state list, and writes kWarmedBaked;
- the Python side: the bake's folder (the shader list linked, the settings and the back end copied), the install (the cache, its
  index and the record moved in, the record last; nothing moved when nothing was baked), the bake's result read from its lines,
  a library without mkwvk_bake, and make_game's switches and fallbacks (HOOKSHOT_BAKE=1, no bake without the prepare, a bake that failed
  leaves the translation to the prepare and its folder removed).

python -I -B tests/test_bake_live.py [--cxx g++]
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
import types
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
DRAW = ROOT / "gpu" / "vk" / "vk_draw.cpp"
SHADER = ROOT / "gpu" / "vk" / "vk_shader.cpp"
PROGCACHE = ROOT / "gpu" / "vk" / "vk_progcache.cpp"
MAIN = ROOT / "gpu" / "vk" / "vk_main.cpp"
sys.path[:0] = [str(ROOT / "nx2"), str(ROOT / "third_party" / "a64-kit" / "tools")]
import bake  # noqa: E402

fails = []


def check(cond, what):
    if not cond:
        fails.append(what)
        print("FAIL:", what)


def block(text, marker):
    start = text.index(marker)
    at = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[at] == "{") - (text[at] == "}")
        at += 1
    return text[start:at]


def handshake(cxx):
    draw = DRAW.read_text(encoding="utf-8")
    shader = SHADER.read_text(encoding="utf-8")
    start = draw.index("struct PreparedFor {")
    helpers = draw[start:draw.index("} // namespace", start)]
    warmed_baked = re.search(r"constexpr uint64_t kWarmedBaked = [^;]+;", draw).group(0)
    baked = re.search(r"(if \(why == PrepareWhy::None && prepared_for\.warmed == kWarmedBaked[^;]+;)", draw).group(1)
    progcache = PROGCACHE.read_text(encoding="utf-8")
    magic = re.search(r"constexpr uint32_t kDiskMagic = [^;]+;", progcache).group(0)
    file_stamp = block(progcache, "uint64_t program_cache_file_stamp(const std::string& path)")
    cpp = r"""
#ifdef _WIN32
#define NOMINMAX
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <string>
#include <vector>
""" + helpers + "\n" + warmed_baked + "\n" + magic + "\n" + file_stamp + r"""
int fails = 0;
void want(const char* what, bool ok) {
    if (!ok) std::printf("%s\n", what), fails++;
}
/// prepare_run's decision, as it is in vk_draw.cpp: the game's prepare (bake false) or the bake itself (true)
bool decide(const std::string& rec, const std::string& seed, uint64_t stamp, bool bake, PrepareWhy* why_out) {
    PreparedFor prepared_for;
    double hash_ms = 0;
    PrepareWhy why = prepare_check(rec, seed, stamp, &prepared_for, &hash_ms);
    """ + baked + r"""
    *why_out = why == PrepareWhy::Baked ? PrepareWhy::None : why;
    return why == PrepareWhy::Baked;
}
void put(const std::string& path, const void* d, size_t n) {
    FILE* f = fopen(path.c_str(), "wb");
    fwrite(d, 1, n, f);
    fclose(f);
}
int main(int argc, char** argv) {
    const std::string dir = argv[1], rec = dir + "/hookshot_prepared.bin", seed = dir + "/hookshot_shaders.bin";
    std::string bytes(1 << 16, 'x');
    put(seed, bytes.data(), bytes.size());
    std::error_code ec;
    std::filesystem::last_write_time(seed, std::filesystem::file_time_type::clock::now() - std::chrono::hours(1), ec);
    PrepareWhy why;
    // no record: a first start translates everything; so does the bake
    want("no record: not baked", !decide(rec, seed, 7, false, &why) && why == PrepareWhy::First);
    want("no record, the bake: not baked", !decide(rec, seed, 7, true, &why) && why == PrepareWhy::First);
    // the bake's record (bake_workers: warmed kWarmedBaked)
    {
        PreparedFor now;
        double ms;
        prepare_check(rec, seed, 7, &now, &ms);
        now.warmed = kWarmedBaked;
        prepared_write(rec, now);
    }
    want("baked record: taken", decide(rec, seed, 7, false, &why) && why == PrepareWhy::None);
    want("baked record, a second bake: not a baked prepare", !decide(rec, seed, 7, true, &why));
    // another translator or GPU (the stamp holds both): from the start, the cache made again by disk_init
    want("baked for another stamp: prepared from the start", !decide(rec, seed, 8, false, &why) && why == PrepareWhy::Translator);
    // another shader list (an update's): not taken as baked; the programs kept stay kept as on any update
    {
        std::string grown = bytes + "more";
        put(seed, grown.data(), grown.size());
        want("baked for another seed: prepared as an update", !decide(rec, seed, 7, false, &why) && why == PrepareWhy::Seed);
        put(seed, bytes.data(), bytes.size());
        std::filesystem::last_write_time(seed, std::filesystem::file_time_type::clock::now() - std::chrono::hours(1), ec);
    }
    // the game's own prepare's record (a real warmed stamp): not a bake's
    {
        PreparedFor now;
        double ms;
        prepare_check(rec, seed, 7, &now, &ms);
        now.warmed = 0x9e3779b97f4a7c15ull;
        prepared_write(rec, now);
    }
    want("the game's record: not baked", !decide(rec, seed, 7, false, &why) && why == PrepareWhy::None);
    // the cache file's stamp, as the bake reads a game folder's
    const std::string cache = dir + "/hookshot_programs.bin";
    want("no cache: 0", program_cache_file_stamp(cache) == 0);
    {
        const uint32_t h[2] = {kDiskMagic, 0};
        const uint64_t s = 0x1234567890abcdefull;
        std::string b((const char*)h, 8);
        b.append((const char*)&s, 8);
        b.append(40, 'r');
        put(cache, b.data(), b.size());
        want("a cache: its stamp", program_cache_file_stamp(cache) == s);
        put(cache, b.data(), 12);
        want("a short cache: 0", program_cache_file_stamp(cache) == 0);
        b[0] ^= 1;
        put(cache, b.data(), b.size());
        want("another file: 0", program_cache_file_stamp(cache) == 0);
    }
    std::printf("%s\n", fails ? "handshake: FAILED" : "handshake: ok");
    return fails != 0;
}
"""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "t.cpp")
        exe = os.path.join(d, "t.exe" if os.name == "nt" else "t")
        Path(src).write_text(cpp, encoding="utf-8")
        r = subprocess.run([cxx, "-std=c++20", "-O1", src, "-o", exe], capture_output=True, text=True)
        check(r.returncode == 0, "the handshake test compiles: " + r.stderr[-2000:])
        if r.returncode:
            return
        work = os.path.join(d, "w")
        os.makedirs(work)
        r = subprocess.run([exe, work], capture_output=True, text=True)
        print(r.stdout.strip())
        check(r.returncode == 0, "the handshake: " + r.stdout[-2000:])


def source():
    draw = DRAW.read_text(encoding="utf-8")
    run = block(draw, "bool prepare_run(void (*progress)(size_t done, size_t total), bool background, bool refresh_states, unsigned")
    check("seed_compute(k, 64, warm_compute, baked)" in run, "a baked prepare passes kept compute programs over")
    check("if (!bake) pcache_init();" in run, "a bake opens no pipeline cache")
    check(re.search(r"warm_cs = [^;]*!bake;", run) is not None, "a bake builds no compute pipelines")
    check("if (!background && !bake) state_list_prepare(nullptr);" in run, "a bake notes no state list; a baked prepare does")
    check("if (bake) prepared_for.warmed = kWarmedBaked;" in run, "a bake's record says baked")
    shader = SHADER.read_text(encoding="utf-8")
    sc = block(shader, "SeedVariants seed_compute(size_t i, size_t cap, const std::function<void(Program&)>& made, bool kept_whole)")
    check(sc.index("if (kept_whole)") < sc.index("stage_of_seed"), "kept_whole is looked at before any translation")
    main = MAIN.read_text(encoding="utf-8")
    mb = block(main, "int mkwvk_bake(const char* folder, const char* into, int workers)")
    check("game_folder_override() = folder;" in mb, "the bake works in its own folder")
    check("program_cache_file_stamp(kept) == program_cache_stamp()" in mb, "a current cache in the game folder is kept")
    check("prepare_run(progress, false, false, n)" in mb, "the bake is the prepare's translation")


def python_side():
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "game")
        os.makedirs(out)
        lib = os.path.join(d, "hookshot_vk.so")
        Path(lib).write_bytes(b"lib")
        check(bake.live_stage(out, lib) is None, "no shader list: nothing staged")
        Path(out, "hookshot_shaders.bin").write_bytes(b"HKSEED01" + b"\0" * 8)
        Path(out, "hookshot_options.ini").write_text("gpu_device=1\n")
        staged = bake.live_stage(out, lib)
        folder = bake.live_folder(out)
        check(staged == os.path.join(folder, "hookshot_vk.so") and Path(staged).read_bytes() == b"lib", "the back end copied")
        check(Path(folder, "hookshot_options.ini").read_text() == "gpu_device=1\n", "the settings copied")
        check(Path(folder, "hookshot_shaders.bin").read_bytes().startswith(b"HKSEED01"), "the shader list in the folder")
        # an install: the cache, index and record replace the folder's
        for name, data in (("hookshot_programs.bin", b"old"), ("hookshot_programs.idx", b"oldidx"), ("hookshot_prepared.bin", b"oldrec")):
            Path(out, name).write_bytes(data)
        for name, data in (("hookshot_programs.bin", b"new"), ("hookshot_programs.idx", b"newidx"), ("hookshot_prepared.bin", b"newrec")):
            Path(folder, name).write_bytes(data)
        check(bake.live_install(out), "baked: installed")
        check(Path(out, "hookshot_programs.bin").read_bytes() == b"new" and Path(out, "hookshot_programs.idx").read_bytes() == b"newidx"
              and Path(out, "hookshot_prepared.bin").read_bytes() == b"newrec", "the bake's files in the game folder")
        check(not os.path.exists(folder), "the bake's folder gone")
        # no index from the bake: the folder's old one goes (it names another file's records)
        bake.live_stage(out, lib)
        Path(folder, "hookshot_programs.bin").write_bytes(b"newer")
        Path(folder, "hookshot_prepared.bin").write_bytes(b"rec")
        check(bake.live_install(out) and not os.path.exists(os.path.join(out, "hookshot_programs.idx")), "a stale index removed")
        # nothing baked (the folder's cache was current): nothing moved
        bake.live_stage(out, lib)
        check(not bake.live_install(out), "nothing baked: nothing installed")
        check(Path(out, "hookshot_programs.bin").read_bytes() == b"newer", "the folder's cache kept")
        # a cache without its record is not installed (the record says what the cache is)
        bake.live_stage(out, lib)
        Path(folder, "hookshot_programs.bin").write_bytes(b"half")
        check(not bake.live_install(out) and Path(out, "hookshot_programs.bin").read_bytes() == b"newer", "a cache without a record left out")

        # the bake's result, from its lines and exit status
        def fake(lines, code):
            script = "import sys\n" + "".join("print(%r)\n" % l for l in lines) + "sys.exit(%d)\n" % code
            p = subprocess.Popen([sys.executable, "-I", "-c", script], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            seen = []
            live = bake.Live(p, out, seen.append)
            fractions = []
            return live.wait(fractions.append), live, seen

        ok, live, seen = fake(["vk: bake: a GPU", "@@bake 10 100", "@@bake 100 100", "@@bake done"], 0)
        check(ok and live.result == "done" and (live.done, live.total) == (100, 100), "a bake that ends: done")
        check("bake: vk: bake: a GPU" in seen, "its log lines go on")
        ok, live, _ = fake(["@@bake current"], 0)
        check(ok and live.result == "current", "a current cache: nothing to install, not a failure")
        ok, live, _ = fake(["@@bake no usable Vulkan here"], 3)
        check(not ok, "no Vulkan: not baked")
        ok, live, _ = fake(["vk: something"], 0)
        check(not ok, "no result line: not baked")
        ok, live, _ = fake(["@@bake 1 2"], -9 if os.name != "nt" else 1)
        check(not ok, "stopped: not baked")
        # a library without the bake (an older back end): said, and not baked
        r = subprocess.run([sys.executable, "-I", str(ROOT / "nx2" / "bake.py"), "live", "--lib", lib, "--folder", out],
                           capture_output=True, text=True)
        check(r.returncode == 4 and "@@bake no bake" in r.stdout, "a library that does not load: exit 4: " + r.stdout + r.stderr)

        # make_game: when the bake runs, and what a failed one leaves
        import make_game
        a = types.SimpleNamespace(no_prepare_shaders=False)
        on = {"HOOKSHOT_BAKE": "1"}
        check(make_game.bake_skipped(a, {}) is not None, "not baked by default")
        check(make_game.bake_skipped(a, {"HOOKSHOT_BAKE": "0"}) is not None, "HOOKSHOT_BAKE=0: not baked")
        check(make_game.bake_skipped(a, on) is None or make_game.CROSS, "HOOKSHOT_BAKE=1: baked")
        check(make_game.bake_skipped(types.SimpleNamespace(no_prepare_shaders=True), on) is not None, "no prepare: no bake")
        check(make_game.bake_skipped(a, dict(on, HOOKSHOT_NO_PREPARE="1")) is not None, "HOOKSHOT_NO_PREPARE: no bake")
        check(make_game.finish_bake(None, out) is False, "no bake: the prepare translates")
        bake.live_stage(out, lib)
        Path(folder, "hookshot_programs.bin").write_bytes(b"partial")
        p = subprocess.Popen([sys.executable, "-I", "-c", "print('@@bake 5 10'); raise SystemExit(1)"], stdout=subprocess.PIPE,
                             text=True)
        check(make_game.finish_bake(bake.Live(p, out, None), out) is False, "a failed bake: the prepare translates")
        check(not os.path.exists(folder) and Path(out, "hookshot_programs.bin").read_bytes() == b"newer",
              "a failed bake: its folder gone, the game folder's cache as it was")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cxx", default="g++")
    a = ap.parse_args()
    handshake(a.cxx)
    source()
    python_side()
    print("test_bake_live: %s" % ("FAILED (%d)" % len(fails) if fails else "ok"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
