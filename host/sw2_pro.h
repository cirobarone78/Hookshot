/* (hookshot) The Nintendo Switch 2 Pro Controller (USB 057E:2069) over USB: its protocol, for host/pad_sw2.c.

   The controller enumerates with a HID interface (0) and a vendor interface (1) with a bulk pipe pair, and sends no
   input until it is set up through the bulk pipes: its calibration read from its flash, then a fixed command
   sequence that starts its 64-byte input reports (format 0x05, every 4 ms) on the HID interface. Its rumble goes out
   on the HID interface too, as output report 0x02. This is the protocol of SDL's Switch 2 driver
   (src/joystick/hidapi/SDL_hidapi_switch2.c, by Vicki Pfau and Sam Lantinga for Valve, zlib license): the init
   sequence, the flash addresses, the input report's layout, the sensor scales and the rumble encoding are SDL's, ported
   here so that no libusb (which SDL's driver needs) and no patched SDL are needed. SDL's driver plays its rumble at
   two fixed frequencies; the game's own vibration values (frequency and amplitude of both bands, per side) go out as
   HD rumble the way Fritchii's Switch 2 Pro Controller support does it (Frizti/Fritchii PR #6, by 101Leafy, GPL-3.0):
   three 5 ms samples a report, frequency code round(96 * log2(Hz / 10)), measured with the controller's own
   accelerometer within about 1% from 20 to 357 Hz (no official documentation).

   Pure (no state but what is passed, no I/O but the callbacks of sw2_setup): tests/test_switch2_pro.py compiles it. */
#pragma once
#include <math.h>
#include <stdint.h>
#include <string.h>

#define SW2_VID 0x057E
#define SW2_PID_PRO 0x2069   /* (SDL's USB_PRODUCT_NINTENDO_SWITCH2_PRO; the Joy-Con 2 are 0x2066/0x2067, the GameCube
                                controller 0x2073: not handled here. The Switch 1 Pro Controller is 0x2009) */
static inline int sw2_is_pro(unsigned vid, unsigned pid) { return vid == SW2_VID && pid == SW2_PID_PRO; }

#define SW2_REPORT_SIZE 64
#define SW2_INPUT_REPORT 0x05          /* (the format the init sequence asks for: "Set report format") */
#define SW2_RUMBLE_REPORT 0x02         /* (the Pro Controller's: both actuators) */
#define SW2_RUMBLE_INTERVAL_NS 12000000LL   /* (SDL's RUMBLE_INTERVAL: a rumble that plays is sent again this often) */
#define SW2_AMP_MAX 453                /* (SDL's RUMBLE_MAX, 29000 of 65535, as the 10-bit field: the strongest SDL sends) */
#define SW2_FREQ_HIGH_DEFAULT 0x187    /* (SDL's fixed frequencies: 168 Hz and 72 Hz on the measured scale) */
#define SW2_FREQ_LOW_DEFAULT 0x112

/* ---- the bulk commands (SDL's): [command, 0x91, 0, subcommand, 0, data length, 0, 0, data...] ---- */
static inline int sw2_cmd_len(const uint8_t *cmd) { return cmd[5] + 8; }
static const uint8_t sw2_init_0[] = {0x07, 0x91, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00};
static const uint8_t sw2_init_1[] = {0x0c, 0x91, 0x00, 0x02, 0x00, 0x04, 0x00, 0x00, 0x27, 0x00, 0x00, 0x00};   /* (feature mask: IMU on) */
static const uint8_t sw2_init_2[] = {0x11, 0x91, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00};
static const uint8_t sw2_init_3[] = {0x0a, 0x91, 0x00, 0x08, 0x00, 0x14, 0x00, 0x00, 0x01, 0xff, 0xff, 0xff, 0xff, 0xff,
                                     0xff, 0xff, 0xff, 0x35, 0x00, 0x46, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00};
