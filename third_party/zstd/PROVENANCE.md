zstd 1.5.7, from https://github.com/facebook/zstd (release v1.5.7, zstd-1.5.7.tar.gz, sha256
eb33e51f49a15e023950cd7825ca74a4a2b43db8354825ac24fc1b7ee09e6fa3), unmodified: lib/zstd.h, lib/zstd_errors.h,
lib/zdict.h, lib/common/, lib/decompress/ and lib/compress/. BSD license (LICENSE; zstd is dual BSD or GPLv2, used here under BSD).

Built with ZSTD_DISABLE_ASM (nx2/build.py). The decoder is used by gpu/vk/vk_imgui.cpp to read the game's own menu font from
the player's game files at run time (romfs Font2, with the dictionary in Pack/ZsDic.pack.zs), in memory, and by host/prompts.c
to read a mod's resource size table and the button prompts' own, to merge them. The encoder (built in the Vulkan back end only,
without ZSTD_MULTITHREAD: lib/compress/zstdmt_compress.c is not built) and the decoder are used by gpu/vk/vk_stage_code.cpp,
which keeps each translated program stage's SPIR-V packed in memory and unpacks it into a shader module only while a pipeline
is made with it.
