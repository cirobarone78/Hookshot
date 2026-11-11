/* (hookshot) The update offer: at start, the latest release on GitHub is asked for (a few seconds at most, nothing when offline), and
   when it is not the release this game folder was built with, the player is asked whether to update. Yes starts the Hookshot Builder
   that made the folder (hookshot_version.txt, written by nx2/make_game.py) with --update: it downloads the new release and builds the
   folder again from the game files the folder keeps, and the game closes. A folder with no hookshot_version.txt (built from the
   repository, or before updates came in) is never asked about. HOOKSHOT_NO_UPDATE_CHECK=1 (hookshot_env.txt) turns it off */
#if defined(_WIN32) || defined(__linux__)
#include <ctype.h>
#include <stdlib.h>
#include <string.h>

/* a release tag as it may be shown and passed on to the Builder: letters, digits and . _ + - (from the network, or a
   file of the game folder) */
static int safe_tag(const char *s) {
    size_t n = strlen(s);
    if (!n || n > 80) return 0;
    for (size_t i = 0; i < n; i++)
        if (!isalnum((unsigned char)s[i]) && !strchr("._+-", s[i])) return 0;
    return 1;
}

/* (hookshot) the builder= and builder_args= lines of hookshot_version.txt name the program the game starts to update and
   its first arguments. They are a file of the game folder, so they are taken only in the shapes the builders write
   (nx2/make_game.py from HOOKSHOT_BUILDER_EXE / _ARGS): an absolute path to HookshotBuilder.exe, or to the Python builder's
   python(w).exe with "-I <its hookshot_builder_start.py>" (builder/py/hookshot_builder/core.py), on Windows; to an
   AppImage or the AppImage's AppRun on Linux. Anything else counts as no builder (the offer opens the download page). The
   folder may be anywhere: the shape is checked, not the place */
static int ends_with_nocase(const char *s, size_t n, const char *end) {
    const size_t e = strlen(end);
    if (n < e) return 0;
    for (size_t i = 0; i < e; i++)
        if (tolower((unsigned char)s[n - e + i]) != tolower((unsigned char)end[i])) return 0;
    return 1;
}

/* an absolute path of n bytes: C:\ or C:/ (no network path) on Windows, / on Linux; no . or .. part, no control
   character, no quote */
static int builder_path_ok(const char *p, size_t n, int windows) {
    if (windows ? !(n > 3 && isalpha((unsigned char)p[0]) && p[1] == ':' && (p[2] == '\\' || p[2] == '/'))
                : !(n > 1 && p[0] == '/'))
        return 0;
    for (size_t i = 0; i < n; i++) {
        const unsigned char c = (unsigned char)p[i];
        if (c < 0x20 || c == 0x7f || c == '"') return 0;
        if (windows && strchr("<>|?*", c)) return 0;
        if (windows && c == ':' && i != 1) return 0;
        const int sep = c == '/' || (windows && c == '\\');
        if (sep || i == 0) {
            size_t a = sep ? i + 1 : i, b = a;
            while (b < n && p[b] != '/' && !(windows && p[b] == '\\')) b++;
            if ((b - a == 1 && p[a] == '.') || (b - a == 2 && p[a] == '.' && p[a + 1] == '.')) return 0;
        }
    }
    return 1;
}

/* the base name of a path of n bytes */
static const char *base_name(const char *p, size_t n, int windows) {
    const char *b = p;
    for (size_t i = 0; i < n; i++)
        if (p[i] == '/' || (windows && p[i] == '\\')) b = p + i + 1;
    return b;
}

