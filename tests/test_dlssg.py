"""NVIDIA DLSS Frame Generation (gpu/vk/vk_dlssg.cpp) without a GPU, the game or NVIDIA's SDK: Reflex's frame limit for
the frames shown, the menu row and its saved key (read before Vulkan starts; RX_VK_DLSSG over both), the stubs of a build
without Streamline, the places the renderer hands over to Streamline (its loader, its Reflex, the frame chain's inputs, the
present) and stands its own frame generation and Reflex aside, the folders NGX is told of through Streamline, and the
exit: Streamline shut down when the window closes, run with a stand-in SDK whose Reflex sleep blocks.

python -I -B tests/test_dlssg.py [--cxx g++]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def read(name):
    return (VK / name).read_text(encoding="utf-8")


def ordered(text, *markers, what):
    at = [text.find(m) for m in markers]
    if -1 in at or at != sorted(at):
        raise SystemExit("%s (%s)" % (what, " before ".join(markers)))


FIXTURE = r"""
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)
int mhz = 0;
int display_refresh_mhz() { return mhz; }
/* FRAME_LIMIT */
int main() {
    /* the frames shown held below the refresh as NVIDIA's driver holds them with G-SYNC: refresh - refresh^2 / 3600 */
    mhz = 120000;
    CHECK(frame_limit_us(true) == 8621);   /* 116 fps */
    mhz = 144000;
    CHECK(frame_limit_us(true) == 7234);   /* 138.24 */
    mhz = 240000;
    CHECK(frame_limit_us(true) == 4464);   /* 224 */
    mhz = 60000;
    CHECK(frame_limit_us(true) == 16949);  /* 59 */
    CHECK(frame_limit_us(false) == 0);     /* DLSS-G off: no limit */
    mhz = 0;
    CHECK(frame_limit_us(true) == 0);      /* the refresh not known */
    std::printf("PASS: Reflex holds DLSS Frame Generation's frames below the display's refresh\n");
}
"""

# The exit (dlssg_shutdown) with vk_dlssg.cpp's own State, token(), dlssg_marker, dlssg_sleep and dlssg_shutdown, and a
# stand-in for Streamline whose Reflex sleep blocks until it is let go. Each run is one process: the exit happens once.
#   order:         a sleep under way when the window closes: the exit waits for it with the present lock free, lets nothing
#                  in meanwhile, then idle, DLSS-G off, slShutdown, in that order; the locks stay held; a second close does
#                  nothing
#   stuck_present: a present that does not end: the exit gives up after its wait, Streamline left as it is, nothing held
#   stuck_sleep:   a sleep that does not end: likewise, and the present lock never taken
SHUTDOWN_FIXTURE = r"""
#include <chrono>
#include <condition_variable>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <string>
#include <thread>
#include <vector>
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)
using HMODULE = void*;
namespace sl {
enum class Result { eOk, eErrorNotInitialized };
struct FrameToken { uint32_t index = 0; operator uint32_t() const { return index; } };
enum class PCLMarker { eSimulationStart, eSimulationEnd, eRenderSubmitStart, eRenderSubmitEnd, ePresentStart, ePresentEnd };
enum class DLSSGMode { eOff, eOn };
enum class DLSSGFlags : uint32_t { eRetainResourcesWhenOff = 1 };
struct DLSSGOptions { DLSSGMode mode = DLSSGMode::eOff; uint32_t numFramesToGenerate = 1; DLSSGFlags flags{}; };
struct ViewportHandle { ViewportHandle(int) {} };
}  // namespace sl
#define SL_FAILED(r, f) sl::Result r = f; r != sl::Result::eOk
using PFun_slInit = sl::Result();
using PFun_slSetTagForFrame = sl::Result();
using PFun_slSetConstants = sl::Result();
using PFun_slGetFeatureFunction = sl::Result();
using PFun_slGetNewFrameToken = sl::Result(sl::FrameToken*& token, const uint32_t* frameIndex);
using PFun_slDLSSGSetOptions = sl::Result(const sl::ViewportHandle& viewport, const sl::DLSSGOptions& options);
using PFun_slDLSSGGetState = sl::Result();
using PFun_slReflexSetOptions = sl::Result();
using PFun_slReflexSleep = sl::Result(const sl::FrameToken& frame);
using PFun_slPCLSetMarker = sl::Result(sl::PCLMarker marker, const sl::FrameToken& frame);
using PFun_slShutdown = sl::Result();
namespace fx {
/* HEADER_ENUMS */
std::chrono::milliseconds kExitWait{5000};
// (what happened, in order: Streamline's calls, the device's idle, a present that does not end)
std::mutex ev_mu;
std::condition_variable ev_cv;
std::vector<std::string> events, logs;
bool sleep_go = false, let_go = false;
void note(const std::string& e) {
    {
        std::lock_guard l(ev_mu);
        events.push_back(e);
    }
    ev_cv.notify_all();
}
int at(const std::string& e) {   // (its first place, -1 when it did not happen)
    std::lock_guard l(ev_mu);
    for (size_t i = 0; i < events.size(); i++)
        if (events[i] == e) return (int)i;
    return -1;
}
int count(const std::string& e) {
    std::lock_guard l(ev_mu);
    int n = 0;
    for (const auto& x : events) n += x == e;
    return n;
}
size_t size() {
    std::lock_guard l(ev_mu);
    return events.size();
}
std::string event(size_t i) {
    std::lock_guard l(ev_mu);
    return events.at(i);
}
bool seen(const std::string& e) {   // (waited for, 5 s at most)
    std::unique_lock l(ev_mu);
    return ev_cv.wait_for(l, std::chrono::seconds(5), [&] {
        for (const auto& x : events)
            if (x == e) return true;
        return false;
    });
}
void release(bool& flag) {
    {
        std::lock_guard l(ev_mu);
        flag = true;
    }
    ev_cv.notify_all();
}
void logf(const char* f, ...) {
    char b[512];
    va_list a;
    va_start(a, f);
    std::vsnprintf(b, sizeof b, f, a);
    va_end(a);
    std::lock_guard l(ev_mu);
    logs.push_back(b);
}
bool logged(const char* part) {
    std::lock_guard l(ev_mu);
    for (const auto& x : logs)
        if (x.find(part) != std::string::npos) return true;
    return false;
}
std::mutex present_image_mu;
struct {
    void* device = &present_image_mu;
    std::mutex present_mu;
} dev;
void device_wait_idle_locked() { note("idle"); }
/* STATE */
bool functions() { return true; }
void apply_reflex(bool, uint32_t) {}
/* CUT */
// (the stand-in SDK)
sl::FrameToken tokens[64];
uint32_t next_token = 0;
sl::Result fake_token(sl::FrameToken*& t, const uint32_t*) {
    tokens[next_token % 64].index = next_token;
    t = &tokens[next_token++ % 64];
    return sl::Result::eOk;
}
sl::Result fake_sleep(const sl::FrameToken&) {
    note("sleep in");
    {
        std::unique_lock l(ev_mu);
        ev_cv.wait(l, [] { return sleep_go; });
    }
    note("sleep out");
    return sl::Result::eOk;
}
sl::Result fake_marker(sl::PCLMarker, const sl::FrameToken&) {
    note("marker");
    return sl::Result::eOk;
}
sl::Result fake_options(const sl::ViewportHandle&, const sl::DLSSGOptions& o) {
    note(o.mode == sl::DLSSGMode::eOff ? "off" : "on");
    return sl::Result::eOk;
}
sl::Result fake_shutdown() {
    note("slShutdown");
    return sl::Result::eOk;
}
bool closing() {
    std::lock_guard l(st().mu);
    return st().closing;
}
double timed_shutdown() {   // (seconds)
    const auto t0 = std::chrono::steady_clock::now();
    dlssg_shutdown();
    return std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
}
}  // namespace fx
using namespace fx;
int main(int argc, char** argv) {
    const std::string mode = argc > 1 ? argv[1] : "order";
    State& s = st();
    s.active = true, s.why = DLSSG_OK;
    s.new_token = fake_token, s.reflex_sleep = fake_sleep, s.pcl_marker = fake_marker;
    s.dlssg_set_options = fake_options, s.shutdown = fake_shutdown;
    s.mode = sl::DLSSGMode::eOn, s.frames = 1;
    dlssg_marker(DLSSG_SIM_END);   /* while Streamline runs, a marker goes to it */
    CHECK(count("marker") == 1);
    if (mode == "order") {
        std::thread sleeper([] { dlssg_sleep(); });   /* the presentation thread, in Reflex's sleep */
        CHECK(seen("sleep in"));
        std::thread closer([] { dlssg_shutdown(); });   /* the window's thread: the window closed */
        while (!closing()) std::this_thread::sleep_for(std::chrono::milliseconds(1));
        const size_t began = size();
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        /* it waits for the sleep, with the present lock and the queue's free: the sleeping thread presents next */
        CHECK(at("idle") < 0 && at("off") < 0 && at("slShutdown") < 0);
        CHECK(present_image_mu.try_lock());
        present_image_mu.unlock();
        CHECK(dev.present_mu.try_lock());
        dev.present_mu.unlock();
        /* nothing is let in meanwhile: no marker, no other sleep */
        dlssg_marker(DLSSG_PRESENT_START);
        dlssg_sleep();
        CHECK(size() == began);
        release(sleep_go);
        sleeper.join();
        closer.join();
        /* the sleep ended without its simulation-start marker; then idle, DLSS-G off, slShutdown */
        for (size_t i = began; i < size(); i++) CHECK(event(i) != "marker");
        CHECK(at("sleep out") >= 0 && at("sleep out") < at("idle") && at("idle") < at("off") && at("off") < at("slShutdown"));
        CHECK(count("slShutdown") == 1 && count("off") == 1 && logged("Streamline shut down for the exit"));
        /* the presents and the queue stay held until the process ends: nothing reaches Streamline after it */
        CHECK(!present_image_mu.try_lock());
        CHECK(!dev.present_mu.try_lock());
        /* a second close, and any call after it, does nothing, at once */
        const size_t after = size();
        CHECK(timed_shutdown() < 1.0);
        dlssg_marker(DLSSG_PRESENT_END);
        dlssg_sleep();
        CHECK(size() == after && count("slShutdown") == 1);
        std::printf("PASS: the exit waits for Reflex's sleep with the presents free, lets nothing in, then idle, DLSS-G off, "
                    "slShutdown, once\n");
    } else if (mode == "stuck_present") {
        kExitWait = std::chrono::milliseconds(300);
        std::thread presenter([] {   /* a present that does not end */
            std::lock_guard l(present_image_mu);
            note("presenting");
            std::unique_lock w(ev_mu);
            ev_cv.wait(w, [] { return let_go; });
        });
        CHECK(seen("presenting"));
        const double took = timed_shutdown();
        CHECK(took >= 0.25 && took < 3.0);
        CHECK(at("idle") < 0 && at("off") < 0 && at("slShutdown") < 0 && logged("a present did not end within"));
        CHECK(dev.present_mu.try_lock());   /* nothing left held */
        dev.present_mu.unlock();
        release(let_go);
        presenter.join();
        CHECK(present_image_mu.try_lock());
        present_image_mu.unlock();
        const size_t after = size();
        dlssg_marker(DLSSG_SIM_START);   /* the exit began all the same: nothing goes to Streamline */
        CHECK(size() == after);
        std::printf("PASS: a present stuck at the exit leaves Streamline as it is after the wait, nothing held\n");
    } else if (mode == "stuck_sleep") {
        kExitWait = std::chrono::milliseconds(300);
        std::thread sleeper([] { dlssg_sleep(); });
        CHECK(seen("sleep in"));
        const double took = timed_shutdown();
        CHECK(took >= 0.25 && took < 3.0);
        CHECK(at("idle") < 0 && at("slShutdown") < 0 && logged("Reflex sleep did not end within"));
        CHECK(present_image_mu.try_lock());   /* never taken */
        present_image_mu.unlock();
        const size_t after = size();
        release(sleep_go);
        sleeper.join();
        for (size_t i = after; i < size(); i++) CHECK(event(i) != "marker");
        std::printf("PASS: a Reflex sleep stuck at the exit leaves Streamline as it is after the wait, the presents free\n");
    } else {
        CHECK(!"a mode: order, stuck_present or stuck_sleep");
    }
}
"""


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    dlssg = read("vk_dlssg.cpp")
    header = read("vk_dlssg.h")

    # a build without Streamline (no HOOKSHOT_SL) has every function of the header, as stubs that say it is not there
    sl, stubs = dlssg.split("#ifdef HOOKSHOT_SL\n\nnamespace {", 1)[1].split("#else", 1)
    for name in re.findall(r"^\S[^;(]*\b(dlssg_\w+)\(", header, re.M):
        for part, what in ((sl, "Streamline's"), (stubs, "the stubs'")):
            if not re.search(r"\b%s\([^;]*\)\s*\{" % name, part):
                raise SystemExit("vk_dlssg.cpp: %s is not in %s part" % (name, what))
    if "return false;" not in block(stubs, "bool dlssg_active()") or "DLSSG_NOT_BUILT" not in block(stubs, "DlssgWhy dlssg_why()"):
        raise SystemExit("vk_dlssg.cpp: a build without Streamline says it runs")
    if "verifyEmbeddedSignature(" not in block(dlssg, "PFN_vkGetInstanceProcAddr dlssg_load() {"):
        raise SystemExit("vk_dlssg.cpp: sl.interposer.dll is loaded without NVIDIA's signature checked")

    # the row, read before the menu reads its file: the key the menu saves it under is the one vk_dlssg.cpp reads
    menu = read("vk_menu.cpp")
    row = re.search(r'\{TAB_GRAPHICS, "(DLSS Frame Gen)", &opts\.dlssg, 0, 3, 1, tx_dlssg,(.*?)\},\n', menu, re.S)
    if not row:
        raise SystemExit("vk_menu.cpp: no DLSS Frame Gen row (0 off to 3: 4x) on the Graphics tab")
    if not row.group(2).rstrip().endswith("hn_dlssg, true, true"):
        raise SystemExit("vk_menu.cpp: the DLSS Frame Gen row does not take a restart, or turns the Quality preset to Custom")
    key = re.search(r'if \(r\.value == &opts\.dlssg\) return "(\w+)";', block(menu, "const char* ini_key(const Row& r) {"))
    if not key:
        raise SystemExit("ini_key: the DLSS Frame Gen row has no key of its own, which vk_dlssg.cpp's saved_dlssg reads")
    if '"%s="' % key.group(1) not in block(dlssg, "int saved_dlssg() {"):
        raise SystemExit("vk_dlssg.cpp: saved_dlssg does not read %s=, the row's key" % key.group(1))
    # RX_VK_DLSSG for one run: Streamline started (saved_dlssg) and the row on (menu_init), before what the run started with
    if 'getenv("RX_VK_DLSSG")' not in block(dlssg, "int saved_dlssg() {"):
        raise SystemExit("vk_dlssg.cpp: saved_dlssg does not take RX_VK_DLSSG over the options file")
    ordered(block(menu, "void menu_init() {"), 'getenv("RX_VK_DLSSG")) opts.dlssg = ', "restart_init();",
            what="menu_init: RX_VK_DLSSG starts Streamline but does not turn the DLSS Frame Gen row on")
    if "v != &opts.dlssg || dlssg_available()" not in block(menu, "bool row_shown(int i) {"):
        raise SystemExit("row_shown: the DLSS Frame Gen row shows where it cannot run")
    if not re.search(r"int dlssg = 0;", read("vk_menu.h")):
        raise SystemExit("vk_menu.h: Options has no dlssg, off by default")

    # Streamline's loader in place of vulkan-1.dll's, asked first
    ordered(block(read("vk_main.cpp"), "bool load_global() {"), "dlssg_load()", 'LoadLibraryExA("vulkan-1.dll"',
            what="load_global: Streamline's loader is not asked before vulkan-1.dll")
    # the renderer's own frame generation and Reflex aside while it runs (vk_reflex.cpp's hooks: test_reflex_swapchain_lifetime)
    for name, fn in (("vk_framegen.cpp", "bool framegen_on() {"), ("vk_fsr3fi.cpp", "uint32_t frames_wanted() {"),
                     ("vk_reflex.cpp", "bool on() {")):
        if "!dlssg_active()" not in block(read(name), fn):
            raise SystemExit("%s: %s still runs with DLSS Frame Generation" % (name, fn.split("(")[0]))
    # the present: on or off for this one, after its submit and before vkQueuePresentKHR, which present_out makes (present
    # ahead, #1702: present_image ends in it, or present_commit later for a deferred one)
    replay = read("vk_replay.cpp")
    ordered(block(replay, "void present_image("), "vkQueueSubmit2(", "dlssg_before_present(src != VK_NULL_HANDLE)",
            "present_out(index, qk)", what="present_image: DLSS Frame Generation is not told about each present in its place")
    ordered(block(replay, "bool present_commit("), "dlssg_before_present(true)", "present_out(p.index, qk)",
            what="present_commit: DLSS Frame Generation is not told about a deferred present in its place")
    if "vkQueuePresentKHR(" not in block(replay, "static void present_out(uint32_t index, std::unique_lock<std::mutex>& qk) {"):
        raise SystemExit("present_out no longer presents: DLSS Frame Generation's hook may not be before vkQueuePresentKHR")
    # the frame chain's depth and motion, once its engine drew them, copyable while Streamline runs
    upscale = block(read("vk_temporal.cpp"), "bool temporal_upscale(")
    ordered(upscale, "engine.e->evaluate(cmd, f)", "dlssg_inputs(cmd, f, cam.projection, cam.current, cam.jitter, motion)",
            "s.last_frame = now;", what="temporal_upscale: DLSS Frame Generation's inputs are not the chain's frame")
    if upscale.count("| copied") != 1 or "iw, ih, copied)" not in upscale or "dlssg_active() ? VK_IMAGE_USAGE_TRANSFER_SRC_BIT" not in upscale:
        raise SystemExit("temporal_upscale: the depth and the motion cannot be copied by Streamline (TRANSFER_SRC)")
    if "std::memcpy(k.projection, c + 0x70 / 4" not in block(read("vk_temporal.cpp"), "void temporal_note_scene_draw("):
        raise SystemExit("temporal_note_scene_draw: the scene camera's projection (0x70) is not kept for DLSS Frame Generation")

    # Streamline's constants: no invalid motion value of 0, which marked every pixel that did not move as invalid
    if re.search(r"motionVectorsInvalidValue\s*=", block(sl, "void dlssg_inputs(")):
        raise SystemExit("dlssg_inputs: motionVectorsInvalidValue set (0 marked every still pixel invalid): Streamline's default has none")

    # NGX starts once, with the folders of its first start, which is Streamline's: the folders vk_dlss.cpp names for DLSS's
    # runtime go to Streamline after the plugins' own (0xbad00004 with nvngx_dlss.dll only in the game folder's ngx)
    load = block(sl, "PFN_vkGetInstanceProcAddr dlssg_load() {")
    folders = block(sl, "std::vector<std::wstring> dlss_runtime_folders(")
    ngx_init = block(read("vk_dlss.cpp"), "bool ngx_init() {")
    for theirs, ours in (('env_path(L"RX_VK_DLSS_DIR")', '_wgetenv(L"RX_VK_DLSS_DIR")'), ('game / L"ngx"', r'game + L"\\ngx"'),
                         ('l / L"Hookshot" / L"ngx"', r'L"\\Hookshot\\ngx"')):
        if theirs not in ngx_init or ours not in folders:
            raise SystemExit("dlss_runtime_folders: not the folders vk_dlss.cpp's ngx_init names for DLSS's runtime (%s)" % ours)
    ordered(load, "s.paths = {s.dir};", "dlss_runtime_folders(s.game_dir)", "pref.pathsToPlugins = s.path_list.data();",
            "s.init(pref", what="dlssg_load: Streamline is not told the folders of DLSS's runtime after the plugins' own")
    if "NVSDK_NGX_Result_FAIL_FeatureNotFound && dlssg_active()" not in ngx_init:
        raise SystemExit("vk_dlss.cpp ngx_init: 0xbad00004 with Streamline running is said as the GPU's fault, not NGX's folders")
    if "game_module_path(" in load:
        raise SystemExit("dlssg_load: the game folder through the ANSI code page (game_module_path), not wide")
    # a --prepare-shaders run has no window, so no close to shut Streamline down: it is not started there
    ordered(load, 'getenv("HOOKSHOT_PREPARE_ONLY")', "LoadLibraryW(", what="dlssg_load: Streamline starts in a --prepare-shaders run")
    if '"slShutdown"' not in load or "!s.shutdown" not in load:
        raise SystemExit("dlssg_load: Streamline starts without its slShutdown")

    # the exit: from mkwvk_close_asked (the window's close, Quit, Restart), last; every call after it does nothing
    ordered(block(read("vk_main.cpp"), "void mkwvk_close_asked(void) {"), "pipeline_cache_close();", "prepare_stop();",
            "dlssg_shutdown();", what="mkwvk_close_asked: Streamline is not shut down last before the process ends")
    display = (ROOT / "host" / "display.c").read_text(encoding="utf-8")
    ordered(display, "case WM_APP + 9:", "hos_relaunch_ask();", "case WM_CLOSE:", "rx_close_asked();",
            "hos_window_closed_exit();", what="display.c: Restart and the window's close do not ask the back end first")
    for fn in ("void dlssg_marker(DlssgMarker m) {", "void dlssg_sleep() {", "void dlssg_inputs(", "void dlssg_before_present("):
        if "!s.active || s.closing ||" not in block(sl, fn):
            raise SystemExit("vk_dlssg.cpp: %s still goes to Streamline once the exit began" % fn.split("(")[0])

    with tempfile.TemporaryDirectory(prefix="dlssg-") as tmp:
        cpp = Path(tmp) / "fixture.cpp"
        exe = Path(tmp) / "fixture"
        cpp.write_text(FIXTURE.replace("/* FRAME_LIMIT */", block(sl, "uint32_t frame_limit_us(bool on) {")), encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)

        # the exit, with vk_dlssg.cpp's own code and a stand-in Streamline (SHUTDOWN_FIXTURE)
        enums = "\n".join(re.search(r"enum %s \{[^}]*\};" % e, header).group(0) for e in ("DlssgWhy", "DlssgMarker"))
        cut = "\n".join(block(sl, m) for m in ("bool lock_within(std::mutex& m) {", "sl::FrameToken* token() {",
                                               "void dlssg_marker(DlssgMarker m) {", "void dlssg_sleep() {",
                                               "void dlssg_shutdown() {"))
        state = block(sl, "struct State {") + ";\n" + block(sl, "State& st() {")
        cpp = Path(tmp) / "shutdown.cpp"
        exe = Path(tmp) / "shutdown"
        cpp.write_text(SHUTDOWN_FIXTURE.replace("/* HEADER_ENUMS */", enums).replace("/* STATE */", state)
                       .replace("/* CUT */", cut), encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-pthread", str(cpp), "-o", str(exe)], check=True)
        for mode in ("order", "stuck_present", "stuck_sleep"):
            subprocess.run([str(exe), mode], check=True, timeout=60)


if __name__ == "__main__":
    main()
