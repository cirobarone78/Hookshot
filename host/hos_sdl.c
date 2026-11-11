/* SDL3 or SDL2 behind one set of calls (hos_sdl.h). Each call is SDL3's or SDL2's, the same work under other names;
   SDL3 returns C's bool where SDL2 returned 0 for success or an SDL_bool, and the events and a few structures are laid
   out differently (both read here at their offsets: SDL_Event is 128 bytes in SDL3, 56 in SDL2). */
#include "hos.h"
#include "hos_sdl.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

static int version;   /* 3, 2, or 0 none */
static struct {
    void *InitSubSystem, *SetHint, *GetError;
    /* window */
    void *CreateWindow, *SetWindowPosition, *SetWindowFullscreen, *SetRelativeMouseMode, *GetPrimaryDisplay,
        *GetDesktopDisplayMode, *Vulkan_CreateSurface, *PixelSize, *GetKeyboardState, *GetMouseState, *WaitEventTimeout,
        *PollEvent, *GetWindowSize, *LoadPNG, *SetWindowIcon, *DestroySurface, *GetWindowDisplay, *GetCurrentDisplayMode;
    /* sound */
    void *OpenAudioDevice, *PauseAudioDevice, *OpenAudioDeviceStream, *ResumeAudioStreamDevice, *PutAudioStreamData;
    /* controllers */
    void *PadOpen, *PadClose, *PadConnected, *PadsUpdate, *PadButton, *PadAxis, *PadName, *PadRumble;
    void *PadType, *PadEffect;   /* (optional: HD rumble, host/pad_sdl.c) */
    void *PadHasSensor, *PadSensorEnable, *PadSensorData;   /* (motion: optional, NULL in an SDL without them) */
    void *GetGamepads, *GetGamepadID, *Free;   /* (SDL3) */
    void *NumJoysticks, *IsGameController, *DeviceInstanceID, *GetJoystick, *JoystickInstanceID;   /* (SDL2) */
} f;
#define CALL(type, fn) ((type)f.fn)

