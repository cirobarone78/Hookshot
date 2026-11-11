/* (hookshot) The Nintendo Switch 2 Pro Controller over USB, without libusb or a patched SDL (host/sw2_pro.h has the
   protocol and where it comes from).

   SDL drives this controller only when it is built with libusb, and the SDL3.dll the game ships (the official
   Windows build) is not; on Linux the system's SDL may or may not have it. So Hookshot sets it up itself, through
   what each system already has, and hands it to host/pad_sdl.c as one more pad (host/hos_sdl.c's hos_sdl_pad_* calls
   come here for it):
   - Windows: the controller's setup interface (MI_01) has Windows' own WinUSB driver (the controller asks for it in
     its descriptors, as WebUSB tools rely on); the bulk setup goes through winusb.dll, the input and the rumble
     through the HID interface (hid.dll, setupapi.dll): nothing to install. Should the setup interface have no
     WinUSB driver, a controller already started (by another program) is still read.
   - Linux: usbfs (/dev/bus/usb), as SDL's libusb does: the setup on the vendor interface, then the HID interface is
     taken from hid-generic (given back when the controller is let go) and read directly. The device node has to be
     the logged-in user's: Steam's udev rules (steam-devices) give it, as they do for SDL's own driver.
   One thread per controller sets it up and reads it (a report every 4 ms), and sends its rumble: the game's HD rumble
   (pad_sdl.c hands each side's vibration value over, hos_sw2_rumble_hd), or with HOS_HD_RUMBLE=0 two motor strengths at
   SDL's fixed frequencies. Inputs are SDL's positions (B the bottom button); Home opens the Insert menu as on other pads;
   Capture and C (GameChat) are the system's, as on the console; GL and GR press nothing unless HOS_SW2_GL / HOS_SW2_GR
   name an input (south east west north back guide start lstick rstick lshoulder rshoulder up down left right zl zr).
   The player lights show player 1. HOS_NO_SW2=1 leaves the controller to SDL, as before. Only USB 057E:2069 is ever
   opened: other controllers, the Switch Pro Controller (057E:2009) among them, are SDL's. */
#include "hos.h"
#include <ctype.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "hos_sdl.h"
#include "sw2_pro.h"
#ifdef _WIN32
#include <setupapi.h>
#include <objbase.h>
#else
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <unistd.h>
#endif

void hos_host_thread_register_self(const char *name);   /* hos_prof.c */

#define SW2_MAX 4
enum { SLOT_FREE, SLOT_STARTING, SLOT_READY, SLOT_GONE, SLOT_FAILED };

typedef struct {
    volatile LONG state, stop;
    char key[512];             /* the device (Linux: its usbfs node; Windows: its HID interface's path) */
    int64_t retry_ns;          /* (FAILED: when it may be tried again) */
    int opened;                /* (pad_sdl.c has it open) */
    int32_t id;
    SRWLOCK lock;              /* (what follows, between the device's thread and pad_sdl.c's) */
    Sw2Input in;
    float accel[3], gyro[3];
    int imu, sensors_on;
    uint8_t want[2][5];        /* the rumble asked for */
    int64_t motor_until;       /* (HOS_HD_RUMBLE=0: when the motors' rumble stops, as SDL's duration does) */
    /* (the device's thread's own) */
    Sw2Calibration cal;
    Sw2ImuClock clock;
    Sw2Rumble rumble;
    int gl, gr;                /* (HOS_SW2_GL / GR: the SW2_* they press, -1 nothing) */
#ifdef _WIN32
    wchar_t path[512];
    HANDLE hid, read_ev, write_ev, usb_file;
    void *usb;
    OVERLAPPED rov;
    int reading;
    uint8_t rbuf[512];
    int in_len, out_len;
    uint8_t bulk_in, bulk_out;
#else
    int fd;
    Sw2Endpoints ep;
    int hid_claimed, bulk_claimed;
#endif
} Sw2Pad;

static Sw2Pad sw2[SW2_MAX];
static SRWLOCK sw2_lock = SRWLOCK_INIT;   /* (the slots' state, key and opened) */
static int32_t sw2_serial;

int hos_sw2_enabled(void) {
    static int on = -1;
    if (on < 0) on = !getenv("HOS_NO_SW2");
    return on;
}

/* ---------------- the platforms: find the controllers, open one, its bulk pipes and its HID reports ---------------- */
#ifdef _WIN32
typedef struct { UCHAR bLength, bDescriptorType, bInterfaceNumber, bAlternateSetting, bNumEndpoints, bInterfaceClass,
                 bInterfaceSubClass, bInterfaceProtocol, iInterface; } Sw2UsbIfDesc;
typedef struct { int PipeType; UCHAR PipeId; USHORT MaximumPacketSize; UCHAR Interval; } Sw2PipeInfo;
typedef struct { USHORT Usage, UsagePage, InputReportByteLength, OutputReportByteLength, FeatureReportByteLength,
                 Reserved[17], counts[10]; } Sw2HidCaps;