static int builder_ok(const char *exe, const char *args, int windows) {
    const size_t n = strlen(exe);
    if (!builder_path_ok(exe, n, windows)) return 0;
    const char *base = base_name(exe, n, windows);
    const size_t bn = n - (size_t)(base - exe);
    if (!windows)   /* (builder/linux/AppRun: $APPIMAGE, or AppRun itself when it is unpacked) */
        return (!args || !*args) && ((bn == 6 && !strcmp(base, "AppRun")) || (bn > 9 && ends_with_nocase(base, bn, ".AppImage")));
    if (bn == 19 && ends_with_nocase(base, bn, "HookshotBuilder.exe")) return !args || !*args;
    if (!((bn == 11 && ends_with_nocase(base, bn, "pythonw.exe")) || (bn == 10 && ends_with_nocase(base, bn, "python.exe"))))
        return 0;
    /* (subprocess.list2cmdline(["-I", start]): the script quoted when it has a space or a tab) */
    if (!args || strncmp(args, "-I ", 3)) return 0;
    const char *s = args + 3;
    size_t sn = strlen(s);
    if (sn >= 2 && s[0] == '"' && s[sn - 1] == '"') s++, sn -= 2;
    else if (strpbrk(s, " \t")) return 0;
    const char *sb = base_name(s, sn, 1);
    return builder_path_ok(s, sn, 1) && sn - (size_t)(sb - s) == 25 && ends_with_nocase(s, sn, "hookshot_builder_start.py");
}

/* (the update tracks, from the folder's version: a release (v2.0.7) is offered the latest release as before; a release
   candidate (v2.1.0-rc.1) the newest of the release candidates and the releases, only when it is newer (so never an older
   release, and its own version's release once that ships); a nightly (git describe --long's v2.1.0-rc.1-3-g1a2b3c4) the
   nightly's build whenever it is another. The builder's Track menu switches track; builder/linux/linux_update.py has the
   same rules) */
static int nightly_version(const char *s) {
    size_t n = strlen(s), h;
    if (n > 6 && !strcmp(s + n - 6, "-dirty")) n -= 6;
    for (h = n; h && isxdigit((unsigned char)s[h - 1]); h--) {}
    if (h == n || h < 3 || s[h - 1] != 'g' || s[h - 2] != '-') return 0;
    size_t d = h - 2;
    while (d && isdigit((unsigned char)s[d - 1])) d--;
    return d < h - 2 && d > 0 && s[d - 1] == '-';
}

/* vX.Y.Z or vX.Y.Z-rc.N: v[3] is N, or a release's (above every N) */
static int parse_version(const char *s, long v[4]) {
    char *e;
    if (*s == 'v') s++;
    for (int i = 0; i < 3; i++) {
        if (!isdigit((unsigned char)*s)) return 0;
        v[i] = strtol(s, &e, 10);
        s = e;
        if (i < 2 && *s++ != '.') return 0;
    }
    if (!*s) return v[3] = 0x7fffffffL, 1;
    if (strncmp(s, "-rc.", 4) || !isdigit((unsigned char)s[4])) return 0;
    v[3] = strtol(s + 4, &e, 10);
    return !*e;
}

/* a newer than b, both vX.Y.Z[-rc.N] (0 when either is not) */
static int newer_version(const char *a, const char *b) {
    long x[4], y[4];
    if (!parse_version(a, x) || !parse_version(b, y)) return 0;
    for (int i = 0; i < 4; i++)
        if (x[i] != y[i]) return x[i] > y[i];
    return 0;
}

/* the first "tag_name":"..." of a body from GitHub's API, or a setup list's "tag " line */
static int tag_in(const char *body, char *tag, size_t cap) {
    const char *k = strstr(body, "\"tag_name\"");
    if (k && (k = strchr(k + 10, '"'))) {
        const char *e = strchr(++k, '"');
        if (e && e > k && (size_t)(e - k) < cap) {
            memcpy(tag, k, (size_t)(e - k));
            tag[e - k] = 0;
            return safe_tag(tag);   /* (hookshot: it goes on the Builder's command line) */
        }
        return 0;
    }
    for (const char *line = body; line; line = strchr(line, '\n') ? strchr(line, '\n') + 1 : NULL)
        if (!strncmp(line, "tag ", 4)) {
            size_t len = strcspn(line + 4, "\r\n ");
            if (!len || len >= cap) return 0;
            memcpy(tag, line + 4, len);
            tag[len] = 0;
            return safe_tag(tag);
        }
    return 0;
}