static const uint8_t sw2_init_4[] = {0x0c, 0x91, 0x00, 0x04, 0x00, 0x04, 0x00, 0x00, 0x27, 0x00, 0x00, 0x00};   /* (features on) */
static const uint8_t sw2_init_5[] = {0x01, 0x91, 0x00, 0x0c, 0x00, 0x00, 0x00, 0x00};
static const uint8_t sw2_init_6[] = {0x01, 0x91, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00};   /* (rumble on) */
static const uint8_t sw2_init_7[] = {0x08, 0x91, 0x00, 0x02, 0x00, 0x04, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00};
static const uint8_t sw2_init_8[] = {0x03, 0x91, 0x00, 0x0a, 0x00, 0x04, 0x00, 0x00, SW2_INPUT_REPORT, 0x00, 0x00, 0x00};
static const uint8_t sw2_init_9[] = {0x03, 0x91, 0x00, 0x0d, 0x00, 0x08, 0x00, 0x00, 0x01, 0x00, 0xff, 0xff, 0xff, 0xff,
                                     0xff, 0xff};   /* (start the input reports) */
static const uint8_t *const sw2_init[] = {sw2_init_0, sw2_init_1, sw2_init_2, sw2_init_3, sw2_init_4,
                                          sw2_init_5, sw2_init_6, sw2_init_7, sw2_init_8, sw2_init_9};
#define SW2_INIT_N ((int)(sizeof sw2_init / sizeof sw2_init[0]))

/* a flash read of 0x40 bytes at addr (the reply: 0x50 bytes, the data from 0x10) */
static inline void sw2_cmd_flash_read(uint32_t addr, uint8_t out[16]) {
    static const uint8_t c[16] = {0x02, 0x91, 0x00, 0x01, 0x00, 0x08, 0x00, 0x00};
    memcpy(out, c, 16);
    out[12] = (uint8_t)addr, out[13] = (uint8_t)(addr >> 8), out[14] = (uint8_t)(addr >> 16), out[15] = (uint8_t)(addr >> 24);
}
/* the player lights: player 0 to 7 (SDL's patterns: 1, 2, 3, 4 lights from the left, then the four others), -1 off */
static inline void sw2_cmd_led(int player, uint8_t out[16]) {
    static const uint8_t c[16] = {0x09, 0x91, 0x00, 0x07, 0x00, 0x08, 0x00, 0x00};
    static const uint8_t pattern[8] = {0x1, 0x3, 0x7, 0xf, 0x9, 0x5, 0xd, 0x6};
    memcpy(out, c, 16);
    if (player >= 0) out[8] = pattern[player % 8];
}

/* ---- the USB descriptors (Linux reads them from usbfs): the HID interface's interrupt pipes and the vendor
   interface's bulk pipes, from the first configuration's alternate setting 0 ---- */
typedef struct {
    uint8_t hid_if, hid_in, hid_out;     /* (hid_out 0: none, the reports go as SET_REPORT on the control pipe) */
    uint8_t bulk_if, bulk_in, bulk_out;
} Sw2Endpoints;
/* 1 when the interfaces are there as expected: interface 0 HID (class 3) with an interrupt IN, interface 1 (SDL takes
   the bulk pair of interface number 1) with a bulk IN and OUT */
static inline int sw2_parse_descriptors(const uint8_t *d, int n, Sw2Endpoints *e) {
    memset(e, 0, sizeof *e);
    int iface = -1, alt = 0, cls = 0, configs = 0;
    for (int at = 0; at + 2 <= n;) {
        const int len = d[at], type = d[at + 1];
        if (len < 2 || at + len > n) break;
        if (type == 2 && ++configs > 1) break;   /* (a second configuration) */
        if (type == 4 && len >= 9) iface = d[at + 2], alt = d[at + 3], cls = d[at + 5];
        if (type == 5 && len >= 7 && alt == 0) {
            const uint8_t addr = d[at + 2], kind = d[at + 3] & 3;
            if (iface == 0 && cls == 3 && kind == 3) {
                e->hid_if = 0;
                if (addr & 0x80) e->hid_in = e->hid_in ? e->hid_in : addr;
                else e->hid_out = e->hid_out ? e->hid_out : addr;
            }
            if (iface == 1 && kind == 2) {
                e->bulk_if = 1;
                if (addr & 0x80) e->bulk_in = e->bulk_in ? e->bulk_in : addr;
                else e->bulk_out = e->bulk_out ? e->bulk_out : addr;
            }
        }
        at += len;
    }
    return e->hid_in && e->bulk_in && e->bulk_out;
}

