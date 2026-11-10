# AMD FSR API headers

Four headers of AMD's FSR SDK (FidelityFX SDK), unmodified, in the SDK's own layout (they include each other by these
paths): `api/include/ffx_api.h`, `api/include/ffx_api_types.h`, `api/include/vk/ffx_api_vk.h` and
`upscalers/include/ffx_upscale.h`.

- Source: https://github.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK, tag v2.4.0, `Kits/FidelityFX/`.
- License: MIT, as each file's own header says (Copyright (C) 2026 Advanced Micro Devices, Inc.).

Only `gpu/vk/vk_ffx.cpp` includes them. AMD's runtime (`amd_fidelityfx_loader_vk.dll` and
`amd_fidelityfx_upscaler_vk.dll`, signed by AMD) is not in the repository: `scripts/ffx_sdk.py` fetches it, and the game
loads it from its `ffx` folder.