/* (hookshot) whether an environment entry (NAME=VALUE) is one the game's shared hookshot_env.txt set: names is
   hos_env_file_names' list (each name and a 0, an empty name at the end). The builder an update starts is not given
   those: they are the game's switches, from a file someone may have handed the player, and the builder reads some of the
   same names (RX_MARCH, RX_HOT_OPT, RX_VK_ONLY...) for the build it makes */
__attribute__((unused)) static int set_by_env_file(const char *entry, const char *names) {   /* (Windows: not called) */
    for (const char *n = names; n && *n; n += strlen(n) + 1) {
        const size_t k = strlen(n);
        if (!strncmp(entry, n, k) && entry[k] == '=') return 1;
    }
    return 0;
}

/* the newest vX.Y.Z[-rc.N] among the "tag_name"s of GitHub's release list (drafts are not shown without a token) */
static int newest_tag(const char *body, char *tag, size_t cap) {
    int found = 0;
    for (const char *k = body; (k = strstr(k, "\"tag_name\"")) != NULL; k += 10) {
        char t[128];
        long v[4];
        if (tag_in(k, t, sizeof t) && parse_version(t, v) && (!found || newer_version(t, tag)) && strlen(t) < cap)
            strcpy(tag, t), found = 1;
    }
    return found;
}
#endif

#ifdef _WIN32
#include "hos_paths.h"
#include <windows.h>
#include <winhttp.h>
const char *hos_env_file_names(void);   /* (host/hos_main.c: what hookshot_env.txt set) */
#include <shellapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define UPDATE_HOST L"api.github.com"
#define UPDATE_PATH L"/repos/NotRexed/Hookshot/releases/latest"
#define RELEASES_PAGE L"https://github.com/NotRexed/Hookshot/releases/latest"

/* (a line "name=value" of a small text file, in UTF-8: its value, trimmed) */
static int read_value(const wchar_t *path, const char *name, char *out, size_t cap) {
    FILE *f = _wfopen(path, L"rb");
    if (!f) return 0;
    char line[1024];
    const size_t n = strlen(name);
    int found = 0;
    while (!found && fgets(line, sizeof line, f)) {
        char *s = line;
        if ((unsigned char)s[0] == 0xEF && (unsigned char)s[1] == 0xBB && (unsigned char)s[2] == 0xBF) s += 3;
        if (strncmp(s, name, n) || s[n] != '=') continue;
        s += n + 1;
        size_t len = strlen(s);
        while (len && (s[len - 1] == 10 || s[len - 1] == 13 || s[len - 1] == ' ' || s[len - 1] == 9)) s[--len] = 0;
        if (len && len < cap) {
            memcpy(out, s, len + 1);
            found = 1;
        }
    }
    fclose(f);
    return found;
}

