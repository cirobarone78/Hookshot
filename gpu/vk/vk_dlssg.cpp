// (hookshot) NVIDIA DLSS Frame Generation through NVIDIA Streamline 2.14 (vk_dlssg.h), on Vulkan with manual hooking (the
// SDK's docs: ProgrammingGuideManualHooking.md, ProgrammingGuideDLSS_G.md). The Insert menu's DLSS Frame Gen row
// (opts.dlssg, dlss_frame_gen in hookshot_options.ini; RX_VK_DLSSG=0..3 over it) is read here before Vulkan is loaded:
// Streamline has to see the instance, the device and the swapchain made, so with the row set it gives the renderer
// sl.interposer.dll's vkGetInstanceProcAddr in place of vulkan-1.dll's (vk_main.cpp load_global). That one returns
// vulkan-1.dll's own functions except for the few Streamline intercepts (sl_hooks.h: the instance's and the device's
// creation, the swapchain's, acquire and present), so turning the row on takes a restart.
//
// Each frame, in the order the renderer goes through it:
//  - dlssg_sleep after a present: the next frame's token, Reflex's sleep (sl.reflex) and the PCL simulation-start marker;
//  - dlssg_inputs from the temporal upscaler's frame chain (vk_temporal.cpp, after its engine drew: NVIDIA DLSS or AMD FSR 4):
//    the chain's depth and motion tagged (copied by Streamline at once, eOnlyValidNow, into the chain's command buffer) and
//    the frame's constants from the scene camera, its jitter taken off. Without that chain (the game's own upscale, FSR 3.1)
//    there are no inputs and frame generation stays off;
//  - dlssg_marker for the rest of the frame (vk_reflex.cpp's hooks), and dlssg_before_present: frame generation on for a game
//    frame, off with the Insert menu open, for the window's own presents, and after a while without inputs.
// The renderer's own frame generation (vk_framegen.cpp, vk_fsr3fi.cpp) and its own Reflex (vk_reflex.cpp) are off while
// Streamline runs: DLSS Frame Generation works only with Streamline's Reflex. When the window closes (an exit or a Restart),
// dlssg_shutdown shuts Streamline down before the host ends the process, and every dlssg_* call does nothing after that.
//
// DLSS (vk_dlss.cpp) runs beside it: NGX starts once in a process, with the folders the first start named for its runtimes,
// and with Streamline that start is sl.common's, when the device is made. So the folders vk_dlss.cpp names for DLSS's
// runtime go to Streamline too (dlssg_load's pathsToPlugins, after the plugins' own folder): without them NGX did not look in
// the game folder's ngx\, and DLSS and DLAA failed with 0xbad00004 (feature not found) unless nvngx_dlss.dll was also beside
// hookshot.exe or NGX had a DLSS of its own downloads (C:\ProgramData\NVIDIA\NGX\models).
//
// Streamline's binaries are NVIDIA's, under NVIDIA's licenses (the SDK's license.txt, nvngx_dlss.license.txt and
// reflex.license.txt), never part of Hookshot: nx2/make_game.py copies them from HOOKSHOT_SL_SDK's bin/x64 beside
// hookshot.exe (sl.interposer.dll, sl.common.dll, sl.dlss_g.dll, sl.reflex.dll, sl.pcl.dll, nvngx_dlssg.dll,
// NvLowLatencyVk.dll), and sl.interposer.dll is loaded only with NVIDIA's valid signature. Streamline's own log goes to sl.log
// in the game folder, its warnings and errors to hookshot_log.txt too.
#ifdef HOOKSHOT_SL   // (sl_security.h's signature check needs Windows 8's WinTrust declarations: before the first windows.h)
#undef _WIN32_WINNT
#define _WIN32_WINNT 0x0A00
#endif
#include "vk_dlssg.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "dlss_math.h"
#include "vk_menu.h"
#include "vk_paths.h"
#include "vk_temporal.h"

#ifdef HOOKSHOT_SL
#include <windows.h>
#include "sl.h"
#include "sl_consts.h"
#include "sl_dlss_g.h"
#include "sl_pcl.h"
#include "sl_reflex.h"
#include "sl_security.h"
#endif

