"""The Switch 2 Pro Controller's own driver (host/sw2_pro.h, host/pad_sw2.c), without the controller.

host/sw2_pro.h ports the protocol of SDL's Switch 2 driver (src/joystick/hidapi/SDL_hidapi_switch2.c, zlib license)
and the HD rumble report of Fritchii's Switch 2 Pro Controller support (Frizti/Fritchii PR #6, GPL-3.0). The fixtures
below hold copies of the functions it was ported from (SDL's report handling, stick calibration, sensor scales and
rumble encoding; Fritchii's HD rumble report), run on the same bytes, and compared:

- which USB ids are taken: 057E:2069 only (never the Switch Pro Controller, 057E:2009, nor the Joy-Con 2 or the
  GameCube controller);
- the input report: every button, the sticks with and without calibration, the sensors and their clock;
- the HD rumble: the bit packing, the frequency scale 10 Hz x 2^(code / 96) both ways, amplitudes and their cap, the
  report's layout, its cadence, SDL's fixed-frequency rumble for HOS_HD_RUMBLE=0;
- the setup over the bulk pipes, against a fake controller: the flash reads, the calibration, the init sequence, the
  player lights;
- the USB descriptors as usbfs gives them; the usbfs requests against linux/usbdevice_fs.h (Linux only);
- how it is wired in: host/hos_sdl.c hands the pads over and leaves SDL's view of the controller out,
  host/pad_sdl.c sends it the game's vibration values.

Nothing here opens a device. Run with: python -I -B tests/test_switch2_pro.py
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "host"
PAD = HOST / "pad_sw2.c"
SDLPAD = HOST / "pad_sdl.c"
SDLWRAP = HOST / "hos_sdl.c"


def function(path, name):
    text = path.read_text(encoding="utf-8")
    found = re.search(re.escape(name) + r"\([^;{]*\)\s*\{", text)   # (the definition, not a declaration)
    if not found:
        raise RuntimeError("no definition of " + name)
    at, start, depth = found.start(), found.end() - 1, 0
    for i in range(start, len(text)):
        depth += text[i] == "{"
        depth -= text[i] == "}"
        if depth == 0:
            return text[at:i + 1]
    raise RuntimeError("no end for " + name)


def build_and_run(test, source, extra=()):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "sw2.c")
        with open(path, "w", encoding="utf-8") as f:
            f.write(source)
        exe = os.path.join(d, "sw2.exe" if os.name == "nt" else "sw2")
        cc = os.environ.get("CC", "cc")
        made = subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", *extra, "-I",
                               str(HOST), path, "-o", exe, "-lm"], capture_output=True, text=True)
        test.assertEqual(made.returncode, 0, made.stderr)
        ran = subprocess.run([exe], capture_output=True, text=True)
        test.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
        return ran.stdout


COMMON = r"""
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "sw2_pro.h"
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL %d %s\n", __LINE__, #x); return 1; } } while (0)
static uint32_t rng = 12345;
static uint32_t rnd(void) { rng = rng * 1664525u + 1013904223u; return rng >> 8; }
typedef uint8_t Uint8;
typedef uint16_t Uint16;
typedef int16_t Sint16;
typedef uint32_t Uint32;
typedef uint64_t Uint64;
#define SDL_MIN_SINT16 (-32768)
#define SDL_MAX_SINT16 32767
#define SDL_clamp(x, a, b) (((x) < (a)) ? (a) : (((x) > (b)) ? (b) : (x)))
#define SDL_memcpy memcpy
"""

# ---- copies from SDL (src/joystick/hidapi/SDL_hidapi_switch2.c, SDL_hidapijoystick.c, release 3.4.20 = main as of
# 2026-11; zlib license, Copyright (C) 1997-2026 Sam Lantinga), with SDL's joystick calls recording into arrays ----
SDL_COPY = r"""
enum { SDL_GAMEPAD_BUTTON_SOUTH, SDL_GAMEPAD_BUTTON_EAST, SDL_GAMEPAD_BUTTON_WEST, SDL_GAMEPAD_BUTTON_NORTH,
       SDL_GAMEPAD_BUTTON_BACK, SDL_GAMEPAD_BUTTON_GUIDE, SDL_GAMEPAD_BUTTON_START, SDL_GAMEPAD_BUTTON_LEFT_STICK,
       SDL_GAMEPAD_BUTTON_RIGHT_STICK, SDL_GAMEPAD_BUTTON_LEFT_SHOULDER, SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER };
enum { SDL_GAMEPAD_BUTTON_SWITCH2_PRO_SHARE = 11, SDL_GAMEPAD_BUTTON_SWITCH2_PRO_C, SDL_GAMEPAD_BUTTON_SWITCH2_PRO_RIGHT_PADDLE,
       SDL_GAMEPAD_BUTTON_SWITCH2_PRO_LEFT_PADDLE };
enum { SDL_GAMEPAD_AXIS_LEFTX, SDL_GAMEPAD_AXIS_LEFTY, SDL_GAMEPAD_AXIS_RIGHTX, SDL_GAMEPAD_AXIS_RIGHTY,
       SDL_GAMEPAD_AXIS_LEFT_TRIGGER, SDL_GAMEPAD_AXIS_RIGHT_TRIGGER };
#define SDL_HAT_UP 0x01
#define SDL_HAT_RIGHT 0x02
#define SDL_HAT_DOWN 0x04
#define SDL_HAT_LEFT 0x08
typedef struct SDL_Joystick SDL_Joystick;
static int sdl_button[16], sdl_hat;
static Sint16 sdl_axis[6];
static void SDL_SendJoystickButton(Uint64 t, SDL_Joystick *j, int b, int down) { (void)t, (void)j; sdl_button[b] = down; }
static void SDL_SendJoystickHat(Uint64 t, SDL_Joystick *j, int h, Uint8 v) { (void)t, (void)j, (void)h; sdl_hat = v; }
static void SDL_SendJoystickAxis(Uint64 t, SDL_Joystick *j, int a, Sint16 v) { (void)t, (void)j; sdl_axis[a] = v; }
typedef struct { Uint16 neutral; Uint16 max; Uint16 min; } Switch2_AxisCalibration;
typedef struct { Switch2_AxisCalibration x; Switch2_AxisCalibration y; } Switch2_StickCalibration;
typedef struct {
    Switch2_StickCalibration left_stick, right_stick;
    float gyro_bias_x, gyro_bias_y, gyro_bias_z;
    bool sensors_ready; int sample_count; Uint64 first_sensor_timestamp; Uint64 sensor_ts_coeff; float gyro_coeff;
    Uint8 last_state[64];
} SDL_DriverSwitch2_Context;