/* a GET of https://host/path: its body (malloc'd, at most 512 KB), NULL when it did not answer 200 */
static char *get_body(const wchar_t *host, const wchar_t *path) {
    char *body = NULL;
    HINTERNET s = WinHttpOpen(L"Hookshot-update-check", WINHTTP_ACCESS_TYPE_DEFAULT_PROXY, WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (!s) return NULL;
    WinHttpSetTimeouts(s, 2500, 2500, 2500, 3000);
    HINTERNET c = WinHttpConnect(s, host, INTERNET_DEFAULT_HTTPS_PORT, 0);
    HINTERNET r = c ? WinHttpOpenRequest(c, L"GET", path, NULL, WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES, WINHTTP_FLAG_SECURE) : NULL;
    if (r && WinHttpSendRequest(r, L"Accept: application/vnd.github+json\r\n", (DWORD)-1, WINHTTP_NO_REQUEST_DATA, 0, 0, 0) &&
        WinHttpReceiveResponse(r, NULL)) {
        DWORD status = 0, size = sizeof status;
        WinHttpQueryHeaders(r, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER, WINHTTP_HEADER_NAME_BY_INDEX, &status, &size, WINHTTP_NO_HEADER_INDEX);
        if (status == 200) {
            const size_t max = 512 << 10;
            body = (char *)malloc(max + 1);
            size_t have = 0;
            DWORD got = 0;
            while (body && have < max && WinHttpReadData(r, body + have, (DWORD)(max - have), &got) && got) have += got;
            if (body) body[have] = 0;
        }
    }
    if (r) WinHttpCloseHandle(r);
    if (c) WinHttpCloseHandle(c);
    WinHttpCloseHandle(s);
    return body;
}

/* (the newest build of the folder's track: the latest release's tag, from GitHub's API: "tag_name":"..."; a release
   candidate's, the newest in the release list, else the latest release's; a nightly's, the nightly's setup list's tag) */
static int latest_tag(const char *have, char *tag, size_t cap) {
    int ok = 0;
    char *body;
    if (nightly_version(have)) {
        if ((body = get_body(L"github.com", L"/NotRexed/Hookshot/releases/download/nightly/hookshot-setup.txt")))
            ok = tag_in(body, tag, cap), free(body);
        return ok;
    }
    if (strchr(have, '-') && (body = get_body(UPDATE_HOST, L"/repos/NotRexed/Hookshot/releases?per_page=20"))) {
        ok = newest_tag(body, tag, cap);
        free(body);
        if (ok) return 1;
    }
    if ((body = get_body(UPDATE_HOST, UPDATE_PATH))) ok = tag_in(body, tag, cap), free(body);
    return ok;
}

/* (hookshot) a symbolic link or a junction (a mount point; WSL's links too). Other reparse points are not links: OneDrive
   marks its files and folders with one, and those are written as they are */
static int is_link(const wchar_t *path, DWORD attributes) {
    if (!(attributes & FILE_ATTRIBUTE_REPARSE_POINT)) return 0;
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(path, &fd);
    if (h == INVALID_HANDLE_VALUE) return 1;
    FindClose(h);
    return fd.dwReserved0 == IO_REPARSE_TAG_SYMLINK || fd.dwReserved0 == IO_REPARSE_TAG_MOUNT_POINT ||
           fd.dwReserved0 == 0xA000001DUL /* IO_REPARSE_TAG_LX_SYMLINK */;
}

void hos_update_check(void) {
    if (getenv("HOOKSHOT_NO_UPDATE_CHECK") && strcmp(getenv("HOOKSHOT_NO_UPDATE_CHECK"), "0")) return;
    wchar_t dir[MAX_PATH], file[MAX_PATH + 64];
    DWORD n = hos_game_path_w(dir, MAX_PATH);
    if (!n || n >= MAX_PATH) return;
    while (n && dir[n - 1] != L'\\' && dir[n - 1] != L'/') n--;
    if (!n) return;
    dir[n - 1] = 0;
    char have[128], builder[MAX_PATH * 3], skipped[128] = "", tag[128];
    _snwprintf(file, MAX_PATH + 64, L"%ls\\hookshot_version.txt", dir);
    if (!read_value(file, "version", have, sizeof have) || !safe_tag(have)) return;
    _snwprintf(file, MAX_PATH + 64, L"%ls\\user\\hookshot_update_skip.txt", dir);
    read_value(file, "skip", skipped, sizeof skipped);
    if (!latest_tag(have, tag, sizeof tag)) {
        fprintf(stderr, "update: the latest release could not be asked for (offline?)\n");
        return;
    }
    fprintf(stderr, "update: this folder is %s, the latest release is %s\n", have, tag);
    if (!strcmp(tag, have) || !strcmp(tag, skipped)) return;
    if (strchr(have, '-') && !nightly_version(have) && !newer_version(tag, have)) return;   /* (a release candidate: newer only) */

    wchar_t wtag[128], whave[128], wbuilder[MAX_PATH], text[2048];
    MultiByteToWideChar(CP_UTF8, 0, tag, -1, wtag, 128);
    MultiByteToWideChar(CP_UTF8, 0, have, -1, whave, 128);
    _snwprintf(file, MAX_PATH + 64, L"%ls\\hookshot_version.txt", dir);
    /* (the Python builder: builder= is its pythonw.exe, and builder_args= what goes before --update, its start script) */
    char bargs[1024] = "";
    wchar_t wbargs[1024] = L"";
    read_value(file, "builder_args", bargs, sizeof bargs);
    DWORD battr = INVALID_FILE_ATTRIBUTES;
    const int has_builder = read_value(file, "builder", builder, sizeof builder) && builder_ok(builder, bargs, 1) &&
                            MultiByteToWideChar(CP_UTF8, 0, builder, -1, wbuilder, MAX_PATH) > 0 &&
                            (!bargs[0] || MultiByteToWideChar(CP_UTF8, 0, bargs, -1, wbargs, 1024) > 0) &&
                            (battr = GetFileAttributesW(wbuilder)) != INVALID_FILE_ATTRIBUTES &&
                            !(battr & FILE_ATTRIBUTE_DIRECTORY);
    if (has_builder)
        _snwprintf(text, 2048,
                   L"A new version of Hookshot is out: %ls (this game is %ls).\n\n"
                   L"Update now? The game closes, and Hookshot Builder downloads the new version and builds this game folder again from the "
                   L"game files it keeps. That takes about as long as your first build. Your saves and settings stay.\n\n"
                   L"Yes: update now\nNo: not now (asked again next time)\nCancel: skip this version",
                   wtag, whave);
    else
        _snwprintf(text, 2048,
                   L"A new version of Hookshot is out: %ls (this game is %ls).\n\n"
                   L"The Hookshot Builder that made this folder was not found, so it can't update by itself. Open the download page?\n\n"
                   L"Yes: open the page\nNo: not now (asked again next time)\nCancel: skip this version",
                   wtag, whave);
    const int answer = MessageBoxW(NULL, text, L"Hookshot update", MB_YESNOCANCEL | MB_ICONINFORMATION | MB_TOPMOST | MB_SETFOREGROUND);
    if (answer == IDCANCEL) {
        wchar_t user[MAX_PATH + 16];
        _snwprintf(user, MAX_PATH + 16, L"%ls\\user", dir);
        CreateDirectoryW(user, NULL);
        _snwprintf(file, MAX_PATH + 64, L"%ls\\user\\hookshot_update_skip.txt", dir);
        /* (not through a link or a junction: the user folder or the file put there in its place would have the write
           land somewhere else) */
        const DWORD ua = GetFileAttributesW(user), fa = GetFileAttributesW(file);
        FILE *f = ua != INVALID_FILE_ATTRIBUTES && (ua & FILE_ATTRIBUTE_DIRECTORY) && !is_link(user, ua) &&
                          (fa == INVALID_FILE_ATTRIBUTES || (!(fa & FILE_ATTRIBUTE_DIRECTORY) && !is_link(file, fa)))
                      ? _wfopen(file, L"wb")
                      : NULL;
        if (f) fprintf(f, "skip=%s\n", tag), fclose(f);
        return;
    }
    if (answer != IDYES) return;
    if (!has_builder) {
        ShellExecuteW(NULL, L"open", RELEASES_PAGE, NULL, NULL, SW_SHOWNORMAL);
        return;
    }
    wchar_t args[MAX_PATH + 1280], wdir[MAX_PATH];
    _snwprintf(args, MAX_PATH + 1280, L"%ls%ls--update \"%ls\" --tag \"%ls\"", wbargs, wbargs[0] ? L" " : L"", dir, wtag);
    wcsncpy(wdir, wbuilder, MAX_PATH);
    wdir[MAX_PATH - 1] = 0;
    wchar_t *slash = wcsrchr(wdir, L'\\');
    if (slash) *slash = 0;
    /* (hookshot) the builder gets the game's environment without what hookshot_env.txt set (set_by_env_file); put back
       if it does not start, as the game then plays on */
    const char *names = hos_env_file_names();
    size_t room = 1;
    for (const char *nm = names; nm && *nm; nm += strlen(nm) + 1) room += strlen(nm) + 2 + (getenv(nm) ? strlen(getenv(nm)) : 0);
    char *kept = (char *)malloc(room);
    size_t used = 0;
    for (const char *nm = names; kept && nm && *nm; nm += strlen(nm) + 1) {
        const char *v = getenv(nm);
        if (!v) continue;
        used += (size_t)sprintf(kept + used, "%s=%s", nm, v) + 1;   /* (room counted above) */
        char gone[520];
        if (snprintf(gone, sizeof gone, "%s=", nm) < (int)sizeof gone) _putenv(gone);
    }
    if ((INT_PTR)ShellExecuteW(NULL, L"open", wbuilder, args, slash ? wdir : NULL, SW_SHOWNORMAL) > 32) {
        void hos_log_flush(void);
        hos_log_flush();   /* (the lines logged before, queued: host/hos_thread.c log_queue) */
        fprintf(stderr, "update: Hookshot Builder started to update to %s; the game closes\n", tag);
        fflush(stderr);
        ExitProcess(0);
    }
    for (size_t at = 0; kept && at < used; at += strlen(kept + at) + 1) _putenv(kept + at);
    free(kept);   /* (_putenv copies) */
    MessageBoxW(NULL, L"Hookshot Builder could not be started. The game starts as it is.", L"Hookshot update", MB_OK | MB_ICONWARNING | MB_TOPMOST);
}
#elif defined(__linux__)
#include "hos_paths.h"
#include <ctype.h>
#include <fcntl.h>
const char *hos_env_file_names(void);   /* (host/hos_main.c: what hookshot_env.txt set) */
#include <sys/stat.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* (the same offer as Windows, when the player started bin/hookshot itself. The launcher sets HOOKSHOT_NO_UPDATE_CHECK
   and asks in its own window. curl and zenity do the network and the question; without either, the game just starts) */

