#!/bin/sh
set -eu
# Native Linux objects/CPU tests only: no renderer linking, game or GPU runtime.
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
out=${HOOKSHOT_CHECK_OUT:-"$root/build/dlss5-linux-check"}
vulkan=${HOOKSHOT_VULKAN_HEADERS:-/vkh}
ngx=${HOOKSHOT_NGX_SDK:-"$root/build/ngx-sdk"}
cxx=${CXX:-g++}
mkdir -p "$out"
"$cxx" --version
# GCC spells Clang's C++ _Static_assert extension static_assert.
set -- -std=c++20 -O0 -fPIC -fmax-errors=6 -D_GNU_SOURCE -DVK_NO_PROTOTYPES -DMKWVK_BUILDING \
    -D_Static_assert=static_assert \
    "-I$root/host/posix" "-I$vulkan/include" "-I$root/gpu/vk/compat" "-I$root/gpu/compat" "-I$root/gpu/vk" \
    "-I$root/third_party/imgui" "-I$root/third_party/zstd/lib" \
    -include algorithm -include cstdio -include cstdlib -include cstring \
    -include functional -include string -include vector
for source in vk_menu vk_imgui
do
    "$cxx" "$@" -c "$root/gpu/vk/$source.cpp" -o "$out/$source.o"
    printf 'PASS Linux object: %s\n' "$source"
done
"$cxx" "$@" -DHOOKSHOT_NGX "-I$ngx/include" -c "$root/gpu/vk/vk_dlss.cpp" -o "$out/vk_dlss.o"
"$cxx" "$@" -c "$root/gpu/vk/vk_dlss.cpp" -o "$out/vk_dlss_nongx.o"
for test in dlss_nr_support dlss_nr_settings dlss_nr_controls menu_hit
do
    "$cxx" -std=c++20 -Wall -Wextra -Werror "$root/tests/test_$test.cpp" -o "$out/$test"
    "$out/$test"
done
printf 'PASS: 4 Linux objects and 4 native CPU tests; no renderer link/GPU test\n'