/* ---- calibration (SDL's ParseStickCalibration and MapJoystickAxis) ---- */
typedef struct { uint16_t neutral, max, min; } Sw2AxisCal;   /* (max and min: the distances from neutral) */
typedef struct { Sw2AxisCal x, y; } Sw2StickCal;
static inline void sw2_stick_cal_parse(const uint8_t *d, Sw2StickCal *s) {
    s->x.neutral = (uint16_t)(d[0] | (d[1] & 0x0F) << 8), s->y.neutral = (uint16_t)(d[1] >> 4 | d[2] << 4);
    s->x.max = (uint16_t)(d[3] | (d[4] & 0x0F) << 8), s->y.max = (uint16_t)(d[4] >> 4 | d[5] << 4);
    s->x.min = (uint16_t)(d[6] | (d[7] & 0x0F) << 8), s->y.min = (uint16_t)(d[7] >> 4 | d[8] << 4);
}
/* a stick's 12-bit reading as SDL's axis (-32768 to 32767; invert: SDL's Y, down positive) */
static inline int16_t sw2_axis(const Sw2AxisCal *c, float value, int invert) {
    int16_t v;
    if (c && c->neutral && c->min && c->max) {
        value -= c->neutral;
        value = value < 0 ? value / c->min : value / c->max;
        const float s = value * 32767.0f;
        v = (int16_t)(s < -32768.0f ? -32768.0f : s > 32767.0f ? 32767.0f : s);
    } else {
        v = (int16_t)(-32768.0f + (32767.0f - -32768.0f) * (value - 0.0f) / (4096.0f - 0.0f));
    }
    return invert ? (int16_t)~v : v;
}

typedef struct {
    Sw2StickCal stick[2];      /* (left, right; zero when the flash did not say: the raw range then) */
    float gyro_bias[3];        /* (factory: rad/s, x y z as the flash has them) */
    char serial[17];
} Sw2Calibration;

/* ---- the input report (format 0x05, SDL's HandleSwitchProState) ---- */
/* The buttons: up to SW2_RIGHT in SDL's gamepad order, which are host/pad_sdl.c's (and HOS_PAD_*) positions: the
   bottom face button first (B on this controller), then the right one (A), the left (Y), the top (X). */
enum { SW2_SOUTH, SW2_EAST, SW2_WEST, SW2_NORTH, SW2_MINUS, SW2_HOME, SW2_PLUS, SW2_LS, SW2_RS, SW2_L, SW2_R, SW2_UP,
       SW2_DOWN, SW2_LEFT, SW2_RIGHT, SW2_CAPTURE, SW2_ZL, SW2_ZR, SW2_GL, SW2_GR, SW2_C, SW2_BTN_N };
typedef struct {
    uint32_t buttons;          /* 1 << SW2_* */
    int16_t axis[4];           /* SDL's: left x, left y, right x, right y (y down positive) */
    uint32_t imu_ts;           /* (the sensors' clock; 0 none yet) */
    int16_t accel[3], gyro[3]; /* (raw, in the report's order) */
} Sw2Input;
/* 1 when r was an input report (SDL takes any report of 64 bytes or more; so does this, the first byte its id) */
static inline int sw2_parse(const uint8_t *r, int n, const Sw2Calibration *cal, Sw2Input *out) {
    if (n < SW2_REPORT_SIZE) return 0;
    static const struct { uint8_t byte, mask, button; } map[] = {
        {5, 0x01, SW2_WEST}, {5, 0x02, SW2_NORTH}, {5, 0x04, SW2_SOUTH}, {5, 0x08, SW2_EAST}, {5, 0x40, SW2_R},
        {5, 0x80, SW2_ZR}, {6, 0x01, SW2_MINUS}, {6, 0x02, SW2_PLUS}, {6, 0x04, SW2_RS}, {6, 0x08, SW2_LS},
        {6, 0x10, SW2_HOME}, {6, 0x20, SW2_CAPTURE}, {6, 0x40, SW2_C}, {7, 0x01, SW2_DOWN}, {7, 0x02, SW2_UP},
        {7, 0x04, SW2_RIGHT}, {7, 0x08, SW2_LEFT}, {7, 0x40, SW2_L}, {7, 0x80, SW2_ZL}, {8, 0x01, SW2_GR},
        {8, 0x02, SW2_GL}};
    uint32_t b = 0;
    for (unsigned i = 0; i < sizeof map / sizeof map[0]; i++)
        if (r[map[i].byte] & map[i].mask) b |= 1u << map[i].button;
    out->buttons = b;
    const Sw2StickCal *l = cal ? &cal->stick[0] : NULL, *rs = cal ? &cal->stick[1] : NULL;
    out->axis[0] = sw2_axis(l ? &l->x : NULL, (float)(r[11] | (r[12] & 0x0F) << 8), 0);
    out->axis[1] = sw2_axis(l ? &l->y : NULL, (float)(r[12] >> 4 | r[13] << 4), 1);
    out->axis[2] = sw2_axis(rs ? &rs->x : NULL, (float)(r[14] | (r[15] & 0x0F) << 8), 0);
    out->axis[3] = sw2_axis(rs ? &rs->y : NULL, (float)(r[15] >> 4 | r[16] << 4), 1);
    out->imu_ts = (uint32_t)r[0x2b] | (uint32_t)r[0x2c] << 8 | (uint32_t)r[0x2d] << 16 | (uint32_t)r[0x2e] << 24;
    for (int k = 0; k < 3; k++) {
        out->accel[k] = (int16_t)(r[0x31 + 2 * k] | r[0x32 + 2 * k] << 8);
        out->gyro[k] = (int16_t)(r[0x37 + 2 * k] | r[0x38 + 2 * k] << 8);
    }
    return 1;
}