/* "Skip this version" is kept with the saves, where they are (hos_main.c sets it first: $XDG_DATA_HOME/hookshot, or
   --user's folder). It was written to user/ beside the game, as on Windows, where Linux keeps no saves any more: the
   start's move of an old user/ folder (saves_dir) took the file for one, moved it to the saves' place and wrote
   saves-moved.txt, so the next start asked again. Skipped again, the file was in both places, which the move reads as
   saves it cannot move: the game then ran on the empty user/ beside it and showed no saves. */
extern const char *hos_user_dir;

static int read_value(const char *path, const char *name, char *out, size_t cap) {
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    char line[1024];
    const size_t n = strlen(name);
    int found = 0;
    while (!found && fgets(line, sizeof line, f)) {
        char *s = line;
        if (strncmp(s, name, n) || s[n] != '=') continue;
        s += n + 1;
        size_t len = strlen(s);
        while (len && (s[len - 1] == '\n' || s[len - 1] == '\r' || s[len - 1] == ' ')) s[--len] = 0;
        if (len && len < cap) memcpy(out, s, len + 1), found = 1;
    }
    fclose(f);
    return found;
}


/* a command's output (malloc'd, at most 1 MB), NULL when it printed nothing */
static char *pipe_body(const char *cmd) {
    FILE *p = popen(cmd, "r");
    if (!p) return NULL;
    const size_t max = 1 << 20;
    char *buf = (char *)malloc(max + 1);
    size_t n = 0, got;
    while (buf && n < max && (got = fread(buf + n, 1, max - n, p)) > 0) n += got;
    pclose(p);
    if (buf && !n) free(buf), buf = NULL;
    if (buf) buf[n] = 0;
    return buf;
}

