// The folders this DLL keeps its files in. The game folder (host/hos_paths.h's rule) holds what the build made (the shader list,
// the shipped pipeline lists): the game is bin\hookshot.exe beside its launcher since the launcher came; its files stay in the
// folder above bin. game_module_path answers as GetModuleFileNameA(nullptr, ...) does, with the folder's path when the exe is in a
// "bin" folder beside image.bin. The game folder's cache/ holds the shader and pipeline caches (cache_path: made for this build
// and this GPU, and it can be deleted), and its logs/ the logs and traces (log_path). The data folder (host/hos_data.c,
// MkwVkHost.data_dir) holds what belongs to the player: the settings (data_path).
#pragma once
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#undef min
#undef max
#include <cstring>
#include <string>
#include "vk_api.h"

namespace mkwvk {
inline DWORD game_module_path(char* buf, DWORD size) {
    DWORD n = GetModuleFileNameA(nullptr, buf, size);
    if (!n || n >= size) return n;
    char* name = buf + n;
    while (name > buf && name[-1] != '\\' && name[-1] != '/') name--;
    if (name - buf < 5) return n;
    char* dir = name - 1;
    char* bin = dir;
    while (bin > buf && bin[-1] != '\\' && bin[-1] != '/') bin--;
    if (dir - bin != 3 || _strnicmp(bin, "bin", 3) != 0) return n;
    char probe[MAX_PATH + 16];
    const size_t root = (size_t)(bin - buf);
    if (root + 10 >= sizeof probe) return n;
    std::memcpy(probe, buf, root);
    std::strcpy(probe + root, "image.bin");
    if (GetFileAttributesA(probe) == INVALID_FILE_ATTRIBUTES) return n;
    std::memmove(buf + root, name, std::strlen(name) + 1);
    return (DWORD)std::strlen(buf);
}
/// The game folder, with its separator at the end
inline std::string game_folder() {
    char exe[MAX_PATH];
    const DWORD n = game_module_path(exe, MAX_PATH);
    const std::string path(exe, n < MAX_PATH ? n : 0);
    return path.substr(0, path.find_last_of("\\/") + 1);
}
/// <game folder>/<name>: a file the build made
inline std::string game_file(const char* name) { return game_folder() + name; }
extern const MkwVkHost* host;   // (vk_main.cpp)
/// <data folder>/<name> (name may hold a sub-folder): the host's data folder, else (a host from before it had one) the game folder
inline std::string data_path(const char* name) {
    const char* dir = host && host->data_dir ? host->data_dir() : nullptr;
    return (dir && *dir ? std::string(dir) + "/" : game_folder()) + name;
}
/// <game folder>/cache/<name>: the shader and pipeline caches (host/hos_data.c makes the folder)
inline std::string cache_path(const char* name) { return game_folder() + "cache/" + name; }
/// <game folder>/logs/<name>: the logs and traces a run writes (host/hos_data.c makes the folder)
inline std::string log_path(const char* name) { return game_folder() + "logs/" + name; }
}  // namespace mkwvk
