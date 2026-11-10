// (hookshot) AMD FSR upscaling, FSR 3.1 and FSR 4, in place of OoT's gameplay upscale network (vk_ffx.h).
//
// vk_dlss.cpp makes the inputs as it does for DLSS (the scene's colour as the network samples it, its depth, the camera's and
// the actors' motion, the camera's jitter) and calls upscale() where DLSS would evaluate; its output goes the same way.
// This file is AMD's side: its signed runtime for Vulkan from the FSR SDK 2.4 (AMD publishes it for Windows), loaded from
// RX_VK_FFX_DIR, the game folder's ffx folder or %LOCALAPPDATA%\Hookshot\ffx, through its five C functions
// (ffxCreateContext and the others), with AMD's MIT headers in gpu/third_party/ffx.
//
// The FSR model row (opts.fsr_model) picks the version and, for FSR 4, the model. AMD's upscaler library carries four FSR 4
// models, each a class: ffxProvider_FSR4 (FP8, RDNA 4), _Int8 (RDNA 3), _Int8_Navi2 (RDNA 2) and ffxProvider_FSR4Lite_Int8
// (APUs and handhelds). It asks each IsSupported(device) in that order and runs the first that says yes; where none does,
// FSR 4 is not offered and FSR 3.1 runs. With a model chosen, exactly that one says yes here, whatever AMD's own check says:
// the classes' vtables are found by their MSVC RTTI names in the loaded library and slot 2, IsSupported, points at
// model_supported below. The file on disk is not changed. With Auto and FSR 3.1 AMD's own answer is passed through.
// (The model classes and their order are as OptiScaler, github.com/optiscaler/OptiScaler, documents them; no code of it here.)
//
// RX_VK_FSR_MODEL=<0..5> over the row for one run. RX_VK_FFX_LOG=1: AMD's runtime messages in our log.
#include "vk_ffx.h"

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <mutex>
#include <string>
#include <vector>

#include "vk_menu.h"

#ifdef HOOKSHOT_FFX
#include <windows.h>

#include "../third_party/ffx/api/include/ffx_api.h"
#include "../third_party/ffx/api/include/vk/ffx_api_vk.h"
#include "../third_party/ffx/upscalers/include/ffx_upscale.h"
#endif
#include "vk_work.h"   // (after the others: counts the commands that do GPU work, for full_barrier)