/* The sensors' scale (SDL): the gyroscope's full scale is 34.8 rad/s when the sensor clock runs in microseconds, 40
   when it runs otherwise (some controllers), found from 100 reports' clock after the first 5 */
typedef struct {
    int count, ready;
    uint32_t first;
    float gyro_coeff;
} Sw2ImuClock;
static inline void sw2_imu_clock_feed(Sw2ImuClock *c, uint32_t ts) {
    if (!ts || c->ready) return;
    c->count++;
    if (c->count >= 5 && !c->first) {
        c->first = ts, c->count = 0;
    } else if (c->count == 100) {
        const uint64_t coeff = 1000ull * (uint32_t)(ts - c->first) / (uint64_t)(c->count * 4);
        if ((coeff + 100000) / 200000 == 5) c->gyro_coeff = 34.8f, c->ready = 1;
        else if (coeff) c->gyro_coeff = 40.0f, c->ready = 1;
        else c->first = 0, c->count = 0;   /* (no reading yet: again) */
    }
}
/* the report's sensors as SDL's: accel in m/s^2, gyro in rad/s, both in SDL's axes (x right, y up, z towards the
   player), the factory gyro bias taken off */
static inline void sw2_imu(const Sw2Input *in, float gyro_coeff, const float bias[3], float accel[3], float gyro[3]) {
    const float scale = 9.80665f * 8.0f / 32767.0f;
    accel[0] = in->accel[0] * scale;
    accel[1] = in->accel[2] * scale;
    accel[2] = in->accel[1] * -scale;
    gyro[0] = in->gyro[0] * gyro_coeff / 32767.0f - bias[0];
    gyro[1] = in->gyro[2] * gyro_coeff / 32767.0f - bias[2];
    gyro[2] = in->gyro[1] * -gyro_coeff / 32767.0f + bias[1];
}

/* ---- HD rumble ---- */
/* A frequency's code: round(96 * log2(Hz / 10)), 0 to 1023 (10 Hz to 15.9 kHz); a frequency that is not one (0, NaN)
   gets otherwise */
static inline int sw2_freq_code(float hz, int otherwise) {
    if (!(hz > 0.0f)) return otherwise;   /* (also NaN) */
    const double c = floor(96.0 * log2((hz < 10.0f ? 10.0 : (double)hz) / 10.0) + 0.5);
    return c > 1023 ? 1023 : (int)c;
}
/* An amplitude (0 to 1) as the 10-bit field: linear, 1 at SW2_AMP_MAX (SDL's strongest; the console's own scale is not
   known) */
