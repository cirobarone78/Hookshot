"""Compile shaders (All, Most, Later) and When a shader isn't ready (Wait, Wait briefly then skip, Skip): gpu/vk/prepare_play.h,
vk_prepare_play.cpp. Checks, with no game and no GPU:
- the rules themselves, compiled from prepare_play.h and run: the choices from hookshot_options.ini and the environment, the threads
  the work behind the game gets for a CPU and the memory free, which draws wait and which are left out, the frame's wait budget, the
  hold of an area's first frames and its cap (a load's frames too), the resume record and its list (a grown list starts again),
  what Most finds left with no record or after a new driver, the overlay's percentage;
- the plumbing: where each choice starts its work, every worker through the gate one variant or pipeline at a time, below normal
  priority, the cache saved only with the workers paused, the dispatch's 50 ms and its budget, the close that never tears the device
  down under a worker, the menu's rows and defaults, the host's area posted only;
- make_game.py's --compile-shaders and the shipped list, and the three builders (passing the choice only when it was made there).

python -I -B tests/test_prepare_play.py [--cxx g++]
"""
import argparse
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

RULES_TEST = r"""
#include "prepare_play.h"
#include <cassert>
#include <cstdio>
using namespace prepare_play;
int main() {
    // the choices: Most and Wait briefly unless the file or the environment says otherwise; the environment over the file
    assert(level_of(nullptr, nullptr) == Level::Most && level_of("vsync=1\n", nullptr) == Level::Most);
    assert(level_of("vsync=1\ncompile_shaders=0\nfps_counter=1\n", nullptr) == Level::All);
    assert(level_of("compile_shaders=2", nullptr) == Level::Later);
    assert(level_of("compile_shaders=0\n", "later") == Level::Later && level_of("compile_shaders=2\n", "all") == Level::All);
    assert(level_of("compile_shaders=2\n", "1") == Level::Most && level_of("compile_shaders=9\n", nullptr) == Level::Later);
    assert(level_of("xcompile_shaders=0\n", nullptr) == Level::Most);   // (a line's start only)
    assert(level_of("compile_shaders=0\n", "") == Level::All);          // (an empty variable is not set)
    assert(miss_of(nullptr, nullptr) == Miss::Briefly && miss_of("shader_miss=0\n", nullptr) == Miss::Wait);
    assert(miss_of("shader_miss=2\n", nullptr) == Miss::Skip && miss_of("shader_miss=2\n", "0") == Miss::Wait);

    // the threads: what the game leaves (2 busy + the renderer), at most 8, one on small CPUs, none with memory short
    assert(workers(24, 12, 20, 0) == 6);   // (a 7900X: 12 cores, 24 threads; at most 6, below normal priority)
    assert(workers(12, 6, 20, 0) == 1);    // (6 cores or fewer: one)
    assert(workers(8, 4, 20, 0) == 1);     // (a Steam Deck)
    assert(workers(16, 8, 20, 0) == 5);    // (8 cores: 8 - 3)
    assert(workers(32, 16, 20, 0) == 6);
    assert(workers(10, 10, 20, 0) == 4);   // (no SMT: 10 cores, 10 threads: 10 - 6 threads left)
    assert(workers(24, 12, 2.5, 0) == 0);  // (under 3 GB available: none)
    assert(workers(24, 12, 5, 0) == 1);    // (under 6 GB: one)
    assert(workers(24, 12, 20, 25) == 0);  // (memory pressure: none)
    assert(workers(24, 12, -1, 0) == 6);   // (memory unknown: by the CPU)
    assert(workers(0, 0, 20, 0) == 1);
    assert(workers_started(24, 12) == 6 && workers_started(8, 4) == 1);

    // the draws: what may not be left out waits whatever the choice
    assert(decide(Miss::Briefly, false, false, true, 1000) == Act::Bounded);
    assert(decide(Miss::Briefly, false, false, true, 0) == Act::LeaveOut);    // (the budget spent)
    assert(decide(Miss::Skip, false, false, true, 1000) == Act::LeaveOut);
    assert(decide(Miss::Wait, false, false, true, 0) == Act::Wait);
    assert(decide(Miss::Skip, true, false, true, 0) == Act::Wait);            // (RX_VK_PIPE_SKIP=0 over all)
    for (Miss m : {Miss::Wait, Miss::Briefly, Miss::Skip})
        for (bool hidden : {false, true}) assert(decide(m, false, hidden, false, 1000) == Act::Wait);   // (writes memory, or a new target)
    assert(decide(Miss::Briefly, false, true, true, 1000) == Act::LeaveOut);  // (a hidden frame: asked for, not waited for)
    assert(decide(Miss::Wait, false, true, true, 1000) == Act::Wait);         // (Wait waits, hidden or not)

    // the budget: a share of the capped frame
    assert(budget_us(1000.0 / 60) == 2500 && budget_us(0) == 2500);           // (no cap: the console's 60)
    assert(budget_us(1000.0 / 144) == 1041);                                  // (144 fps: a smaller budget)
    assert(budget_us(1000.0 / 60, 0.45) == 7500);
    Budget b;
    assert(b.left(5, 2500) == 2500);
    b.spend(1000);
    assert(b.left(5, 2500) == 1500);
    b.spend(2000);
    assert(b.left(5, 2500) < 0);
    assert(b.left(6, 2500) == 2500);   // (a new frame: full again)

    // the hold
    Hold h;
    const int64_t ms = 1000000;
    int64_t t = 0;
    for (int i = 0; i < 30; i++) assert(!h.frame(5, 0, t += 16 * ms, true));   // (a loading screen)
    assert(h.loading);
    assert(h.frame(5, 2, t += 16 * ms, true));        // (a load's frame lacking something: hidden)
    assert(h.frame(900, 40, t += 16 * ms, true));     // (the area's first frame, 40 not ready: hidden)
    assert(h.frame(900, 10, t += 16 * ms, true));
    for (int i = 0; i < 7; i++) assert(h.frame(900, 0, t += 16 * ms, true));   // (clean, but not 8 in a row yet)
    assert(!h.frame(900, 0, t += 16 * ms, true));     // (the 8th clean frame is shown)
    assert(h.hidden == 9 && !h.holding);
    assert(!h.frame(900, 5, t += 16 * ms, true));     // (not a load: shown)
    for (int i = 0; i < 30; i++) h.frame(5, 0, t += 16 * ms, true);   // (the cap)
    assert(h.frame(900, 40, t += 16 * ms, true));
    int n = 1;
    while (h.frame(900, 3, t += 16 * ms, true)) n++;
    assert(n > 100 && n < 200 && !h.holding);         // (3 s at 16 ms: ~188 frames)
    for (int i = 0; i < 30; i++) h.frame(5, 0, t += 16 * ms, true);   // (a load whose first frame lacks nothing: not held)
    assert(!h.frame(900, 0, t += 16 * ms, true) && !h.holding);
    for (int i = 0; i < 30; i++) h.frame(5, 0, t += 16 * ms, false);  // (disabled: never)
    assert(!h.frame(900, 40, t += 16 * ms, false));
    for (int i = 0; i < 30; i++) h.frame(60, 0, t += 16 * ms, true);  // (menus, then the game: a load too)
    assert(h.frame(1200, 3, t += 16 * ms, true));
    while (h.frame(1200, 3, t += 16 * ms, true)) {}
    // (a pause menu or a dark room draws few too: its frames lacking something are hidden for the cap at most, never longer)
    Hold q;
    int64_t u = 0;
    for (int i = 0; i < 30; i++) q.frame(40, 0, u += 16 * ms, true);
    int hid = 0;
    for (int i = 0; i < 1000; i++) hid += q.frame(40, 2, u += 16 * ms, true);
    assert(hid > 100 && hid < 200);   // (3 s at 16 ms)
    assert(!q.frame(40, 2, u += 16 * ms, true));

    // the record
    Progress p{0x1234, kPredicted, 777, 0xabc};
    Progress r = progress_parse(progress_text(p).c_str(), 0x1234);
    assert(r.stamp == 0x1234 && r.phase == kPredicted && r.at == 777 && r.list == 0xabc);
    // (a part resumes only in the same list: one that grew since (play noted more pipelines) starts again)
    assert(resume_at(r, kPredicted, 0xabc) == 777 && resume_at(r, kPredicted, 0xabd) == 0 && resume_at(r, kNoted, 0xabc) == 0);
    const uint64_t k1[] = {1, 2, 3}, k2[] = {1, 2, 3, 4};
    assert(list_hash(k1, 3) != list_hash(k2, 4) && list_hash(k1, 3) == list_hash(k2, 3));
    // (Most: no record does what Most leaves (not "prepared with All"); a new driver needs the predicted pipelines again)
    assert(most_left(-1, false) == kComputeRest && most_left(kDone, false) == kDone);
    assert(most_left(kDone, true) == kPredicted && most_left(kComputeRest, true) == kComputeRest);
    r = progress_parse(progress_text(p).c_str(), 0x9999);   // (another translator or seed: no record)
    assert(r.phase == -1 && r.stamp == 0x9999);
    assert(progress_parse(nullptr, 1).phase == -1 && progress_parse("garbage", 1).phase == -1);
    assert(progress_parse("stamp=0000000000000001\nphase=9\nat=3\n", 1).phase == -1);
    assert(progress_parse("stamp=0000000000000001\nphase=4\nat=3\n", 1).at == 0);
    assert(first_part(Level::Later, -1) == kPrograms && first_part(Level::Most, -1) == kComputeRest);
    assert(first_part(Level::Most, kPredicted) == kPredicted && first_part(Level::Later, kNoted) == kNoted);
    std::atomic<uint8_t> done[6];
    const uint8_t d0[6] = {1, 1, 0, 1, 1, 1};
    for (int i = 0; i < 6; i++) done[i] = d0[i];
    assert(done_prefix(done, 6, 0) == 2);
    done[2] = 1;
    assert(done_prefix(done, 6, 0) == 6);

    // the overlay's percentage, over the parts this start does
    const uint64_t counts[kParts] = {100, 25, 50, 50};   // (costs 100 + 100 + 100 + 100)
    assert(percent(kPrograms, kPrograms, 0, 100, counts) == 0);
    assert(percent(kPrograms, kPrograms, 50, 100, counts) == 12);
    assert(percent(kPrograms, kPredicted, 25, 50, counts) == 62);
    assert(percent(kComputeRest, kComputeRest, 25, 25, counts) == 33);   // (Most: from the compute variants)
    assert(percent(kComputeRest, kNoted, 50, 50, counts) == 99);          // (never 100 before it is done)
    assert(percent(kPrograms, kDone, 0, 0, counts) == 100);
    puts("ok");
    return 0;
}
"""