static struct {
    int loaded;
    HDEVINFO (WINAPI *ClassDevs)(const GUID *, PCWSTR, HWND, DWORD);
    BOOL (WINAPI *EnumInterfaces)(HDEVINFO, PSP_DEVINFO_DATA, const GUID *, DWORD, PSP_DEVICE_INTERFACE_DATA);
    BOOL (WINAPI *InterfaceDetail)(HDEVINFO, PSP_DEVICE_INTERFACE_DATA, PSP_DEVICE_INTERFACE_DETAIL_DATA_W, DWORD, PDWORD, PSP_DEVINFO_DATA);
    BOOL (WINAPI *EnumInfo)(HDEVINFO, DWORD, PSP_DEVINFO_DATA);
    BOOL (WINAPI *InstanceId)(HDEVINFO, PSP_DEVINFO_DATA, PWSTR, DWORD, PDWORD);
    HKEY (WINAPI *OpenDevRegKey)(HDEVINFO, PSP_DEVINFO_DATA, DWORD, DWORD, DWORD, REGSAM);
    BOOL (WINAPI *DestroyList)(HDEVINFO);
    BOOL (WINAPI *UsbInit)(HANDLE, void **);
    BOOL (WINAPI *UsbFree)(void *);
    BOOL (WINAPI *UsbIfSettings)(void *, UCHAR, Sw2UsbIfDesc *);
    BOOL (WINAPI *UsbPipe)(void *, UCHAR, UCHAR, Sw2PipeInfo *);
    BOOL (WINAPI *UsbPolicy)(void *, UCHAR, ULONG, ULONG, void *);
    BOOL (WINAPI *UsbWrite)(void *, UCHAR, UCHAR *, ULONG, ULONG *, OVERLAPPED *);
    BOOL (WINAPI *UsbRead)(void *, UCHAR, UCHAR *, ULONG, ULONG *, OVERLAPPED *);
    BOOL (WINAPI *HidPreparsed)(HANDLE, void **);
    BOOL (WINAPI *HidFreePreparsed)(void *);
    LONG (WINAPI *HidCaps)(void *, Sw2HidCaps *);
} w;
static int win_load(void) {
    static volatile LONG state;   /* 0 not tried, 1 loading, 2 loaded, 3 not there */
    if (InterlockedCompareExchange(&state, 1, 0) == 0) {
        HMODULE s = LoadLibraryExA("setupapi.dll", NULL, LOAD_LIBRARY_SEARCH_SYSTEM32);
        HMODULE u = LoadLibraryExA("winusb.dll", NULL, LOAD_LIBRARY_SEARCH_SYSTEM32);
        HMODULE h = LoadLibraryExA("hid.dll", NULL, LOAD_LIBRARY_SEARCH_SYSTEM32);
#define W(field, m, name) *(FARPROC *)&w.field = m ? GetProcAddress(m, name) : NULL
        W(ClassDevs, s, "SetupDiGetClassDevsW"); W(EnumInterfaces, s, "SetupDiEnumDeviceInterfaces");
        W(InterfaceDetail, s, "SetupDiGetDeviceInterfaceDetailW"); W(EnumInfo, s, "SetupDiEnumDeviceInfo");
        W(InstanceId, s, "SetupDiGetDeviceInstanceIdW"); W(OpenDevRegKey, s, "SetupDiOpenDevRegKey");
        W(DestroyList, s, "SetupDiDestroyDeviceInfoList");
        W(UsbInit, u, "WinUsb_Initialize"); W(UsbFree, u, "WinUsb_Free"); W(UsbIfSettings, u, "WinUsb_QueryInterfaceSettings");
        W(UsbPipe, u, "WinUsb_QueryPipe"); W(UsbPolicy, u, "WinUsb_SetPipePolicy"); W(UsbWrite, u, "WinUsb_WritePipe");
        W(UsbRead, u, "WinUsb_ReadPipe");
        W(HidPreparsed, h, "HidD_GetPreparsedData"); W(HidFreePreparsed, h, "HidD_FreePreparsedData"); W(HidCaps, h, "HidP_GetCaps");
#undef W
        w.loaded = w.ClassDevs && w.EnumInterfaces && w.InterfaceDetail && w.EnumInfo && w.InstanceId && w.OpenDevRegKey &&
                   w.DestroyList && w.HidPreparsed && w.HidFreePreparsed && w.HidCaps;
        InterlockedExchange(&state, w.loaded ? 2 : 3);
        if (!w.loaded) hos_log("hid: Switch 2 Pro Controller: setupapi.dll or hid.dll is missing, the controller is SDL's");
    }
    while (state == 1) Sleep(0);
    return state == 2;
}
static int wide_has(const wchar_t *s, const char *lower) {   /* (s contains lower, ignoring case: ASCII) */
    for (; *s; s++) {
        int i = 0;
        while (lower[i] && s[i] && (s[i] < 128 ? (char)tolower((int)s[i]) : 0) == lower[i]) i++;
        if (!lower[i]) return 1;
    }
    return 0;
}
/* the first interface of class guid whose path names 057E:2069 (and part, when not NULL), into path */
static int win_interface(const GUID *guid, const char *part, wchar_t *path, size_t cap, int index) {
    HDEVINFO set = w.ClassDevs(guid, NULL, NULL, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
    if (set == INVALID_HANDLE_VALUE) return 0;
    int found = 0, seen = 0;
    SP_DEVICE_INTERFACE_DATA d = {sizeof d};
    for (DWORD i = 0; !found && w.EnumInterfaces(set, NULL, guid, i, &d); i++) {
        union { SP_DEVICE_INTERFACE_DETAIL_DATA_W h; char b[sizeof(SP_DEVICE_INTERFACE_DETAIL_DATA_W) + 1024 * sizeof(wchar_t)]; } u;
        u.h.cbSize = sizeof u.h;
        if (!w.InterfaceDetail(set, &d, &u.h, sizeof u, NULL, NULL)) continue;
        if (!wide_has(u.h.DevicePath, "vid_057e&pid_2069") || (part && !wide_has(u.h.DevicePath, part))) continue;
        if (seen++ < index) continue;
        if (wcslen(u.h.DevicePath) < cap) wcscpy(path, u.h.DevicePath), found = 1;
    }
    w.DestroyList(set);
    return found;
}
/* the setup interface's WinUSB device interface: its class GUID from the device's registry (DeviceInterfaceGUIDs, which
   the controller's descriptors give it), else the one it has been seen with */
static int win_usb_path(wchar_t *path, size_t cap) {
    GUID guid;
    int have = 0;
    HDEVINFO set = w.ClassDevs(NULL, L"USB", NULL, DIGCF_PRESENT | DIGCF_ALLCLASSES);
    if (set != INVALID_HANDLE_VALUE) {
        SP_DEVINFO_DATA info = {sizeof info};
        for (DWORD i = 0; !have && w.EnumInfo(set, i, &info); i++) {
            wchar_t id[256];
            if (!w.InstanceId(set, &info, id, 256, NULL) || !wide_has(id, "vid_057e&pid_2069&mi_01")) continue;
            HKEY k = w.OpenDevRegKey(set, &info, DICS_FLAG_GLOBAL, 0, DIREG_DEV, KEY_READ);
            if (k == INVALID_HANDLE_VALUE) continue;
            wchar_t v[512];
            DWORD size = sizeof v - sizeof(wchar_t), type = 0;
            memset(v, 0, sizeof v);
            if (RegQueryValueExW(k, L"DeviceInterfaceGUIDs", NULL, &type, (BYTE *)v, &size) == ERROR_SUCCESS ||
                (size = sizeof v - sizeof(wchar_t), RegQueryValueExW(k, L"DeviceInterfaceGUID", NULL, &type, (BYTE *)v, &size) == ERROR_SUCCESS))
                have = CLSIDFromString(v, &guid) == S_OK;
            RegCloseKey(k);
        }
        w.DestroyList(set);
    }
    if (have && win_interface(&guid, NULL, path, cap, 0)) return 1;
    static const GUID seen = {0x6F13725E, 0xEF0E, 0x4FD3, {0xAE, 0x5F, 0xB2, 0xDE, 0x98, 0x9E, 0xC8, 0x25}};
    return win_interface(&seen, NULL, path, cap, 0);
}
static const GUID hid_guid = {0x4D1E55B2, 0xF16F, 0x11CF, {0x88, 0xCB, 0x00, 0x11, 0x11, 0x00, 0x00, 0x30}};
/* the controllers there now: their keys. One at a time: the setup interface found (win_usb_path) is the first one's,
   and telling which belongs to which HID interface is left for when someone has two */
static int dev_list(char keys[][512], int max) {
    if (!win_load()) return 0;
    int n = 0;
    wchar_t path[512];
    if (max > 1) max = 1;
    for (int i = 0; n < max && win_interface(&hid_guid, NULL, path, 512, i); i++)
        if (WideCharToMultiByte(CP_UTF8, 0, path, -1, keys[n], 512, NULL, NULL) > 0) n++;
    return n;
}
static int usb_out(void *ctx, const uint8_t *data, int size) {
    Sw2Pad *p = ctx;
    ULONG n = 0;
    return w.UsbWrite(p->usb, p->bulk_out, (UCHAR *)data, (ULONG)size, &n, NULL) ? (int)n : -1;
}
static int usb_in(void *ctx, uint8_t *data, int size, int timeout_ms) {
    Sw2Pad *p = ctx;
    ULONG n = 0, t = (ULONG)timeout_ms;
    w.UsbPolicy(p->usb, p->bulk_in, 0x03 /* PIPE_TRANSFER_TIMEOUT */, sizeof t, &t);
    return w.UsbRead(p->usb, p->bulk_in, data, (ULONG)size, &n, NULL) ? (int)n : -1;
}
/* the setup interface opened: 1 with its bulk pipes */
static int dev_bulk_open(Sw2Pad *p) {
    wchar_t path[512];
    if (!w.UsbInit || !win_usb_path(path, 512)) return 0;
    p->usb_file = CreateFileW(path, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING,
                              FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OVERLAPPED, NULL);
    if (p->usb_file == INVALID_HANDLE_VALUE) return p->usb_file = NULL, 0;
    if (!w.UsbInit(p->usb_file, &p->usb)) {
        CloseHandle(p->usb_file), p->usb_file = NULL, p->usb = NULL;
        return 0;
    }
    Sw2UsbIfDesc d;
    p->bulk_in = p->bulk_out = 0;
    if (w.UsbIfSettings(p->usb, 0, &d))
        for (UCHAR i = 0; i < d.bNumEndpoints; i++) {
            Sw2PipeInfo pi;
            if (!w.UsbPipe(p->usb, 0, i, &pi) || pi.PipeType != 2 /* bulk */) continue;
            if (pi.PipeId & 0x80) p->bulk_in = p->bulk_in ? p->bulk_in : pi.PipeId;
            else p->bulk_out = p->bulk_out ? p->bulk_out : pi.PipeId;
        }
    if (p->bulk_in && p->bulk_out) {
        ULONG t = 1000;
        w.UsbPolicy(p->usb, p->bulk_out, 0x03, sizeof t, &t);
        return 1;
    }
    w.UsbFree(p->usb), CloseHandle(p->usb_file), p->usb = NULL, p->usb_file = NULL;
    return 0;
}
static void dev_bulk_close(Sw2Pad *p) {
    if (p->usb) w.UsbFree(p->usb);
    if (p->usb_file) CloseHandle(p->usb_file);
    p->usb = NULL, p->usb_file = NULL;
}
/* the HID interface opened: 1 when done, 0 not (the reason logged), -1 not now (busy) */
static int dev_open(Sw2Pad *p) {
    if (!MultiByteToWideChar(CP_UTF8, 0, p->key, -1, p->path, 512)) return 0;
    p->hid = CreateFileW(p->path, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING,
                         FILE_FLAG_OVERLAPPED, NULL);
    if (p->hid == INVALID_HANDLE_VALUE) {
        static int warned;
        p->hid = NULL;
        if (!warned++) hos_log("hid: Switch 2 Pro Controller: its HID interface could not be opened (%lu)", (unsigned long)GetLastError());
        return -1;
    }
    void *pp = NULL;
    Sw2HidCaps caps;
    memset(&caps, 0, sizeof caps);
    if (w.HidPreparsed(p->hid, &pp)) {
        w.HidCaps(pp, &caps);
        w.HidFreePreparsed(pp);
    }
    p->in_len = caps.InputReportByteLength ? caps.InputReportByteLength : SW2_REPORT_SIZE;
    p->out_len = caps.OutputReportByteLength ? caps.OutputReportByteLength : SW2_REPORT_SIZE;
    if (p->in_len > (int)sizeof p->rbuf) p->in_len = sizeof p->rbuf;
    p->read_ev = CreateEventW(NULL, TRUE, FALSE, NULL);
    p->write_ev = CreateEventW(NULL, TRUE, FALSE, NULL);
    p->reading = 0;
    return 1;
}
static int dev_has_bulk(Sw2Pad *p) {
    static int warned;
    const int ok = dev_bulk_open(p);
    if (!ok && !warned) {
        warned = 1;
        hos_log("hid: Switch 2 Pro Controller: its setup interface (MI_01) is not available through WinUSB, so it cannot "
                "be started here; if another program has started it, its input is read");
    }
    return ok;
}
static void dev_bulk_done(Sw2Pad *p) { dev_bulk_close(p); }
static int dev_claim_hid(Sw2Pad *p) { (void)p; return 1; }
/* a report: its length, 0 none in timeout_ms, -1 the controller is gone */
static int dev_read(Sw2Pad *p, uint8_t *out, int cap, int timeout_ms) {
    DWORD n = 0;
    if (!p->reading) {
        memset(&p->rov, 0, sizeof p->rov);
        p->rov.hEvent = p->read_ev;
        ResetEvent(p->read_ev);
        if (ReadFile(p->hid, p->rbuf, (DWORD)p->in_len, &n, &p->rov)) goto got;
        if (GetLastError() != ERROR_IO_PENDING) return -1;
        p->reading = 1;
    }
    if (WaitForSingleObject(p->read_ev, (DWORD)timeout_ms) != WAIT_OBJECT_0) return 0;
    p->reading = 0;
    if (!GetOverlappedResult(p->hid, &p->rov, &n, FALSE)) return -1;
got:
    if ((int)n > cap) n = (DWORD)cap;
    memcpy(out, p->rbuf, n);
    return (int)n;
}
static int dev_write(Sw2Pad *p, const uint8_t *report, int size) {
    uint8_t buf[512] = {0};
    const int len = p->out_len < (int)sizeof buf ? p->out_len : (int)sizeof buf;
    memcpy(buf, report, size < len ? size : len);
    OVERLAPPED ov;
    memset(&ov, 0, sizeof ov);
    ov.hEvent = p->write_ev;
    ResetEvent(p->write_ev);
    DWORD n = 0;
    if (WriteFile(p->hid, buf, (DWORD)len, &n, &ov)) return 1;
    if (GetLastError() != ERROR_IO_PENDING) return 0;
    if (WaitForSingleObject(p->write_ev, 50) != WAIT_OBJECT_0) CancelIo(p->hid);
    return GetOverlappedResult(p->hid, &ov, &n, TRUE) != 0;
}
static void dev_close(Sw2Pad *p) {
    dev_bulk_close(p);
    if (p->hid) {
        CancelIo(p->hid);
        if (p->reading) {
            DWORD n;
            GetOverlappedResult(p->hid, &p->rov, &n, TRUE);
        }
        CloseHandle(p->hid);
    }
    if (p->read_ev) CloseHandle(p->read_ev);
    if (p->write_ev) CloseHandle(p->write_ev);
    p->hid = p->read_ev = p->write_ev = NULL, p->reading = 0;
}
#else   /* (linux: usbfs; the structures and requests of linux/usbdevice_fs.h, which not every build has) */
struct sw2_bulk { unsigned int ep, len, timeout; void *data; };
struct sw2_ctrl { uint8_t bRequestType, bRequest; uint16_t wValue, wIndex, wLength; uint32_t timeout; void *data; };
struct sw2_ioctl { int ifno, ioctl_code; void *data; };
struct sw2_disclaim { unsigned int interface, flags; char driver[256]; };
#define SW2_USBDEVFS_CONTROL _IOWR('U', 0, struct sw2_ctrl)
#define SW2_USBDEVFS_BULK _IOWR('U', 2, struct sw2_bulk)
#define SW2_USBDEVFS_CLAIMINTERFACE _IOR('U', 15, unsigned int)
#define SW2_USBDEVFS_RELEASEINTERFACE _IOR('U', 16, unsigned int)
#define SW2_USBDEVFS_IOCTL _IOWR('U', 18, struct sw2_ioctl)
#define SW2_USBDEVFS_CONNECT _IO('U', 23)
#define SW2_USBDEVFS_DISCONNECT_CLAIM _IOR('U', 27, struct sw2_disclaim)
#define SW2_DISCONNECT_CLAIM_EXCEPT_DRIVER 0x02

static int read_hex(const char *dir, const char *name, unsigned *out, int base) {
    char path[600], buf[32];
    snprintf(path, sizeof path, "/sys/bus/usb/devices/%s/%s", dir, name);
    FILE *f = fopen(path, "r");
    if (!f) return 0;
    const int ok = fgets(buf, sizeof buf, f) != NULL;
    fclose(f);
    if (ok) *out = (unsigned)strtoul(buf, NULL, base);
    return ok;
}
/* the controllers there now: their usbfs nodes (sysfs says which devices they are; nothing else is opened) */
static int dev_list(char keys[][512], int max) {
    DIR *d = opendir("/sys/bus/usb/devices");
    if (!d) return 0;
    int n = 0;
    struct dirent *e;
    while (n < max && (e = readdir(d))) {
        if (e->d_name[0] == '.' || strchr(e->d_name, ':')) continue;   /* (interfaces) */
        unsigned vid, pid, bus, dev;
        if (!read_hex(e->d_name, "idVendor", &vid, 16) || !read_hex(e->d_name, "idProduct", &pid, 16) ||
            !sw2_is_pro(vid, pid))
            continue;
        if (!read_hex(e->d_name, "busnum", &bus, 10) || !read_hex(e->d_name, "devnum", &dev, 10)) continue;
        snprintf(keys[n++], 512, "/dev/bus/usb/%03u/%03u", bus, dev);
    }
    closedir(d);
    return n;
}
static int usb_out(void *ctx, const uint8_t *data, int size) {
    Sw2Pad *p = ctx;
    struct sw2_bulk b = {p->ep.bulk_out, (unsigned)size, 1000, (void *)data};
    return ioctl(p->fd, SW2_USBDEVFS_BULK, &b);
}
static int usb_in(void *ctx, uint8_t *data, int size, int timeout_ms) {
    Sw2Pad *p = ctx;
    struct sw2_bulk b = {p->ep.bulk_in, (unsigned)size, (unsigned)timeout_ms, data};
    return ioctl(p->fd, SW2_USBDEVFS_BULK, &b);
}
static int dev_open(Sw2Pad *p) {
    static int warned_access;
    p->fd = open(p->key, O_RDWR | O_CLOEXEC);
    if (p->fd < 0) {
        if ((errno == EACCES || errno == EPERM) && !warned_access) {
            warned_access = 1;
            hos_log("hid: Switch 2 Pro Controller: no access to its USB device %s. It needs a udev rule that gives it "
                    "to the logged-in user, as Steam's steam-devices package has: SUBSYSTEM==\"usb\", "
                    "ATTRS{idVendor}==\"057e\", ATTRS{idProduct}==\"2069\", MODE=\"0660\", TAG+=\"uaccess\"", p->key);
        }
        return 0;
    }
    uint8_t d[4096];
    const ssize_t n = read(p->fd, d, sizeof d);   /* (usbfs: the device's descriptor, then its configurations') */
    if (n <= 18 || !sw2_parse_descriptors(d + 18, (int)n - 18, &p->ep)) {
        hos_log("hid: Switch 2 Pro Controller at %s: its USB interfaces are not the expected ones", p->key);
        close(p->fd), p->fd = -1;
        return 0;
    }
    unsigned ifc = p->ep.bulk_if;
    if (ioctl(p->fd, SW2_USBDEVFS_CLAIMINTERFACE, &ifc) < 0) {
        static int warned;
        if (!warned++) hos_log("hid: Switch 2 Pro Controller at %s is in use by another program (Steam?): it stays there (%d)", p->key, errno);
        close(p->fd), p->fd = -1;
        return -1;
    }
    p->bulk_claimed = 1, p->hid_claimed = 0;
    return 1;
}
static int dev_has_bulk(Sw2Pad *p) { return p->bulk_claimed; }
static void dev_bulk_done(Sw2Pad *p) { (void)p; }
/* the HID interface taken from hid-generic (not from another program's usbfs claim) */
static int dev_claim_hid(Sw2Pad *p) {
    struct sw2_disclaim dc;
    memset(&dc, 0, sizeof dc);
    dc.interface = p->ep.hid_if, dc.flags = SW2_DISCONNECT_CLAIM_EXCEPT_DRIVER;
    snprintf(dc.driver, sizeof dc.driver, "usbfs");
    if (ioctl(p->fd, SW2_USBDEVFS_DISCONNECT_CLAIM, &dc) < 0) {
        static int warned;
        if (!warned++) hos_log("hid: Switch 2 Pro Controller at %s: its HID interface is in use by another program (%d)", p->key, errno);
        return 0;
    }
    p->hid_claimed = 1;
    return 1;
}
static int dev_read(Sw2Pad *p, uint8_t *out, int cap, int timeout_ms) {
    struct sw2_bulk b = {p->ep.hid_in, (unsigned)cap, (unsigned)timeout_ms, out};
    const int n = ioctl(p->fd, SW2_USBDEVFS_BULK, &b);
    if (n >= 0) return n;
    return errno == ETIMEDOUT || errno == EAGAIN || errno == EINTR || errno == EOVERFLOW ? 0 : -1;
}
static int dev_write(Sw2Pad *p, const uint8_t *report, int size) {
    if (p->ep.hid_out) {
        struct sw2_bulk b = {p->ep.hid_out, (unsigned)size, 50, (void *)report};
        return ioctl(p->fd, SW2_USBDEVFS_BULK, &b) == size;
    }
    struct sw2_ctrl c = {0x21, 0x09 /* SET_REPORT */, (uint16_t)(0x0200 | report[0]), p->ep.hid_if, (uint16_t)size, 50, (void *)report};
    return ioctl(p->fd, SW2_USBDEVFS_CONTROL, &c) == size;
}
static void dev_close(Sw2Pad *p) {
    if (p->fd < 0) return;
    if (p->hid_claimed) {
        unsigned ifc = p->ep.hid_if;
        ioctl(p->fd, SW2_USBDEVFS_RELEASEINTERFACE, &ifc);
        struct sw2_ioctl c = {p->ep.hid_if, SW2_USBDEVFS_CONNECT, NULL};   /* (hid-generic back) */
        ioctl(p->fd, SW2_USBDEVFS_IOCTL, &c);
    }
    if (p->bulk_claimed) {
        unsigned ifc = p->ep.bulk_if;
        ioctl(p->fd, SW2_USBDEVFS_RELEASEINTERFACE, &ifc);
    }
    close(p->fd);
    p->fd = -1, p->hid_claimed = p->bulk_claimed = 0;
}
#endif

/* ---------------- one controller's thread ---------------- */
static void finish(Sw2Pad *p, int state, int64_t retry_ns) {
    AcquireSRWLockExclusive(&sw2_lock);
    p->retry_ns = retry_ns;
    InterlockedExchange(&p->state, state);
    ReleaseSRWLockExclusive(&sw2_lock);
}
static DWORD WINAPI sw2_main(void *arg) {
    Sw2Pad *p = arg;
    hos_host_thread_register_self("gamepad (Switch 2 Pro)");
#ifndef _WIN32
    p->fd = -1;
#endif
    const int opened = dev_open(p);
    if (opened <= 0) {
        dev_close(p);
        finish(p, SLOT_FAILED, hos_now_ns() + (opened < 0 ? 5000000000LL : 3600000000000LL));
        return 0;
    }
    Sw2Bulk bulk = {p, usb_out, usb_in};
    const int bulk_ok = dev_has_bulk(p);
    const int set = bulk_ok && sw2_setup(&bulk, &p->cal, 0);
    if (!bulk_ok) memset(&p->cal, 0, sizeof p->cal);
    dev_bulk_done(p);
    if (bulk_ok && !set) hos_log("hid: Switch 2 Pro Controller: it did not take its setup");
    if (!dev_claim_hid(p)) {
        dev_close(p);
        finish(p, SLOT_FAILED, hos_now_ns() + 5000000000LL);
        return 0;
    }
    memset(&p->clock, 0, sizeof p->clock);
    sw2_rumble_init(&p->rumble);
    const char *gl = getenv("HOS_SW2_GL"), *gr = getenv("HOS_SW2_GR");
    p->gl = sw2_extra_target(gl), p->gr = sw2_extra_target(gr);
    uint8_t r[512], out[SW2_REPORT_SIZE];
    int64_t deadline = hos_now_ns() + 3000000000LL;   /* (its first report: no input in 3 s, it has not started) */
    int live = 0, logged_id = 0, errors = 0;
    while (!p->stop) {
        const int n = dev_read(p, r, sizeof r, 8);
        const int64_t now = hos_now_ns();
        if (n < 0) {
            if (++errors < 3) continue;
            break;
        }
        errors = 0;
        Sw2Input in;
        if (n > 0 && sw2_parse(r, n, &p->cal, &in)) {
            if (!logged_id && r[0] != SW2_INPUT_REPORT)
                logged_id = 1, hos_log("hid: Switch 2 Pro Controller: its reports are 0x%02x, not 0x%02x", r[0], SW2_INPUT_REPORT);
            sw2_imu_clock_feed(&p->clock, in.imu_ts);
            float a[3], g[3];
            if (p->clock.ready) sw2_imu(&in, p->clock.gyro_coeff, p->cal.gyro_bias, a, g);
            if (p->gl >= 0 && (in.buttons >> SW2_GL & 1)) in.buttons |= 1u << p->gl;
            if (p->gr >= 0 && (in.buttons >> SW2_GR & 1)) in.buttons |= 1u << p->gr;
            AcquireSRWLockExclusive(&p->lock);
            p->in = in;
            if (p->clock.ready && in.imu_ts) memcpy(p->accel, a, sizeof a), memcpy(p->gyro, g, sizeof g), p->imu = 1;
            ReleaseSRWLockExclusive(&p->lock);
            if (!live) {
                live = 1;
                hos_log("hid: Switch 2 Pro Controller connected (%s%s%s)", set ? "set up over USB" : "already started",
                        p->cal.serial[0] ? ", serial " : "", p->cal.serial);
                AcquireSRWLockExclusive(&sw2_lock);
                InterlockedExchange(&p->state, SLOT_READY);
                ReleaseSRWLockExclusive(&sw2_lock);
            }
        }
        if (!live) {
            if (now > deadline) {   /* (until it is plugged in again) */
                hos_log("hid: Switch 2 Pro Controller: no input from it%s", bulk_ok ? "" : " (it was not started)");
                break;
            }
            continue;
        }
        uint8_t want[2][5];
        AcquireSRWLockShared(&p->lock);
        memcpy(want, p->want, sizeof want);
        const int64_t until = p->motor_until;
        ReleaseSRWLockShared(&p->lock);
        if (until && now >= until) sw2_silence(want[0]), sw2_silence(want[1]);
        sw2_rumble_set(&p->rumble, want[0], want[1]);
        if (sw2_rumble_due(&p->rumble, now)) {
            sw2_rumble_next(&p->rumble, now, out);
            dev_write(p, out, sizeof out);
        }
    }
    if (live && (!sw2_silent(p->rumble.side[0]) || !sw2_silent(p->rumble.side[1]))) {   /* (still) */
        uint8_t q[5];
        sw2_silence(q);
        sw2_rumble_report(p->rumble.seq++, q, q, out);
        dev_write(p, out, sizeof out);
    }
    dev_close(p);
    if (live) hos_log("hid: Switch 2 Pro Controller disconnected");
    finish(p, live ? SLOT_GONE : SLOT_FAILED, hos_now_ns() + 3600000000000LL);
    return 0;
}

/* ---------------- for host/hos_sdl.c (pad_sdl.c's calls) ---------------- */
int hos_sw2_is(const void *pad) { return pad >= (const void *)&sw2[0] && pad < (const void *)&sw2[SW2_MAX]; }

/* The controllers ready now (and a look for new ones, at most once a second): their ids, and what opens each (-1 -
   slot, never an SDL id or index) */
int hos_sw2_list(int32_t *ids, int *opens, int max) {
    if (!hos_sw2_enabled()) return 0;
    static int64_t next;
    const int64_t now = hos_now_ns();
    if (now >= next) {
        next = now + 1000000000LL;
        char keys[SW2_MAX][512];
        const int n = dev_list(keys, SW2_MAX);
        AcquireSRWLockExclusive(&sw2_lock);
        for (int i = 0; i < SW2_MAX; i++) {   /* (gone ones let go; a failed one unplugged may be tried at once) */
            int present = 0;
            for (int k = 0; k < n; k++) present |= !strcmp(sw2[i].key, keys[k]);
            if ((sw2[i].state == SLOT_GONE && !sw2[i].opened) || (sw2[i].state == SLOT_FAILED && !present))
                sw2[i].state = SLOT_FREE, sw2[i].key[0] = 0;
        }
        for (int k = 0; k < n; k++) {
            int have = -1, free_slot = -1;
            for (int i = 0; i < SW2_MAX; i++) {
                if (sw2[i].state != SLOT_FREE && !strcmp(sw2[i].key, keys[k])) have = i;
                if (sw2[i].state == SLOT_FREE && free_slot < 0) free_slot = i;
            }
            if (have >= 0 && sw2[have].state == SLOT_FAILED && now >= sw2[have].retry_ns) free_slot = have;
            else if (have >= 0) continue;
            if (free_slot < 0) continue;
            Sw2Pad *p = &sw2[free_slot];
            memset((char *)p + offsetof(Sw2Pad, key), 0, sizeof *p - offsetof(Sw2Pad, key));
            InitializeSRWLock(&p->lock);
            snprintf(p->key, sizeof p->key, "%s", keys[k]);
            for (int s = 0; s < 2; s++) sw2_silence(p->want[s]);
            p->stop = 0;
            p->id = 0x7E000000 + (++sw2_serial & 0xFFFFFF);
            p->state = SLOT_STARTING;
            HANDLE t = CreateThread(NULL, 0, sw2_main, p, 0, NULL);
            if (t) CloseHandle(t);
            else p->state = SLOT_FAILED, p->retry_ns = now + 5000000000LL;
        }
        ReleaseSRWLockExclusive(&sw2_lock);
    }
    int count = 0;
    AcquireSRWLockShared(&sw2_lock);
    for (int i = 0; i < SW2_MAX && count < max; i++)
        if (sw2[i].state == SLOT_READY) ids[count] = sw2[i].id, opens[count] = -1 - i, count++;
    ReleaseSRWLockShared(&sw2_lock);
    return count;
}
void *hos_sw2_open(int what) {
    const int i = -1 - what;
    if (i < 0 || i >= SW2_MAX) return NULL;
    AcquireSRWLockExclusive(&sw2_lock);
    void *p = sw2[i].state == SLOT_READY ? (sw2[i].opened = 1, &sw2[i]) : NULL;
    ReleaseSRWLockExclusive(&sw2_lock);
    return p;
}
void hos_sw2_close(void *pad) {
    Sw2Pad *p = pad;
    AcquireSRWLockExclusive(&sw2_lock);
    p->opened = 0;
    InterlockedExchange(&p->stop, 1);   /* (a pad closed while it is still there lets it go too) */
    ReleaseSRWLockExclusive(&sw2_lock);
}
int hos_sw2_connected(void *pad) { return ((Sw2Pad *)pad)->state == SLOT_READY; }
int32_t hos_sw2_id(void *pad) { return ((Sw2Pad *)pad)->id; }
const char *hos_sw2_name(void *pad) { (void)pad; return "Nintendo Switch 2 Pro Controller"; }
int hos_sw2_button(void *pad, int button) {
    Sw2Pad *p = pad;
    if (button < 0 || button > SW2_RIGHT) return 0;
    AcquireSRWLockShared(&p->lock);
    const int on = p->in.buttons >> button & 1;
    ReleaseSRWLockShared(&p->lock);
    return on;
}
int16_t hos_sw2_axis(void *pad, int axis) {   /* (SDL's: LX LY RX RY, then the triggers, ZL and ZR full or not) */
    Sw2Pad *p = pad;
    AcquireSRWLockShared(&p->lock);
    const int16_t v = axis >= 0 && axis < 4 ? p->in.axis[axis]
                    : axis == 4 ? (p->in.buttons >> SW2_ZL & 1 ? 32767 : 0)
                    : axis == 5 ? (p->in.buttons >> SW2_ZR & 1 ? 32767 : 0) : 0;
    ReleaseSRWLockShared(&p->lock);
    return v;
}
int hos_sw2_has_sensor(void *pad, int type) { (void)pad; return type == HOS_SDL_SENSOR_ACCEL || type == HOS_SDL_SENSOR_GYRO; }
int hos_sw2_sensor_enable(void *pad, int type, int on) {
    (void)type;
    ((Sw2Pad *)pad)->sensors_on = on;   /* (the sensors run all the time; off, they are not read) */
    return 1;
}
int hos_sw2_sensor(void *pad, int type, float *data, int n) {
    Sw2Pad *p = pad;
    if (!p->sensors_on || n < 3) return 0;
    AcquireSRWLockShared(&p->lock);
    const int ok = p->imu;
    if (ok) memcpy(data, type == HOS_SDL_SENSOR_GYRO ? p->gyro : p->accel, 3 * sizeof(float));
    ReleaseSRWLockShared(&p->lock);
    return ok;
}
/* The game's vibration values for both sides (as hd_rumble_felt gives them), at the menu's Rumble strength */
void hos_sw2_rumble_hd(void *pad, const float left[4], const float right[4], int percent) {
    Sw2Pad *p = pad;
    uint8_t s[2][5];
    sw2_side(left, percent, s[0]), sw2_side(right, percent, s[1]);
    AcquireSRWLockExclusive(&p->lock);
    memcpy(p->want, s, sizeof s);
    p->motor_until = 0;
    ReleaseSRWLockExclusive(&p->lock);
}
/* (HOS_HD_RUMBLE=0) two motors' strengths for ms milliseconds, as SDL_RumbleGamepad */
void hos_sw2_rumble(void *pad, uint16_t low, uint16_t high, uint32_t ms) {
    Sw2Pad *p = pad;
    uint8_t s[5];
    sw2_side_motors(low, high, s);
    AcquireSRWLockExclusive(&p->lock);
    memcpy(p->want[0], s, 5), memcpy(p->want[1], s, 5);
    p->motor_until = (low || high) && ms ? hos_now_ns() + (int64_t)ms * 1000000 : 0;
    ReleaseSRWLockExclusive(&p->lock);
}