static inline int sw2_amp_field(float a) {
    if (!(a > 0.0f)) return 0;   /* (also NaN) */
    return a >= 1.0f ? SW2_AMP_MAX : (int)floorf(a * SW2_AMP_MAX + 0.5f);
}
/* One sample: four 10-bit fields, little endian (SDL's EncodeHDRumble, with the amplitudes as the fields) */
static inline void sw2_sample(int hf, int ha, int lf, int la, uint8_t out[5]) {
    const uint64_t v = (uint64_t)(hf & 0x3FF) | (uint64_t)(ha & 0x3FF) << 10 | (uint64_t)(lf & 0x3FF) << 20 |
                       (uint64_t)(la & 0x3FF) << 30;
    for (int i = 0; i < 5; i++) out[i] = (uint8_t)(v >> 8 * i);
}
static inline void sw2_silence(uint8_t out[5]) { sw2_sample(SW2_FREQ_HIGH_DEFAULT, 0, SW2_FREQ_LOW_DEFAULT, 0, out); }
static inline int sw2_silent(const uint8_t s[5]) {
    const uint64_t v = (uint64_t)s[0] | (uint64_t)s[1] << 8 | (uint64_t)s[2] << 16 | (uint64_t)s[3] << 24 | (uint64_t)s[4] << 32;
    return !(v >> 10 & 0x3FF) && !(v >> 30 & 0x3FF);
}
/* One side from the game's vibration value {amp_low, freq_low, amp_high, freq_high} (as host/hd_rumble.h's
   hd_rumble_felt gives it), the amplitudes scaled by percent the way hd_rumble_encode scales them (over 100 both bands
   by the same factor, the stronger stopping at 1) */
static inline void sw2_side(const float v[4], int percent, uint8_t out[5]) {
    float scale = percent > 0 ? (float)percent / 100.0f : 0.0f;
    const float top = v[0] > v[2] ? v[0] : v[2];
    if (scale > 1.0f && top * scale > 1.0f) scale = top > 1.0f ? 1.0f : 1.0f / top;   /* (NaN: not above, kept) */
    const int la = sw2_amp_field(v[0] * scale), ha = sw2_amp_field(v[2] * scale);
    if (!la && !ha) {
        sw2_silence(out);
        return;
    }
    sw2_sample(sw2_freq_code(v[3], SW2_FREQ_HIGH_DEFAULT), ha, sw2_freq_code(v[1], SW2_FREQ_LOW_DEFAULT), la, out);
}
/* One side from two motor strengths (0 to 65535: low, high), as SDL plays SDL_RumbleGamepad on this controller: its
   fixed frequencies, the amplitudes scaled to RUMBLE_MAX (HOS_HD_RUMBLE=0) */
static inline void sw2_side_motors(uint16_t low, uint16_t high, uint8_t out[5]) {
    const int la = (int)((unsigned)low * 29000u / 65535u) >> 6, ha = (int)((unsigned)high * 29000u / 65535u) >> 6;
    sw2_sample(SW2_FREQ_HIGH_DEFAULT, ha, SW2_FREQ_LOW_DEFAULT, la, out);
}
/* The rumble report (Fritchii's): id 0x02; the left actuator at 0x01 (sequence number, then three 5 ms samples), the
   right at 0x11; the rest zero */
static inline void sw2_rumble_report(uint32_t seq, const uint8_t left[5], const uint8_t right[5], uint8_t out[SW2_REPORT_SIZE]) {
    memset(out, 0, SW2_REPORT_SIZE);
    out[0] = SW2_RUMBLE_REPORT;
    out[0x01] = out[0x11] = (uint8_t)(0x50 | (seq & 0xF));
    for (int i = 0; i < 3; i++) {
        memcpy(out + 0x02 + 5 * i, left, 5);
        memcpy(out + 0x12 + 5 * i, right, 5);
    }
}

/* What the pad plays and when its next report goes: a change goes at once (no sooner than the interval after the last),
   a rumble that plays is sent again every interval, silence once */
typedef struct {
    uint8_t side[2][5];
    int dirty;
    int64_t next_ns;
    uint32_t seq;
} Sw2Rumble;
static inline void sw2_rumble_init(Sw2Rumble *r) {
    memset(r, 0, sizeof *r);
    sw2_silence(r->side[0]), sw2_silence(r->side[1]);
}
static inline void sw2_rumble_set(Sw2Rumble *r, const uint8_t left[5], const uint8_t right[5]) {
    if (memcmp(r->side[0], left, 5) || memcmp(r->side[1], right, 5)) {
        memcpy(r->side[0], left, 5), memcpy(r->side[1], right, 5);
        r->dirty = 1;
    }
}
static inline int sw2_rumble_due(const Sw2Rumble *r, int64_t now) {
    return (r->dirty || !sw2_silent(r->side[0]) || !sw2_silent(r->side[1])) && now >= r->next_ns;
}
static inline void sw2_rumble_next(Sw2Rumble *r, int64_t now, uint8_t out[SW2_REPORT_SIZE]) {
    sw2_rumble_report(r->seq++, r->side[0], r->side[1], out);
    r->dirty = 0;
    r->next_ns = now + SW2_RUMBLE_INTERVAL_NS;
}