static int pipe_tag(const char *cmd, char *tag, size_t cap, int newest) {
    char *body = pipe_body(cmd);
    if (!body) return 0;
    const int ok = newest ? newest_tag(body, tag, cap) : tag_in(body, tag, cap);
    free(body);
    return ok;
}

static int latest_tag(const char *have, char *tag, size_t cap) {
    if (nightly_version(have))
        return pipe_tag("curl -fsSL --max-time 8 --retry 2 -A Hookshot-update-check "
                        "https://github.com/NotRexed/Hookshot/releases/download/nightly/hookshot-linux.txt 2>/dev/null", tag, cap, 0);
    if (strchr(have, '-') && pipe_tag("curl -fsSL --max-time 6 --retry 2 -A Hookshot-update-check "
                                      "-H \"Accept: application/vnd.github+json\" "
                                      "'https://api.github.com/repos/NotRexed/Hookshot/releases?per_page=20' 2>/dev/null", tag, cap, 1))
        return 1;
    if (pipe_tag("curl -fsSL --max-time 4 --retry 2 -A Hookshot-update-check "
                 "-H \"Accept: application/vnd.github+json\" "
                 "https://api.github.com/repos/NotRexed/Hookshot/releases/latest 2>/dev/null", tag, cap, 0))
        return 1;
    return pipe_tag("curl -fsSL --max-time 8 --retry 2 -A Hookshot-update-check "
                    "https://github.com/NotRexed/Hookshot/releases/latest/download/hookshot-linux.txt 2>/dev/null", tag, cap, 0);
}