namespace mkwvk {

int display_refresh_mhz();   // (vk_main.cpp: the window's display's refresh, 0 when not known)
extern std::mutex present_image_mu;   // (vk_replay.cpp: one present at a time, held from its acquire to its present)

namespace {

/// The row's value as saved, read before the menu reads its file (menu_init comes after the instance): 0 off, 1 to 3 (2x to
/// 4x). RX_VK_DLSSG=<0..3> over it
int saved_dlssg() {
    if (const char* e = getenv("RX_VK_DLSSG")) return std::clamp(atoi(e), 0, 3);
    char exe[MAX_PATH];
    const DWORD n = game_module_path(exe, MAX_PATH);
    std::string ini(exe, n);
    ini = ini.substr(0, ini.find_last_of("\\/") + 1) + "hookshot_options.ini";
    FILE* f = fopen(ini.c_str(), "r");
    if (!f) return 0;
    int v = 0;
    char line[256];
    while (fgets(line, sizeof line, f))
        if (!strncmp(line, "dlss_frame_gen=", 15)) v = std::clamp(atoi(line + 15), 0, 3);
    fclose(f);
    return v;
}

}  // namespace

#ifdef HOOKSHOT_SL

namespace {

// ---- the game's matrices: row major, clip = M * position (column vectors) ----
void mul(const float* a, const float* b, float* out) {
    float r[16];
    for (int i = 0; i < 4; i++)
        for (int j = 0; j < 4; j++) {
            float s = 0;
            for (int k = 0; k < 4; k++) s += a[i * 4 + k] * b[k * 4 + j];
            r[i * 4 + j] = s;
        }
    std::memcpy(out, r, sizeof r);
}
/// The inverse (dlss_math::reprojection of the identity: identity * m^-1); false when singular or not finite
bool inverse(const float* m, float* out) {
    static const float id[16] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1};
    return dlss_math::reprojection(m, id, out);
}

struct State {
    std::mutex mu;
    bool tried = false, active = false;
    DlssgWhy why = DLSSG_LATER;
    HMODULE module = nullptr;
    PFun_slInit* init = nullptr;
    PFun_slSetTagForFrame* set_tag = nullptr;
    PFun_slSetConstants* set_constants = nullptr;
    PFun_slGetFeatureFunction* feature_function = nullptr;
    PFun_slGetNewFrameToken* new_token = nullptr;
    PFun_slDLSSGSetOptions* dlssg_set_options = nullptr;
    PFun_slDLSSGGetState* dlssg_get_state = nullptr;
    PFun_slReflexSetOptions* reflex_set_options = nullptr;
    PFun_slReflexSleep* reflex_sleep = nullptr;
    PFun_slPCLSetMarker* pcl_marker = nullptr;
    PFun_slShutdown* shutdown = nullptr;
    bool functions_tried = false, functions_ok = false;
    // (the exit, dlssg_shutdown: from closing on no call goes to Streamline; sleeping counts the Reflex sleeps under way, which
    // let the lock go, and slept is told as each ends)
    bool closing = false;
    int sleeping = 0;
    std::condition_variable slept;
    sl::FrameToken* token = nullptr;
    uint32_t inputs_frame = UINT32_MAX;   // (the token's index whose inputs were tagged)
    int reflex_mode = -1;
    sl::DLSSGMode mode = sl::DLSSGMode::eOff;
    uint32_t frames = 0;                  // (numFramesToGenerate as last set)
    uint32_t frames_max = 3;
    float last_vp[16]{};                  // (the frame before's view-projection, its jitter taken off)
    bool have_last = false;
    uint32_t limit_us = UINT32_MAX;       // (Reflex's frame limit as last set)
    int missing = 0;                      // (game frames in a row without inputs)
    // (the FPS counter: the frames DLSS-G presented, the game's own among them, and the made ones already counted)
    int64_t presented = 0, own = 0, noted = 0;
    int64_t rate_at = 0, rate_presented = 0, rate_own = 0;
    std::wstring dir, game_dir;
    std::vector<std::wstring> paths;      // (Preferences::pathsToPlugins: the plugins' folder, then DLSS's runtime's)
    std::vector<const wchar_t*> path_list;
};
// (never destroyed: the process ends through ExitProcess with Streamline's threads gone, and with dlssg_shutdown's locks
// held; a destructor then has nothing to do)
State& st() {
    static State& s = *new State;
    return s;
}

/// How long the exit waits for a Reflex sleep, and for a present, before it leaves Streamline as it is
constexpr std::chrono::milliseconds kExitWait{2000};

/// m locked within kExitWait (polled: the renderer's locks are plain mutexes); false when it was not
bool lock_within(std::mutex& m) {
    const auto until = std::chrono::steady_clock::now() + kExitWait;
    while (!m.try_lock()) {
        if (std::chrono::steady_clock::now() >= until) return false;
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    return true;
}

/// The game folder (vk_paths.h's rule, wide: Streamline takes wide paths): the exe's folder, or the one above it when that
/// is bin\ beside image.bin. exe_dir ends with its separator
std::wstring game_folder(const std::wstring& exe_dir) {
    std::wstring d = exe_dir.substr(0, exe_dir.empty() ? 0 : exe_dir.size() - 1);
    const size_t slash = d.find_last_of(L"\\/");
    if (slash != std::wstring::npos && !_wcsicmp(d.c_str() + slash + 1, L"bin") &&
        GetFileAttributesW((d.substr(0, slash + 1) + L"image.bin").c_str()) != INVALID_FILE_ATTRIBUTES)
        d.resize(slash);
    return d;
}

/// Where DLSS's runtime (nvngx_dlss.dll) is, as vk_dlss.cpp's ngx_init names the folders: RX_VK_DLSS_DIR when set, the game
/// folder's ngx, %LOCALAPPDATA%\Hookshot\ngx. sl.common starts NGX with the plugins' folder and every one of
/// Preferences::pathsToPlugins as where its runtimes are (Streamline's commonEntry.cpp), and NGX keeps the folders of its
/// first start: vk_dlss.cpp's own start comes later and its list is not used
std::vector<std::wstring> dlss_runtime_folders(const std::wstring& game) {
    std::vector<std::wstring> v;
    if (const wchar_t* e = _wgetenv(L"RX_VK_DLSS_DIR"); e && *e) v.push_back(e);
    v.push_back(game + L"\\ngx");
    if (const wchar_t* l = _wgetenv(L"LOCALAPPDATA"); l && *l) v.push_back(std::wstring(l) + L"\\Hookshot\\ngx");
    return v;
}

void sl_log(sl::LogType type, const char* msg) {
    std::string m(msg ? msg : "");
    while (!m.empty() && (m.back() == '\n' || m.back() == '\r')) m.pop_back();
    if (type == sl::LogType::eInfo) {   // (Streamline's own sl.log has those, but for one)
        // (the NVIDIA app's DLSS override: Streamline then loads NVIDIA's own plugins from its downloads, over the ones beside
        // hookshot.exe, whatever Preferences asks. The plugins it kept are sl.log's "is an OTA override" lines)
        static bool told;
        if (!told && m.find("OTA override DRS key is set") != std::string::npos) {
            told = true;
            logf("vk: Streamline: the NVIDIA app's DLSS override is on: Streamline uses NVIDIA's own plugins from "
                 "C:\\ProgramData\\NVIDIA\\NGX\\models where it has them, not the ones beside hookshot.exe (sl.log lists them)");
        }
        return;
    }
    logf("vk: Streamline %s: %s", type == sl::LogType::eError ? "error" : "warning", m.c_str());
}

template <typename F>
bool feature_function(sl::Feature feature, const char* name, F*& out) {
    void* p = nullptr;
    State& s = st();
    const sl::Result r = s.feature_function ? s.feature_function(feature, name, p) : sl::Result::eErrorNotInitialized;
    if (r != sl::Result::eOk || !p) {
        logf("vk: Streamline: no %s (%d)", name, (int)r);
        return false;
    }
    out = reinterpret_cast<F*>(p);
    return true;
}

/// The features' functions, once the device is made (Streamline loads its plugins then). With s.mu held
bool functions() {
    State& s = st();
    if (s.functions_tried) return s.functions_ok;
    s.functions_tried = true;
    s.functions_ok = feature_function(sl::kFeatureDLSS_G, "slDLSSGSetOptions", s.dlssg_set_options) &&
                     feature_function(sl::kFeatureDLSS_G, "slDLSSGGetState", s.dlssg_get_state) &&
                     feature_function(sl::kFeatureReflex, "slReflexSetOptions", s.reflex_set_options) &&
                     feature_function(sl::kFeatureReflex, "slReflexSleep", s.reflex_sleep) &&
                     feature_function(sl::kFeaturePCL, "slPCLSetMarker", s.pcl_marker);
    if (!s.functions_ok) {
        s.why = DLSSG_FAILED;
        logf("vk: Streamline: DLSS Frame Generation is not available (sl.log in the game folder says why)");
        return false;
    }
    sl::DLSSGState state{};
    if (SL_SUCCEEDED(r, s.dlssg_get_state(sl::ViewportHandle(0), state, nullptr)))
        s.frames_max = std::max(1u, state.numFramesToGenerateMax);
    logf("vk: Streamline: DLSS Frame Generation ready (up to %ux)", s.frames_max + 1);
    return true;
}

/// This frame's token (made at its first marker when no sleep came before it). With s.mu held
sl::FrameToken* token() {
    State& s = st();
    if (!s.token && s.new_token) s.new_token(s.token, nullptr);
    return s.token;
}

/// Reflex's frame limit while DLSS-G makes frames: the frames shown held below the display's refresh, as NVIDIA's driver caps
/// them with G-SYNC (refresh - refresh^2 / 3600: 116 at 120 Hz, 138 at 144, 224 at 240), so the output stays inside the
/// variable refresh range. Streamline's limit is on what is presented, the made frames with the game's (measured: 17241 us
/// gave 58 shown, 29 of the game's at 2x), so it is the output's interval, not the game's. 0 (none) when DLSS-G is off or the
/// refresh is not known; RX_VK_DLSSG_CAP=0: none
uint32_t frame_limit_us(bool on) {
    static const bool off = getenv("RX_VK_DLSSG_CAP") && atoi(getenv("RX_VK_DLSSG_CAP")) == 0;
    const double hz = display_refresh_mhz() / 1000.0;
    if (off || !on || hz < 30) return 0;
    const double out = hz - hz * hz / 3600.0;
    return (uint32_t)(1000000.0 / out + 0.5);
}

/// Streamline's Reflex as the NVIDIA Reflex row has it, at least on (DLSS-G needs it), with the frame limit above. With s.mu
/// held
void apply_reflex(bool on, uint32_t frames) {
    State& s = st();
    const int want = std::max(1, std::clamp(opts.reflex, 0, 2));
    const uint32_t limit = frame_limit_us(on);
    if ((want == s.reflex_mode && limit == s.limit_us) || !s.reflex_set_options) return;
    sl::ReflexOptions o{};
    o.mode = want == 2 ? sl::ReflexMode::eLowLatencyWithBoost : sl::ReflexMode::eLowLatency;
    o.frameLimitUs = limit;
    if (SL_SUCCEEDED(r, s.reflex_set_options(o))) {
        if (limit)
            logf("vk: Streamline Reflex: %s, the frames shown held to %.1f fps (%.1f of the game's with DLSS Frame Gen %ux)",
                 want == 2 ? "on + boost" : "on", 1e6 / limit, 1e6 / limit / (frames + 1), frames + 1);
        else logf("vk: Streamline Reflex: %s, no frame limit", want == 2 ? "on + boost" : "on");
    }
    s.reflex_mode = want, s.limit_us = limit;
}

}  // namespace

PFN_vkGetInstanceProcAddr dlssg_load() {
    State& s = st();
    std::lock_guard lk(s.mu);
    if (s.tried) return nullptr;
    s.tried = true;
    const int want = saved_dlssg();
    if (want <= 0) return nullptr;   // (s.why: DLSSG_LATER, the row turned on now starts it with the next launch)
    // (hookshot --prepare-shaders, a build's last step: no window, nothing to make frames for, and no close through
    // mkwvk_close_asked to shut Streamline down before the process ends)
    if (getenv("HOOKSHOT_PREPARE_ONLY")) return nullptr;
    std::wstring exe(32768, L'\0');
    const DWORD n = GetModuleFileNameW(nullptr, exe.data(), (DWORD)exe.size());
    if (!n || n >= exe.size()) {   // (no folder: never a relative path, which would load sl.interposer.dll from elsewhere)
        s.why = DLSSG_NO_FILES;
        logf("vk: DLSS Frame Gen is set but hookshot.exe's folder was not found: off");
        return nullptr;
    }
    exe.resize(n);
    s.dir = exe.substr(0, exe.find_last_of(L"\\/") + 1);   // (beside hookshot.exe: bin\ in a game folder with the launcher)
    s.game_dir = game_folder(s.dir);
    const std::wstring path = s.dir + L"sl.interposer.dll";
    if (GetFileAttributesW(path.c_str()) == INVALID_FILE_ATTRIBUTES) {
        s.why = DLSSG_NO_FILES;
        logf("vk: DLSS Frame Gen is set but sl.interposer.dll is not beside hookshot.exe: off");
        return nullptr;
    }
    if (!sl::security::verifyEmbeddedSignature(path.c_str())) {
        s.why = DLSSG_NOT_SIGNED;
        logf("vk: sl.interposer.dll has no valid NVIDIA signature: DLSS Frame Gen off");
        return nullptr;
    }
    s.why = DLSSG_FAILED;   // (from here on, until it started)
    s.module = LoadLibraryW(path.c_str());
    if (!s.module) {
        logf("vk: sl.interposer.dll did not load (%lu): DLSS Frame Gen off", GetLastError());
        return nullptr;
    }
    const auto get = [&](const char* name) { return (void*)GetProcAddress(s.module, name); };
    s.init = (PFun_slInit*)get("slInit");
    s.set_tag = (PFun_slSetTagForFrame*)get("slSetTagForFrame");
    s.set_constants = (PFun_slSetConstants*)get("slSetConstants");
    s.feature_function = (PFun_slGetFeatureFunction*)get("slGetFeatureFunction");
    s.new_token = (PFun_slGetNewFrameToken*)get("slGetNewFrameToken");
    s.shutdown = (PFun_slShutdown*)get("slShutdown");
    const auto gipa = (PFN_vkGetInstanceProcAddr)get("vkGetInstanceProcAddr");
    if (!s.init || !s.set_tag || !s.set_constants || !s.feature_function || !s.new_token || !s.shutdown || !gipa) {
        logf("vk: sl.interposer.dll lacks Streamline's functions: DLSS Frame Gen off");
        FreeLibrary(s.module), s.module = nullptr;
        return nullptr;
    }
    static const sl::Feature features[] = {sl::kFeatureDLSS_G, sl::kFeatureReflex, sl::kFeaturePCL};
    // (the plugins: the first of these folders that has any, beside hookshot.exe; none downloaded over the air is asked for,
    // though the NVIDIA app's DLSS override has Streamline take NVIDIA's own anyway (sl_log). The others are where DLSS's
    // runtime is: sl.common hands NGX every folder here, and NGX's first start is Streamline's (dlss_runtime_folders))
    s.paths = {s.dir};
    for (const std::wstring& f : dlss_runtime_folders(s.game_dir)) s.paths.push_back(f);
    s.path_list.clear();
    for (const std::wstring& p : s.paths) s.path_list.push_back(p.c_str());
    sl::Preferences pref{};
    pref.showConsole = false;
    pref.logLevel = sl::LogLevel::eDefault;
    pref.pathsToPlugins = s.path_list.data();
    pref.numPathsToPlugins = (uint32_t)s.path_list.size();
    pref.pathToLogsAndData = s.game_dir.c_str();
    pref.logMessageCallback = sl_log;
    pref.flags = sl::PreferenceFlags::eDisableCLStateTracking | sl::PreferenceFlags::eUseManualHooking |
                 sl::PreferenceFlags::eUseFrameBasedResourceTagging;
    pref.featuresToLoad = features;
    pref.numFeaturesToLoad = (uint32_t)(sizeof features / sizeof features[0]);
    pref.engine = sl::EngineType::eCustom;
    pref.engineVersion = "hookshot";
    pref.projectId = "7b2f5d0c-6a1e-4c39-9f84-3d5e2a1b0c96";   // (vk_dlss.cpp's NGX project id)
    pref.renderAPI = sl::RenderAPI::eVulkan;
    if (SL_FAILED(r, s.init(pref, sl::kSDKVersion))) {
        logf("vk: Streamline did not start (result %d): DLSS Frame Gen off", (int)r);
        return nullptr;   // (the module stays loaded: Streamline may have hooked something already)
    }
    s.active = true, s.why = DLSSG_OK;
    logf("vk: Streamline started for DLSS Frame Gen %dx (its loader in place of vulkan-1.dll)", want + 1);
    return gipa;
}

bool dlssg_active() { return st().active; }

bool dlssg_available() { return st().active || dev.props.vendorID == 0x10DE; }   // (NVIDIA's)

DlssgWhy dlssg_why() {
    State& s = st();
    std::lock_guard lk(s.mu);
    return s.why;
}

void dlssg_marker(DlssgMarker m) {
    State& s = st();
    std::lock_guard lk(s.mu);
    if (!s.active || s.closing || !functions()) return;
    sl::FrameToken* t = token();
    if (!t) return;
    static const sl::PCLMarker map[] = {sl::PCLMarker::eSimulationStart, sl::PCLMarker::eSimulationEnd,
                                        sl::PCLMarker::eRenderSubmitStart, sl::PCLMarker::eRenderSubmitEnd,
                                        sl::PCLMarker::ePresentStart, sl::PCLMarker::ePresentEnd};
    s.pcl_marker(map[m], *t);
}

void dlssg_sleep() {
    State& s = st();
    sl::FrameToken* t = nullptr;
    {
        std::lock_guard lk(s.mu);
        if (!s.active || s.closing || !functions()) return;
        apply_reflex(s.mode == sl::DLSSGMode::eOn, s.frames);
        if (s.new_token(s.token, nullptr) != sl::Result::eOk) return;
        t = s.token;
        s.sleeping++;   // (dlssg_shutdown waits for it: Streamline is not shut down under its sleep)
    }
    s.reflex_sleep(*t);   // (outside the lock: the sleep waits)
    std::lock_guard lk(s.mu);
    s.sleeping--;
    if (!s.closing && s.token == t) s.pcl_marker(sl::PCLMarker::eSimulationStart, *t);
    s.slept.notify_all();
}

void dlssg_shutdown() {
    State& s = st();
    {
        std::unique_lock lk(s.mu);
        if (!s.active || s.closing) return;   // (once; nothing without Streamline)
        s.closing = true;                     // (no dlssg_* call goes to Streamline from here on)
        // (a Reflex sleep under way let the lock go: Streamline is not shut down under it. The present lock is not taken
        // before it ends: the sleeping thread presents next)
        if (!s.slept.wait_for(lk, kExitWait, [&] { return s.sleeping == 0; })) {
            logf("vk: Streamline: its Reflex sleep did not end within 2 s: left running for the exit");
            return;
        }
    }
    // (then no present: the one under way ends first, and none starts again. A present stuck for 2 s, in the driver or in
    // Streamline's hooks, leaves Streamline as it is rather than shut it down under that thread or hang the exit)
    if (!lock_within(present_image_mu)) {
        logf("vk: Streamline: a present did not end within 2 s: left running for the exit");
        return;
    }
    if (!lock_within(dev.present_mu)) {   // (the queue's lock: submits, and device_wait_idle_locked's)
        present_image_mu.unlock();
        logf("vk: Streamline: the queue stayed busy for 2 s: left running for the exit");
        return;
    }
    // (the frame's work done on every queue, Streamline's own copies of the tagged depth and motion among it, before DLSS-G
    // goes off and Streamline lets its resources go. No device: closed before it was made)
    if (dev.device) device_wait_idle_locked();
    std::lock_guard lk(s.mu);
    if (s.dlssg_set_options && s.mode != sl::DLSSGMode::eOff) {
        sl::DLSSGOptions o{};
        o.mode = sl::DLSSGMode::eOff;
        o.numFramesToGenerate = std::max(s.frames, 1u);
        o.flags = sl::DLSSGFlags::eRetainResourcesWhenOff;   // (as the Insert menu turns it off: slShutdown lets them go)
        if (SL_FAILED(r, s.dlssg_set_options(sl::ViewportHandle(0), o)))
            logf("vk: Streamline: DLSS Frame Gen not turned off for the exit (%d)", (int)r);
        s.mode = sl::DLSSGMode::eOff;
    }
    const sl::Result r = s.shutdown();
    logf("vk: Streamline shut down for the exit (result %d)", (int)r);
    // (present_image_mu and dev.present_mu stay held: the process ends next (host/hos_relaunch.c hos_window_closed_exit), and
    // a present or a submit after this would go through Streamline's hooks, or use what it let go)
}

void dlssg_inputs(VkCommandBuffer cmd, const TemporalFrame& f, const float projection[16], const float view_projection[16],
                  const float clip_jitter[2], bool motion) {
    State& s = st();
    std::lock_guard lk(s.mu);
    if (!s.active || s.closing || !functions()) return;
    if (opts.dlssg <= 0) return void(s.have_last = false);   // (turned off: the next inputs start a new history)
    sl::FrameToken* t = token();
    if (!t || (uint32_t)*t == s.inputs_frame) return;   // (once a frame: constants twice in a frame confuse DLSS-G)
    const uint32_t rw = f.render_w, rh = f.render_h;
    if (!f.depth.image || !f.motion.image || !rw || !rh) return;
    float p[16], vp[16];
    std::memcpy(p, projection, sizeof p), std::memcpy(vp, view_projection, sizeof vp);
    dlss_math::unjitter(p, clip_jitter), dlss_math::unjitter(vp, clip_jitter);
    float ip[16], view[16], cam[16];
    if (!inverse(p, ip)) return;
    mul(ip, vp, view);   // (view = P^-1 * VP)
    if (!inverse(view, cam)) return;
    // (this clip to the frame before's, VP_prev * VP^-1, and back; none across a new history)
    static const float id[16] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1};
    const bool motion_ok = s.have_last && motion;
    float to_prev[16], from_prev[16];
    if (!motion_ok || !dlss_math::reprojection(vp, s.last_vp, to_prev)) std::memcpy(to_prev, id, sizeof id);
    if (!inverse(to_prev, from_prev)) return;
    std::memcpy(s.last_vp, vp, sizeof vp), s.have_last = true;
    // (Streamline's matrices are row major for row vectors, position * M: the game's, transposed)
    const auto put = [](sl::float4x4& out, const float* m) {
        for (int r = 0; r < 4; r++) out.row[r] = sl::float4(m[0 * 4 + r], m[1 * 4 + r], m[2 * 4 + r], m[3 * 4 + r]);
    };
    sl::Constants c{};
    put(c.cameraViewToClip, p);
    put(c.clipToCameraView, ip);
    put(c.clipToLensClip, id);
    put(c.clipToPrevClip, to_prev);
    put(c.prevClipToClip, from_prev);
    c.jitterOffset = sl::float2(f.jitter[0], f.jitter[1]);
    c.mvecScale = sl::float2(1.0f / (float)rw, 1.0f / (float)rh);   // (render pixels to the [-1, 1] Streamline takes)
    c.cameraPinholeOffset = sl::float2(0.0f, 0.0f);
    // (the camera's frame in the world: its view's inverse; OpenGL's, looking down -z)
    c.cameraPos = sl::float3(cam[3], cam[7], cam[11]);
    c.cameraRight = sl::float3(cam[0], cam[4], cam[8]);
    c.cameraUp = sl::float3(cam[1], cam[5], cam[9]);
    c.cameraFwd = sl::float3(-cam[2], -cam[6], -cam[10]);
    c.cameraNear = f.near_z > 0 ? f.near_z : 0.1f;   // (the chain's, from the scene's projection)
    c.cameraFar = f.far_z > c.cameraNear ? f.far_z : 100000.0f;
    c.cameraFOV = f.fov_y > 0 ? f.fov_y : 1.0f;
    c.cameraAspectRatio = p[0] != 0 ? std::fabs(p[5] / p[0]) : 16.0f / 9.0f;
    // (motionVectorsInvalidValue left at Streamline's INVALID_FLOAT, no invalid value: the chain's motion has none, and 0
    // marked every pixel that did not move, all of a still scene under a still camera, as invalid)
    c.depthInverted = sl::Boolean::eFalse;
    c.cameraMotionIncluded = sl::Boolean::eTrue;
    c.motionVectors3D = sl::Boolean::eFalse;
    c.reset = motion_ok ? sl::Boolean::eFalse : sl::Boolean::eTrue;
    c.orthographicProjection = sl::Boolean::eFalse;
    c.motionVectorsDilated = sl::Boolean::eFalse;
    c.motionVectorsJittered = sl::Boolean::eFalse;
    const sl::ViewportHandle viewport(0);
    if (SL_FAILED(r, s.set_constants(c, *t, viewport))) {
        static bool told;
        if (!told) told = true, logf("vk: Streamline: its constants were refused (%d)", (int)r);
        return;
    }
    // (the chain's images, as large as its engine asked: the frame's part at their top left, the extent)
    sl::Resource d(sl::ResourceType::eTex2d, (void*)f.depth.image, nullptr, (void*)f.depth.view, VK_IMAGE_LAYOUT_GENERAL);
    d.width = f.depth.width, d.height = f.depth.height, d.nativeFormat = f.depth.format, d.mipLevels = 1, d.arrayLayers = 1;
    d.flags = 0;
    d.usage = VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT;
    sl::Resource mv(sl::ResourceType::eTex2d, (void*)f.motion.image, nullptr, (void*)f.motion.view, VK_IMAGE_LAYOUT_GENERAL);
    mv.width = f.motion.width, mv.height = f.motion.height, mv.nativeFormat = f.motion.format, mv.mipLevels = 1;
    mv.arrayLayers = 1, mv.flags = 0;
    mv.usage = VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT |
               VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;
    const sl::Extent extent{0, 0, rw, rh};
    const sl::ResourceLifecycle now = sl::ResourceLifecycle::eOnlyValidNow;
    const sl::ResourceTag tags[] = {sl::ResourceTag(&d, sl::kBufferTypeDepth, now, &extent),
                                    sl::ResourceTag(&mv, sl::kBufferTypeMotionVectors, now, &extent)};
    if (SL_FAILED(r, s.set_tag(*t, viewport, tags, 2, reinterpret_cast<sl::CommandBuffer*>(cmd)))) {
        static bool told;
        if (!told) told = true, logf("vk: Streamline: its inputs were refused (%d)", (int)r);
        return;
    }
    s.inputs_frame = (uint32_t)*t;
    static bool told;
    if (!told) {
        told = true;
        logf("vk: DLSS Frame Gen: inputs %ux%u (near %.3f far %.1f fov %.1f deg)", rw, rh, c.cameraNear, c.cameraFar,
             c.cameraFOV * 57.29578f);
    }
}