def need(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def body(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def rules(cxx):
    with tempfile.TemporaryDirectory() as d:
        src, exe = os.path.join(d, "t.cpp"), os.path.join(d, "t.exe")
        Path(src).write_text(RULES_TEST, encoding="utf-8")
        subprocess.run([cxx, "-std=c++20", "-O1", "-I" + str(ROOT / "gpu" / "vk"), src, "-o", exe], check=True)
        out = subprocess.run([exe], check=True, capture_output=True, text=True).stdout
        need(out.strip() == "ok", "the rules' test did not finish")


def plumbing():
    vk = ROOT / "gpu" / "vk"
    draw = (vk / "vk_draw.cpp").read_text(encoding="utf-8")
    main = (vk / "vk_main.cpp").read_text(encoding="utf-8")
    replay = (vk / "vk_replay.cpp").read_text(encoding="utf-8")
    menu = (vk / "vk_menu.cpp").read_text(encoding="utf-8")
    play = (vk / "vk_prepare_play.cpp").read_text(encoding="utf-8")
    # the start: Later before the start-up screen, Most after it; the predicted pipelines before the game on All only
    up = body(main, "bool started_up()")
    need("prepare_level() == prepare_play::Level::Later && prepare_play_begin()" in up, "Later does not start the work behind the game")
    need(up.index("prepare_level() == prepare_play::Level::Later") < up.index("prepare_with_screen();"),
         "Later still holds the game for the preparation")
    need("prepare_with_screen();\n            if (!prepare_stopped()) prepare_play_begin();" in up, "Most does not start the rest after the screen")
    pbp = body(main, "bool predict_before_play(bool prepared)")
    need("prepare_level() != prepare_play::Level::All) return false" in pbp, "Most or Later predict before the game")
    need(up.count("predict_before_play(") == 2 and "predict_before_play(" in body(main, "void prepare_with_screen()"),
         "a start path predicts without asking predict_before_play")
    begin = body(play, "bool prepare_play_begin()")
    need("prepare_play::Level::All" in begin and "HOOKSHOT_PREPARE_ONLY" in begin, "All or the builder's run would prepare behind the game")
    need("prep_pcache_init()" in begin, "the start's pipeline cache is not read before play")
    close = body(main, "void mkwvk_close_asked(void)")
    need("prepare_play_close()" in close, "closing the window does not stop the work behind the game")
    need("if (!stopped)" in close and "std::_Exit(0)" in close, "a worker still in the driver at the close: the device would be torn down under it")
    # (Most with no record, or after a new driver: the parts Most leaves are done again)
    need("most_left(progress_rec.phase, false)" in body(play, "bool prepare_play_begin()"), "Most reads no record as all prepared")
    need("prep_driver_changed()" in run_body_driver(draw), "a new driver does not bring the predicted pipelines back on Most")
    # the programs' part: the unlisted compute programs at their base variant, on Most and Later
    run = body(draw, "bool prepare_run(")
    need("prep_compute_every(0)" in run and "seed_compute(k, every ? 64 : 1," in run and "prep_compute_every(key)" in run,
         "the programs' part does not leave the unlisted compute programs at their base variant")
    need("prep_programs_prepared()" in run, "the programs' part does not record what it left")
    need("seed_compute(computes[i], 64," in body(draw, "bool compute_rest_run("), "the other compute variants are not made behind the game")
    # the workers: each goes through the gate (the frame's work first) and the thread count, in every part
    for fn in ("bool prepare_run(", "void predict_run(", "void precompile_into_cache(", "bool warm_libraries(", "void state_list_prepare(",
               "bool compute_rest_run("):
        b = body(draw, fn)
        need("prep_gate()" in b, "%s does not go through prep_gate" % fn)
        need("prep_thread_begin(" in b, "%s does not start its threads through prep_thread_begin" % fn)
        need("prep_threads(" in b, "%s does not count its threads through prep_threads" % fn)
    gate = body(play, "void prep_gate()")
    need("jobs_pending() == 0" in gate and "allowed" in gate and "pausing" in gate,
         "the gate does not wait for the frame's own work, the threads allowed and the checkpoints")
    need("std::lock_guard lk(gate_mu)" in gate and "std::lock_guard lk(gate_mu)" in body(play, "bool pause_and_save()"),
         "a slot can be taken while a checkpoint saves the cache")
    begin = body(play, "void prep_thread_begin(")
    need("THREAD_PRIORITY_BELOW_NORMAL" in begin and "THREAD_PRIORITY_IDLE" not in begin and "THREAD_PRIORITY_IDLE" not in play,
         "the work behind the game holds play's locks at idle priority")
    # (the gate before each variant's compile and each pipeline, not each program's whole list)
    need("prep_gate();" in body(draw, "bool compute_rest_run(").split("seed_compute(computes[i], 64,")[1].split("});")[0],
         "the compute variants are not gated one by one")
    pred = body(draw, "void predict_run(")
    need("prep_gate();" in pred.split("for (const PipeNote* n : list)")[1].split("build_graphics(")[0], "the predicted pipelines are not gated one by one")
    need("prep_gate()" in body(draw, "void precompile_into_cache(").split("const auto build_notes")[1].split("};")[0],
         "the noted pipelines are not gated one by one")
    # (the dispatch: main's 50 ms for a compile; a variant not translated yet by the choice and its budget, never open-ended on Most)
    disp = body(draw, "void dispatch(VkCommandBuffer cmd, NvnState& s, uint32_t x, uint32_t y, uint32_t z, uint64_t indirect)")
    need("std::chrono::milliseconds(50)" in disp and "? 1000" not in disp, "a dispatch waits longer than main's 50 ms for a compile")
    need("prep_miss_act(true, false)" in disp and "jobs_wait_for(cp->ready, prep_miss_budget_left())" in disp,
         "a dispatch's untranslated variant is not waited for by the choice and the frame's budget")
    # (the cache read for a save only with the workers paused; the record only after the save; checkpoints only on growth)
    need("prep_cache_save_ok()" in body(draw, "void pipeline_cache_save(bool force)"), "the cache is saved while the work behind the game builds into it")
    cb = body(play, "void progress_cb(")
    need("seconds(300)" in cb and "pcache_unsaved() >= 256" in cb, "the checkpoint saves the whole cache every minute")
    need("record(" not in body(play, "void run()").split("} else {")[-1], "a stop records a position whose pipelines were not saved")
    need("!predict_gave_up()" in body(play, "void run()"), "a prediction that gave up is recorded done")
    # (the game's thread only posts its area)
    need("areas_want" not in body(play, "void mkwvk_area_state(") and "posted_mu" in body(play, "void mkwvk_area_state("),
         "the game's thread does the areas' work under their lock")
    # (held frames paced)
    need("sleep_until(next)" in body(replay, "void do_present("), "held frames run unpaced")
    need("prep_direct_cache()" in body(draw, "VkResult create_cached("), "the preparation's pipelines would go into play's cache")
    need("prep_record_suffix()" in run, "prepare_run writes the record before everything is done")
    # the draws: memory writers and new targets always wait; the rest by the choice
    d = body(draw, "void draw(VkCommandBuffer cmd, NvnState& s, const DrawArgs& d)")
    need("prep_miss_act(may_skip)" in d and "!writes_memory(p)" in d, "the pipeline's wait does not go by the choice and the memory rule")
    need("jobs_wait_for(pe->ready, prep_miss_budget_left())" in d, "Wait briefly does not wait out of the frame's budget")
    need("prep_present_hidden(" in body(replay, "void do_present(") and "|| hidden) return;" in body(replay, "void do_present("),
         "a held frame is still shown")
    # the menu
    need(re.search(r'\{TAB_GRAPHICS, "Compile shaders", &opts\.compile_shaders, 0, 2, 1, tx_compile_shaders,', menu), "no Compile shaders row")
    need(re.search(r'\{TAB_GRAPHICS, "When a shader isn\'t ready", &opts\.shader_miss, 0, 2, 1, tx_shader_miss,', menu),
         "no When a shader isn't ready row")
    need('return "compile_shaders";' in body(menu, "const char* ini_key("), "the row is not saved as compile_shaders=")
    need("writes the game's memory" in menu, "the row's help does not say memory-writing draws always wait")
    need("prep_overlay_text(" in body(menu, "void menu_record(VkCommandBuffer cmd") and "draw_prep(" in body(menu, "void menu_record(VkCommandBuffer cmd"),
         "the overlay is not drawn")
    need("!has_shader_miss && opts.compile_shaders == 0" in menu, "All's default for When a shader isn't ready is not main's (Skip)")
    h = (vk / "vk_menu.h").read_text(encoding="utf-8")
    need("int compile_shaders = 1;" in h and "int shader_miss = 1;" in h, "the defaults are not Most and Wait briefly")
    # the host: the area read only when the back end wants it
    host = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    rep = body(host, "static void oot_area_report(")
    need(rep.index("rx_area_wanted()") < rep.index("oot_gamedata_string("), "the host reads the game's area when nothing is prepared behind it")


def make_game():
    spec = importlib.util.spec_from_file_location("make_game", ROOT / "nx2" / "make_game.py")
    mg = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT / "nx2"))
    spec.loader.exec_module(mg)
    with tempfile.TemporaryDirectory() as d:
        ini = os.path.join(d, "hookshot_options.ini")
        mg.set_compile_shaders(d, None)
        need(not os.path.exists(ini), "no choice still wrote the options file")
        mg.set_compile_shaders(d, "later")
        need(Path(ini).read_text() == "compile_shaders=2\n", "later did not write compile_shaders=2")
        Path(ini).write_text("vsync=1\npad_a=3\ncompile_shaders=2\nkey_a=4,5")
        mg.set_compile_shaders(d, "all")
        need(Path(ini).read_text() == "vsync=1\npad_a=3\ncompile_shaders=0\nkey_a=4,5", "all did not keep the file's other lines")
        Path(ini).write_text("vsync=1")
        mg.set_compile_shaders(d, "most")
        need(Path(ini).read_text() == "vsync=1\ncompile_shaders=1\n", "most did not end the last line first")
    later = mg.prepare_skipped(SimpleNamespace(no_prepare_shaders=False, compile_shaders="later"), {})
    need(later and "Later" in later, "Later did not skip the build's preparation")
    for level in ("all", "most", None):
        need(mg.prepare_skipped(SimpleNamespace(no_prepare_shaders=False, compile_shaders=level), {}) is None, "%s skipped it" % level)
    need(mg.prepare_skipped(SimpleNamespace(no_prepare_shaders=False), {}) is None, "an old caller's arguments now skip it")
    src = (ROOT / "nx2" / "make_game.py").read_text(encoding="utf-8")
    need('"--compile-shaders", choices=COMPILE_SHADERS' in src, "make_game has no --compile-shaders")
    need(src.index("set_compile_shaders(out, a.compile_shaders)") < src.index("skipped = prepare_skipped(a)"),
         "the choice is not written before the shaders' step")
    need("ship_computes_list(out)" in src, "the dispatched compute list is not shipped")
    lines = (ROOT / "assets" / "computes_dispatched.txt").read_text(encoding="ascii").split()
    need(lines and all(re.fullmatch(r"[0-9a-f]{16}", l) for l in lines), "assets/computes_dispatched.txt is not hex keys")
    need(lines == sorted(set(lines)), "the dispatched compute list is not sorted, each key once")
    with tempfile.TemporaryDirectory() as d:
        mg.ship_computes_list(d)
        data = Path(d, "hookshot_computes_shipped.bin").read_bytes()
        need(data[:8] == mg.COMPUTES_MAGIC and len(data) == 8 + 8 * len(lines) and
             int.from_bytes(data[8:16], "little") == int(lines[0], 16), "the shipped list is not hookshot_computes.bin's format")