static float HIDAPI_RemapVal(float val, float val_min, float val_max, float output_min, float output_max)
{
    return output_min + (output_max - output_min) * (val - val_min) / (val_max - val_min);
}
static void ParseStickCalibration(Switch2_StickCalibration *stick_data, const Uint8 *data)
{
    stick_data->x.neutral = data[0];
    stick_data->x.neutral |= (data[1] & 0x0F) << 8;
    stick_data->y.neutral = data[1] >> 4;
    stick_data->y.neutral |= data[2] << 4;
    stick_data->x.max = data[3];
    stick_data->x.max |= (data[4] & 0x0F) << 8;
    stick_data->y.max = data[4] >> 4;
    stick_data->y.max |= data[5] << 4;
    stick_data->x.min = data[6];
    stick_data->x.min |= (data[7] & 0x0F) << 8;
    stick_data->y.min = data[7] >> 4;
    stick_data->y.min |= data[8] << 4;
}
static void MapJoystickAxis(Uint64 timestamp, SDL_Joystick *joystick, Uint8 axis, const Switch2_AxisCalibration *calib, float value, bool invert)
{
    Sint16 mapped_value;
    if (calib && calib->neutral && calib->min && calib->max) {
        value -= calib->neutral;
        if (value < 0) {
            value /= calib->min;
        } else {
            value /= calib->max;
        }
        mapped_value = (Sint16) SDL_clamp(value * SDL_MAX_SINT16, SDL_MIN_SINT16, SDL_MAX_SINT16);
    } else {
        mapped_value = (Sint16) HIDAPI_RemapVal(value, 0, 4096, SDL_MIN_SINT16, SDL_MAX_SINT16);
    }
    if (invert) {
        mapped_value = ~mapped_value;
    }
    SDL_SendJoystickAxis(timestamp, joystick, axis, mapped_value);
}
static void HandleSwitchProState(Uint64 timestamp, SDL_Joystick *joystick, SDL_DriverSwitch2_Context *ctx, Uint8 *data, int size)
{
    Sint16 axis;
    (void)size;
    if (data[5] != ctx->last_state[5]) {
        SDL_SendJoystickButton(timestamp, joystick, SDL_GAMEPAD_BUTTON_WEST, ((data[5] & 0x01) != 0));
        SDL_SendJoystickButton(timestamp, joystick, SDL_GAMEPAD_BUTTON_NORTH, ((data[5] & 0x02) != 0));
        SDL_SendJoystickButton(timestamp, joystick, SDL_GAMEPAD_BUTTON_SOUTH, ((data[5] & 0x04) != 0));
        SDL_SendJoystickButton(timestamp, joystick, SDL_GAMEPAD_BUTTON_EAST, ((data[5] & 0x08) != 0));
        SDL_SendJoystickButton(timestamp, joystick, SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER, ((data[5] & 0x40) != 0));
    }
    if (data[6] != ctx->last_state[6]) {
        SDL_SendJoystickButton(timestamp, joystick, SDL_GAMEPAD_BUTTON_BACK, ((data[6] & 0x01) != 0));
        SDL_SendJoystickButton(timestamp, joystick, SDL_GAMEPAD_BUTTON_START, ((data[6] & 0x02) != 0));
        SDL_SendJoystickButton(timestamp, joystick, SDL_GAMEPAD_BUTTON_RIGHT_STICK, ((data[6] & 0x04) != 0));
        SDL_SendJoystickButton(timestamp, joystick, SDL_GAMEPAD_BUTTON_LEFT_STICK, ((data[6] & 0x08) != 0));
        SDL_SendJoystickButton(timestamp, joystick, SDL_GAMEPAD_BUTTON_GUIDE, ((data[6] & 0x10) != 0));
        SDL_SendJoystickButton(timestamp, joystick, SDL_GAMEPAD_BUTTON_SWITCH2_PRO_SHARE, ((data[6] & 0x20) != 0));
        SDL_SendJoystickButton(timestamp, joystick, SDL_GAMEPAD_BUTTON_SWITCH2_PRO_C, ((data[6] & 0x40) != 0));
    }
    if (data[7] != ctx->last_state[7]) {
        Uint8 hat = 0;
        if (data[7] & 0x01) {
            hat |= SDL_HAT_DOWN;
        }
        if (data[7] & 0x02) {
            hat |= SDL_HAT_UP;
        }
        if (data[7] & 0x04) {
            hat |= SDL_HAT_RIGHT;
        }
        if (data[7] & 0x08) {
            hat |= SDL_HAT_LEFT;
        }
        SDL_SendJoystickHat(timestamp, joystick, 0, hat);
        SDL_SendJoystickButton(timestamp, joystick, SDL_GAMEPAD_BUTTON_LEFT_SHOULDER, ((data[7] & 0x40) != 0));
    }
    if (data[8] != ctx->last_state[8]) {
        SDL_SendJoystickButton(timestamp, joystick, SDL_GAMEPAD_BUTTON_SWITCH2_PRO_RIGHT_PADDLE, ((data[8] & 0x01) != 0));
        SDL_SendJoystickButton(timestamp, joystick, SDL_GAMEPAD_BUTTON_SWITCH2_PRO_LEFT_PADDLE, ((data[8] & 0x02) != 0));
    }
    axis = (data[5] & 0x80) ? 32767 : -32768;
    SDL_SendJoystickAxis(timestamp, joystick, SDL_GAMEPAD_AXIS_RIGHT_TRIGGER, axis);
    axis = (data[7] & 0x80) ? 32767 : -32768;
    SDL_SendJoystickAxis(timestamp, joystick, SDL_GAMEPAD_AXIS_LEFT_TRIGGER, axis);
    MapJoystickAxis(timestamp, joystick, SDL_GAMEPAD_AXIS_LEFTX, &ctx->left_stick.x, (float) (data[11] | ((data[12] & 0x0F) << 8)), false);
    MapJoystickAxis(timestamp, joystick, SDL_GAMEPAD_AXIS_LEFTY, &ctx->left_stick.y, (float) ((data[12] >> 4) | (data[13] << 4)), true);
    MapJoystickAxis(timestamp, joystick, SDL_GAMEPAD_AXIS_RIGHTX, &ctx->right_stick.x, (float) (data[14] | ((data[15] & 0x0F) << 8)), false);
    MapJoystickAxis(timestamp, joystick, SDL_GAMEPAD_AXIS_RIGHTY, &ctx->right_stick.y, (float)((data[15] >> 4) | (data[16] << 4)), true);
}
/* (HIDAPI_DriverSwitch2_HandleStatePacket's sensor part: the clock, then the values; 1 when it would send them) */
static int SensorPart(SDL_DriverSwitch2_Context *ctx, Uint8 *data, float accel_data[3], float gyro_data[3])
{
    Uint64 sensor_timestamp = (Uint32) (data[0x2b] | (data[0x2c] << 8U) | (data[0x2d] << 16U) | (data[0x2e] << 24U));
    if (sensor_timestamp && !ctx->sensors_ready) {
        ctx->sample_count++;
        if (ctx->sample_count >= 5 && !ctx->first_sensor_timestamp) {
            ctx->first_sensor_timestamp = sensor_timestamp;
            ctx->sample_count = 0;
        } else if (ctx->sample_count == 100) {
            Uint64 coeff = 1000 * (sensor_timestamp - ctx->first_sensor_timestamp) / (ctx->sample_count * 4);
            if ((coeff + 100000) / 200000 == 5) {
                ctx->sensor_ts_coeff = 10000;
                ctx->gyro_coeff = 34.8f;
                ctx->sensors_ready = true;
            } else if (coeff != 0) {
                ctx->sensor_ts_coeff = 10000000000 / coeff;
                ctx->gyro_coeff = 40.0f;
                ctx->sensors_ready = true;
            } else {
                ctx->first_sensor_timestamp = 0;
                ctx->sample_count = 0;
            }
        }
    }
    if (sensor_timestamp && ctx->sensors_ready) {
        const float g = 9.80665f;
        const float accel_scale = g * 8.f / INT16_MAX;
        accel_data[0] = (Sint16)(data[0x31] | (data[0x32] << 8)) * accel_scale;
        accel_data[1] = (Sint16)(data[0x35] | (data[0x36] << 8)) * accel_scale;
        accel_data[2] = (Sint16)(data[0x33] | (data[0x34] << 8)) * -accel_scale;
        gyro_data[0] = (Sint16)(data[0x37] | (data[0x38] << 8)) * ctx->gyro_coeff / INT16_MAX - ctx->gyro_bias_x;
        gyro_data[1] = (Sint16)(data[0x3b] | (data[0x3c] << 8)) * ctx->gyro_coeff / INT16_MAX - ctx->gyro_bias_z;
        gyro_data[2] = (Sint16)(data[0x39] | (data[0x3a] << 8)) * -ctx->gyro_coeff / INT16_MAX + ctx->gyro_bias_y;
        return 1;
    }
    return 0;
}
"""

SDL_ENCODE = r"""
static void EncodeHDRumble(Uint16 high_freq, Uint16 high_amp, Uint16 low_freq, Uint16 low_amp, Uint8 rumble_data[5])
{
    rumble_data[0] = (Uint8)(high_freq & 0xFF);
    rumble_data[1] = (Uint8)(((high_amp >> 4) & 0xfc) | ((high_freq >> 8) & 0x03));
    rumble_data[2] = (Uint8)((high_amp >> 12) | (low_freq << 4));
    rumble_data[3] = (Uint8)((low_amp & 0xc0) | ((low_freq >> 4) & 0x3f));
    rumble_data[4] = (Uint8)(low_amp >> 8);
}
"""
SDL_COPY += SDL_ENCODE

# ---- copies from Fritchii PR #6 (101Leafy, GPL-3.0): its SDL patch's Pro Controller report and its frequency code ----
FRITCHII_COPY = r"""
static void EncodeHDRumbleMotor(const Uint16 *values, Uint8 rumble_data[16])
{
    for (int i = 0; i < 3; ++i) {
        EncodeHDRumble(values[0], values[1], values[2], values[3], &rumble_data[1 + i * 5]);
    }
}
/* (UpdateRumble's HD branch, USB_PRODUCT_NINTENDO_SWITCH2_PRO) */
static void FritchiiProReport(Uint32 rumble_seq, const Uint16 hd[8], unsigned char rumble_data[64])
{
    const Uint16 *left = &hd[0];
    const Uint16 *right = &hd[4];
    memset(rumble_data, 0, 64);
    rumble_data[0x01] = 0x50 | (rumble_seq & 0xf);
    rumble_data[0] = 0x2;
    EncodeHDRumbleMotor(left, &rumble_data[0x01]);
    rumble_data[0x11] = rumble_data[0x01];
    EncodeHDRumbleMotor(right, &rumble_data[0x11]);
}
/* (sdl_driver.cpp's Switch2FrequencyCode, in C) */
static Uint16 Switch2FrequencyCode(float hz)
{
    const float code = 96.0f * log2f((hz > 10.0f ? hz : 10.0f) / 10.0f);
    return (Uint16)(code + 0.5f < 1023.0f ? code + 0.5f : 1023.0f);
}
"""

PARSE = COMMON + "#include <stdbool.h>\n" + SDL_COPY + r"""
int main(void) {
    /* the ids: only the Switch 2 Pro Controller */
    CHECK(sw2_is_pro(0x057E, 0x2069));
    static const unsigned others[] = {0x2009, 0x2006, 0x2007, 0x200E, 0x2017, 0x2019, 0x201E, 0x2066, 0x2067, 0x2068, 0x2073, 0x0337};
    for (unsigned i = 0; i < sizeof others / sizeof others[0]; i++) CHECK(!sw2_is_pro(0x057E, others[i]));
    CHECK(!sw2_is_pro(0x045E, 0x2069) && !sw2_is_pro(0x28DE, 0x2069) && !sw2_is_pro(0, 0));

    /* the input report against SDL's, on random bytes: buttons, hat, triggers, sticks raw and calibrated, sensors */
    static const struct { int sdl, sw2; } buttons[] = {
        {SDL_GAMEPAD_BUTTON_SOUTH, SW2_SOUTH}, {SDL_GAMEPAD_BUTTON_EAST, SW2_EAST}, {SDL_GAMEPAD_BUTTON_WEST, SW2_WEST},
        {SDL_GAMEPAD_BUTTON_NORTH, SW2_NORTH}, {SDL_GAMEPAD_BUTTON_BACK, SW2_MINUS}, {SDL_GAMEPAD_BUTTON_GUIDE, SW2_HOME},
        {SDL_GAMEPAD_BUTTON_START, SW2_PLUS}, {SDL_GAMEPAD_BUTTON_LEFT_STICK, SW2_LS},
        {SDL_GAMEPAD_BUTTON_RIGHT_STICK, SW2_RS}, {SDL_GAMEPAD_BUTTON_LEFT_SHOULDER, SW2_L},
        {SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER, SW2_R}, {SDL_GAMEPAD_BUTTON_SWITCH2_PRO_SHARE, SW2_CAPTURE},
        {SDL_GAMEPAD_BUTTON_SWITCH2_PRO_C, SW2_C}, {SDL_GAMEPAD_BUTTON_SWITCH2_PRO_RIGHT_PADDLE, SW2_GR},
        {SDL_GAMEPAD_BUTTON_SWITCH2_PRO_LEFT_PADDLE, SW2_GL}};
    /* (the positions host/pad_sdl.c reads are SDL's gamepad buttons: the same numbers) */
    CHECK(SW2_SOUTH == 0 && SW2_EAST == 1 && SW2_WEST == 2 && SW2_NORTH == 3 && SW2_MINUS == 4 && SW2_HOME == 5 &&
          SW2_PLUS == 6 && SW2_LS == 7 && SW2_RS == 8 && SW2_L == 9 && SW2_R == 10 && SW2_UP == 11 && SW2_DOWN == 12 &&
          SW2_LEFT == 13 && SW2_RIGHT == 14);
    for (int round = 0; round < 20000; round++) {
        uint8_t r[64];
        for (int i = 0; i < 64; i++) r[i] = (uint8_t)rnd();
        SDL_DriverSwitch2_Context ctx;
        memset(&ctx, 0, sizeof ctx);
        Sw2Calibration cal;
        memset(&cal, 0, sizeof cal);
        if (round % 3) {   /* (a third with no calibration: the raw range) */
            uint8_t c[2][9];
            for (int s = 0; s < 2; s++)
                for (int i = 0; i < 9; i++) c[s][i] = (uint8_t)rnd();
            if (round % 7 == 0) c[0][0] = c[0][1] = 0;   /* (no neutral: raw) */
            ParseStickCalibration(&ctx.left_stick, c[0]), ParseStickCalibration(&ctx.right_stick, c[1]);
            sw2_stick_cal_parse(c[0], &cal.stick[0]), sw2_stick_cal_parse(c[1], &cal.stick[1]);
            CHECK(!memcmp(&ctx.left_stick, &cal.stick[0], sizeof cal.stick[0]));
            CHECK(!memcmp(&ctx.right_stick, &cal.stick[1], sizeof cal.stick[1]));
        }
        for (int i = 0; i < 64; i++) ctx.last_state[i] = (uint8_t)~r[i];   /* (every byte a change) */
        HandleSwitchProState(0, NULL, &ctx, r, 64);
        Sw2Input in;
        CHECK(sw2_parse(r, 64, &cal, &in));
        for (unsigned i = 0; i < sizeof buttons / sizeof buttons[0]; i++)
            CHECK(sdl_button[buttons[i].sdl] == (int)(in.buttons >> buttons[i].sw2 & 1));
        CHECK(!!(sdl_hat & SDL_HAT_UP) == !!(in.buttons >> SW2_UP & 1));
        CHECK(!!(sdl_hat & SDL_HAT_DOWN) == !!(in.buttons >> SW2_DOWN & 1));
        CHECK(!!(sdl_hat & SDL_HAT_LEFT) == !!(in.buttons >> SW2_LEFT & 1));
        CHECK(!!(sdl_hat & SDL_HAT_RIGHT) == !!(in.buttons >> SW2_RIGHT & 1));
        CHECK((sdl_axis[SDL_GAMEPAD_AXIS_LEFT_TRIGGER] == 32767) == !!(in.buttons >> SW2_ZL & 1));
        CHECK((sdl_axis[SDL_GAMEPAD_AXIS_RIGHT_TRIGGER] == 32767) == !!(in.buttons >> SW2_ZR & 1));
        for (int a = 0; a < 4; a++) CHECK(sdl_axis[a] == in.axis[a]);
        CHECK(!(in.buttons >> SW2_BTN_N));
    }
    /* a report shorter than 64 bytes is no report (SDL: "We don't know how to handle this report") */
    {
        uint8_t r[64] = {0};
        Sw2Input in;
        CHECK(!sw2_parse(r, 63, NULL, &in) && sw2_parse(r, 64, NULL, &in));
    }
    /* the sensors: the clock settles as SDL's does (microseconds: 34.8 rad/s; other clocks: 40), then the values */
    static const uint32_t steps[] = {4000, 4100, 3700, 4, 1, 250, 0};
    for (unsigned s = 0; s < sizeof steps / sizeof steps[0]; s++) {
        SDL_DriverSwitch2_Context ctx;
        memset(&ctx, 0, sizeof ctx);
        ctx.gyro_bias_x = 0.01f, ctx.gyro_bias_y = -0.02f, ctx.gyro_bias_z = 0.005f;
        const float bias[3] = {0.01f, -0.02f, 0.005f};
        Sw2ImuClock clock;
        memset(&clock, 0, sizeof clock);
        uint32_t ts = 77;
        for (int k = 0; k < 400; k++) {
            uint8_t r[64];
            for (int i = 0; i < 64; i++) r[i] = (uint8_t)rnd();
            ts += steps[s];
            r[0x2b] = (uint8_t)ts, r[0x2c] = (uint8_t)(ts >> 8), r[0x2d] = (uint8_t)(ts >> 16), r[0x2e] = (uint8_t)(ts >> 24);
            float sa[3], sg[3], a[3], g[3];
            const int sdl_sends = SensorPart(&ctx, r, sa, sg);
            Sw2Input in;
            sw2_parse(r, 64, NULL, &in);
            sw2_imu_clock_feed(&clock, in.imu_ts);
            CHECK(clock.ready == ctx.sensors_ready && (!clock.ready || clock.gyro_coeff == ctx.gyro_coeff));
            CHECK(sdl_sends == (clock.ready && in.imu_ts != 0));
            if (!sdl_sends) continue;
            sw2_imu(&in, clock.gyro_coeff, bias, a, g);
            for (int i = 0; i < 3; i++) CHECK(fabsf(a[i] - sa[i]) <= 1e-5f && fabsf(g[i] - sg[i]) <= 1e-5f);
        }
        if (steps[s] >= 3700) CHECK(clock.ready && clock.gyro_coeff == 34.8f);
        else if (steps[s]) CHECK(clock.ready && clock.gyro_coeff == 40.0f);
        else CHECK(!clock.ready);   /* (a clock that does not move: never ready, as SDL) */
    }
    /* still: a pad lying flat reads 1 G on SDL's y */
    {
        uint8_t r[64] = {0};
        const int16_t one_g = 4096;   /* (8 G full scale) */
        r[0x35] = (uint8_t)one_g, r[0x36] = (uint8_t)(one_g >> 8);
        Sw2Input in;
        sw2_parse(r, 64, NULL, &in);
        float a[3], g[3];
        const float none[3] = {0, 0, 0};
        sw2_imu(&in, 34.8f, none, a, g);
        CHECK(fabsf(a[1] - 9.80665f) < 0.01f && a[0] == 0 && a[2] == 0);
    }
    puts("ok");
    return 0;
}
"""

RUMBLE = COMMON + SDL_ENCODE + FRITCHII_COPY + r"""
int main(void) {
    /* the bit packing: SDL's EncodeHDRumble with the amplitudes as 16-bit values whose top 10 bits are the field */
    for (int i = 0; i < 20000; i++) {
        const int hf = (int)(rnd() & 0x3FF), ha = (int)(rnd() & 0x3FF), lf = (int)(rnd() & 0x3FF), la = (int)(rnd() & 0x3FF);
        uint8_t a[5], b[5];
        sw2_sample(hf, ha, lf, la, a);
        EncodeHDRumble((Uint16)hf, (Uint16)(ha << 6), (Uint16)lf, (Uint16)(la << 6), b);
        CHECK(!memcmp(a, b, 5));
        CHECK(sw2_silent(a) == (!ha && !la));
    }
    for (int bit = 0; bit < 40; bit++) {   /* (each field's every bit on its own) */
        const int f = bit / 10, v = 1 << (bit % 10);
        uint8_t a[5], b[5];
        sw2_sample(f == 0 ? v : 0, f == 1 ? v : 0, f == 2 ? v : 0, f == 3 ? v : 0, a);
        EncodeHDRumble((Uint16)(f == 0 ? v : 0), (Uint16)(f == 1 ? v << 6 : 0), (Uint16)(f == 2 ? v : 0), (Uint16)(f == 3 ? v << 6 : 0), b);
        CHECK(!memcmp(a, b, 5));
        uint64_t x = 0;
        for (int k = 0; k < 5; k++) x |= (uint64_t)a[k] << 8 * k;
        CHECK(x == 1ull << bit);
    }
    /* the frequency scale: 10 Hz x 2^(code / 96), every code back from its own frequency; SDL's fixed ones */
    for (int c = 0; c <= 1023; c++) CHECK(sw2_freq_code((float)(10.0 * pow(2.0, c / 96.0)), -1) == c);
    CHECK(sw2_freq_code(168.0f, -1) == SW2_FREQ_HIGH_DEFAULT && sw2_freq_code(72.3f, -1) == SW2_FREQ_LOW_DEFAULT);
    CHECK(sw2_freq_code(0.0f, 7) == 7 && sw2_freq_code(NAN, 7) == 7 && sw2_freq_code(-5.0f, 7) == 7);
    CHECK(sw2_freq_code(5.0f, -1) == 0 && sw2_freq_code(1e6f, -1) == 1023);
    /* as Fritchii's measured scale codes it (the game's frequencies: 40 to 1253 Hz, and the measured range) */
    static const float hz[] = {20, 40.875885f, 55, 72, 100, 140.5f, 160, 168.3f, 200, 320, 357, 626.28f, 640, 1000, 1252.57f};
    for (unsigned i = 0; i < sizeof hz / sizeof hz[0]; i++) CHECK(sw2_freq_code(hz[i], -1) == Switch2FrequencyCode(hz[i]));
    for (float f = 10.0f; f < 15000.0f; f *= 1.0071f) {
        const int d = sw2_freq_code(f, -1) - Switch2FrequencyCode(f);
        CHECK(d >= -1 && d <= 1);   /* (float rounding at the half-codes only) */
    }
    /* amplitudes: linear, capped at SDL's strongest */
    CHECK(sw2_amp_field(0) == 0 && sw2_amp_field(-1) == 0 && sw2_amp_field(NAN) == 0);
    CHECK(sw2_amp_field(1.0f) == SW2_AMP_MAX && sw2_amp_field(7.0f) == SW2_AMP_MAX && SW2_AMP_MAX == (29000 >> 6));
    CHECK(sw2_amp_field(0.5f) == 227 && sw2_amp_field(0.001f) == 0 && sw2_amp_field(0.0012f) == 1);
    /* a side from the game's value: silence, the frequencies kept, the strength scaling as hd_rumble_encode's */
    {
        uint8_t s[5], q[5];
        const float quiet[4] = {0, 160, 0, 320};
        sw2_side(quiet, 100, s), sw2_silence(q);
        CHECK(!memcmp(s, q, 5) && sw2_silent(s));
        const float v[4] = {0.5f, 72.3f, 0.25f, 168.3f};   /* {amp_low, freq_low, amp_high, freq_high} */
        uint8_t e[5];
        sw2_side(v, 100, s);
        sw2_sample(SW2_FREQ_HIGH_DEFAULT, 113, SW2_FREQ_LOW_DEFAULT, 227, e);
        CHECK(!memcmp(s, e, 5));
        sw2_side(v, 0, s);   /* (Rumble strength Off) */
        CHECK(sw2_silent(s));
        sw2_side(v, 300, s);   /* (over 100: both by the same factor, the stronger stopping at 1) */
        sw2_sample(SW2_FREQ_HIGH_DEFAULT, 227, SW2_FREQ_LOW_DEFAULT, 453, e);
        CHECK(!memcmp(s, e, 5));
        const float nofreq[4] = {0.5f, 0.0f, 0.5f, NAN};   /* (no frequency given: SDL's) */
        sw2_side(nofreq, 100, s);
        sw2_sample(SW2_FREQ_HIGH_DEFAULT, 227, SW2_FREQ_LOW_DEFAULT, 227, e);
        CHECK(!memcmp(s, e, 5));
    }
    /* HOS_HD_RUMBLE=0: two motors as SDL's own rumble on this controller (RUMBLE_MAX, its fixed frequencies) */
    for (int i = 0; i < 2000; i++) {
        const uint16_t lo = (uint16_t)rnd(), hi = (uint16_t)rnd();
        uint8_t a[5], b[5];
        sw2_side_motors(lo, hi, a);
        const Uint16 low_amp = (Uint16)((int)lo * 29000 / 65535), high_amp = (Uint16)((int)hi * 29000 / 65535);
        EncodeHDRumble(0x187, high_amp, 0x112, low_amp, b);
        CHECK(!memcmp(a, b, 5));
    }
    /* the report: Fritchii's, from the same values */
    for (int i = 0; i < 2000; i++) {
        Uint16 hd[8];
        uint8_t side[2][5], mine[64], theirs[64];
        for (int s = 0; s < 2; s++) {
            hd[4 * s + 0] = (Uint16)(rnd() & 0x3FF), hd[4 * s + 1] = (Uint16)((rnd() & 0x3FF) << 6);
            hd[4 * s + 2] = (Uint16)(rnd() & 0x3FF), hd[4 * s + 3] = (Uint16)((rnd() & 0x3FF) << 6);
            sw2_sample(hd[4 * s], hd[4 * s + 1] >> 6, hd[4 * s + 2], hd[4 * s + 3] >> 6, side[s]);
        }
        const uint32_t seq = rnd();
        sw2_rumble_report(seq, side[0], side[1], mine);
        FritchiiProReport(seq, hd, theirs);
        CHECK(!memcmp(mine, theirs, 64) && mine[0] == 0x02);
    }
    /* the cadence: a change at once, a rumble every 12 ms, silence once */
    {
        Sw2Rumble r;
        sw2_rumble_init(&r);
        uint8_t q[5], on[5], out[64];
        sw2_silence(q), sw2_sample(0x187, 200, 0x112, 0, on);
        CHECK(!sw2_rumble_due(&r, 0));   /* (silence from the start: nothing to send) */
        sw2_rumble_set(&r, on, q);
        CHECK(sw2_rumble_due(&r, 1000));
        sw2_rumble_next(&r, 1000, out);
        CHECK(out[1] == 0x50 && !memcmp(out + 2, on, 5) && !memcmp(out + 0x12, q, 5));
        CHECK(!sw2_rumble_due(&r, 1000 + SW2_RUMBLE_INTERVAL_NS - 1) && sw2_rumble_due(&r, 1000 + SW2_RUMBLE_INTERVAL_NS));
        sw2_rumble_next(&r, 1000 + SW2_RUMBLE_INTERVAL_NS, out);
        CHECK(out[1] == 0x51 && out[0x11] == 0x51);
        sw2_rumble_set(&r, q, q);   /* (stopped: once, when the interval allows) */
        const int64_t t = 1000 + 2 * SW2_RUMBLE_INTERVAL_NS;
        CHECK(sw2_rumble_due(&r, t));
        sw2_rumble_next(&r, t, out);
        CHECK(sw2_silent(out + 2) && sw2_silent(out + 0x12) && !sw2_rumble_due(&r, t + 1000000000LL));
        for (int k = 0; k < 20; k++) sw2_rumble_next(&r, t, out);
        CHECK((out[1] & 0xF0) == 0x50);   /* (the sequence number wraps in the low 4 bits) */
    }
    /* GL and GR: nothing unless named */
    CHECK(sw2_extra_target(NULL) == -1 && sw2_extra_target("") == -1 && sw2_extra_target("capture") == -1);
    CHECK(sw2_extra_target("south") == SW2_SOUTH && sw2_extra_target("right") == SW2_RIGHT);
    CHECK(sw2_extra_target("zl") == SW2_ZL && sw2_extra_target("zr") == SW2_ZR && sw2_extra_target("ZL") == -1);
    puts("ok");
    return 0;
}
"""

SETUP = COMMON + "#include <stdbool.h>\n" + SDL_COPY.split("static void MapJoystickAxis")[0] + r"""
/* a fake controller on the bulk pipes: records what is sent, answers flash reads from its own flash */
static uint8_t flash_at[8][0x40];
static uint32_t flash_addr[8];
static int flash_n, sent_n, fail_from = 1 << 30, reply_len, reply_at;
static uint8_t sent[64][64];
static int sent_len[64];
static uint8_t reply[0x50];
static int fake_out(void *ctx, const uint8_t *d, int n) {
    (void)ctx;
    if (sent_n >= fail_from) return -1;
    memcpy(sent[sent_n], d, n > 64 ? 64 : n), sent_len[sent_n++] = n;
    memset(reply, 0, sizeof reply);
    reply_len = 0x40, reply_at = 0;
    if (d[0] == 0x02 && d[1] == 0x91) {   /* (a flash read: 0x50 bytes, the data at 0x10) */
        const uint32_t a = d[12] | d[13] << 8 | d[14] << 16 | (uint32_t)d[15] << 24;
        for (int i = 0; i < flash_n; i++)
            if (flash_addr[i] == a) memcpy(reply + 0x10, flash_at[i], 0x40);
        reply_len = 0x50;
    }
    return n;
}
static int fake_in(void *ctx, uint8_t *d, int n, int t) {
    (void)ctx, (void)t;
    const int left = reply_len - reply_at, give = n < left ? n : left;
    if (give <= 0) return 0;
    memcpy(d, reply + reply_at, give);
    reply_at += give;
    return give;
}
static void set_flash(uint32_t addr, const uint8_t *data, int off, int n) {
    flash_addr[flash_n] = addr;
    memset(flash_at[flash_n], 0, 0x40);
    memcpy(flash_at[flash_n] + off, data, n);
    flash_n++;
}
int main(void) {
    if (sdl_hat || sdl_button[0] || sdl_axis[0]) return 2;   /* (SDL's stand-ins, unused here) */
    const uint8_t serial[18] = {0, 0, 'H', 'S', 'W', '2', '0', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'A'};
    const float bias[3] = {0.0125f, -0.0031f, 0.0007f};
    uint8_t b[12];
    memcpy(b, bias, 12);
    const uint8_t lstick[9] = {0x00, 0x08, 0x80, 0x10, 0xC8, 0x5D, 0x20, 0xA6, 0x5E};
    const uint8_t rstick[9] = {0x10, 0x18, 0x7F, 0x00, 0xB7, 0x5A, 0x40, 0x60, 0x5B};
    const uint8_t user_l[11] = {0xb2, 0xa1, 0x22, 0x08, 0x81, 0x00, 0xA0, 0x5F, 0x00, 0x90, 0x60};
    set_flash(0x13000, serial, 0, 18);
    set_flash(0x13040, b, 4, 12);
    set_flash(0x13080, lstick, 0x28, 9);
    set_flash(0x130C0, rstick, 0x28, 9);
    set_flash(0x1FC040, user_l, 0, 11);   /* (the left stick recalibrated by the user; the right not) */
    Sw2Bulk bulk = {NULL, fake_out, fake_in};
    Sw2Calibration cal;
    CHECK(sw2_setup(&bulk, &cal, 0));
    /* what went out: SDL's flash reads in its order, its init sequence, then the lights (player 1) */
    static const uint32_t reads[] = {0x13000, 0x13040, 0x13080, 0x130C0, 0x1FC040, 0x1FC080};
    const int nr = (int)(sizeof reads / sizeof reads[0]);
    CHECK(sent_n == nr + SW2_INIT_N + 1);
    for (int i = 0; i < nr; i++) {
        uint8_t c[16];
        sw2_cmd_flash_read(reads[i], c);
        CHECK(sent_len[i] == 16 && !memcmp(sent[i], c, 16) && sent[i][0] == 0x02 && sent[i][5] == 0x08);
    }
    static const uint8_t sdl_init[][28] = {
        {0x7, 0x91, 0x0, 0x1, 0x0, 0x0, 0x0, 0x0},
        {0x0c, 0x91, 0x00, 0x02, 0x00, 0x04, 0x00, 0x00, 0x27, 0x00, 0x00, 0x00},
        {0x11, 0x91, 0x0, 0x1, 0x0, 0x0, 0x0, 0x0},
        {0x0a, 0x91, 0x00, 0x08, 0x00, 0x14, 0x00, 0x00, 0x01, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
         0xff, 0x35, 0x00, 0x46, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
        {0x0c, 0x91, 0x00, 0x04, 0x00, 0x04, 0x00, 0x00, 0x27, 0x00, 0x00, 0x00},
        {0x01, 0x91, 0x0, 0xc, 0x0, 0x0, 0x0, 0x0},
        {0x01, 0x91, 0x0, 0x1, 0x0, 0x0, 0x0, 0x0},
        {0x8, 0x91, 0x0, 0x2, 0x0, 0x4, 0x0, 0x0, 0x01, 0x0, 0x0, 0x0},
        {0x03, 0x91, 0x00, 0x0a, 0x00, 0x04, 0x00, 0x00, 0x05, 0x00, 0x00, 0x00},
        {0x03, 0x91, 0x00, 0x0d, 0x00, 0x08, 0x00, 0x00, 0x01, 0x00, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff}};
    CHECK(SW2_INIT_N == (int)(sizeof sdl_init / sizeof sdl_init[0]));
    for (int i = 0; i < SW2_INIT_N; i++) {
        const int len = sdl_init[i][5] + 8;   /* (SDL sends init_sequence[i][5] + 8 bytes) */
        CHECK(sent_len[nr + i] == len && !memcmp(sent[nr + i], sdl_init[i], len));
    }
    const uint8_t led[16] = {0x09, 0x91, 0x00, 0x07, 0x00, 0x08, 0x00, 0x00, 0x01};
    CHECK(sent_len[nr + SW2_INIT_N] == 16 && !memcmp(sent[nr + SW2_INIT_N], led, 16));
    uint8_t c[16];
    sw2_cmd_led(3, c);
    CHECK(c[8] == 0xf);
    sw2_cmd_led(-1, c);
    CHECK(c[8] == 0);
    /* what came back: the serial, the gyro bias, the sticks (the user's calibration over the factory's) */
    CHECK(!strcmp(cal.serial, "HSW200123456789A"));
    CHECK(cal.gyro_bias[0] == bias[0] && cal.gyro_bias[1] == bias[1] && cal.gyro_bias[2] == bias[2]);
    Switch2_StickCalibration l, r;
    ParseStickCalibration(&l, user_l + 2), ParseStickCalibration(&r, rstick);
    CHECK(!memcmp(&l, &cal.stick[0], sizeof l) && !memcmp(&r, &cal.stick[1], sizeof r));
    CHECK(cal.stick[0].x.neutral == 0x822);
    /* unset flash (0xff: NaN) is no bias */
    flash_n = 0, sent_n = 0;
    const uint8_t ff[12] = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff};
    set_flash(0x13040, ff, 4, 12);
    CHECK(sw2_setup(&bulk, &cal, 0) && cal.gyro_bias[0] == 0 && cal.gyro_bias[1] == 0 && cal.gyro_bias[2] == 0);
    CHECK(cal.stick[0].x.neutral == 0 && !cal.serial[0]);   /* (nothing there: the raw range) */
    /* a controller that stops taking commands during the sequence: not set up */
    flash_n = 0, sent_n = 0, fail_from = nr + 3;
    CHECK(!sw2_setup(&bulk, &cal, 0));
    puts("ok");
    return 0;
}
"""

DESCRIPTORS = COMMON + r"""
int main(void) {
    /* a configuration as usbfs gives it (after the 18-byte device descriptor): HID interface 0 with its HID descriptor,
       interrupt IN 0x81 and OUT 0x01; vendor interface 1 with bulk 0x02 / 0x82; an audio interface; alt setting 1 of
       interface 1 with other pipes, which are not taken */
    const uint8_t d[] = {
        9, 2, 0, 0, 3, 1, 0, 0xa0, 250,
        9, 4, 0, 0, 2, 3, 0, 0, 0,   9, 0x21, 0x11, 0x01, 0, 1, 0x22, 0x61, 0,
        7, 5, 0x81, 3, 64, 0, 4,   7, 5, 0x01, 3, 64, 0, 4,
        9, 4, 1, 0, 2, 0xff, 0, 0, 0,   7, 5, 0x02, 2, 64, 0, 0,   7, 5, 0x82, 2, 64, 0, 0,
        9, 4, 1, 1, 2, 0xff, 0, 0, 0,   7, 5, 0x03, 2, 64, 0, 0,   7, 5, 0x83, 2, 64, 0, 0,
        9, 4, 2, 0, 0, 1, 1, 0, 0,
        9, 2, 0, 0, 1, 2, 0, 0xa0, 250,   9, 4, 0, 0, 1, 3, 0, 0, 0,   7, 5, 0x84, 3, 64, 0, 4};
    Sw2Endpoints e;
    CHECK(sw2_parse_descriptors(d, sizeof d, &e));
    CHECK(e.hid_if == 0 && e.hid_in == 0x81 && e.hid_out == 0x01);
    CHECK(e.bulk_if == 1 && e.bulk_out == 0x02 && e.bulk_in == 0x82);
    /* no interrupt OUT: the reports go on the control pipe */
    uint8_t d2[sizeof d];
    memcpy(d2, d, sizeof d);
    d2[9 + 9 + 9 + 7 + 2] = 0x00, d2[9 + 9 + 9 + 7 + 3] = 0;   /* (OUT 0x01 made a control endpoint) */
    CHECK(sw2_parse_descriptors(d2, sizeof d2, &e) && e.hid_out == 0 && e.hid_in == 0x81);
    /* no vendor interface (another device; or truncated): not this controller */
    CHECK(!sw2_parse_descriptors(d, 9 + 9 + 9 + 7 + 7, &e));
    const uint8_t bad[] = {9, 2, 0, 0, 1, 1, 0, 0xa0, 250, 0, 4};   /* (a zero length: stops) */
    CHECK(!sw2_parse_descriptors(bad, sizeof bad, &e));
    puts("ok");
    return 0;
}
"""


def usbfs_block():
    src = PAD.read_text(encoding="utf-8")
    start = src.index("struct sw2_bulk {")
    end = src.index("#define SW2_DISCONNECT_CLAIM_EXCEPT_DRIVER", start)
    end = src.index("\n", end)
    return src[start:end]


IOCTLS = r"""
#include <stdint.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include <linux/usbdevice_fs.h>
""" + "%(block)s" + r"""
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL %%d %%s\n", __LINE__, #x); return 1; } } while (0)
int main(void) {
    CHECK(SW2_USBDEVFS_CONTROL == USBDEVFS_CONTROL && SW2_USBDEVFS_BULK == USBDEVFS_BULK);
    CHECK(SW2_USBDEVFS_CLAIMINTERFACE == USBDEVFS_CLAIMINTERFACE && SW2_USBDEVFS_RELEASEINTERFACE == USBDEVFS_RELEASEINTERFACE);
    CHECK(SW2_USBDEVFS_IOCTL == USBDEVFS_IOCTL && SW2_USBDEVFS_CONNECT == USBDEVFS_CONNECT);
    CHECK(SW2_USBDEVFS_DISCONNECT_CLAIM == USBDEVFS_DISCONNECT_CLAIM);
    CHECK(SW2_DISCONNECT_CLAIM_EXCEPT_DRIVER == USBDEVFS_DISCONNECT_CLAIM_EXCEPT_DRIVER);
    CHECK(sizeof(struct sw2_bulk) == sizeof(struct usbdevfs_bulktransfer));
    CHECK(sizeof(struct sw2_ctrl) == sizeof(struct usbdevfs_ctrltransfer));
    CHECK(sizeof(struct sw2_disclaim) == sizeof(struct usbdevfs_disconnect_claim));
    puts("ok");
    return 0;
}
"""


class Switch2ProTests(unittest.TestCase):
    def test_ids_and_input_report(self):
        build_and_run(self, PARSE)

    def test_hd_rumble(self):
        build_and_run(self, RUMBLE)

    def test_setup(self):
        build_and_run(self, SETUP)

    def test_descriptors(self):
        build_and_run(self, DESCRIPTORS)

    @unittest.skipUnless(sys.platform.startswith("linux"), "usbfs is Linux's")
    def test_usbfs_requests(self):
        if not Path("/usr/include/linux/usbdevice_fs.h").exists():
            self.skipTest("no linux/usbdevice_fs.h")
        build_and_run(self, IOCTLS % {"block": usbfs_block()})

    def test_only_this_controller_is_opened(self):
        src = PAD.read_text(encoding="utf-8")
        linux = src[src.index("#else   /* (linux"):]
        listing = linux[linux.index("static int dev_list"):linux.index("static int usb_out")]
        # (Linux: a device is a key only after its ids are checked; nothing is opened while looking)
        self.assertLess(listing.index("sw2_is_pro(vid, pid)"), listing.index("snprintf(keys[n++]"))
        self.assertNotIn("open(", listing.replace("opendir(", "").replace("fopen(", ""))
        # (Windows: only interfaces whose path names 057E:2069)
        self.assertIn('wide_has(u.h.DevicePath, "vid_057e&pid_2069")', src)
        self.assertIn('"vid_057e&pid_2069&mi_01"', src)
        # (SDL's view of the controller is left out by these ids alone: the Switch Pro Controller stays SDL's)
        skip = function(SDLWRAP, "static int sw2_skip")
        self.assertIn("vid == 0x057E && pid == 0x2069", skip)
        self.assertIn("hos_sw2_enabled()", skip)
        # (HOS_NO_SW2=1: nothing of it runs)
        self.assertIn('getenv("HOS_NO_SW2")', function(PAD, "int hos_sw2_enabled"))
        self.assertIn("if (!hos_sw2_enabled()) return 0;", function(PAD, "int hos_sw2_list"))
        # (another program's claim on the HID interface is never taken: hid-generic only)
        claim = linux[linux.index("static int dev_claim_hid"):linux.index("static int dev_read")]
        self.assertIn("dc.flags = SW2_DISCONNECT_CLAIM_EXCEPT_DRIVER", claim)
        self.assertIn('"usbfs"', claim)

    def test_wired_in(self):
        wrap = SDLWRAP.read_text(encoding="utf-8")
        for name in ("hos_sdl_pad_close", "hos_sdl_pad_connected", "hos_sdl_pad_button", "hos_sdl_pad_axis",
                     "hos_sdl_pad_name", "hos_sdl_pad_id", "hos_sdl_pad_rumble", "hos_sdl_pad_type",
                     "hos_sdl_pad_effect", "hos_sdl_pad_has_sensor", "hos_sdl_pad_sensor_enable", "hos_sdl_pad_sensor"):
            body = function(SDLWRAP, name)
            self.assertIn("hos_sw2_is(pad)", body, name)
            self.assertLess(body.index("hos_sw2_is(pad)"), body.index("CALL(") if "CALL(" in body else len(body), name)
        self.assertIn("if (what < 0) return hos_sw2_open(what);", function(SDLWRAP, "void *hos_sdl_pad_open"))
        lst = function(SDLWRAP, "int hos_sdl_pads_list")
        self.assertIn("return n + hos_sw2_list(ids + n, opens + n, max - n);", lst)
        self.assertEqual(lst.count("sw2_skip("), 2)   # (SDL3's list and SDL2's)
        self.assertIn("if (hos_sw2_is(pad)) return 0;", function(SDLWRAP, "int hos_sdl_pad_type"))   # (no Switch packets)
        self.assertIn("opens[count] = -1 - i", function(PAD, "int hos_sw2_list"))   # (never an SDL id or index)
        # (pad_sdl.c: the game's values to it, before the Switch HD rumble and the motors; HOS_HD_RUMBLE=0 the motors)
        poll = function(SDLPAD, "static void pads_poll")
        self.assertIn("hos_sw2_rumble_hd(gc, felt[0], felt[1], strength);", poll)
        self.assertLess(poll.index("hos_sw2_rumble_hd("), poll.index("if (hd_poll(i, side, now)) continue;"))
        self.assertLess(poll.index("hd_rumble_felt(hv[1], felt[1])"), poll.index("hos_sw2_rumble_hd("))
        self.assertIn("hos_sw2_is(gc) && sw2_hd_rumble()", poll)
        self.assertIn('getenv("HOS_HD_RUMBLE")', function(SDLPAD, "static int sw2_hd_rumble"))
        start = function(SDLPAD, "static int pads_start")
        self.assertIn('hos_sdl_hint("SDL_HIDAPI_IGNORE_DEVICES", ignore)', start)   # (SDL's HIDAPI: this one id only)
        self.assertIn('"%s%s0x057e/0x2069"', start)
        self.assertNotIn("SDL_JOYSTICK_HIDAPI_SWITCH2", start)   # (that would take the Joy-Con 2 and GameCube from SDL)
        self.assertLess(start.index("SDL_HIDAPI_IGNORE_DEVICES"), start.index("hos_sdl_init("))
        # (the felt amplitudes: the same curve as the Switch controllers' HD rumble)
        self.assertIn("hd_rumble_felt(hv[0], felt[0])", poll)


if __name__ == "__main__":
    unittest.main()