/* the builder an update installed (builder/linux/linux_update.py): <data>/hookshot/builder/versions/<current>/AppRun. The
   builder= line names the AppImage that built the folder, which the player may have deleted since */
static int installed_builder(char *out, size_t cap) {
    const char *home = getenv("HOOKSHOT_BUILDER_HOME"), *data = getenv("XDG_DATA_HOME"), *user = getenv("HOME");
    char root[MAX_PATH * 2], path[MAX_PATH * 2 + 64], tag[128];
    if (home && *home) snprintf(root, sizeof root, "%s/hookshot/builder", home);
    else if (data && *data) snprintf(root, sizeof root, "%s/hookshot/builder", data);
    else if (user && *user) snprintf(root, sizeof root, "%s/.local/share/hookshot/builder", user);
    else return 0;
    snprintf(path, sizeof path, "%s/current", root);
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    const int got = fgets(tag, sizeof tag, f) != NULL;
    fclose(f);
    if (!got) return 0;
    tag[strcspn(tag, "\r\n ")] = 0;
    if (!safe_tag(tag)) return 0;
    if (snprintf(out, cap, "%s/versions/%s/AppRun", root, tag) >= (int)cap) return 0;
    return access(out, X_OK) == 0;
}

/* (hookshot) "Skip this version": <hos_user_dir>/hookshot_update_skip.txt, never written through a link at the file's
   name (a symbolic link put there would have the write truncate what it points to). The saves folder itself may be a
   link: a player can keep it elsewhere */
static int write_skip(const char *path, const char *tag) {
    struct stat st;
    mkdir(hos_user_dir, 0755);
    if (stat(hos_user_dir, &st) != 0 || !S_ISDIR(st.st_mode)) return 0;
    const int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK, 0644);
    if (fd < 0) return 0;
    if (fstat(fd, &st) != 0 || !S_ISREG(st.st_mode)) return close(fd), 0;
    char line[160];
    const int n = snprintf(line, sizeof line, "skip=%s\n", tag);
    const int ok = n > 0 && n < (int)sizeof line && write(fd, line, (size_t)n) == n;
    close(fd);
    return ok;
}