void dlssg_before_present(bool game_frame) {
    State& s = st();
    std::lock_guard lk(s.mu);
    if (!s.active || s.closing || !functions()) return;
    sl::FrameToken* t = token();
    const bool inputs = t && (uint32_t)*t == s.inputs_frame;
    // (a frame now and then without inputs (a loading hitch, the game's upscale left out once) keeps it on: each switch off and
    // on again stopped the interpolation for seconds and changed the present's sync. Off at once only for the Insert menu and
    // the window's own presents; after 60 game frames without inputs too)
    if (inputs) s.missing = 0;
    else if (game_frame) s.missing++;
    const char* why_off = opts.dlssg <= 0 ? "the row is off" : menu_is_open() ? "the Insert menu is open"
                          : !game_frame ? "no game frame" : s.missing > 60 ? "no inputs for 60 frames" : nullptr;
    const bool on = !why_off && (inputs || s.mode == sl::DLSSGMode::eOn);
    const uint32_t frames = std::clamp((uint32_t)std::max(opts.dlssg, 1), 1u, s.frames_max);
    const sl::DLSSGMode mode = on ? sl::DLSSGMode::eOn : sl::DLSSGMode::eOff;
    if (s.mode == sl::DLSSGMode::eOn) {
        // (the FPS counter counts the renderer's own presents, one a game frame: the frames DLSS-G presented besides them are
        // added, from its own count of what it presented since the last ask)
        sl::DLSSGState state{};
        if (SL_SUCCEEDED(r, s.dlssg_get_state(sl::ViewportHandle(0), state, nullptr))) {
            s.presented += state.numFramesActuallyPresented, s.own++;
            const int64_t extra = s.presented - s.own - s.noted;
            if (extra > 0) menu_note_frame(false, (int)extra), s.noted += extra;
            const int64_t now = (int64_t)GetTickCount64();
            if (!s.rate_at) {
                s.rate_at = now, s.rate_presented = s.presented, s.rate_own = s.own;
            } else if (now - s.rate_at >= 10000) {   // (every 10 s in the log: what reached the display, and the game's own)
                const double secs = (now - s.rate_at) / 1000.0;
                logf("vk: DLSS Frame Gen: %.1f fps shown, %.1f of the game's (status %#x)",
                     (s.presented - s.rate_presented) / secs, (s.own - s.rate_own) / secs, (unsigned)state.status);
                s.rate_at = now, s.rate_presented = s.presented, s.rate_own = s.own;
            }
        }
    }
    if (mode == s.mode && (!on || frames == s.frames)) return;
    sl::DLSSGOptions o{};
    o.mode = mode;
    o.numFramesToGenerate = frames;
    o.flags = sl::DLSSGFlags::eRetainResourcesWhenOff;
    if (SL_FAILED(r, s.dlssg_set_options(sl::ViewportHandle(0), o))) {
        logf("vk: Streamline: DLSS Frame Gen options refused (%d)", (int)r);
        return;
    }
    if (on) logf("vk: DLSS Frame Gen: on, %ux", frames + 1);
    else logf("vk: DLSS Frame Gen: off (%s)", why_off ? why_off : "no inputs yet");
    s.mode = mode, s.frames = frames;
}

#else  // (no Streamline SDK in this build: DLSS Frame Gen is not there)

PFN_vkGetInstanceProcAddr dlssg_load() {
    if (saved_dlssg() > 0) logf("vk: DLSS Frame Gen is set, but this build has no Streamline: off");
    return nullptr;
}
bool dlssg_active() { return false; }
bool dlssg_available() { return false; }
DlssgWhy dlssg_why() { return DLSSG_NOT_BUILT; }
void dlssg_marker(DlssgMarker) {}
void dlssg_sleep() {}
void dlssg_inputs(VkCommandBuffer, const TemporalFrame&, const float*, const float*, const float*, bool) {}
void dlssg_before_present(bool) {}
void dlssg_shutdown() {}

#endif

}  // namespace mkwvk
