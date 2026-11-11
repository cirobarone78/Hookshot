// Activation policy shared by the menu and renderer; no GPU-name heuristics.
#pragma once

namespace mkwvk::dlss_nr {
enum class Issue {
    none, not_built, platform, unsupported_gpu, missing_runtime, invalid_runtime, needs_upscaler,
    needs_driver, missing_dlss_runtime, disabled, unavailable, render_failed, upstream_failed, configuration_rejected, out_of_memory,
    linux_opt_in, linux_runtime, native_hdr, runtime_path
};
struct Requirements {
    bool built = true, nvidia = true, runtime = true, valid_file = true, upscaler = true;
    Issue upstream = Issue::none;
};
inline bool blocking(Issue issue) { return issue != Issue::none && issue != Issue::configuration_rejected; }
// Native Linux NR is opt-in. A Windows DLL is not a Linux implementation.
inline Issue linux_gate(bool experimental) { return experimental ? Issue::none : Issue::linux_opt_in; }
inline Issue prerequisite(const Requirements& r) {
    if (!r.built) return Issue::not_built;
    if (!r.nvidia) return Issue::unsupported_gpu;
    if (!r.runtime) return Issue::missing_runtime;
    if (!r.valid_file) return Issue::invalid_runtime;
    if (r.upstream != Issue::none) return r.upstream;
    if (!r.upscaler) return Issue::needs_upscaler;
    return Issue::none;
}
inline Issue capability(bool queried, bool available, bool unsupported, bool needs_driver) {
    if (needs_driver) return Issue::needs_driver;
    if (unsupported) return Issue::unsupported_gpu;
    if (!queried || !available) return Issue::unavailable;
    return Issue::none;
}
inline Issue linux_capability(bool queried, bool available, bool unsupported, bool needs_driver) {
    const auto issue = capability(queried, available, unsupported, needs_driver);
    return issue == Issue::unavailable ? Issue::linux_runtime : issue;
}
inline const char* message(Issue issue) {
    switch (issue) {
    case Issue::missing_runtime:
        return "DLSS 5 is off: nvngx_dlssnr.dll is missing from the game's ngx folder. Supply your own DLL there, then try again. The game does not include or download it.";
    case Issue::invalid_runtime:
        return "DLSS 5 is off: ngx/nvngx_dlssnr.dll is not a readable, non-empty file. Replace it with a valid compatible NVIDIA DLSSNR DLL, then restart the game.";
    case Issue::unsupported_gpu:
        return "DLSS 5 is off: the selected GPU does not support Neural Rendering with the installed driver/runtime. DLSS Super Resolution support alone is not enough. Select a compatible GPU and driver.";
    case Issue::needs_upscaler:
        return "DLSS 5 is off. First select NVIDIA DLSS or NVIDIA DLAA under Graphics > Upscaler, then enable Neural Rendering again. The game's own upscaler cannot run DLSS 5.";
    case Issue::needs_driver:
        return "DLSS 5 is off: NVIDIA reports that a newer graphics driver is required. Update the driver and restart the game.";
    case Issue::missing_dlss_runtime:
#ifdef _WIN32
        return "DLSS 5 is off: DLSS Super Resolution could not find its runtime. Restore nvngx_dlss.dll in the game's ngx folder and restart the game.";
#else
        return "DLSS 5 is off: DLSS Super Resolution could not find its native Linux runtime. Restore a compatible libnvidia-ngx-dlss.so library in the game's ngx folder and restart the game.";
#endif
    case Issue::disabled:
        return "DLSS 5 is off: DLSS has been disabled for this launch (RX_VK_DLSS=0). Remove that override and restart the game.";
    case Issue::not_built:
        return "DLSS 5 is off: this build has no NVIDIA NGX support. Use a build with DLSS enabled.";
    case Issue::platform:
        return "Neural Rendering is not available on this platform: no compatible NR runtime path has been integrated and validated. Vulkan rendering and DLSS SR/DLAA remain independent.";
    case Issue::linux_opt_in:
        return "Linux Neural Rendering is experimental and off by default. Launch with RX_VK_DLSS_NR_LINUX=1 to probe native NGX NR support. A compatible native Linux runtime is required; nvngx_dlssnr.dll cannot be loaded natively. The game continues without NR.";
    case Issue::linux_runtime:
        return "Experimental Linux NR is unavailable: native NGX did not advertise Neural Rendering. The Windows nvngx_dlssnr.dll cannot be used by native Linux Hookshot. Compatible native driver/runtime support is required. SR/DLAA and the game continue without NR.";
    case Issue::native_hdr:
        return "DLSS 5 is off: this Neural Rendering path uses SDR scene data and does not support Native HDR. Select SDR or Expanded HDR to use NR. Your requested NR settings are retained.";
    case Issue::runtime_path:
        return "DLSS 5 is off: native Linux NGX cannot load the SR runtime from this non-ASCII path. Place the native runtime in an ASCII path and set RX_VK_DLSS_DIR to it, then restart. Your NR preferences are retained.";
    case Issue::unavailable:
#ifdef _WIN32
        return "DLSS 5 is off: NVIDIA could not initialize Neural Rendering. Check that your DLSSNR DLL and driver are compatible with the selected GPU, then restart the game. See the log for details.";
#else
        return "Experimental Linux NR is off: NVIDIA could not initialize native Neural Rendering. Check the native NGX runtime and driver, then restart the game. Windows DLLs cannot be loaded natively. See the log for details.";
#endif
    case Issue::out_of_memory:
        return "DLSS 5 is off: NVIDIA could not allocate enough GPU memory. Lower the render resolution or other graphics settings, then try enabling it again.";
    case Issue::render_failed:
        return "DLSS 5 has been turned off because Neural Rendering failed. Use Reset NR settings before enabling it again, or restart the game. See the log for details.";
    case Issue::configuration_rejected:
        return "The requested model settings could not be created. The last working NR model is still running. Change the settings or use Retry detection; the requested preferences have been retained.";
    case Issue::upstream_failed:
        return "DLSS 5 is off because DLSS/DLAA failed earlier in this session. Restart the game to restore the DLSS upscaler before enabling Neural Rendering. See the log for details.";
    default: return "";
    }
}
} // namespace mkwvk::dlss_nr