void hos_update_check(void) {
    const char *off = getenv("HOOKSHOT_NO_UPDATE_CHECK");
    if (off && strcmp(off, "0")) return;
    char path[MAX_PATH + 64], have[128], builder[MAX_PATH * 2], skipped[128] = "", tag[128];
    DWORD n = hos_game_path_a(path, MAX_PATH);
    if (!n || n >= MAX_PATH) return;
    while (n && path[n - 1] != '/') n--;
    if (!n) return;
    path[n] = 0;
    char dir[MAX_PATH];
    memcpy(dir, path, n);
    dir[n] = 0;
    snprintf(path, sizeof path, "%shookshot_version.txt", dir);
    if (!read_value(path, "version", have, sizeof have) || !safe_tag(have)) return;
    char skip[MAX_PATH + 64];
    snprintf(skip, sizeof skip, "%s/hookshot_update_skip.txt", hos_user_dir);
    read_value(skip, "skip", skipped, sizeof skipped);
    if (!latest_tag(have, tag, sizeof tag)) {
        fprintf(stderr, "update: the latest release could not be asked for (offline?)\n");
        return;
    }
    fprintf(stderr, "update: this folder is %s, the latest release is %s\n", have, tag);
    if (!strcmp(tag, have) || !strcmp(tag, skipped)) return;
    if (strchr(have, '-') && !nightly_version(have) && !newer_version(tag, have)) return;   /* (a release candidate: newer only) */
    snprintf(path, sizeof path, "%shookshot_version.txt", dir);
    struct stat bst;
    const int has_builder = installed_builder(builder, sizeof builder) ||
                            (read_value(path, "builder", builder, sizeof builder) && builder_ok(builder, NULL, 0) &&
                             stat(builder, &bst) == 0 && S_ISREG(bst.st_mode) && access(builder, X_OK) == 0);
    char text[1600], cmd[4096];
    snprintf(text, sizeof text,
             has_builder
                 ? "A new version of Hookshot is out: %s (this game is %s). Update now? The game closes, and Hookshot Builder downloads only what changed and builds this folder again. Your saves and settings stay."
                 : "A new version of Hookshot is out: %s (this game is %s). The builder that made this folder was not found. Open the download page?",
             tag, have);
    snprintf(cmd, sizeof cmd, "zenity --list --title=Hookshot --hide-header --column= --text='%s' 'Update now' 'Not now' 'Skip this version'", text);
    FILE *pick = popen(cmd, "r");
    if (!pick) return;
    char answer[64] = "";
    if (!fgets(answer, sizeof answer, pick)) answer[0] = 0;
    pclose(pick);
    if (!strncmp(answer, "Skip", 4)) {
        write_skip(skip, tag);
        return;
    }
    if (strncmp(answer, "Update", 6)) return;
    if (!has_builder) {
        if (fork() == 0) {
            execlp("xdg-open", "xdg-open", "https://github.com/NotRexed/Hookshot/releases/latest", (char *)0);
            _exit(127);
        }
        return;
    }
    /* (hookshot) the builder gets the game's environment without what hookshot_env.txt set (set_by_env_file), made here:
       the child only calls execve */
    extern char **environ;
    const char *names = hos_env_file_names();
    size_t count = 0;
    while (environ[count]) count++;
    char **env = malloc((count + 1) * sizeof *env);
    if (!env) return;
    size_t kept = 0;
    for (size_t i = 0; i < count; i++)
        if (!set_by_env_file(environ[i], names)) env[kept++] = environ[i];
    env[kept] = NULL;
    char *const args[] = {builder, "--update", dir, "--tag", tag, NULL};
    pid_t pid = fork();
    if (pid == 0) {
        execve(builder, args, env);
        _exit(127);
    }
    free(env);
    if (pid > 0) {
        fprintf(stderr, "update: Hookshot Builder started to update to %s; the game closes\n", tag);
        fflush(stderr);
        _exit(0);
    }
}
#else
void hos_update_check(void) {}
#endif
