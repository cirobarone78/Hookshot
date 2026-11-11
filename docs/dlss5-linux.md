# Experimental native Linux Neural Rendering

Status: experimental source integration, NOT verified Linux GPU NR support.
Windows remains the primary tested NR implementation. Hookshot's ordinary
Linux Vulkan rendering and existing SR/DLAA are independent of this optional
feature.

## Runtime limitation

The Windows nvngx_dlssnr.dll is a PE/Windows library. A native Linux Hookshot
process cannot load it as a Linux shared object; renaming it does not help.

The inspected [NVIDIA SDK 310.9.16 Linux release directory](https://github.com/NVIDIA/DLSS/tree/9981c6350dc58c0ce21f024fd65e31e851c31689/lib/Linux_x86_64/rel)
contains native dlss, dlssd and dlssg libraries, but no NR library. The main
branch had the same set when checked on 10 November 2026. Therefore the local
Windows NR DLL does not make the current Linux build capable of NR.
No native NR filename, ABI availability or future release date is assumed.

## What is implemented

- Shared native Vulkan color/depth/motion resources, NR evaluation,
  compositing, debug, comparison, UI, persistence and error handling compile
  for Linux.
- The menu and comparison toolbar use the project's existing Dear ImGui
  draw lists, fonts, input handling and Vulkan overlay path on both platforms.
- Linux NR defaults to unavailable until explicitly opted in.
- Opt-in probes the existing native NGX session. An actual successful
  DLSSNR.Available capability response is mandatory before CreateFeature(18).
  Missing keys/unavailable capability produce a specific native-runtime
  explanation in the NR submenu; unsupported GPU and driver-update responses
  retain their respective errors.
- Native NGX owns feature discovery through the existing NGX search paths.
  No private .so filename is guessed, no Windows DLL is dlopened, and no
  Wine/Proton bridge, proxy or external rendering layer is introduced.
- If native NGX ever provides the compatible feature/parameter contract,
  the existing single-pass direct Vulkan path can attempt it. Creation or
  evaluation failure retains the normal rendering fallback and saved NR
  preferences, without a startup popup or automatic infinite retry.
- Without the NGX SDK, the existing no-SDK stubs remain available.

This is a capability-gated integration path for future compatible runtimes
and contributors, not an implementation of NVIDIA's proprietary runtime.

## Trying the experimental path

Use the project's normal Linux build/install flow and a build configured
with HOOKSHOT_NGX_SDK pointing to a Linux SDK (include/ and lib/libnvsdk_ngx.a).
The Windows .lib cannot replace the Linux static library. The existing
scripts/ngx_sdk.py --platform linux flow supplies SR SDK files, not NR.

On a Linux system with a compatible native NVIDIA driver/runtime:

```sh
RX_VK_DLSS_NR_LINUX=1 ./hookshot
```

Or set RX_VK_DLSS_NR_LINUX=1 in the existing launch environment, then restart.
This setting is intentionally not an in-game promise of availability.
Select NVIDIA DLSS/DLAA and open the Graphics > DLSS 5 Neural Rendering submenu. It reports experimental
status, capability failure or effective evaluation. Retry refreshes cached
capability checks; changing the driver/runtime or opt-in setting requires
restart. A copied Windows DLL is not considered proof of Linux support.

With no native NR implementation the expected result is original rendering
plus a compact availability explanation inside Base/Advanced, with requested
preferences retained. Other tabs and normal gameplay do not show the error.

## Windows isolation

The Windows DLL file checks and version metadata remain under _WIN32.
The Linux opt-in variable has no effect on Windows. The native NGX feature
number, parameters, Vulkan pipeline, presets and saved file format were not
changed. No libraries or launch defaults were added to the Windows package.

## Verification performed

- Windows NGX renderer build passed; eleven focused Windows CPU checks passed.
- A pre-existing offline Debian 12 Docker image (x86_64, GCC 12.2) compiled
  vk_menu.cpp, vk_imgui.cpp and vk_dlss.cpp with NGX, plus vk_dlss.cpp
  without NGX into native Linux objects.
- Four Linux CPU tests passed: NR activation policy, model edits,
  profiles/comparison and menu hit-testing. New cases cover opt-in denial,
  missing capability, driver requirement, unsupported device and positive
  native capability. Linux errors use Linux SR library terminology.
- The object checks use the project's POSIX compatibility headers and
  pinned Vulkan/NGX headers. GCC maps Clang's _Static_assert extension to
  equivalent C++ static_assert; assertions are not removed.
- The project/headers were read-only and network/GPU access disabled inside
  the check container. No Linux NR runtime was installed or loaded.

The reproducible check is tests/check_dlss_nr_linux.sh. Set
HOOKSHOT_VULKAN_HEADERS to the Vulkan-Headers root, HOOKSHOT_NGX_SDK to the SDK
headers' root, and optionally HOOKSHOT_CHECK_OUT/CXX. It builds objects only,
so no NGX library or proprietary runtime is loaded for this check.

These are real Linux object/CPU checks, not a full renderer link or game
launch. No native NR runtime, Linux GPU execution, visual/controller testing,
HDR NR or shutdown recovery was validated. The earlier Windows shutdown
timeout remains a separate open investigation.

## Contributor handoff

Confirm an actual supported native NGX NR implementation and its parameter/
resource contract before claiming functional support. Do not substitute a
Windows filename or parameter-setter success for capability and evaluation.
Validate native SDK linking, scene resources, alpha/color space, histories,
resize, comparison input, repeated enable/disable and normal shutdown on GPU.
Record SDK/driver/runtime versions and distinguish Linux from Proton.
Keep Linux-only experimentation guarded and rerun Windows checks.