/* ---- the GL and GR buttons: nothing on the console unless the player assigns them; here HOS_SW2_GL / HOS_SW2_GR name
   the input they press (a SDL button position, or zl / zr), else nothing ---- */
static inline int sw2_extra_target(const char *name) {
    static const char *const names[] = {"south", "east", "west", "north", "back", "guide", "start", "lstick", "rstick",
                                        "lshoulder", "rshoulder", "up", "down", "left", "right", "", "zl", "zr"};
    if (!name || !name[0]) return -1;
    for (int i = 0; i < (int)(sizeof names / sizeof names[0]); i++)
        if (names[i][0] && !strcmp(name, names[i])) return i;   /* (SW2_SOUTH ... SW2_RIGHT, SW2_ZL, SW2_ZR) */
    return -1;
}

/* ---- the setup over the bulk pipes (SDL's HIDAPI_DriverSwitch2_InitUSB, then its player lights) ---- */
typedef struct {
    void *ctx;
    int (*out)(void *ctx, const uint8_t *data, int size);              /* bytes sent, < 0 an error */
    int (*in)(void *ctx, uint8_t *data, int size, int timeout_ms);     /* bytes read, < 0 an error */
} Sw2Bulk;
/* a reply: 64 bytes at a time until a short one (SDL's RecvBulkData) */
static inline int sw2_recv(const Sw2Bulk *b, uint8_t *data, int size) {
    int total = 0;
    while (size > 0) {
        const int want = size > 64 ? 64 : size;
        const int got = b->in(b->ctx, data, want, 100);
        if (got < 0) return got;
        total += got, size -= got, data += want;
        if (got < want) break;
    }
    return total;
}
static inline int sw2_flash_read(const Sw2Bulk *b, uint32_t addr, uint8_t out[0x40]) {
    uint8_t cmd[16], reply[0x50] = {0};
    sw2_cmd_flash_read(addr, cmd);
    int r = b->out(b->ctx, cmd, sizeof cmd);
    if (r < 0) return r;
    if ((r = sw2_recv(b, reply, sizeof reply)) < 0) return r;
    memcpy(out, reply + 0x10, 0x40);
    return 0;
}
/* Calibration from the flash (what cannot be read stays zero: the raw range, no bias), the init sequence, the player
   lights. 1 when the controller took the sequence (its input reports start), 0 when a command could not be sent. */
static inline int sw2_setup(const Sw2Bulk *b, Sw2Calibration *cal, int player) {
    uint8_t d[0x40];
    memset(cal, 0, sizeof *cal);
    if (!sw2_flash_read(b, 0x13000, d)) memcpy(cal->serial, d + 2, 16);
    if (!sw2_flash_read(b, 0x13040, d))
        memcpy(&cal->gyro_bias[0], d + 4, 4), memcpy(&cal->gyro_bias[1], d + 8, 4), memcpy(&cal->gyro_bias[2], d + 12, 4);
    if (!sw2_flash_read(b, 0x13080, d)) sw2_stick_cal_parse(d + 0x28, &cal->stick[0]);
    if (!sw2_flash_read(b, 0x130C0, d)) sw2_stick_cal_parse(d + 0x28, &cal->stick[1]);
    if (!sw2_flash_read(b, 0x1FC040, d) && d[0] == 0xb2 && d[1] == 0xa1) sw2_stick_cal_parse(d + 2, &cal->stick[0]);   /* (the user's) */
    if (!sw2_flash_read(b, 0x1FC080, d) && d[0] == 0xb2 && d[1] == 0xa1) sw2_stick_cal_parse(d + 2, &cal->stick[1]);
    for (int i = 0; i < 3; i++)
        if (!(cal->gyro_bias[i] == cal->gyro_bias[i]) || fabsf(cal->gyro_bias[i]) > 1.0f) cal->gyro_bias[i] = 0.0f;   /* (unset flash) */
    for (int i = 0; i < SW2_INIT_N; i++) {
        if (b->out(b->ctx, sw2_init[i], sw2_cmd_len(sw2_init[i])) < 0) return 0;
        sw2_recv(b, d, 0x40);
    }
    uint8_t led[16];
    sw2_cmd_led(player, led);
    if (b->out(b->ctx, led, sizeof led) >= 0) sw2_recv(b, d, 8);
    return 1;
}