static HMODULE load_one(const char *dll) {   /* beside the executable, else the system's */
    char path[MAX_PATH];
    DWORD n = GetModuleFileNameA(NULL, path, sizeof path);
    while (n && path[n - 1] != '\\' && path[n - 1] != '/') n--;
    snprintf(path + n, sizeof path - n, "%s", dll);
    HMODULE m = n ? LoadLibraryA(path) : NULL;   /* (no folder: a bare name would search the current folder and PATH) */
#ifdef _WIN32   /* (hookshot: else the system's, not the current folder's or PATH's) */
    return m ? m : LoadLibraryExA(dll, NULL, LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
#else
    return m ? m : LoadLibraryA(dll);
#endif
}
static int get_all(HMODULE m, int three) {
#define GET(field, name) if (!(*(FARPROC *)&f.field = GetProcAddress(m, name))) { hos_log("sdl: SDL%d has no %s", three ? 3 : 2, name); return 0; }
#define GET2(field, n3, n2) GET(field, three ? n3 : n2)
    GET(InitSubSystem, "SDL_InitSubSystem");
    GET(SetHint, "SDL_SetHint");
    GET(GetError, "SDL_GetError");
    GET(CreateWindow, "SDL_CreateWindow");
    GET(SetWindowFullscreen, "SDL_SetWindowFullscreen");
    GET2(SetRelativeMouseMode, "SDL_SetWindowRelativeMouseMode", "SDL_SetRelativeMouseMode");
    GET(GetDesktopDisplayMode, "SDL_GetDesktopDisplayMode");
    GET(Vulkan_CreateSurface, "SDL_Vulkan_CreateSurface");
    GET2(PixelSize, "SDL_GetWindowSizeInPixels", "SDL_Vulkan_GetDrawableSize");
    GET(GetKeyboardState, "SDL_GetKeyboardState");
    GET(GetMouseState, "SDL_GetMouseState");
    GET(GetWindowSize, "SDL_GetWindowSize");
    GET(WaitEventTimeout, "SDL_WaitEventTimeout");
    GET(PollEvent, "SDL_PollEvent");
    GET2(PadOpen, "SDL_OpenGamepad", "SDL_GameControllerOpen");
    GET2(PadClose, "SDL_CloseGamepad", "SDL_GameControllerClose");
    GET2(PadConnected, "SDL_GamepadConnected", "SDL_GameControllerGetAttached");
    GET2(PadsUpdate, "SDL_UpdateGamepads", "SDL_GameControllerUpdate");
    GET2(PadButton, "SDL_GetGamepadButton", "SDL_GameControllerGetButton");
    GET2(PadAxis, "SDL_GetGamepadAxis", "SDL_GameControllerGetAxis");
    GET2(PadName, "SDL_GetGamepadName", "SDL_GameControllerName");
    GET2(PadRumble, "SDL_RumbleGamepad", "SDL_GameControllerRumble");
    /* (SDL2 2.0.12 and 2.0.16 on, SDL3 3.2 on: without them every pad keeps the motor rumble) */
    *(FARPROC *)&f.PadType = GetProcAddress(m, three ? "SDL_GetGamepadType" : "SDL_GameControllerGetType");
    *(FARPROC *)&f.PadEffect = GetProcAddress(m, three ? "SDL_SendGamepadEffect" : "SDL_GameControllerSendEffect");
    /* (motion sensors: SDL 2.0.14 on and every SDL3; without them the pads still play, with no gyro) */
    *(FARPROC *)&f.PadHasSensor = GetProcAddress(m, three ? "SDL_GamepadHasSensor" : "SDL_GameControllerHasSensor");
    *(FARPROC *)&f.PadSensorEnable = GetProcAddress(m, three ? "SDL_SetGamepadSensorEnabled" : "SDL_GameControllerSetSensorEnabled");
    *(FARPROC *)&f.PadSensorData = GetProcAddress(m, three ? "SDL_GetGamepadSensorData" : "SDL_GameControllerGetSensorData");
    if (three) {
        GET(SetWindowPosition, "SDL_SetWindowPosition");
        GET(GetPrimaryDisplay, "SDL_GetPrimaryDisplay");
        GET(OpenAudioDeviceStream, "SDL_OpenAudioDeviceStream");
        GET(ResumeAudioStreamDevice, "SDL_ResumeAudioStreamDevice");
        GET(PutAudioStreamData, "SDL_PutAudioStreamData");
        GET(GetGamepads, "SDL_GetGamepads");
        GET(GetGamepadID, "SDL_GetGamepadID");
        GET(Free, "SDL_free");
        *(FARPROC *)&f.LoadPNG = GetProcAddress(m, "SDL_LoadPNG");   /* (3.4 on: the icon, when there) */
        *(FARPROC *)&f.SetWindowIcon = GetProcAddress(m, "SDL_SetWindowIcon");
        *(FARPROC *)&f.DestroySurface = GetProcAddress(m, "SDL_DestroySurface");
        *(FARPROC *)&f.GetWindowDisplay = GetProcAddress(m, "SDL_GetDisplayForWindow");   /* (the refresh: hos_sdl_refresh_mhz) */
        *(FARPROC *)&f.GetCurrentDisplayMode = GetProcAddress(m, "SDL_GetCurrentDisplayMode");
    } else {
        *(FARPROC *)&f.GetWindowDisplay = GetProcAddress(m, "SDL_GetWindowDisplayIndex");   /* (the refresh: hos_sdl_refresh_mhz) */
        *(FARPROC *)&f.GetCurrentDisplayMode = GetProcAddress(m, "SDL_GetCurrentDisplayMode");
        GET(OpenAudioDevice, "SDL_OpenAudioDevice");
        GET(PauseAudioDevice, "SDL_PauseAudioDevice");
        GET(NumJoysticks, "SDL_NumJoysticks");
        GET(IsGameController, "SDL_IsGameController");
        GET(DeviceInstanceID, "SDL_JoystickGetDeviceInstanceID");
        GET(GetJoystick, "SDL_GameControllerGetJoystick");
        GET(JoystickInstanceID, "SDL_JoystickInstanceID");
    }
#undef GET2
#undef GET
    return 1;
}
int hos_sdl_load(void) {
    static volatile LONG state;   /* 0 not tried, 1 loading, 2 done */
    if (InterlockedCompareExchange(&state, 1, 0) == 0) {
        const char *want = getenv("HOS_SDL_VERSION");
        HMODULE m = want && atoi(want) == 2 ? NULL : load_one("SDL3.dll");
        if (m && get_all(m, 1)) version = 3;
        else if ((m = load_one("SDL2.dll")) && get_all(m, 0)) version = 2;
        hos_log(version ? "sdl: SDL%d" : "sdl: no SDL3 or SDL2 found: no window, sound or SDL controllers", version);
        InterlockedExchange(&state, 2);
    }
    while (state != 2) Sleep(0);
    return version;
}

int hos_sdl_init(uint32_t subsystems) {
    if (!hos_sdl_load()) return 0;
    return version == 3 ? CALL(_Bool (*)(uint32_t), InitSubSystem)(subsystems)
                        : CALL(int (*)(uint32_t), InitSubSystem)(subsystems) == 0;
}
void hos_sdl_hint(const char *name, const char *value) {
    if (!hos_sdl_load()) return;
    if (version == 3) CALL(_Bool (*)(const char *, const char *), SetHint)(name, value);
    else CALL(int (*)(const char *, const char *), SetHint)(name, value);
}
void hos_sdl_identity(const char *name, const char *app_id) {
    if (!hos_sdl_load()) return;
    if (version == 3) {
        static void *set;
        if (!set) {
            HMODULE m = load_one("SDL3.dll");   /* (the one loaded: the same handle back) */
            set = m ? (void *)GetProcAddress(m, "SDL_SetAppMetadata") : NULL;
        }
        if (set) ((_Bool (*)(const char *, const char *, const char *))set)(name, NULL, app_id);
        return;
    }
    hos_sdl_hint("SDL_APP_NAME", name);
#ifndef _WIN32   /* (SDL2 reads the window's class from these, not from hints) */
    setenv("SDL_VIDEO_WAYLAND_WMCLASS", app_id, 0);
    setenv("SDL_VIDEO_X11_WMCLASS", app_id, 0);
#endif
}
const char *hos_sdl_error(void) { return version ? CALL(const char *(*)(void), GetError)() : "no SDL"; }

/* ---- the window ---- */
enum { WIN_SHOWN2 = 0x4, WIN_RESIZABLE = 0x20, WIN_HIGH_DENSITY = 0x2000, WIN_VULKAN = 0x10000000, CENTRED = 0x2FFF0000 };
void *hos_sdl_window(const char *title, int width, int height) {
    if (version == 2)
        return CALL(void *(*)(const char *, int, int, int, int, uint32_t), CreateWindow)(
            title, CENTRED, CENTRED, width, height, WIN_SHOWN2 | WIN_RESIZABLE | WIN_HIGH_DENSITY | WIN_VULKAN);
    void *w = CALL(void *(*)(const char *, int, int, uint64_t), CreateWindow)(title, width, height,
                                                                              WIN_RESIZABLE | WIN_HIGH_DENSITY | WIN_VULKAN);
    if (w) CALL(_Bool (*)(void *, int, int), SetWindowPosition)(w, CENTRED, CENTRED);
    return w;
}
void hos_sdl_fullscreen(void *window, int on) {
    if (version == 3) CALL(_Bool (*)(void *, _Bool), SetWindowFullscreen)(window, on != 0);
    else CALL(int (*)(void *, uint32_t), SetWindowFullscreen)(window, on ? 0x1001 /* FULLSCREEN_DESKTOP */ : 0);
}
void hos_sdl_relative_mouse(void *window, int on) {
    if (version == 3) CALL(_Bool (*)(void *, _Bool), SetRelativeMouseMode)(window, on != 0);
    else CALL(int (*)(int), SetRelativeMouseMode)(on);
}
int hos_sdl_desktop_size(int *width, int *height) {
    if (version == 3) {   /* (SDL_DisplayMode: displayID, format, w and h at 8 and 12 in screen units, pixel_density at
                             16: in pixels, as SDL2 gave them) */
        const uint8_t *m = CALL(const uint8_t *(*)(uint32_t), GetDesktopDisplayMode)(CALL(uint32_t (*)(void), GetPrimaryDisplay)());
        if (!m) return 0;
        int w, h;
        float density;
        memcpy(&w, m + 8, 4), memcpy(&h, m + 12, 4), memcpy(&density, m + 16, 4);
        if (!(density > 0)) density = 1;
        *width = (int)(w * density + 0.5f), *height = (int)(h * density + 0.5f);
        return 1;
    }
    struct { uint32_t format; int w, h, refresh_rate; void *driverdata; } m;
    if (CALL(int (*)(int, void *), GetDesktopDisplayMode)(0, &m)) return 0;
    *width = m.w, *height = m.h;
    return 1;
}
int hos_sdl_refresh_mhz(void *window) {
    if (!window || !f.GetWindowDisplay || !f.GetCurrentDisplayMode) return 0;
    float hz = 0;
    if (version == 3) {   /* (SDL_DisplayMode: refresh_rate, a float, at 20) */
        const uint32_t id = CALL(uint32_t (*)(void *), GetWindowDisplay)(window);
        const uint8_t *m = id ? CALL(const uint8_t *(*)(uint32_t), GetCurrentDisplayMode)(id) : NULL;
        if (m) memcpy(&hz, m + 20, 4);
    } else {
        const int index = CALL(int (*)(void *), GetWindowDisplay)(window);
        struct { uint32_t format; int w, h, refresh_rate; void *driverdata; } m;
        if (index >= 0 && CALL(int (*)(int, void *), GetCurrentDisplayMode)(index, &m) == 0) hz = (float)m.refresh_rate;
    }
    return hz > 1 && hz < 1000 ? (int)(hz * 1000 + 0.5f) : 0;
}
int hos_sdl_vulkan_surface(void *window, void *instance, void *surface_out) {
    return version == 3 ? CALL(_Bool (*)(void *, void *, const void *, void *), Vulkan_CreateSurface)(window, instance, NULL, surface_out)
                        : CALL(int (*)(void *, void *, void *), Vulkan_CreateSurface)(window, instance, surface_out) != 0;
}
void hos_sdl_pixel_size(void *window, int *width, int *height) {
    if (version == 3) CALL(_Bool (*)(void *, int *, int *), PixelSize)(window, width, height);
    else CALL(void (*)(void *, int *, int *), PixelSize)(window, width, height);
}
const uint8_t *hos_sdl_keys(int *count) {   /* (SDL3's bool and SDL2's Uint8: a byte each) */
    return CALL(const uint8_t *(*)(int *), GetKeyboardState)(count);
}
void hos_sdl_icon(void *window, const char *png) {
    if (version != 3 || !f.LoadPNG || !f.SetWindowIcon || !f.DestroySurface) return;
    void *icon = CALL(void *(*)(const char *), LoadPNG)(png);
    if (!icon) return;
    CALL(_Bool (*)(void *, void *), SetWindowIcon)(window, icon);
    CALL(void (*)(void *), DestroySurface)(icon);
}
uint32_t hos_sdl_mouse_buttons(void) {
    return version == 3 ? CALL(uint32_t (*)(float *, float *), GetMouseState)(NULL, NULL)
                        : CALL(uint32_t (*)(int *, int *), GetMouseState)(NULL, NULL);
}
void hos_sdl_mouse_position(float *x, float *y) {
    if (version == 3) CALL(uint32_t (*)(float *, float *), GetMouseState)(x, y);
    else {
        int ix = 0, iy = 0;
        CALL(uint32_t (*)(int *, int *), GetMouseState)(&ix, &iy);
        *x = (float)ix, *y = (float)iy;
    }
}
void hos_sdl_window_size(void *window, int *width, int *height) {
    if (version == 3) CALL(_Bool (*)(void *, int *, int *), GetWindowSize)(window, width, height);
    else CALL(void (*)(void *, int *, int *), GetWindowSize)(window, width, height);
}

/* ---- events ---- */
static void read_event(const uint8_t *raw, HosSdlEvent *e) {
    uint32_t type;
    memcpy(&type, raw, 4);
    memset(e, 0, sizeof *e);
    int32_t i[2];
    if (version == 3) {
        switch (type) {
        case 0x100: e->type = HOS_SDL_EV_QUIT; break;
        case 0x207: e->type = HOS_SDL_EV_RESIZED; break;   /* (PIXEL_SIZE_CHANGED) */
        case 0x20d: e->type = HOS_SDL_EV_MOUSE_LEAVE; break;
        case 0x20e: e->type = HOS_SDL_EV_FOCUS_GAINED; break;
        case 0x20f: e->type = HOS_SDL_EV_FOCUS_LOST; break;
        case 0x210: e->type = HOS_SDL_EV_CLOSE; break;
        case 0x300:   /* (SDL_KeyboardEvent: scancode at 24, mod at 32, repeat at 37) */
            e->type = HOS_SDL_EV_KEY_DOWN;
            memcpy(i, raw + 24, 4), e->scancode = i[0];
            memcpy(&e->mod, raw + 32, 2), e->repeat = raw[37];
            break;
        case 0x20c: e->type = HOS_SDL_EV_MOUSE_ENTER; break;
        case 0x400:   /* (SDL_MouseMotionEvent: x and y at 28 and 32, xrel and yrel at 36 and 40, floats) */
            e->type = HOS_SDL_EV_MOUSE_MOTION;
            memcpy(&e->x, raw + 28, 4), memcpy(&e->y, raw + 32, 4);
            memcpy(&e->dx, raw + 36, 4), memcpy(&e->dy, raw + 40, 4);
            break;
        case 0x401:
        case 0x402:   /* (SDL_MouseButtonEvent: button at 24, x and y at 28 and 32, floats) */
            e->type = type == 0x401 ? HOS_SDL_EV_MOUSE_DOWN : HOS_SDL_EV_MOUSE_UP;
            e->button = raw[24];
            memcpy(&e->x, raw + 28, 4), memcpy(&e->y, raw + 32, 4);
            break;
        case 0x403: {   /* (SDL_MouseWheelEvent: y at 28, a float; direction at 32, 1 flipped) */
            uint32_t dir;
            e->type = HOS_SDL_EV_MOUSE_WHEEL;
            memcpy(&e->wheel, raw + 28, 4), memcpy(&dir, raw + 32, 4);
            if (dir == 1) e->wheel = -e->wheel;
            break;
        }
        }
        return;
    }
    switch (type) {
    case 0x100: e->type = HOS_SDL_EV_QUIT; break;
    case 0x200:   /* (SDL_WindowEvent: what at 12) */
        e->type = raw[12] == 6 ? HOS_SDL_EV_RESIZED : raw[12] == 10 ? HOS_SDL_EV_MOUSE_ENTER : raw[12] == 11 ? HOS_SDL_EV_MOUSE_LEAVE
                : raw[12] == 12 ? HOS_SDL_EV_FOCUS_GAINED : raw[12] == 13 ? HOS_SDL_EV_FOCUS_LOST
                : raw[12] == 14 ? HOS_SDL_EV_CLOSE : HOS_SDL_EV_OTHER;
        break;
    case 0x300:   /* (SDL_KeyboardEvent: repeat at 13, scancode at 16, mod at 24) */
        e->type = HOS_SDL_EV_KEY_DOWN;
        memcpy(i, raw + 16, 4), e->scancode = i[0];
        memcpy(&e->mod, raw + 24, 2), e->repeat = raw[13];
        break;
    case 0x400:   /* (SDL_MouseMotionEvent: x and y at 20 and 24, xrel and yrel at 28 and 32, whole pixels) */
        e->type = HOS_SDL_EV_MOUSE_MOTION;
        memcpy(i, raw + 20, 8), e->x = (float)i[0], e->y = (float)i[1];
        memcpy(i, raw + 28, 8), e->dx = (float)i[0], e->dy = (float)i[1];
        break;
    case 0x401:
    case 0x402:   /* (SDL_MouseButtonEvent: button at 16, x and y at 20 and 24, whole pixels) */
        e->type = type == 0x401 ? HOS_SDL_EV_MOUSE_DOWN : HOS_SDL_EV_MOUSE_UP;
        e->button = raw[16];
        memcpy(i, raw + 20, 8), e->x = (float)i[0], e->y = (float)i[1];
        break;
    case 0x403: {   /* (SDL_MouseWheelEvent: y at 20, whole notches; direction at 24, 1 flipped) */
        uint32_t dir;
        e->type = HOS_SDL_EV_MOUSE_WHEEL;
        memcpy(i, raw + 20, 4), memcpy(&dir, raw + 24, 4);
        e->wheel = (float)(dir == 1 ? -i[0] : i[0]);
        break;
    }
    }
}
int hos_sdl_wait_event(HosSdlEvent *e, int timeout_ms) {
    _Alignas(8) uint8_t raw[128];
    const int got = version == 3 ? CALL(_Bool (*)(void *, int32_t), WaitEventTimeout)(raw, timeout_ms)
                                 : CALL(int (*)(void *, int), WaitEventTimeout)(raw, timeout_ms) != 0;
    if (got) read_event(raw, e);
    return got;
}
int hos_sdl_poll_event(HosSdlEvent *e) {
    _Alignas(8) uint8_t raw[128];
    const int got = version == 3 ? CALL(_Bool (*)(void *), PollEvent)(raw) : CALL(int (*)(void *), PollEvent)(raw) != 0;
    if (got) read_event(raw, e);
    return got;
}

/* ---- sound ---- */
typedef struct {
    void (*pull)(void *user, uint8_t *out, int len);
    void *user;
    int frame;   /* bytes a sample frame (all channels) */
} Pull;
static void pull3(void *p, void *stream, int want, int total) {   /* (SDL3: a stream asks for want more bytes) */
    (void)total;
    const Pull *s = (const Pull *)p;
    uint8_t buf[4096];
    /* whole sample frames at a time: SDL3 takes no part of one (4096 bytes is not whole 5.1 frames, 12 bytes each:
       every piece was refused and 5.1 played silence) */
    const int most = (int)sizeof buf / s->frame * s->frame;
    for (int n; want > 0; want -= n) {
        n = want < most ? want : most;
        s->pull(s->user, buf, n);
        CALL(_Bool (*)(void *, const void *, int), PutAudioStreamData)(stream, buf, n);
    }
}
static void pull2(void *p, uint8_t *out, int len) {   /* (SDL2: a device callback fills its buffer) */
    const Pull *s = (const Pull *)p;
    s->pull(s->user, out, len);
}
int hos_sdl_audio_open(int freq, int channels, int s16, void (*pull)(void *user, uint8_t *out, int len), void *user) {
    if (!hos_sdl_load()) return 0;
    const uint16_t format = s16 ? 0x8010 /* S16LE */ : 0x8120 /* F32LE */;   /* (both's numbers) */
    const char *env_samples = getenv("SDL_AUDIO_DEVICE_SAMPLE_FRAMES");
    if (version == 3 && !env_samples) hos_sdl_hint("SDL_AUDIO_DEVICE_SAMPLE_FRAMES", "480");   /* (SDL2's device buffer below) */
    if (!hos_sdl_init(HOS_SDL_AUDIO)) return 0;
    Pull *p = (Pull *)calloc(1, sizeof *p);
    p->pull = pull, p->user = user, p->frame = channels * (s16 ? 2 : 4);
    if (version == 3) {
        const struct { uint32_t format; int channels, freq; } spec = {format, channels, freq};
        void *stream = CALL(void *(*)(uint32_t, const void *, void (*)(void *, void *, int, int), void *), OpenAudioDeviceStream)(
            0xFFFFFFFFu /* the default output */, &spec, pull3, p);
        if (stream && CALL(_Bool (*)(void *), ResumeAudioStreamDevice)(stream)) return 1;
        free(p);
        return 0;
    }
    struct {
        int freq;
        uint16_t format;
        uint8_t channels, silence;
        uint16_t samples, padding;
        uint32_t size;
        void (*callback)(void *, uint8_t *, int);
        void *userdata;
    } want, have;
    memset(&want, 0, sizeof want);
    want.freq = freq, want.format = format, want.channels = (uint8_t)channels;
    want.samples = (uint16_t)(env_samples && atoi(env_samples) > 0 ? atoi(env_samples) : 512);   /* (SDL2 asks for a power of two) */
    want.callback = pull2, want.userdata = p;
    /* (no changes allowed: SDL converts to what the device wants) */
    const uint32_t dev = CALL(uint32_t (*)(const char *, int, const void *, void *, int), OpenAudioDevice)(NULL, 0, &want, &have, 0);
    if (!dev) {
        free(p);
        return 0;
    }
    CALL(void (*)(uint32_t, int), PauseAudioDevice)(dev, 0);
    return 1;
}
/* SDL3's format of the default device; SDL2's default audio info (2.24 on: the bundled 2.32 has it). Looked up here,
   not at load: an SDL without it still plays, in stereo. */
int hos_sdl_audio_channels(void) {
    if (!hos_sdl_load() || !hos_sdl_init(HOS_SDL_AUDIO)) return 2;
    HMODULE m = load_one(version == 3 ? "SDL3.dll" : "SDL2.dll");   /* (the one loaded: the same handle back) */
    if (!m) return 2;
    int n = 0;
    if (version == 3) {
        void *get = (void *)GetProcAddress(m, "SDL_GetAudioDeviceFormat");
        struct { uint32_t format; int channels, freq; } spec = {0, 0, 0};
        int frames = 0;
        if (get && ((_Bool (*)(uint32_t, void *, int *))get)(0xFFFFFFFFu /* the default output */, &spec, &frames))
            n = spec.channels;
    } else {
        void *get = (void *)GetProcAddress(m, "SDL_GetDefaultAudioInfo"), *release = (void *)GetProcAddress(m, "SDL_free");
        struct {
            int freq;
            uint16_t format;
            uint8_t channels, silence;
            uint16_t samples, padding;
            uint32_t size;
            void *callback, *userdata;
        } spec;
        memset(&spec, 0, sizeof spec);
        char *name = NULL;
        if (get && ((int (*)(char **, void *, int))get)(&name, &spec, 0) == 0) n = spec.channels;
        if (name && release) ((void (*)(void *))release)(name);
    }
    return n > 0 ? n : 2;
}

/* ---- (hookshot) microphones: SDL3's recording devices, or SDL2's capture devices (the Linux AppImage carries SDL2): a
   stream each opened, in the format asked for, read as the game asks ---- */
static struct {
    void *GetDevices, *DeviceName, *Available, *GetData, *Clear, *Destroy, *DeviceFormat;   /* (SDL3) */
    void *CreateStream, *Put;   /* (SDL3: the Windows raw path's conversion, below) */
    void *NumDevices, *DeviceName2, *CloseDevice, *LockDevice, *UnlockDevice;   /* (SDL2) */
    int tried, ok;
} rec;
#define REC_GET(field, name) (*(FARPROC *)&rec.field = GetProcAddress(m, name))
static int rec_ready(void) {
    if (!hos_sdl_load()) return 0;
    if (!rec.tried) {
        rec.tried = 1;
        HMODULE m = load_one(version == 3 ? "SDL3.dll" : "SDL2.dll");   /* (the one loaded: the same handle back) */
        if (m && version == 3) {
            REC_GET(GetDevices, "SDL_GetAudioRecordingDevices"), REC_GET(DeviceName, "SDL_GetAudioDeviceName");
            REC_GET(Available, "SDL_GetAudioStreamAvailable"), REC_GET(GetData, "SDL_GetAudioStreamData");
            REC_GET(Clear, "SDL_ClearAudioStream"), REC_GET(Destroy, "SDL_DestroyAudioStream");
            REC_GET(DeviceFormat, "SDL_GetAudioDeviceFormat");   /* (optional: the device's own channels) */
            REC_GET(CreateStream, "SDL_CreateAudioStream"), REC_GET(Put, "SDL_PutAudioStreamData");   /* (optional) */
            rec.ok = rec.GetDevices && rec.DeviceName && rec.Available && rec.GetData && rec.Clear && rec.Destroy;
        } else if (m) {
            REC_GET(NumDevices, "SDL_GetNumAudioDevices"), REC_GET(DeviceName2, "SDL_GetAudioDeviceName");
            REC_GET(CloseDevice, "SDL_CloseAudioDevice"), REC_GET(LockDevice, "SDL_LockAudioDevice");
            REC_GET(UnlockDevice, "SDL_UnlockAudioDevice");
            rec.ok = rec.NumDevices && rec.DeviceName2 && rec.CloseDevice && rec.LockDevice && rec.UnlockDevice;
        }
        if (!rec.ok) hos_log("sdl: no recording functions: no microphone");
    }
    return rec.ok && hos_sdl_init(HOS_SDL_AUDIO);
}
#undef REC_GET
/* SDL2: the capture callback fills a ring of about a second, the oldest dropped when full; read under the device's lock */
typedef struct {
    uint32_t dev;
    uint8_t *ring;
    int cap, start, len;
} Mic2;
static void mic2_push(void *user, uint8_t *in, int n) {   /* (SDL2's audio thread, the device locked) */
    Mic2 *m = (Mic2 *)user;
    if (n > m->cap) in += n - m->cap, n = m->cap;
    const int drop = m->len + n - m->cap;
    if (drop > 0) m->start = (m->start + drop) % m->cap, m->len -= drop;
    const int at = (m->start + m->len) % m->cap, first = n < m->cap - at ? n : m->cap - at;
    memcpy(m->ring + at, in, (size_t)first);
    memcpy(m->ring, in + first, (size_t)(n - first));
    m->len += n;
}
static void mic2_lock(Mic2 *m, int on) { ((void (*)(uint32_t))(on ? rec.LockDevice : rec.UnlockDevice))(m->dev); }

int hos_sdl_mic_list(uint32_t *ids, char (*names)[128], int max) {
    if (!rec_ready()) return 0;
    int n = 0;
    if (version == 2) {   /* (SDL2 names them by index: the id is the index + 1, 0 the default) */
        const int count = ((int (*)(int))rec.NumDevices)(1);
        for (int i = 0; i < count && n < max; i++, n++) {
            const char *name = ((const char *(*)(int, int))rec.DeviceName2)(i, 1);
            ids[n] = (uint32_t)i + 1;
            snprintf(names[n], 128, "%s", name ? name : "Microphone");
        }
        return n;
    }
    int count = 0;
    uint32_t *all = ((uint32_t *(*)(int *))rec.GetDevices)(&count);
    for (int i = 0; all && i < count && n < max; i++, n++) {
        const char *name = ((const char *(*)(uint32_t))rec.DeviceName)(all[i]);
        ids[n] = all[i];
        snprintf(names[n], 128, "%s", name ? name : "Microphone");
    }
    if (all) CALL(void (*)(void *), Free)(all);
    return n;
}
/* ---- (hookshot) Windows: the microphone through WASAPI's raw stream (AUDCLNT_STREAMOPTIONS_RAW: every channel of the
   device, no capture effects), its sound converted by an SDL audio stream to the format asked for. SDL's own recording
   opens the processed stream, whatever SDL_AUDIO_DEVICE_RAW_STREAM says (SDL 3.4.20: a Focusrite Scarlett Solo opened as
   2 channels at 48 kHz, both its first, silent input, while the microphone was on its second: the ocarina heard nothing).
   A thread a microphone reads the device into the stream; the caller reads the stream as it reads SDL's. Found by the
   name SDL lists it under (the endpoint's friendly name); one that cannot be had this way, HOS_MIC_RAW=0, or SDL2: SDL's
   own, as before ---- */
#ifdef _WIN32
#include <objbase.h>
#include <mmreg.h>
#include <mmdeviceapi.h>
#include <audioclient.h>

static const GUID was_clsid_enum = {0xbcde0395, 0xe52f, 0x467c, {0x8e, 0x3d, 0xc4, 0x57, 0x92, 0x91, 0x69, 0x2e}};
static const GUID was_iid_enum = {0xa95664d2, 0x9614, 0x4f35, {0xa7, 0x46, 0xde, 0x8d, 0xb6, 0x36, 0x17, 0xe6}};
static const GUID was_iid_client2 = {0x726778cd, 0xf60a, 0x4eda, {0x82, 0xde, 0xe4, 0x76, 0x10, 0xcd, 0x78, 0xaa}};
static const GUID was_iid_capture = {0xc8adbd64, 0xe71e, 0x48a0, {0xa4, 0xde, 0x18, 0x5c, 0x39, 0x5c, 0xd3, 0x17}};
static const GUID was_float = {0x00000003, 0x0000, 0x0010, {0x80, 0x00, 0x00, 0xaa, 0x00, 0x38, 0x9b, 0x71}};
static const PROPERTYKEY was_name_key = {{0xa45c254e, 0xdf1c, 0x4efd, {0x80, 0x20, 0x67, 0xd1, 0x46, 0xa8, 0x50, 0xe0}}, 14};

static int was_wanted(void) {   /* (SDL3, with the conversion it needs, and not HOS_MIC_RAW=0) */
    static int raw = -1;
    if (raw < 0) raw = !getenv("HOS_MIC_RAW") || strcmp(getenv("HOS_MIC_RAW"), "0");
    return raw && version == 3 && rec.CreateStream && rec.Put && rec.DeviceName;
}
/* the endpoint of SDL's recording device id (0: the default), by the name SDL gives it; NULL none */
static IMMDevice *was_device(IMMDeviceEnumerator *e, uint32_t id) {
    IMMDevice *d = NULL;
    if (!id) {
        if (FAILED(e->lpVtbl->GetDefaultAudioEndpoint(e, eCapture, eConsole, &d))) d = NULL;
        return d;
    }
    const char *want = ((const char *(*)(uint32_t))rec.DeviceName)(id);
    IMMDeviceCollection *all = NULL;
    UINT n = 0;
    if (!want || FAILED(e->lpVtbl->EnumAudioEndpoints(e, eCapture, DEVICE_STATE_ACTIVE, &all)) || !all) return NULL;
    all->lpVtbl->GetCount(all, &n);
    for (UINT i = 0; i < n && !d; i++) {
        IMMDevice *x = NULL;
        if (FAILED(all->lpVtbl->Item(all, i, &x)) || !x) continue;
        char name[256] = "";
        IPropertyStore *ps = NULL;
        if (SUCCEEDED(x->lpVtbl->OpenPropertyStore(x, STGM_READ, &ps)) && ps) {
            PROPVARIANT v;
            memset(&v, 0, sizeof v);
            if (SUCCEEDED(ps->lpVtbl->GetValue(ps, &was_name_key, &v)) && v.vt == VT_LPWSTR && v.pwszVal)
                WideCharToMultiByte(CP_UTF8, 0, v.pwszVal, -1, name, (int)sizeof name, NULL, NULL);
            PropVariantClear(&v);
            ps->lpVtbl->Release(ps);
        }
        if (!strcmp(name, want)) d = x;   /* (of two with one name: the first) */
        else x->lpVtbl->Release(x);
    }
    all->lpVtbl->Release(all);
    return d;
}
/* the device's client, asked for the raw stream (refused: the processed one), and its format then */
static IAudioClient2 *was_client(IMMDevice *d, WAVEFORMATEX **mix) {
    IAudioClient2 *a = NULL;
    *mix = NULL;
    if (FAILED(d->lpVtbl->Activate(d, &was_iid_client2, CLSCTX_ALL, NULL, (void **)&a)) || !a) return NULL;
    AudioClientProperties props;
    memset(&props, 0, sizeof props);
    props.cbSize = sizeof props, props.eCategory = AudioCategory_Other, props.Options = AUDCLNT_STREAMOPTIONS_RAW;
    a->lpVtbl->SetClientProperties(a, &props);
    if (FAILED(a->lpVtbl->GetMixFormat(a, mix)) || !*mix) {
        a->lpVtbl->Release(a);
        return NULL;
    }
    return a;
}
/* the SDL_AudioFormat of a WASAPI format (0: not one this takes); *packed24: 3-byte samples, given to SDL as 32-bit */
static uint32_t was_format(const WAVEFORMATEX *m, int *packed24) {
    const int is_float = m->wFormatTag == WAVE_FORMAT_IEEE_FLOAT ||
                         (m->wFormatTag == WAVE_FORMAT_EXTENSIBLE &&
                          !memcmp(&((const WAVEFORMATEXTENSIBLE *)m)->SubFormat, &was_float, sizeof(GUID)));
    *packed24 = 0;
    if (is_float) return m->wBitsPerSample == 32 ? 0x8120 : 0;
    if (m->wBitsPerSample == 16) return 0x8010;
    if (m->wBitsPerSample == 32) return 0x8020;
    if (m->wBitsPerSample == 24) return *packed24 = 1, 0x8020;
    return 0;
}
/* the raw stream's channels, 1 to 8 (0: not to be had this way) */
static int was_channels(uint32_t id) {
    const HRESULT com = CoInitializeEx(NULL, COINIT_MULTITHREADED);   /* (a thread in another apartment keeps it) */
    int n = 0;
    IMMDeviceEnumerator *e = NULL;
    if (SUCCEEDED(CoCreateInstance(&was_clsid_enum, NULL, CLSCTX_ALL, &was_iid_enum, (void **)&e)) && e) {
        IMMDevice *d = was_device(e, id);
        if (d) {
            WAVEFORMATEX *mix = NULL;
            IAudioClient2 *a = was_client(d, &mix);
            int packed24;
            if (a && was_format(mix, &packed24)) n = mix->nChannels >= 1 && mix->nChannels <= 8 ? mix->nChannels : 0;
            if (mix) CoTaskMemFree(mix);
            if (a) a->lpVtbl->Release(a);
            d->lpVtbl->Release(d);
        }
        e->lpVtbl->Release(e);
    }
    if (SUCCEEDED(com)) CoUninitialize();
    return n;
}

typedef struct {
    void *stream;                /* the SDL_AudioStream the caller reads: the device's format in, the asked one out */
    uint32_t id;                 /* (what was asked: SDL's id, the format) */
    int freq, channels;
    uint16_t format;
    HANDLE thread, ready;
    volatile LONG stop;
    volatile LONG ok;            /* (the thread's word: started) */
} WasMic;
#define WAS_MAX 8
static WasMic *was_mics[WAS_MAX];
static SRWLOCK was_lock = SRWLOCK_INIT;
static WasMic *was_of(void *mic) {
    WasMic *w = NULL;
    AcquireSRWLockShared(&was_lock);
    for (int i = 0; i < WAS_MAX && !w; i++)
        if (was_mics[i] && was_mics[i] == mic) w = was_mics[i];
    ReleaseSRWLockShared(&was_lock);
    return w;
}
/* the thread of a microphone: opened, then what it records put into the stream every 5 ms until stopped (the device gone:
   nothing more comes, and host/nn_audio_in.c takes it as stopped sending) */
static DWORD WINAPI was_run(void *arg) {
    WasMic *w = (WasMic *)arg;
    const HRESULT com = CoInitializeEx(NULL, COINIT_MULTITHREADED);
    IMMDeviceEnumerator *e = NULL;
    IMMDevice *d = NULL;
    IAudioClient2 *a = NULL;
    IAudioCaptureClient *cap = NULL;
    WAVEFORMATEX *mix = NULL;
    int packed24 = 0;
    uint32_t fmt = 0;
    if (SUCCEEDED(CoCreateInstance(&was_clsid_enum, NULL, CLSCTX_ALL, &was_iid_enum, (void **)&e)) && e) d = was_device(e, w->id);
    if (d) a = was_client(d, &mix);
    if (a) fmt = was_format(mix, &packed24);
    if (fmt && SUCCEEDED(a->lpVtbl->Initialize(a, AUDCLNT_SHAREMODE_SHARED, 0, 10000000 /* 1 s */, 0, mix, NULL)) &&
        SUCCEEDED(a->lpVtbl->GetService(a, &was_iid_capture, (void **)&cap)) && cap) {
        const struct { uint32_t format; int channels, freq; } src = {fmt, mix->nChannels, (int)mix->nSamplesPerSec},
                                                             dst = {w->format, w->channels, w->freq};
        w->stream = ((void *(*)(const void *, const void *))rec.CreateStream)(&src, &dst);
        if (w->stream && SUCCEEDED(a->lpVtbl->Start(a))) InterlockedExchange(&w->ok, 1);
    }
    SetEvent(w->ready);
    const int block = mix ? mix->nBlockAlign : 0;
    static const uint8_t zeros[4096];
    while (w->ok && !w->stop) {
        Sleep(5);
        UINT32 frames = 0;
        BYTE *data = NULL;
        DWORD flags = 0;
        HRESULT hr;
        while (SUCCEEDED(hr = cap->lpVtbl->GetBuffer(cap, &data, &frames, &flags, NULL, NULL)) && frames) {
            int bytes = (int)frames * block;
            if (flags & AUDCLNT_BUFFERFLAGS_SILENT) {   /* (silence: its frames as zeros) */
                const int out = packed24 ? bytes / 3 * 4 : bytes;
                for (int done = 0; done < out;) {
                    const int n = out - done < (int)sizeof zeros ? out - done : (int)sizeof zeros;
                    ((_Bool (*)(void *, const void *, int))rec.Put)(w->stream, zeros, n), done += n;
                }
            } else if (packed24) {   /* (3-byte samples to 32-bit ones, a piece at a time) */
                int32_t wide[1024];
                for (int at = 0; at + 3 <= bytes;) {
                    int k = 0;
                    for (; k < 1024 && at + 3 <= bytes; k++, at += 3)
                        wide[k] = (int32_t)((uint32_t)data[at] << 8 | (uint32_t)data[at + 1] << 16 | (uint32_t)data[at + 2] << 24);
                    ((_Bool (*)(void *, const void *, int))rec.Put)(w->stream, wide, k * 4);
                }
            } else {
                ((_Bool (*)(void *, const void *, int))rec.Put)(w->stream, data, bytes);
            }
            cap->lpVtbl->ReleaseBuffer(cap, frames);
        }
        if (FAILED(hr)) break;   /* (the device gone, or another format: no more sound) */
    }
    if (a && w->ok) a->lpVtbl->Stop(a);
    if (cap) cap->lpVtbl->Release(cap);
    if (a) a->lpVtbl->Release(a);
    if (mix) CoTaskMemFree(mix);
    if (d) d->lpVtbl->Release(d);
    if (e) e->lpVtbl->Release(e);
    if (SUCCEEDED(com)) CoUninitialize();
    return 0;
}
static void was_close(WasMic *w) {
    AcquireSRWLockExclusive(&was_lock);
    for (int i = 0; i < WAS_MAX; i++)
        if (was_mics[i] == w) was_mics[i] = NULL;
    ReleaseSRWLockExclusive(&was_lock);
    InterlockedExchange(&w->stop, 1);
    WaitForSingleObject(w->thread, INFINITE);   /* (it sleeps 5 ms at a time) */
    CloseHandle(w->thread), CloseHandle(w->ready);
    if (w->stream) ((void (*)(void *))rec.Destroy)(w->stream);
    free(w);
}
/* microphone id opened raw, its sound in format (SDL_AudioFormat), channels, freq; NULL: not to be had this way */
static void *was_open(uint32_t id, int freq, int channels, uint16_t format) {
    if (!was_wanted()) return NULL;
    WasMic *w = (WasMic *)calloc(1, sizeof *w);
    if (!w) return NULL;
    w->id = id, w->freq = freq, w->channels = channels, w->format = format;
    w->ready = CreateEventA(NULL, TRUE, FALSE, NULL);
    w->thread = w->ready ? CreateThread(NULL, 0, was_run, w, 0, NULL) : NULL;
    if (!w->thread) {
        if (w->ready) CloseHandle(w->ready);
        free(w);
        return NULL;
    }
    if (WaitForSingleObject(w->ready, 5000) != WAIT_OBJECT_0) {   /* (a driver that hangs: let go of it, the thread kept) */
        InterlockedExchange(&w->stop, 1);
        return NULL;
    }
    int slot = -1;
    AcquireSRWLockExclusive(&was_lock);
    for (int i = 0; i < WAS_MAX && slot < 0; i++)
        if (!was_mics[i]) slot = i;
    if (slot >= 0 && w->ok) was_mics[slot] = w;
    ReleaseSRWLockExclusive(&was_lock);
    if (slot < 0 || !w->ok) {
        was_close(w);
        return NULL;
    }
    return w;
}
#else
static void *was_of(void *mic) { (void)mic; return NULL; }
#endif

/* (hookshot) the recording device's own channel count (id 0: the default), 1 to 8; 1 when SDL cannot say, and on SDL2 (its
   capture is opened mono, as before). An audio interface has several: its inputs, then often loopbacks of what the PC plays
   (a Focusrite Scarlett Solo: 4, its microphone on the second) */
int hos_sdl_mic_channels(uint32_t id) {
    if (!rec_ready() || version != 3) return 1;
#ifdef _WIN32
    if (was_wanted()) {   /* (Windows: the raw stream's, as was_open opens it) */
        const int n = was_channels(id);
        if (n) return n;
    }
#endif
    if (!rec.DeviceFormat) return 1;
    struct { uint32_t format; int channels, freq; } spec = {0, 0, 0};
    int frames = 0;
    if (!((_Bool (*)(uint32_t, void *, int *))rec.DeviceFormat)(id ? id : 0xFFFFFFFEu, &spec, &frames)) return 1;
    return spec.channels >= 1 && spec.channels <= 8 ? spec.channels : 1;
}
void *hos_sdl_mic_open(uint32_t id, int freq, int channels, uint16_t sdl_format) {
    if (!rec_ready()) return NULL;
    if (version == 2) {
        const int bytes = (sdl_format & 0xFF) / 8 * channels;
        Mic2 *m = (Mic2 *)calloc(1, sizeof *m);
        if (!m || !(m->ring = (uint8_t *)malloc((size_t)freq * bytes))) {
            free(m);
            return NULL;
        }
        m->cap = freq * bytes;
        struct {
            int freq;
            uint16_t format;
            uint8_t channels, silence;
            uint16_t samples, padding;
            uint32_t size;
            void (*callback)(void *, uint8_t *, int);
            void *userdata;
        } want, have;
        memset(&want, 0, sizeof want);
        want.freq = freq, want.format = sdl_format, want.channels = (uint8_t)channels, want.samples = 512;
        want.callback = mic2_push, want.userdata = m;
        /* (no changes allowed: SDL converts the device's sound to this. SDL2's id is a place in its list, so the caller takes
           it from a list made just before (host/nn_audio_in.c find_device). SDL2 opens a device by its name: of two with one
           name it takes the first, whichever was chosen; telling them apart is SDL3's) */
        const char *name = id ? ((const char *(*)(int, int))rec.DeviceName2)((int)id - 1, 1) : NULL;
        m->dev = CALL(uint32_t (*)(const char *, int, const void *, void *, int), OpenAudioDevice)(name, 1, &want, &have, 0);
        if (!m->dev) {   /* (the caller says so, once: hos_sdl_error) */
            free(m->ring), free(m);
            return NULL;
        }
        CALL(void (*)(uint32_t, int), PauseAudioDevice)(m->dev, 0);
        return m;
    }
    const struct { uint32_t format; int channels, freq; } spec = {sdl_format, channels, freq};
#ifdef _WIN32
    void *raw = was_open(id, freq, channels, sdl_format);   /* (hookshot: Windows' raw stream, above) */
    if (raw) return raw;
#endif
    void *s = CALL(void *(*)(uint32_t, const void *, void *, void *), OpenAudioDeviceStream)(
        id ? id : 0xFFFFFFFEu /* SDL_AUDIO_DEVICE_DEFAULT_RECORDING */, &spec, NULL, NULL);
    if (s && !CALL(_Bool (*)(void *), ResumeAudioStreamDevice)(s)) {   /* (one that does not start did not open) */
        ((void (*)(void *))rec.Destroy)(s);
        s = NULL;
    }
    return s;   /* (none: the caller says so, once: hos_sdl_error) */
}
int hos_sdl_mic_available(void *mic) {
    if (!mic || !rec.ok) return 0;
    if (version == 2) {
        Mic2 *m = (Mic2 *)mic;
        mic2_lock(m, 1);
        const int n = m->len;
        mic2_lock(m, 0);
        return n;
    }
    void *w = was_of(mic);
    return ((int (*)(void *))rec.Available)(w ? *(void **)w /* (its stream: WasMic's first) */ : mic);
}
int hos_sdl_mic_read(void *mic, void *dst, int bytes) {
    if (!mic || !rec.ok || bytes <= 0) return 0;
    if (version == 2) {
        Mic2 *m = (Mic2 *)mic;
        mic2_lock(m, 1);
        const int n = bytes < m->len ? bytes : m->len, first = n < m->cap - m->start ? n : m->cap - m->start;
        memcpy(dst, m->ring + m->start, (size_t)first);
        memcpy((uint8_t *)dst + first, m->ring, (size_t)(n - first));
        m->start = (m->start + n) % m->cap, m->len -= n;
        mic2_lock(m, 0);
        return n;
    }
    void *w = was_of(mic);
    const int n = ((int (*)(void *, void *, int))rec.GetData)(w ? *(void **)w /* (its stream: WasMic's first) */ : mic, dst, bytes);
    return n > 0 ? n : 0;
}
void hos_sdl_mic_clear(void *mic) {
    if (!mic || !rec.ok) return;
    if (version == 2) {
        Mic2 *m = (Mic2 *)mic;
        mic2_lock(m, 1);
        m->start = m->len = 0;
        mic2_lock(m, 0);
        return;
    }
    void *w = was_of(mic);
    ((_Bool (*)(void *))rec.Clear)(w ? *(void **)w /* (its stream: WasMic's first) */ : mic);
}
void hos_sdl_mic_close(void *mic) {
    if (!mic || !rec.ok) return;
    if (version == 2) {
        Mic2 *m = (Mic2 *)mic;
        ((void (*)(uint32_t))rec.CloseDevice)(m->dev);   /* (the callback has stopped when this returns) */
        free(m->ring), free(m);
        return;
    }
#ifdef _WIN32
    if (was_of(mic)) {
        was_close((WasMic *)mic);
        return;
    }
#endif
    ((void (*)(void *))rec.Destroy)(mic);
}

/* ---- controllers ---- */
int hos_sdl_pads_list(int32_t *ids, int *opens, int max) {   /* (SDL3 opens by id; SDL2 by device index) */
    int n = 0;
    if (version == 3) {
        int count = 0;
        uint32_t *got = CALL(uint32_t *(*)(int *), GetGamepads)(&count);
        for (int i = 0; got && i < count && n < max; i++) ids[n] = (int32_t)got[i], opens[n] = (int)got[i], n++;
        if (got) CALL(void (*)(void *), Free)(got);
        return n;
    }
    const int nj = CALL(int (*)(void), NumJoysticks)();
    for (int j = 0; j < nj && n < max; j++)
        if (CALL(int (*)(int), IsGameController)(j)) ids[n] = CALL(int32_t (*)(int), DeviceInstanceID)(j), opens[n] = j, n++;
    return n;
}
void *hos_sdl_pad_open(int what) {
    return version == 3 ? CALL(void *(*)(uint32_t), PadOpen)((uint32_t)what) : CALL(void *(*)(int), PadOpen)(what);
}
void hos_sdl_pad_close(void *pad) { CALL(void (*)(void *), PadClose)(pad); }
int hos_sdl_pad_connected(void *pad) {
    return version == 3 ? CALL(_Bool (*)(void *), PadConnected)(pad) : CALL(int (*)(void *), PadConnected)(pad) != 0;
}
void hos_sdl_pads_update(void) { CALL(void (*)(void), PadsUpdate)(); }
int hos_sdl_pad_button(void *pad, int button) {
    return version == 3 ? CALL(_Bool (*)(void *, int), PadButton)(pad, button)
                        : CALL(uint8_t (*)(void *, int), PadButton)(pad, button) != 0;
}
int16_t hos_sdl_pad_axis(void *pad, int axis) { return CALL(int16_t (*)(void *, int), PadAxis)(pad, axis); }
const char *hos_sdl_pad_name(void *pad) {
    const char *n = CALL(const char *(*)(void *), PadName)(pad);
    return n ? n : "?";
}
int32_t hos_sdl_pad_id(void *pad) {
    return version == 3 ? (int32_t)CALL(uint32_t (*)(void *), GetGamepadID)(pad)
                        : CALL(int32_t (*)(void *), JoystickInstanceID)(CALL(void *(*)(void *), GetJoystick)(pad));
}
void hos_sdl_pad_rumble(void *pad, uint16_t low, uint16_t high, uint32_t ms) {
    if (version == 3) CALL(_Bool (*)(void *, uint16_t, uint16_t, uint32_t), PadRumble)(pad, low, high, ms);
    else CALL(int (*)(void *, uint16_t, uint16_t, uint32_t), PadRumble)(pad, low, high, ms);
}
int hos_sdl_pad_type(void *pad) { return f.PadType ? CALL(int (*)(void *), PadType)(pad) : 0; }
int hos_sdl_pad_has_effect(void) { return f.PadEffect != NULL; }
int hos_sdl_pad_effect(void *pad, const void *data, int size) {
    if (!f.PadEffect) return 0;
    if (version == 3) return CALL(_Bool (*)(void *, const void *, int), PadEffect)(pad, data, size);
    return CALL(int (*)(void *, const void *, int), PadEffect)(pad, data, size) == 0;
}
/* (motion) type: HOS_SDL_SENSOR_ACCEL or _GYRO, the same numbers in both */
int hos_sdl_pad_has_sensor(void *pad, int type) {
    if (!f.PadHasSensor || !f.PadSensorEnable || !f.PadSensorData) return 0;
    return version == 3 ? CALL(_Bool (*)(void *, int), PadHasSensor)(pad, type)
                        : CALL(int (*)(void *, int), PadHasSensor)(pad, type) != 0;
}
int hos_sdl_pad_sensor_enable(void *pad, int type, int on) {
    if (!f.PadSensorEnable) return 0;
    return version == 3 ? CALL(_Bool (*)(void *, int, _Bool), PadSensorEnable)(pad, type, on != 0)
                        : CALL(int (*)(void *, int, int), PadSensorEnable)(pad, type, on != 0) == 0;
}
int hos_sdl_pad_sensor(void *pad, int type, float *data, int n) {
    if (!f.PadSensorData) return 0;
    return version == 3 ? CALL(_Bool (*)(void *, int, float *, int), PadSensorData)(pad, type, data, n)
                        : CALL(int (*)(void *, int, float *, int), PadSensorData)(pad, type, data, n) == 0;
}
#undef CALL
