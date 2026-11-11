// (hookshot) Workarounds for one GPU vendor's or driver's behaviour, chosen from the device's properties alone: who made it
// (vendorID), whose driver it runs (driverID, and driverInfo where a driver names its compiler) and what kind of GPU it is.
// vendor_fixes() is plain code with no Vulkan calls, so tests/test_vendor_fixes.py runs it on made-up devices: each fix on
// the GPUs it is for and on no other, and NVIDIA's driver with none of them (the GPU every row of the game was checked on).
// Each one has an RX_VK_ switch to force it on (1) or off (0) on any GPU, to test it where it is not needed.
#pragma once

#include <cstdint>
#include <cstdlib>
#include <cstring>

#include <vulkan/vulkan_core.h>

namespace mkwvk {

struct VendorFacts {
    uint32_t vendor_id = 0;
    VkDriverId driver_id{};
    VkPhysicalDeviceType device_type = VK_PHYSICAL_DEVICE_TYPE_OTHER;
    const char* driver_info = "";   // (VkPhysicalDeviceDriverProperties::driverInfo)
};

struct VendorFixes {
    // Pipeline builds into the pipeline cache kept apart from vkGetPipelineCacheData (vk_draw.cpp pipeline_cache_save). Vulkan
    // allows the two at once on a cache made without VK_PIPELINE_CACHE_CREATE_EXTERNALLY_SYNCHRONIZED_BIT, but Intel's Windows
    // driver faults in vkGetPipelineCacheData (an access violation in igvk64.dll) when a save meets pipelines being built:
    // totk-pc-recomp b358b8f1f1 (itaskaev2, MIT) and Eglantine db093d7325 (kraibse, GPL) found it, the second for MKW. Intel's
    // Windows driver, any GPU. RX_VK_PCACHE_APART
    bool pcache_apart = false;
    // Alpha to coverage set in the pipeline, not as dynamic state (VK_EXT_extended_dynamic_state3). Intel's Windows driver on its
    // integrated GPUs (UHD Graphics, Iris Xe) drew coloured noise on foliage with the dynamic state, and players saw it go with
    // it off (totk-pc-recomp 905e2e720d, Valiantsin Dzerakh, MIT: its issues 970, 992, 419). Every GPU that driver reports as
    // integrated gets it, so the Arc Graphics built into Meteor, Lunar and Arrow Lake processors too; discrete Arc cards and
    // Mesa's ANV keep the dynamic state: no report there. Without it the stage libraries (RX_VK_GPL) stay off: they need the
    // state dynamic (vk_draw.cpp gpl_wanted). RX_VK_DYN_A2C=0 / 1
    bool static_a2c = false;
    // Out-of-bounds texel fetches answered with zero in the shader (emit_spirv_image.cpp EmitImageFetch). Vulkan leaves such a
    // fetch undefined without robustImageAccess, which Hookshot does not turn on; NVIDIA's GPUs (the Switch 2's among them)
    // return zero (measured on an RTX 3090: every texture type, past each edge, the last level and the last sample). The ground fog's shader reads depth at points projected off screen near the edges, and on AMD (RX 9070) those
    // pixels took the other branch: a pale stepped box at the left, right and top edges. Every GPU but NVIDIA's. RX_VK_FETCH_BOUNDS
    bool fetch_bounds = false;
    // isnan(x) as a test of x's bits, not OpIsNan (emit_spirv_floating_point.cpp IsNan), for AMD's older Windows shader compiler
    // (the driver branch for RDNA 1 and 2, RX 5000 and RX 6000: its driverInfo names the "AMD proprietary shader compiler" where
    // the RDNA 3 and 4 driver names LLPC; the test of driverInfo is totk-pc-recomp's vk_caps.c, MIT). Players of OoT ports on
    // those cards saw black and white blocks where a NaN test did not hold. The colour outputs' NaN guard is such a test too.
    // RX_VK_NAN_BITS
    bool nan_bits = false;
    // Gathers nudged by 1/512 of a texel, so that the four texels a gather picks match Maxwell's at texel edges
    // (emit_spirv_image.cpp ImageGatherSubpixelOffset, Eden's, which Hookshot had never turned on). Eden and Lichii turn it on
    // for these drivers (the AMD and Intel ones, and the mobile ones Eden runs on): shadow edges drawn as dashed lines without it.
    // RX_VK_GATHER_OFFSET
    bool gather_offset = false;
};

/// Which of the fixes the device needs (before the RX_VK_ switches: vendor_fixes_env)
inline VendorFixes vendor_fixes(const VendorFacts& f) {
    VendorFixes x;
    const bool intel_windows = f.driver_id == VK_DRIVER_ID_INTEL_PROPRIETARY_WINDOWS;
    x.pcache_apart = intel_windows;
    x.static_a2c = intel_windows && f.device_type == VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU;
    x.fetch_bounds = f.vendor_id != 0x10DE;
    x.nan_bits = f.driver_id == VK_DRIVER_ID_AMD_PROPRIETARY && f.driver_info && std::strstr(f.driver_info, "proprietary shader compiler");
    switch (f.driver_id) {
    case VK_DRIVER_ID_AMD_PROPRIETARY:
    case VK_DRIVER_ID_AMD_OPEN_SOURCE:
    case VK_DRIVER_ID_MESA_RADV:
    case VK_DRIVER_ID_INTEL_PROPRIETARY_WINDOWS:
    case VK_DRIVER_ID_INTEL_OPEN_SOURCE_MESA:
    case VK_DRIVER_ID_QUALCOMM_PROPRIETARY:
    case VK_DRIVER_ID_MESA_TURNIP:
        x.gather_offset = true;
        break;
    default:
        break;
    }
    return x;
}

/// The RX_VK_ switches over them: 0 off, anything else on, unset as the device has it. get: getenv, or a test's own
template <class Get> void vendor_fixes_env(VendorFixes& x, Get get) {
    const auto over = [&](const char* name, bool& v) {
        if (const char* e = get(name); e && *e) v = std::atoi(e) != 0;
    };
    over("RX_VK_PCACHE_APART", x.pcache_apart);
    bool dyn_a2c = !x.static_a2c;
    over("RX_VK_DYN_A2C", dyn_a2c);
    x.static_a2c = !dyn_a2c;
    over("RX_VK_FETCH_BOUNDS", x.fetch_bounds);
    over("RX_VK_NAN_BITS", x.nan_bits);
    over("RX_VK_GATHER_OFFSET", x.gather_offset);
}

} // namespace mkwvk
