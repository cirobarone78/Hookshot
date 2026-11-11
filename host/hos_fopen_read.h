/* (hookshot) The reads that go with host/hos_fopen_write.h, in a header of their own: it needs no windows.h, so
   checks that cut a reader out of the sources can include it on Windows beside their own stand-ins. */
#pragma once
#include <stdio.h>
#ifndef _WIN32
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

/* fopen(path, "r") for the small text files the game reads from its folder at the start (hookshot_env.txt,
   hookshot_options.ini, language.txt, mouse_sens.txt): only a regular file. A folder unpacked from an archive can hold a
   FIFO under one of those names (tar keeps them), and the game waited on it forever before its window opened. Linux:
   opened without waiting, and refused unless it is a regular file. Windows: as fopen */
static inline FILE *hos_fopen_read_mode(const char *path, const char *mode) {
#ifdef _WIN32
    return fopen(path, mode);
#else
    (void)mode;   /* ("r" and "rb" are the same here) */
    const int fd = open(path, O_RDONLY | O_CLOEXEC | O_NONBLOCK);
    if (fd < 0) return NULL;
    struct stat st;
    if (fstat(fd, &st) != 0 || !S_ISREG(st.st_mode)) {
        close(fd);
        return NULL;
    }
    const int flags = fcntl(fd, F_GETFL);
    if (flags != -1) fcntl(fd, F_SETFL, flags & ~O_NONBLOCK);
    FILE *f = fdopen(fd, "r");
    if (!f) close(fd);
    return f;
#endif
}
static inline FILE *hos_fopen_read(const char *path) { return hos_fopen_read_mode(path, "r"); }
/* (and the binary files the renderer reads from the game folder at the start: the pipeline caches, notes, state lists and
   the preparation's records and markers) */
static inline FILE *hos_fopen_read_binary(const char *path) { return hos_fopen_read_mode(path, "rb"); }