namespace mkwvk::ffx {

namespace {
int env_int(const char* name) {   // (-1: unset)
    const char* e = getenv(name);
    return e && *e ? atoi(e) : -1;
}
}  // namespace

int wanted_model() {
    static const int env = env_int("RX_VK_FSR_MODEL");
    if (env >= 0) return std::clamp(env, 0, kModels - 1);
    switch (opts.fsr_version) {
    case 1: {   // (FSR 4: AMD's choice of model, or the one chosen)
        const int m = std::clamp(opts.fsr_model, 0, kFsr4Models - 1);
        return m == 0 ? MODEL_FSR4_AUTO : MODEL_FP8 + (m - 1);
    }
    case 2: return MODEL_FSR3;
    default: return MODEL_AUTO;
    }
}

#ifdef HOOKSHOT_FFX

namespace {

namespace fs = std::filesystem;

// ---- the FSR 4 model choice: AMD's four model classes, their IsSupported pointed at model_supported ----

struct ModelClass {
    const char* label;
    const char* rtti;               // (the MSVC decorated type name)
    void** vtable = nullptr;        // (null until found)
    bool (*amd)(void*, void*) = nullptr;   // (AMD's own check)
    std::atomic<int> said{-1};      // (the last decision logged: 0 no, 1 yes)
};
ModelClass g_classes[4] = {
    {"FP8", ".?AVffxProvider_FSR4@@"},
    {"INT8", ".?AVffxProvider_FSR4_Int8@@"},
    {"INT8 RDNA2", ".?AVffxProvider_FSR4_Int8_Navi2@@"},
    {"INT8 Lite", ".?AVffxProvider_FSR4Lite_Int8@@"},
};
std::atomic<int> g_model{MODEL_AUTO};   // (the model the next query and create are for: model_supported reads it)

/// Every FSR 4 model's IsSupported lands here (AMD's library calls it on its threads too): with Auto or FSR 3.1, AMD's answer;
/// with a model chosen, yes for that one and no for the others
bool model_supported(void* self, void* device) {
    void** vt = *static_cast<void***>(self);
    for (int i = 0; i < 4; i++) {
        ModelClass& c = g_classes[i];
        if (c.vtable != vt) continue;
        const bool amd = c.amd ? c.amd(self, device) : false;
        const int want = g_model.load(std::memory_order_relaxed);
        const bool forced = want >= MODEL_FP8 && want <= MODEL_LITE;
        const bool yes = forced ? want - MODEL_FP8 == i : amd;
        if (c.said.exchange(yes ? 1 : 0) != (yes ? 1 : 0))
            logf("vk: AMD FSR: FSR 4 model %s: AMD's check says %s; %s", c.label, amd ? "yes" : "no",
                 forced ? (yes ? (amd ? "chosen (FSR model row)" : "CHOSEN ANYWAY (FSR model row): it runs on this "
                                                    "GPU by the row's choice")
                                          : "not chosen (FSR model row)")
                                   : "AMD's own choice");
        return yes;
    }
    return false;
}

bool section(HMODULE m, const char* name, uint8_t** start, size_t* size) {
    uint8_t* base = reinterpret_cast<uint8_t*>(m);
    auto* nt = reinterpret_cast<IMAGE_NT_HEADERS*>(base + reinterpret_cast<IMAGE_DOS_HEADER*>(base)->e_lfanew);
    IMAGE_SECTION_HEADER* sec = IMAGE_FIRST_SECTION(nt);
    for (unsigned i = 0; i < nt->FileHeader.NumberOfSections; i++, sec++)
        if (!strncmp(reinterpret_cast<const char*>(sec->Name), name, 8)) {
            *start = base + sec->VirtualAddress, *size = sec->Misc.VirtualSize;
            return true;
        }
    return false;
}

/// A class's vtable by its RTTI name (x64 MSVC): the type descriptor holds the name 16 bytes in; a complete object locator
/// (signature 1, offset 0) names that descriptor and itself by RVA; the vtable starts one pointer after a pointer to it
void** class_vtable(HMODULE m, const char* rtti) {
    uint8_t* base = reinterpret_cast<uint8_t*>(m);
    uint8_t *data, *rdata;
    size_t data_size, rdata_size;
    if (!section(m, ".data", &data, &data_size) || !section(m, ".rdata", &rdata, &rdata_size)) return nullptr;
    const size_t len = strlen(rtti) + 1;   // (with the terminator: a longer name that starts the same never matches)
    uint8_t* name = nullptr;
    for (size_t i = 16; i + len <= data_size && !name; i++)
        if (!memcmp(data + i, rtti, len)) name = data + i;
    if (!name) return nullptr;
    const uint32_t td = (uint32_t)((name - 16) - base);
    for (size_t i = 0; i + 24 <= rdata_size; i += 4) {
        const uint32_t* col = reinterpret_cast<const uint32_t*>(rdata + i);
        if (col[0] != 1 || col[1] != 0 || col[3] != td) continue;
        if (col[5] != (uint32_t)(reinterpret_cast<const uint8_t*>(col) - base)) continue;
        const uint64_t at = reinterpret_cast<uint64_t>(col);
        for (size_t j = 0; j + 16 <= rdata_size; j += 8)
            if (*reinterpret_cast<const uint64_t*>(rdata + j) == at) return reinterpret_cast<void**>(rdata + j + 8);
    }
    return nullptr;
}

/// AMD's model classes in its upscaler library, hooked (once, as the library is loaded)
std::string hook_models(HMODULE m) {
    std::string found;
    for (ModelClass& c : g_classes) {
        c.vtable = class_vtable(m, c.rtti);
        if (!c.vtable) continue;
        DWORD old = 0;
        if (!VirtualProtect(&c.vtable[2], sizeof(void*), PAGE_READWRITE, &old)) {
            c.vtable = nullptr;
            continue;
        }
        c.amd = reinterpret_cast<bool (*)(void*, void*)>(c.vtable[2]);
        c.vtable[2] = reinterpret_cast<void*>(&model_supported);
        VirtualProtect(&c.vtable[2], sizeof(void*), old, &old);
        found += (found.empty() ? "" : ", ") + std::string(c.label);
    }
    return found;
}

// ---- AMD's runtime ----

constexpr const wchar_t* kLoader = L"amd_fidelityfx_loader_vk.dll";
constexpr const wchar_t* kUpscaler = L"amd_fidelityfx_upscaler_vk.dll";

struct State {
    std::mutex mu;
    bool tried = false;
    std::atomic<int> why{-1};   // (-1 not known yet, else a Why)
    HMODULE loader = nullptr, upscaler = nullptr;
    PfnFfxCreateContext create = nullptr;
    PfnFfxDestroyContext destroy = nullptr;
    PfnFfxConfigure configure = nullptr;
    PfnFfxQuery query = nullptr;
    PfnFfxDispatch dispatch = nullptr;
    VkDeviceContext device{};
    ffxContext ctx = nullptr;
    uint32_t max_w = 0, max_h = 0, out_w = 0, out_h = 0;
    int ctx_model = -1;
    bool ctx_failed = false;   // (the last try for these sizes and model failed)
    uint64_t made = 0;
    std::string version, model;
    uint64_t gpu_bytes = 0;
    const char* reason = nullptr;
    int reason_repeats = 0;
};
State& st() {
    static State s;
    return s;
}

bool fail(const char* why) {
    State& s = st();
    if (why != s.reason || ++s.reason_repeats % 600 == 0) logf("vk: AMD FSR: the game's upscale runs (%s)", why);
    if (why != s.reason) s.reason = why, s.reason_repeats = 0;
    return false;
}

std::string utf8(const fs::path& p) {
    const std::wstring& w = p.native();
    const int n = WideCharToMultiByte(CP_UTF8, 0, w.data(), (int)w.size(), nullptr, 0, nullptr, nullptr);
    std::string s(n > 0 ? n : 0, '\0');
    if (n > 0) WideCharToMultiByte(CP_UTF8, 0, w.data(), (int)w.size(), s.data(), n, nullptr, nullptr);
    return s;
}

/// The game folder (bin\hookshot.exe beside image.bin is the folder above bin), as vk_dlss.cpp finds it
fs::path game_dir() {
    std::wstring exe(32768, L'\0');
    const DWORD n = GetModuleFileNameW(nullptr, exe.data(), (DWORD)exe.size());
    if (!n || n >= exe.size()) return {};
    exe.resize(n);
    fs::path dir = fs::path(exe).parent_path();
    if (!_wcsicmp(dir.filename().c_str(), L"bin") &&
        GetFileAttributesW((dir.parent_path() / L"image.bin").c_str()) != INVALID_FILE_ATTRIBUTES)
        dir = dir.parent_path();
    return dir;
}

void message(uint32_t type, const wchar_t* text) {
    std::wstring w(text ? text : L"");
    while (!w.empty() && (w.back() == L'\n' || w.back() == L'\r')) w.pop_back();
    logf("vk: AMD FSR runtime (%u): %s", type, utf8(fs::path(w)).c_str());
}

/// AMD's runtime, once: false when it is not there or does not load (the reason logged, why() set)
bool load() {
    State& s = st();
    if (s.tried) return s.create != nullptr;
    s.tried = true;
    std::vector<fs::path> dirs;
    if (const wchar_t* e = _wgetenv(L"RX_VK_FFX_DIR"); e && *e) dirs.push_back(e);
    dirs.push_back(game_dir() / L"ffx");
    if (const wchar_t* l = _wgetenv(L"LOCALAPPDATA"); l && *l) dirs.push_back(fs::path(l) / L"Hookshot" / L"ffx");
    std::string where;
    for (const auto& d : dirs) where += (where.empty() ? "" : ", ") + utf8(d);
    std::error_code ec;
    fs::path dir;
    for (const auto& d : dirs)
        if (fs::is_regular_file(d / kLoader, ec) && fs::is_regular_file(d / kUpscaler, ec)) {
            dir = d;
            break;
        }
    if (dir.empty()) {
        logf("vk: AMD FSR: not available: no amd_fidelityfx_loader_vk.dll and amd_fidelityfx_upscaler_vk.dll in %s "
             "(scripts/ffx_sdk.py fetches them)", where.c_str());
        s.why = NO_RUNTIME;
        return false;
    }
    // (the upscaler library first, by its full path: its model classes are hooked before the loader asks them anything, and
    // the loader's own load of it by name finds this module)
    s.upscaler = LoadLibraryExW((dir / kUpscaler).c_str(), nullptr, LOAD_WITH_ALTERED_SEARCH_PATH);
    s.loader = s.upscaler ? LoadLibraryExW((dir / kLoader).c_str(), nullptr, LOAD_WITH_ALTERED_SEARCH_PATH) : nullptr;
    if (!s.upscaler || !s.loader) {
        logf("vk: AMD FSR: not available: AMD's runtime in %s did not load (error %lu)", utf8(dir).c_str(), GetLastError());
        s.why = NOT_LOADED;
        return false;
    }
    const std::string models = hook_models(s.upscaler);
    s.create = (PfnFfxCreateContext)GetProcAddress(s.loader, "ffxCreateContext");
    s.destroy = (PfnFfxDestroyContext)GetProcAddress(s.loader, "ffxDestroyContext");
    s.configure = (PfnFfxConfigure)GetProcAddress(s.loader, "ffxConfigure");
    s.query = (PfnFfxQuery)GetProcAddress(s.loader, "ffxQuery");
    s.dispatch = (PfnFfxDispatch)GetProcAddress(s.loader, "ffxDispatch");
    if (!s.create || !s.destroy || !s.configure || !s.query || !s.dispatch) {
        logf("vk: AMD FSR: not available: AMD's loader in %s lacks its functions", utf8(dir).c_str());
        s.create = nullptr;
        s.why = NOT_LOADED;
        return false;
    }
    s.device = {dev.device, dev.physical, vkGetDeviceProcAddr};
    if (env_int("RX_VK_FFX_LOG") > 0) {
        ffxConfigureDescGlobalDebug d{};
        d.header.type = FFX_API_CONFIGURE_DESC_TYPE_GLOBALDEBUG;
        d.fpMessage = message, d.debugLevel = FFX_API_CONFIGURE_GLOBALDEBUG_LEVEL_VERBOSE;
        s.configure(nullptr, &d.header);
    }
    logf("vk: AMD FSR: AMD's runtime loaded from %s (FSR 4 models in it: %s)", utf8(dir).c_str(),
         models.empty() ? "none found" : models.c_str());
    return true;
}

struct Version {
    uint64_t id = 0;
    std::string name;
};
/// The upscaler versions AMD's runtime offers on this device, newest first, for the model g_model asks for
std::vector<Version> versions() {
    State& s = st();
    std::vector<Version> out;
    uint64_t count = 0;
    ffxQueryDescGetVersions q{};
    q.header.type = FFX_API_QUERY_DESC_TYPE_GET_VERSIONS;
    q.createDescType = FFX_API_CREATE_CONTEXT_DESC_TYPE_UPSCALE;
    q.device = &s.device;
    q.outputCount = &count;
    if (s.query(nullptr, &q.header) != FFX_API_RETURN_OK || !count) return out;
    std::vector<uint64_t> ids(count);
    std::vector<const char*> names(count);
    q.versionIds = ids.data(), q.versionNames = names.data();
    if (s.query(nullptr, &q.header) != FFX_API_RETURN_OK) return out;
    for (uint64_t i = 0; i < count; i++) out.push_back({ids[i], names[i] ? names[i] : "?"});
    return out;
}

std::string listed(const std::vector<Version>& v) {
    std::string t;
    for (const auto& x : v) t += (t.empty() ? "" : ", ") + x.name;
    return t.empty() ? "none" : t;
}

FfxApiResource resource(const Image& im, bool write) {
    VkImageCreateInfo ci{VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO};
    ci.imageType = VK_IMAGE_TYPE_2D, ci.format = im.format, ci.extent = {im.width, im.height, 1};
    ci.mipLevels = 1, ci.arrayLayers = 1, ci.usage = VK_IMAGE_USAGE_SAMPLED_BIT | (write ? VK_IMAGE_USAGE_STORAGE_BIT : 0);
    return ffxApiGetResourceVK((void*)im.image, ffxApiGetImageResourceDescriptionVK(im.image, ci, 0),
                               FFX_API_RESOURCE_STATE_UNORDERED_ACCESS);   // (GENERAL: AMD's backend returns it so)
}

const char* model_label(int model) {
    static const char* const t[kModels] = {"AMD's choice", "FSR 3.1", "FSR 4 FP8", "FSR 4 INT8", "FSR 4 INT8 RDNA2",
                                           "FSR 4 INT8 Lite", "FSR 4, AMD's choice of model"};
    return t[std::clamp(model, 0, kModels - 1)];
}

/// The context for these sizes and the model asked for, made when either changes (an old one goes to later)
bool make_context(const Frame& f, const Later& later) {
    State& s = st();
    const int model = wanted_model();
    const bool same = s.out_w == f.out_w && s.out_h == f.out_h && f.max_w <= s.max_w && f.max_h <= s.max_h && s.ctx_model == model;
    if (same && s.ctx) return true;
    if (same && s.ctx_failed) return false;   // (not tried again each frame: a change of size or model tries again)
    s.ctx_failed = false;
    if (s.ctx) {
        ffxContext old = s.ctx;
        const PfnFfxDestroyContext destroy = s.destroy;
        later([old, destroy]() mutable { destroy(&old, nullptr); });
        s.ctx = nullptr;
    }
    // (FSR 4 by AMD's choice of model: AMD's own answers first; where it offers no FSR 4 (a GPU it does not list), INT8 Lite)
    g_model = model == MODEL_FSR4_AUTO ? MODEL_AUTO : model;
    std::vector<Version> v = versions();
    if (model == MODEL_FSR4_AUTO &&
        std::none_of(v.begin(), v.end(), [](const Version& x) { return x.name.rfind("4.", 0) == 0; })) {
        logf("vk: AMD FSR: AMD offers no FSR 4 model on this GPU (it offers: %s): INT8 Lite", listed(v).c_str());
        g_model = MODEL_LITE;
        v = versions();
    }
    // (the version: AMD's newest for Auto; the 3.x one for FSR 3.1; the 4.x one for a model, which says yes now)
    const Version* pick = nullptr;
    for (const auto& x : v) {
        const bool four = x.name.rfind("4.", 0) == 0, three = x.name.rfind("3.", 0) == 0;
        if (model == MODEL_AUTO || (model == MODEL_FSR3 && three) || (model >= MODEL_FP8 && four)) {
            pick = &x;
            break;
        }
    }
    if (!pick) {
        logf("vk: AMD FSR: the FSR model row asks for %s, which AMD's runtime does not offer here (it offers: %s)",
             model_label(model), listed(v).c_str());
        s.ctx_model = model, s.out_w = f.out_w, s.out_h = f.out_h, s.max_w = f.max_w, s.max_h = f.max_h, s.ctx_failed = true;
        return fail("the FSR version asked for is not offered");
    }
    ffxCreateBackendVKDesc be{};
    be.header.type = FFX_API_CREATE_CONTEXT_DESC_TYPE_BACKEND_VK;
    be.deviceContext = s.device;
    ffxOverrideVersion ov{};
    ov.header.type = FFX_API_DESC_TYPE_OVERRIDE_VERSION;
    ov.versionId = pick->id;
    be.header.pNext = &ov.header;
    ffxCreateContextDescUpscale cd{};
    cd.header.type = FFX_API_CREATE_CONTEXT_DESC_TYPE_UPSCALE;
    cd.header.pNext = &be.header;
    // (the colour is the network's input: the square root of the tonemapped scene, so perceptual, not linear. The depth is
    // not reversed; the motion is at the render size and has no jitter in it. The render size can change each frame)
    cd.flags = FFX_UPSCALE_ENABLE_NON_LINEAR_COLORSPACE | FFX_UPSCALE_ENABLE_DYNAMIC_RESOLUTION;
    cd.maxRenderSize = {f.max_w, f.max_h};
    cd.maxUpscaleSize = {f.out_w, f.out_h};
    cd.fpMessage = env_int("RX_VK_FFX_LOG") > 0 ? message : nullptr;
    const ffxReturnCode_t r = s.create(&s.ctx, &cd.header, nullptr);
    note_work();   // (AMD's own commands at creation, if any)
    s.ctx_model = model, s.out_w = f.out_w, s.out_h = f.out_h, s.max_w = f.max_w, s.max_h = f.max_h;
    if (r != FFX_API_RETURN_OK || !s.ctx) {
        logf("vk: AMD FSR: its context was not made (%u) for %ux%u -> %ux%u, version %s", (unsigned)r, f.max_w, f.max_h,
             f.out_w, f.out_h, pick->name.c_str());
        s.ctx = nullptr, s.ctx_failed = true;
        return fail("its context was not made");
    }
    ffxQueryGetProviderVersion pv{};
    pv.header.type = FFX_API_QUERY_DESC_TYPE_GET_PROVIDER_VERSION;
    s.version = s.query(&s.ctx, &pv.header) == FFX_API_RETURN_OK && pv.versionName ? pv.versionName : pick->name;
    s.model = "";
    if (s.version.rfind("4.", 0) == 0)
        for (const auto& c : g_classes)
            if (c.said.load() == 1) s.model = c.label;
    FfxApiEffectMemoryUsage mem{};
    ffxQueryDescUpscaleGetGPUMemoryUsage mq{};
    mq.header.type = FFX_API_QUERY_DESC_TYPE_UPSCALE_GPU_MEMORY_USAGE;
    mq.gpuMemoryUsageUpscaler = &mem;
    s.gpu_bytes = s.query(&s.ctx, &mq.header) == FFX_API_RETURN_OK ? mem.totalUsageInBytes : 0;
    s.made++;
    logf("vk: AMD FSR: context %llu made: FSR %s%s%s (row: %s; offered: %s), %ux%u -> %ux%u, %llu MB",
         (unsigned long long)s.made, s.version.c_str(), s.model.empty() ? "" : " ", s.model.c_str(), model_label(model),
         listed(v).c_str(), f.max_w, f.max_h, f.out_w, f.out_h, (unsigned long long)(s.gpu_bytes >> 20));
    return true;
}

}  // namespace

bool built() { return true; }

Why why() {
    static const bool off = env_int("RX_VK_FSR") == 0;
    if (off) return ENV_OFF;
    const int w = st().why.load(std::memory_order_relaxed);
    return w < 0 ? OK : (Why)w;
}

void probe() {
    if (why() != OK || st().why.load() >= 0 || !dev.device) return;
    State& s = st();
    std::lock_guard lk(s.mu);
    if (!load()) return;
    const std::vector<Version> v = versions();
    if (v.empty()) {
        logf("vk: AMD FSR: AMD's runtime offers no upscaler on this GPU");
        s.why = NO_DEVICE_SUPPORT;
        return;
    }
    logf("vk: AMD FSR: offered on this GPU: %s", listed(v).c_str());
    s.why = OK;
}

bool upscale(const Frame& f, const Later& later) {
    State& s = st();
    std::lock_guard lk(s.mu);
    if (!load()) return fail("AMD's runtime is not there");
    if (!make_context(f, later) || !s.ctx) return false;
    if (f.max_w > s.max_w || f.max_h > s.max_h || f.render_w > f.color.width || f.render_h > f.color.height)
        return fail("the render size is past the context's");
    ffxDispatchDescUpscale d{};
    d.header.type = FFX_API_DISPATCH_DESC_TYPE_UPSCALE;
    d.commandList = (void*)f.cmd;
    d.color = resource(f.color, false), d.depth = resource(f.depth, false), d.motionVectors = resource(f.motion, false);
    d.output = resource(f.output, true);
    d.jitterOffset = {f.jitter[0], f.jitter[1]};
    d.motionVectorScale = {1.0f, 1.0f};   // (in render pixels already)
    d.renderSize = {f.render_w, f.render_h};
    d.upscaleSize = {f.out_w, f.out_h};
    d.enableSharpening = false;           // (the Sharpness row's own pass follows)
    d.frameTimeDelta = f.frame_ms;
    d.preExposure = 1.0f;
    d.reset = f.reset;
    d.cameraNear = f.near_plane, d.cameraFar = f.far_plane, d.cameraFovAngleVertical = f.fov_y;
    d.viewSpaceToMetersFactor = 1.0f;
    d.flags = FFX_UPSCALE_FLAG_NON_LINEAR_COLOR_SRGB;
    const ffxReturnCode_t r = s.dispatch(&s.ctx, &d.header);
    note_work();   // (AMD's commands, which vk_work.h does not see: the next full_barrier is not left out)
    if (r != FFX_API_RETURN_OK) {
        logf("vk: AMD FSR: its dispatch failed (%u)", (unsigned)r);
        return fail("its dispatch failed");
    }
    if (s.reason) logf("vk: AMD FSR draws the upscale again");
    s.reason = nullptr;
    return true;
}

void release(const Later& later) {
    State& s = st();
    std::lock_guard lk(s.mu);
    if (!s.ctx) return;
    ffxContext old = s.ctx;
    const PfnFfxDestroyContext destroy = s.destroy;
    later([old, destroy]() mutable { destroy(&old, nullptr); });
    s.ctx = nullptr;
    s.ctx_model = -1, s.max_w = s.max_h = s.out_w = s.out_h = 0;
    logf("vk: AMD FSR: not used for 120 frames: its context let go");
}

const char* version_name() { return st().version.c_str(); }
const char* model_name() { return st().model.c_str(); }
uint64_t memory() { return st().ctx ? st().gpu_bytes : 0; }

#else  // (not Windows: AMD's runtime is not there)

bool built() { return false; }
Why why() { return NOT_BUILT; }
void probe() {}
bool upscale(const Frame&, const Later&) { return false; }
void release(const Later&) {}
const char* version_name() { return ""; }
const char* model_name() { return ""; }
uint64_t memory() { return 0; }

#endif

} // namespace mkwvk::ffx