def builders():
    b = ROOT / "builder"
    xaml = (b / "HookshotBuilder" / "MainWindow.xaml").read_text(encoding="utf-8")
    need('x:Name="CompileBox"' in xaml and all('<ComboBoxItem Content="%s"/>' % n in xaml for n in ("All", "Most", "Later")),
         "the WPF builder has no Compile shaders box")
    need('SelectedIndex="1"' in xaml[xaml.index('x:Name="CompileBox"'):], "the WPF builder's box is not on Most")
    cs = (b / "HookshotBuilder" / "MainWindow.xaml.cs").read_text(encoding="utf-8")
    need("CompileShaders = compileChosen ? ChosenLevel() : null" in cs and "CompileBox.SelectedIndex = " in cs,
         "the WPF builder does not save and restore it, or saves a choice never made")
    need(cs.count("ShaderStep.Args(") == 2 and "compileLevel" in cs, "the WPF builder's build and update do not pass it")
    step = (b / "HookshotBuilder" / "ShaderStep.cs").read_text(encoding="utf-8")
    need('Compile = "--compile-shaders"' in step and 'DefaultLevel = "most"' in step, "ShaderStep does not pass the level")
    need("public string? CompileShaders" in (b / "HookshotBuilder" / "BuilderSettings.cs").read_text(encoding="utf-8"),
         "the WPF builder's settings do not keep it")
    qt = (b / "py" / "hookshot_builder" / "window.py").read_text(encoding="utf-8")
    need('"CompileShaders": self.chosen_level()' in qt and "self.compile_box" in qt and "if self.compile_chosen else None" in qt,
         "the Qt builder has no box, or saves a choice never made")
    need(qt.count("shader_args(") == 3, "the Qt builder's build and update do not pass it")
    lx = (b / "linux" / "hookshot_builder.py").read_text(encoding="utf-8")
    need("Compile shaders" in lx and '{"compile_shaders": self.compile_level()} if self.compile_level()' in lx,
         "the Linux builder has no box, or saves a choice never made")
    need(lx.count("compile_shaders_args(self.compile_level())") == 2, "the Linux builder's build and update do not pass it")
    ns = {"re": re}
    block = qt[qt.index("SHADERS_LATER = "):qt.index("def shader_args(")]
    exec(compile(block + "\n" + body_py(qt, "def shader_args("), "w", "exec"), ns)
    need(ns["shader_args"](True, "most") == ["--compile-shaders", "most"], "Qt: prepared now")
    need(ns["shader_args"](False, "all") == ["--no-prepare-shaders", "--compile-shaders", "all"], "Qt: left to the first start")
    need(ns["shader_args"](True, "later") == ["--compile-shaders", "later"], "Qt: Later")
    need(ns["shader_args"](True, None) == [], "Qt: never chosen, still passed (a rebuild would undo the game menu's choice)")
    need(ns["shader_args"](False, None) == ["--no-prepare-shaders"], "Qt: never chosen, unticked")
    need("if (level != null) args.AddRange" in step, "WPF: the level is passed when never chosen")


def run_body_driver(draw):
    """prepare_run's path that remakes the driver's part alone"""
    run = body(draw, "bool prepare_run(")
    return run[run.index("their driver's part was made for another driver"):run.index("// (the translator is the same")]


def body_py(text, marker):
    start = text.index(marker)
    end = text.find("\n\n\n", start)
    return text[start:end if end > 0 else len(text)]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    rules(a.cxx)
    plumbing()
    make_game()
    builders()
    print("ok: Compile shaders and When a shader isn't ready (rules, plumbing, make_game, builders)")


if __name__ == "__main__":
    main()
