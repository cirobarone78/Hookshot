/* (hookshot) fopen for the files the game writes by itself in its folder and the user folder (hookshot_options.ini, the
   pipeline caches and lists, the button-prompt textures, mouse_sens.txt, language.txt and the like), without following a
   symbolic link at the file's name. A game folder unpacked from an archive someone shared can hold such a link (tar and
   unzip keep them on Linux): a plain fopen("w") then emptied and rewrote the file it named, anywhere the player can write.
   Linux: O_NOFOLLOW, and only a regular file (not a FIFO or a device). Windows: not when the name is a symbolic link or a
   junction (an archive tool makes them in Developer Mode); OneDrive's own reparse points are files and are written.
   mode: "w", "wb", "a" or "ab". Used by the host (C) and the renderer (C++). */
#pragma once
#include <stdio.h>
#include "hos_fopen_read.h"   /* (and the reads: hos_fopen_read, hos_fopen_read_binary) */
#include <errno.h>
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#else
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

/* (a refusal is said once per file that includes this, on stderr (the game's log): a setting that "does not stick" has a reason) */
static inline void hos_fopen_write_refused(const char *path) {
    static int said;
    if (!said++) fprintf(stderr, "files: %s is a link or not a plain file: the game does not write through it\n", path);
}
static inline FILE *hos_fopen_write(const char *path, const char *mode) {
#ifdef _WIN32
    if (mode[0] != 'w' && mode[0] != 'a') return NULL;
    const DWORD attributes = GetFileAttributesA(path);   /* (the same code page as fopen's) */
    if (attributes != INVALID_FILE_ATTRIBUTES && (attributes & FILE_ATTRIBUTE_REPARSE_POINT)) {
        WIN32_FIND_DATAA fd;
        const HANDLE h = FindFirstFileA(path, &fd);
        if (h == INVALID_HANDLE_VALUE) return NULL;
        FindClose(h);
        if (fd.dwReserved0 == 0xA000000CUL || fd.dwReserved0 == 0xA0000003UL || fd.dwReserved0 == 0xA000001DUL) {
            hos_fopen_write_refused(path);
            return NULL;   /* (IO_REPARSE_TAG_SYMLINK, _MOUNT_POINT, WSL's _LX_SYMLINK) */
        }
    }
    return fopen(path, mode);
#else
    const int append = mode[0] == 'a';
    if (!append && mode[0] != 'w') return NULL;
    const int fd = open(path, O_WRONLY | O_CREAT | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK | (append ? O_APPEND : 0), 0666);
    if (fd < 0) {
        if (errno == ELOOP || errno == ENXIO) hos_fopen_write_refused(path);   /* (a link; a FIFO with no reader) */
        return NULL;
    }
    struct stat st;
    /* (truncated only once it is known to be a regular file of its own name) */
    const int plain = fstat(fd, &st) == 0 && S_ISREG(st.st_mode);
    if (!plain || (!append && ftruncate(fd, 0) != 0)) {
        if (!plain) hos_fopen_write_refused(path);
        close(fd);
        return NULL;
    }
    const int flags = fcntl(fd, F_GETFL);
    if (flags != -1) fcntl(fd, F_SETFL, flags & ~O_NONBLOCK);
    FILE *f = fdopen(fd, mode);
    if (!f) close(fd);
    return f;
#endif
}
