"""Check the microphone's input streams (host/nn_audio_in.c) as the game drives them: one device listed, streams opened on
the game's format and started (state 2), silence at their rate with the microphone off, one microphone opened for both
streams and its samples given to each, the newest kept past a stream's capacity, a microphone that stops sending or does
not open (silence, tries again after 3 s, then twice as long each time, said once), a named one by its id (of two with one
name, the one chosen), the default standing in for an unplugged one until it is back under another id, purge, stop and
close; the Microphone volume (every sample format scaled and clipped, and the game's samples through a stream), the menu's
Test microphone (its states, its level at the volume, let go) and the pitch it finds (tones, a hum's harmonics, noise,
silence); a device of several channels (an audio interface's) opened with them all, one given to the game (Auto's of the
first two, the loopbacks left out, or the menu's); and the menu's row keeping its choice by name. SDL, the menu and the clock are stand-ins. No GPU or game files.
python -I -B tests/test_audio_in.py [--cc gcc] [--cxx g++]
"""
import argparse
import re
from pathlib import Path
import subprocess
import tempfile

# (env_on, the switches' rule, before the code cut out of the sources: gpu/vk/compat/hookshot_env.h)
ENV_ON_H = str(Path(__file__).resolve().parents[1] / "gpu" / "vk" / "compat" / "hookshot_env.h")

RUN_ALL_ARGS = ["--cc", "gcc", "--cxx", "g++"]

ROOT = Path(__file__).resolve().parents[1]

HOS_H = r'''
#pragma once
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef struct { uint64_t x[32]; uint64_t vreg[32][2]; } Ctx;
#define HLE(sym) void imp_##sym(Ctx *c)
#define ARG(n) (c->x[n])
#define RET(v) (c->x[0] = (uint64_t)(v))
#define GP(a) ((void *)(uintptr_t)(a))
#define G64(a) (*(uint64_t *)GP(a))
#define G32(a) (*(uint32_t *)GP(a))
#define HOS_WRITTEN(p, n) ((void)0)
static inline void *hos_guest_range(uint64_t a, uint64_t n) { (void)n; return a ? GP(a) : (void *)0; }   /* (the test's addresses are host ones) */
void hos_log(const char *fmt, ...);
int64_t hos_now_ns(void);
'''
WINDOWS_H = r'''
#pragma once
typedef int SRWLOCK;
#define SRWLOCK_INIT 0
static inline void AcquireSRWLockExclusive(SRWLOCK *l) { (void)l; }
static inline void ReleaseSRWLockExclusive(SRWLOCK *l) { (void)l; }
static inline void AcquireSRWLockShared(SRWLOCK *l) { (void)l; }
static inline void ReleaseSRWLockShared(SRWLOCK *l) { (void)l; }
'''
FIXTURE = r'''
#include <math.h>
#include <stdarg.h>
#include <stdlib.h>
#include "nn_audio_in.c"

/* the menu's Microphone volume (HOS_OPT_MIC_GAIN), in percent */
static int gain = 100, chan_opt = 0;   /* (and the Microphone channel, 0 Auto) */
int rx_option(int id, int otherwise) { return id == OPT_MIC_GAIN ? gain : id == OPT_MIC_CHANNEL ? chan_opt : otherwise; }
/* the device's own channels; with several, the samples on loud_ch alone (the others silent) */
static int dev_channels = 1, loud_ch = 0;
int hos_sdl_mic_channels(uint32_t id) { (void)id; return dev_channels; }

static int64_t clock_ns = 1000000000;
int64_t hos_now_ns(void) { return clock_ns; }
static int logged;
void hos_log(const char *fmt, ...) { (void)fmt; logged++; }
const char *hos_sdl_error(void) { return "no device"; }
/* SDL's microphones: "Test microphone", two "Twin" and a long name, as ids id_base.. ; the default (id 0) opens unless
   no_default */
static int listed = 1, no_default, opens, opened, closed, mic_bytes, next_sample, last_format, last_rate, last_channels;
static uint32_t id_base = 7, last_id = 99;
#define LONG_NAME "Microphone Array (Intel\xc2\xae Smart Sound Technology for Digital Microphones)"
int hos_sdl_mic_list(uint32_t *ids, char (*names)[128], int max) {
    static const char *const all[4] = {"Test microphone", "Twin", "Twin", LONG_NAME};
    int n = 0;
    for (; n < listed && n < max && n < 4; n++) ids[n] = id_base + (uint32_t)n, strcpy(names[n], all[n]);
    return n;
}
void *hos_sdl_mic_open(uint32_t id, int freq, int channels, uint16_t format) {
    opens++;
    if (id ? id < id_base || id >= id_base + (uint32_t)listed : no_default) return NULL;
    opened++, last_id = id, last_rate = freq, last_channels = channels, last_format = format;
    return &opened;
}
int hos_sdl_mic_available(void *mic) { return mic ? mic_bytes : 0; }
int hos_sdl_mic_read(void *mic, void *dst, int bytes) {
    (void)mic;
    if (bytes > mic_bytes) bytes = mic_bytes;
    for (int i = 0; i < bytes / 2; i++)
        ((int16_t *)dst)[i] = last_channels > 1 && i % last_channels != loud_ch ? 0 : (int16_t)(next_sample++);
    mic_bytes -= bytes;
    return bytes;
}
void hos_sdl_mic_clear(void *mic) { (void)mic; mic_bytes = 0; }
void hos_sdl_mic_close(void *mic) { (void)mic; closed++; }

/* an HLE function called with its arguments in x0.. as the lifted code makes the call: the result in x0 */
static Ctx c;
static uint64_t call(void (*fn)(Ctx *), int n, ...) {
    va_list ap;
    va_start(ap, n);
    memset(&c, 0, sizeof c);
    for (int i = 0; i < n; i++) c.x[i] = va_arg(ap, uint64_t);
    va_end(ap);
    fn(&c);
    return c.x[0];
}
#define NARGS(...) (int)(sizeof((uint64_t[]){__VA_ARGS__}) / sizeof(uint64_t))
#define CALL(fn, ...) call(fn, NARGS(__VA_ARGS__), __VA_ARGS__)
#define FAIL(n, ...) do { fprintf(stderr, __VA_ARGS__); fputc('\n', stderr); return n; } while (0)
#define U(p) ((uint64_t)(uintptr_t)(p))
#define OPEN(s, name) CALL(imp__ZN2nn5audio15OpenInputStreamEPNS0_15InputStreamTypeEPvmRKNS0_15AudioDeviceNameERKNS0_12StreamFormatEi, \
                           U(s), U(work), (uint64_t)sizeof work, U(name), U(format), (uint64_t)4800)
#define START(s) CALL(imp__ZN2nn5audio16StartInputStreamEPNS0_15InputStreamTypeE, U(s))
#define STATE(s) CALL(imp__ZN2nn5audio19GetInputStreamStateEPKNS0_15InputStreamTypeE, U(s))
#define FILLED(s) (int)CALL(imp__ZN2nn5audio30GetInputStreamFilledFrameCountEPKNS0_15InputStreamTypeE, U(s))
#define READ(s, buf, n) (int)CALL(imp__ZN2nn5audio15ReadInputStreamEPNS0_15InputStreamTypeEPvi, U(s), U(buf), (uint64_t)(n))
#define PURGE(s) CALL(imp__ZN2nn5audio16PurgeInputStreamEPNS0_15InputStreamTypeE, U(s))
#define MS(n) (clock_ns += (int64_t)(n) * 1000000)

int main(void) {
    int cases = 0;
    static uint8_t names[8][256], raw[256], work[0x4000];
    static uint64_t stream[0x360 / 8], other[0x360 / 8], never[0x360 / 8];
    static const uint32_t format[4] = {2, 1, 48000, 0};   /* {PcmInt16, 1 channel, 48000 Hz}: the game's */
    static int16_t buf[4800], buf2[4800];
    if (CALL(imp__ZN2nn5audio23ListVirtualInputDevicesEPNS0_15AudioDeviceNameEi, U(names), (uint64_t)8) != 1 ||
        strcmp((char *)names[0], "MainAudioIn"))
        FAIL(1, "the device list: one device");
    if (CALL(imp__ZN2nn5audio23ListVirtualInputDevicesEPNS0_15AudioDeviceNameEi, U(names), (uint64_t)0) != 0) FAIL(2, "a list of none");
    CALL(imp__ZN2nn5audio26GetTrueRawAudioInputDeviceEPNS0_15AudioDeviceNameE, U(raw));
    if (OPEN(stream, names[0]) != 0 || (stream[0] >> 32) != 0x4D494349u) FAIL(3, "the stream did not open");
    if (OPEN(other, raw) != 0 || stream[0] == other[0]) FAIL(4, "the raw stream did not open apart");
    if (STATE(stream) == 2 || FILLED(stream) != 0) FAIL(5, "an opened stream is not started, and has nothing");
    if (START(never) == 0 || STATE(never) == 2 || FILLED(never)) FAIL(6, "a stream never opened does not start");
    hos_mic_select(0, "", -1);   /* (the menu: Off) */
    if (START(stream) != 0 || STATE(stream) != 2) FAIL(7, "the started state is 2: the game's check");
    if (opens) FAIL(8, "the microphone opened while the menu has it off");
    cases += 8;

    /* off: silence at 48 kHz, at most the capacity */
    MS(10);
    if (FILLED(stream) != 480) FAIL(9, "10 ms of silence: %d frames, not 480", FILLED(stream));
    memset(buf, 0x55, sizeof buf);
    if (READ(stream, buf, 256) != 256 || buf[0] || buf[255] || FILLED(stream) != 224) FAIL(10, "silence read");
    MS(5000);
    if (FILLED(stream) != 4800) FAIL(11, "silence held to the capacity");
    START(other);
    MS(10);
    if (FILLED(other) != 480 || FILLED(stream) != 4800) FAIL(12, "the second stream: its own silence from its start");
    cases += 4;

    /* the default microphone: opened once for both streams, in their format, its samples given to each */
    PURGE(stream), PURGE(other);
    hos_mic_select(1, "", -1), mic_bytes = 1000;
    if (FILLED(stream) != 500 || FILLED(other) != 500 || opened != 1 || last_id != 0 || last_rate != 48000 ||
        last_channels != 1 || last_format != 0x8010)
        FAIL(13, "one microphone for both, 48 kHz mono S16: %d and %d frames, opened %d, id %u, %d Hz %d ch fmt %#x",
             FILLED(stream), FILLED(other), opened, last_id, last_rate, last_channels, last_format);
    if (READ(stream, buf, 256) != 256 || READ(other, buf2, 256) != 256 || buf[0] != 0 || buf[255] != 255 ||
        memcmp(buf, buf2, 512))
        FAIL(14, "both streams read the same samples");
    mic_bytes = 20000;   /* the game stopped reading: only the newest capacity's worth is kept */
    if (FILLED(stream) != 4800 || mic_bytes != 0) FAIL(15, "past the capacity: %d frames", FILLED(stream));
    if (READ(stream, buf, 10000) != 4800 || buf[0] != 5700 || buf[4799] != 10499) FAIL(16, "the newest kept: %d .. %d", buf[0], buf[4799]);
    cases += 4;

    /* it stops sending: 2 s of nothing, then silence; tried again after 3 s, then 6, 12: said once */
    MS(1000);
    if (FILLED(stream) != 0 || closed) FAIL(17, "a second of nothing is not yet a lost microphone");
    MS(1500);
    if (FILLED(stream) != 0 || closed != 1) FAIL(18, "2.5 s of nothing: closed (%d)", closed);
    MS(10);
    if (FILLED(stream) != 480) FAIL(19, "silence once it stopped sending: %d", FILLED(stream));
    no_default = 1;
    const int said = logged, tried = opens;
    MS(3000), (void)FILLED(stream);
    if (opens != tried + 1 || FILLED(stream) != 4800) FAIL(20, "a failed try after 3 s: still silence (%d)", opens - tried);
    MS(3000), (void)FILLED(stream);
    if (opens != tried + 1) FAIL(21, "the next wait is 6 s, not 3");
    MS(3000), (void)FILLED(stream);
    MS(11000), (void)FILLED(stream);
    if (opens != tried + 2) FAIL(22, "then 12 s: %d tries", opens - tried);
    MS(1000), (void)FILLED(stream);
    if (opens != tried + 3 || logged != said) FAIL(23, "then: tried again, and nothing more said (%d tries, %d lines)", opens - tried, logged - said);
    no_default = 0;
    MS(24000), (void)FILLED(stream);
    PURGE(stream), mic_bytes = 200;
    if (opened != 2 || FILLED(stream) != 100) FAIL(24, "the default back: %d opens, %d frames", opened, FILLED(stream));
    cases += 8;

    /* one that opens but never sends: closed and opened again, the waits growing, not every 5 s */
    const int quiet_from = opens;
    MS(2500), (void)FILLED(stream);   /* (it gave sound: the waits started over at 3 s) */
    MS(3000), (void)FILLED(stream);
    MS(2500), (void)FILLED(stream);
    MS(3000), (void)FILLED(stream);
    if (opens != quiet_from + 1) FAIL(25, "a quiet one: the second wait is 6 s (%d opens)", opens - quiet_from);
    MS(3000), (void)FILLED(stream);
    if (opens != quiet_from + 2) FAIL(26, "then opened again (%d)", opens - quiet_from);
    cases += 2;

    /* a named one, by the id SDL lists it under; of two with one name, the one chosen */
    hos_mic_count();
    if (strcmp(hos_mic_name(0), "Test microphone") || hos_mic_name(1)[0]) FAIL(27, "the menu's list");
    hos_mic_select(2, "Test microphone", 0);
    (void)FILLED(stream);
    if (last_id != 7) FAIL(28, "the named microphone: id %u", last_id);
    const int before = opens;
    hos_mic_select(2, "Test microphone", 0);
    (void)FILLED(stream);
    if (opens != before) FAIL(29, "the same choice again: not opened again");
    listed = 3, hos_mic_count();
    hos_mic_select(2, "Twin", 2);
    (void)FILLED(stream);
    if (last_id != 9) FAIL(30, "the second of two named alike: id %u", last_id);
    cases += 4;

    /* stalled (it stops sending): the default stands in at once, the chosen one tried again; plugged in again under another
       id, found in a list made at the retry */
    listed = 1, hos_mic_count(), hos_mic_select(2, "Test microphone", 0);
    (void)FILLED(stream);
    if (last_id != 7) FAIL(31, "the named one first (%u)", last_id);
    listed = 0, mic_bytes = 0;   /* (pulled out: the menu's list still has it, as 7) */
    MS(2500), (void)FILLED(stream);
    if (last_id != 0) FAIL(32, "the default stands in once it stops sending (id %u)", last_id);
    listed = 1, id_base = 20;   /* (plugged in again: another id; the menu's list still says 7) */
    MS(3000), (void)FILLED(stream);
    if (last_id != 20) FAIL(33, "back under its new id, found in a list made at the retry (%u)", last_id);
    hos_mic_count();
    const int reopened = opens;
    hos_mic_select(2, "Test microphone", 0);   /* (the menu, opened since: the same one, under its new id) */
    (void)FILLED(stream);
    if (opens != reopened) FAIL(41, "the menu's word of the id it has now: not opened again");
    cases += 4;

    /* pulled out and still sending zeros (SDL3 on Windows): no longer listed, so the default stands in within 5 s */
    listed = 0;
    for (int i = 0; i < 6; i++) mic_bytes = 9600, MS(1000), (void)FILLED(stream);
    if (last_id != 0) FAIL(42, "a pulled-out one sending zeros: the default stands in (%u)", last_id);
    listed = 1;
    MS(4000), (void)FILLED(stream);
    if (last_id != 20) FAIL(43, "and it is back on the next try (%u)", last_id);
    listed = 0, hos_mic_select(2, "Test microphone", -1);   /* (the menu sees it unplugged: looked for at once) */
    mic_bytes = 9600, (void)FILLED(stream);
    if (last_id != 0) FAIL(44, "the menu's word that it is unplugged: the default at once (%u)", last_id);
    cases += 3;

    /* a name past the ini's 60 bytes: the menu's kept name (cut) finds it, as does its whole name */
    listed = 4, id_base = 7, hos_mic_count();
    char kept[64] = {0};
    memcpy(kept, LONG_NAME, 60);   /* (the menu's kept name: its first 60 bytes) */
    hos_mic_select(2, kept, -1);
    MS(10), (void)FILLED(stream);
    if (last_id != 10) FAIL(45, "the long name by its first 60 bytes (%u)", last_id);
    hos_mic_select(2, LONG_NAME, 3);
    const int long_opens = opens;
    (void)FILLED(stream);
    if (opens != long_opens || last_id != 10) FAIL(46, "its whole name: the same one, not opened again");
    cases += 2;

    hos_mic_select(0, "", -1);
    const int closes = closed;
    (void)FILLED(stream);
    if (closed != closes + 1) FAIL(34, "off: closed");
    PURGE(stream);
    MS(10);
    if (FILLED(stream) != 480) FAIL(35, "off: silence from then");
    cases += 2;

    memset(buf, 0, sizeof buf);
    c.x[8] = U(buf);
    buf[4] = 77;
    imp__ZN2nn5audio24GetInputStreamStatisticsEPNS0_15InputStreamTypeEb(&c);
    if (buf[4]) FAIL(36, "the statistics: nothing lost");
    cases++;

    hos_mic_select(1, "", -1);
    (void)FILLED(stream);
    const int open_now = closed;
    CALL(imp__ZN2nn5audio15StopInputStreamEPNS0_15InputStreamTypeE, U(stream));
    if (STATE(stream) == 2 || FILLED(stream) != 0 || closed != open_now) FAIL(37, "one stopped: the other still has the microphone");
    CALL(imp__ZN2nn5audio15StopInputStreamEPNS0_15InputStreamTypeE, U(other));
    if (closed != open_now + 1) FAIL(38, "both stopped: the microphone closed");
    CALL(imp__ZN2nn5audio16CloseInputStreamEPNS0_15InputStreamTypeE, U(stream));
    if (stream[0] || READ(stream, buf, 16) != 0) FAIL(39, "closed: the handle gone");
    if (OPEN(stream, names[0]) != 0) FAIL(40, "a closed stream's slot is used again");
    cases += 4;

    /* a frame count from the game past 10 s is held to 10 s (its ring's byte offsets are ints: 0x20000001 stereo
       frames overflowed them) */
    CALL(imp__ZN2nn5audio16CloseInputStreamEPNS0_15InputStreamTypeE, U(stream));
    CALL(imp__ZN2nn5audio16CloseInputStreamEPNS0_15InputStreamTypeE, U(other));
    hos_mic_select(0, "", -1);
    static uint64_t big[0x360 / 8];
    static const uint32_t stereo[4] = {2, 2, 48000, 0};
    if (CALL(imp__ZN2nn5audio15OpenInputStreamEPNS0_15InputStreamTypeEPvmRKNS0_15AudioDeviceNameERKNS0_12StreamFormatEi,
             U(big), U(work), (uint64_t)sizeof work, U(names[0]), U(stereo), (uint64_t)0x20000001) != 0)
        FAIL(41, "a stream of a huge frame count did not open");
    START(big);
    for (int k = 0; k < 12; k++) MS(1000), (void)FILLED(big);   /* (silence comes a second at most a poll) */
    if (FILLED(big) != 480000) FAIL(42, "a huge frame count: %d frames held, not 10 s", FILLED(big));
    cases += 2;
    CALL(imp__ZN2nn5audio16CloseInputStreamEPNS0_15InputStreamTypeE, U(big));

    /* (hookshot) the Microphone volume: every format scaled and clipped at full scale; 100 leaves them as they come */
    {
        int16_t s16[4] = {1000, -1000, 20000, -20000}, same[1] = {1234};
        amplify((uint8_t *)s16, (int)sizeof s16, FMT_PCM16, 250);
        if (s16[0] != 2500 || s16[1] != -2500 || s16[2] != 32767 || s16[3] != -32768)
            FAIL(50, "16-bit at 250 %%: %d %d %d %d", s16[0], s16[1], s16[2], s16[3]);
        amplify((uint8_t *)same, (int)sizeof same, FMT_PCM16, 100);
        if (same[0] != 1234) FAIL(51, "100 %%: as it comes");
        amplify((uint8_t *)same, (int)sizeof same, FMT_PCM16, 0);
        if (same[0] != 0) FAIL(52, "0 %%: silence");
        int8_t s8[2] = {10, -100};
        amplify((uint8_t *)s8, (int)sizeof s8, FMT_PCM8, 200);
        int32_t s32[2] = {0x40000000, -0x40000000};
        amplify((uint8_t *)s32, (int)sizeof s32, FMT_PCM32, 300);
        float f32[2] = {0.25f, -0.75f};
        amplify((uint8_t *)f32, (int)sizeof f32, FMT_FLOAT, 200);
        if (s8[0] != 20 || s8[1] != -128 || s32[0] != INT32_MAX || s32[1] != INT32_MIN || f32[0] != 0.5f || f32[1] != -1.0f)
            FAIL(53, "8-bit, 32-bit and float scaled and clipped");
    }
    /* and the game's samples, through a stream: twice as loud at 200 % */
    hos_mic_select(1, "", -1);
    if (OPEN(stream, names[0]) != 0 || START(stream) != 0) FAIL(54, "a stream for the volume");
    (void)FILLED(stream);
    PURGE(stream);
    gain = 200, next_sample = 100, mic_bytes = 8;
    if (READ(stream, buf, 4) != 4 || buf[0] != 200 || buf[3] != 206) FAIL(55, "200 %%: %d .. %d", buf[0], buf[3]);
    gain = 100, next_sample = 100, mic_bytes = 8;
    if (READ(stream, buf, 4) != 4 || buf[0] != 100 || buf[3] != 103) FAIL(56, "100 %%: %d .. %d", buf[0], buf[3]);
    CALL(imp__ZN2nn5audio16CloseInputStreamEPNS0_15InputStreamTypeE, U(stream));
    cases += 7;

    /* (hookshot) the menu's Test microphone: the choice opened on its own in the game's format, its level at the volume,
       falling back once it is quiet; let go when the menu stops asking */
    {
        float level = -1, hz = -1;
        hos_mic_select(0, "", -1);
        if (hos_mic_test(1, &level, &hz, NULL, NULL) != 0 || level != 0 || hz != 0) FAIL(60, "the test with the microphone Off");
        listed = 1, id_base = 7, hos_mic_count();
        hos_mic_select(2, "Absent", -1);
        if (hos_mic_test(1, &level, &hz, NULL, NULL) != -2) FAIL(61, "the test of one not plugged in");
        const int test_opens = opened;
        hos_mic_select(2, "Test microphone", 0);
        gain = 200, next_sample = 1000, mic_bytes = 20;
        if (hos_mic_test(1, &level, &hz, NULL, NULL) != 1 || opened != test_opens + 1 || last_id != 7 || last_rate != 48000 ||
            last_channels != 1 || last_format != 0x8010)
            FAIL(62, "the test opened the chosen one, 48 kHz mono S16 (id %u)", last_id);
        if (level < 0.0615f || level > 0.0617f) FAIL(63, "its level at 200 %%: %f, not 2018 of 32767", level);
        if (hos_mic_test(1, &level, &hz, NULL, NULL) != 1 || opened != test_opens + 1) FAIL(64, "asked again: not opened again");
        MS(250);
        hos_mic_test(1, &level, &hz, NULL, NULL);
        if (level != 0) FAIL(65, "a quarter second quiet: the level fell back (%f)", level);
        no_default = 1, hos_mic_select(1, "", -1);
        if (hos_mic_test(1, &level, &hz, NULL, NULL) != -1) FAIL(66, "another choice that does not open: said so");
        no_default = 0, hos_mic_select(1, "", -1);
        if (hos_mic_test(1, &level, &hz, NULL, NULL) != 1 || last_id != 0) FAIL(67, "the default, chosen since: listened to");
        const int test_closes = closed;
        if (hos_mic_test(0, &level, &hz, NULL, NULL) != 0 || closed != test_closes + 1 || level != 0) FAIL(68, "let go: closed");
        gain = 100;
        /* a device of 4 channels, the microphone on the second: the test hears that one, and says so */
        dev_channels = 4, loud_ch = 1, hos_mic_select(1, "", -1);
        next_sample = 1000, mic_bytes = 4 * 2 * 64;
        int ch = 0, chs = 0;
        if (hos_mic_test(1, &level, &hz, &ch, &chs) != 1 || last_channels != 4 || ch != 2 || chs != 4 || level < 0.032f)
            FAIL(69, "the test of a 4-channel device: opened with %d, channel %d of %d, level %f", last_channels, ch, chs, level);
        hos_mic_test(0, &level, &hz, NULL, NULL);
        dev_channels = 1, loud_ch = 0;
    }
    cases += 10;

    /* (hookshot) an audio interface's 4 channels (a Scarlett Solo: the microphone on its second, loopbacks on 3 and 4):
       opened with them all, one given to the game's mono stream */
    {
        dev_channels = 4, loud_ch = 1, hos_mic_select(1, "", -1);
        if (OPEN(stream, names[0]) != 0 || START(stream) != 0) FAIL(80, "a stream for the 4 channels");
        (void)FILLED(stream);
        if (last_channels != 4 || last_format != 0x8010) FAIL(81, "opened with the device's 4 channels (%d)", last_channels);
        PURGE(stream);
        next_sample = 1000, mic_bytes = 4 * 2 * 64;   /* (64 frames) */
        if (FILLED(stream) != 64) FAIL(82, "64 frames of 4 channels: 64 mono frames, not %d", FILLED(stream));
        if (READ(stream, buf, 64) != 64 || buf[0] != 1000 || buf[63] != 1063) FAIL(83, "Auto: the second channel (%d)", buf[0]);
        loud_ch = 2, next_sample = 1000, mic_bytes = 4 * 2 * 256;   /* (a loopback loud: Auto leaves it out) */
        if (READ(stream, buf, 256) != 256 || buf[0] || buf[255]) FAIL(84, "Auto: a loopback (channel 3) left out (%d)", buf[255]);
        chan_opt = 3, next_sample = 1000, mic_bytes = 4 * 2 * 64;   /* (the menu's Channel 3) */
        if (READ(stream, buf, 64) != 64 || buf[0] != 1000) FAIL(85, "the menu's channel 3 (%d)", buf[0]);
        chan_opt = 9, loud_ch = 0, next_sample = 1000, mic_bytes = 4 * 2 * 256;   /* (past its channels: as Auto) */
        if (READ(stream, buf, 256) != 256 || buf[255] != 1255) FAIL(86, "a channel past the device's: Auto (%d)", buf[255]);
        CALL(imp__ZN2nn5audio16CloseInputStreamEPNS0_15InputStreamTypeE, U(stream));
        chan_opt = 0, dev_channels = 1, loud_ch = 0;
    }
    cases += 7;

    /* the pitch: a tone, a hum's harmonics, at 48 kHz; noise and silence have none */
    {
        static int16_t tone[TEST_WINDOW];
        static const double hzs[] = {110, 220, 293.66, 440, 587.33, 880, 1200};
        for (int k = 0; k < (int)(sizeof hzs / sizeof hzs[0]); k++) {
            for (int i = 0; i < TEST_WINDOW; i++) tone[i] = (int16_t)(8000 * sin(2 * M_PI * hzs[k] * i / 48000));
            const float got = hos_mic_pitch(tone, TEST_WINDOW, 48000);
            if (fabs(got - hzs[k]) > hzs[k] * 0.01) FAIL(70, "a %.2f Hz tone: %.2f Hz", hzs[k], got);
        }
        for (int i = 0; i < TEST_WINDOW; i++) {
            const double w = 2 * M_PI * 196 * i / 48000;
            tone[i] = (int16_t)(6000 * sin(w) + 4500 * sin(2 * w + 0.3) + 2500 * sin(3 * w + 1.1));
        }
        const float hum = hos_mic_pitch(tone, TEST_WINDOW, 48000);
        if (fabs(hum - 196) > 2) FAIL(71, "a hum with its harmonics: %.2f Hz, not 196 (an octave off?)", hum);
        unsigned seed = 1;
        for (int i = 0; i < TEST_WINDOW; i++) seed = seed * 1103515245u + 12345u, tone[i] = (int16_t)((int)(seed >> 16 & 0x7fff) - 16384);
        if (hos_mic_pitch(tone, TEST_WINDOW, 48000) != 0) FAIL(72, "noise: no note");
        memset(tone, 0, sizeof tone);
        if (hos_mic_pitch(tone, TEST_WINDOW, 48000) != 0) FAIL(73, "silence: no note");
    }
    cases += 4;
    printf("PASS: %d input stream cases (device list, open, start, silence, a shared microphone, capacity, a lost one and its"
           " retries, a quiet one, named ones, a stand-in, stop, close, the volume, the test, the pitch)\n", cases);
    return 0;
}
'''


MENU_FIXTURE = r"""#include <algorithm>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
struct Opts { int mic = 1; } opts;
std::vector<std::string> names;   /* the host's microphones */
struct Told { int mode; std::string name; int index; } told{-9, "", -9};
struct Host { int (*mic_count)(); const char* (*mic_name)(int); void (*mic_select)(int, const char*, int); };
int count() { return (int)names.size(); }
const char* name(int i) { return i >= 0 && i < (int)names.size() ? names[i].c_str() : ""; }
void select_mic(int mode, const char* n, int index) { told = {mode, n, index}; }
Host h{count, name, select_mic}, *host = &h;
struct Row { int* value; int hi; } rows[] = {{&opts.mic, 18}};
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); return 1; } } while (0)
@TEXT@
@REFRESH@
int main() {
    names = {"USB Mic", "USB Mic", "Webcam"};
    refresh_mics();
    CHECK(rows[0].hi == 4 && opts.mic == 1 && mic_want.empty() && told.mode == 1);
    opts.mic = 3, mic_chosen();                  /* the second of two of one name */
    CHECK(told.mode == 2 && told.name == "USB Mic" && told.index == 1);
    refresh_mics();
    CHECK(opts.mic == 3 && mic_want == "USB Mic" && told.index == 1);   /* stays the second */
    names = {"Webcam"};                          /* unplugged: an entry of its own, the host told by name */
    refresh_mics();
    CHECK(opts.mic == 3 && rows[0].hi == 3 && std::strstr(tx_mic(3), "USB Mic (not connected)") && told.mode == 2 &&
          told.name == "USB Mic" && told.index == -1);
    names = {"Webcam", "USB Mic"};               /* back, elsewhere in the list */
    refresh_mics();
    CHECK(opts.mic == 3 && rows[0].hi == 3 && !std::strcmp(tx_mic(3), "USB Mic") && told.index == 1);
    opts.mic = 1, mic_chosen();                  /* the default chosen: the name goes */
    refresh_mics();
    CHECK(opts.mic == 1 && mic_want.empty() && !std::strcmp(tx_mic(1), "Default") && !std::strcmp(tx_mic(0), "Off") &&
          told.mode == 1);
    opts.mic = 0, mic_chosen();
    CHECK(told.mode == 0);
    names = {std::string(100, 'x'), "Webcam"};   /* a long name: kept short, matched by as much of it */
    opts.mic = 2, mic_chosen();
    CHECK(mic_want.size() == kMicNameKept && std::strlen("microphone_device=") + mic_want.size() + 1 < 80);
    names = {"Webcam", std::string(100, 'x')};
    refresh_mics();
    CHECK(opts.mic == 3 && told.name == std::string(100, 'x') && told.index == 1);   /* (the whole name to the host) */
    names = {"Webcam"};
    refresh_mics();
    CHECK(told.name == std::string(60, 'x') && told.index == -1);   /* (unplugged: the kept one, cut) */
    names = {std::string(59, 'x') + "\xc3\xa9" + "yy"};   /* cut at a character's start, not inside the 2-byte one */
    opts.mic = 2, mic_chosen();
    CHECK(mic_want == std::string(59, 'x'));
    std::puts("PASS: the Microphone row keeps its choice by name, and tells the host");
    return 0;
}
"""

NOTE_FIXTURE = r"""#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); return 1; } } while (0)
@NOTE@
@METER@
int main() {
    CHECK(note_name(440) == "A4  440 Hz" && note_name(261.63f) == "C4  262 Hz" && note_name(293.7f) == "D4  294 Hz");
    CHECK(note_name(587.3f) == "D5  587 Hz" && note_name(110) == "A2  110 Hz" && note_name(452) == "A4  452 Hz");
    CHECK(mic_meter(0) == 0 && mic_meter(1) == 1 && mic_meter(2) == 1 && mic_meter(0.001f) == 0);
    CHECK(std::fabs(mic_meter(0.0631f) - 0.5f) < 0.01f);   /* (-24 dB: half way) */
    std::puts("PASS: the Test microphone's notes and meter");
    return 0;
}
"""


def block(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i)]


def through_function(text, start, last):
    """text from start to the end of the function that begins with last (its braces counted)"""
    i = text.index(start)
    j = text.index('{', text.index(last, i))
    depth = 0
    while True:
        depth += text[j] == '{'
        depth -= text[j] == '}'
        j += 1
        if depth == 0:
            return text[i:j] + '\n'


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cc', default='gcc')
    p.add_argument('--cxx', default='g++')
    a = p.parse_args()
    source = (ROOT / 'host' / 'nn_audio_in.c').read_text(encoding='utf-8')
    sdl_h = (ROOT / 'host' / 'hos_sdl.h').read_text(encoding='utf-8')
    # (the menu's row reaches the host: hos_mic_select, in the table it is given)
    check('"Microphone", &opts.mic, 0,' in (ROOT / 'gpu' / 'vk' / 'vk_menu.cpp').read_text(encoding='utf-8'),
          'the Insert menu has no Microphone row')
    check(re.search(r'hos_mic_count,\s*hos_mic_name,\s*hos_mic_select', (ROOT / 'host' / 'rx_backend.c').read_text(encoding='utf-8')),
          'the menu is not given the microphones')
    check('if (!mic_want.empty()) refresh_mics();' in (ROOT / 'gpu' / 'vk' / 'vk_menu.cpp').read_text(encoding='utf-8'),
          'the start lists the microphones (and starts SDL audio) even with none chosen')
    # (the Microphone volume reaches the host under one id on both sides; the test is in the host's table)
    api = (ROOT / 'gpu' / 'vk' / 'vk_api.h').read_text(encoding='utf-8')
    menu_src = (ROOT / 'gpu' / 'vk' / 'vk_menu.cpp').read_text(encoding='utf-8')
    api_id = re.search(r'HOS_OPT_MIC_GAIN = (\d+)', api)
    host_id = re.search(r'#define OPT_MIC_GAIN (\d+)', source)
    check(api_id and host_id and api_id.group(1) == host_id.group(1),
          'nn_audio_in.c reads the Microphone volume under another id than vk_api.h HOS_OPT_MIC_GAIN')
    chan_api, chan_host = re.search(r'HOS_OPT_MIC_CHANNEL = (\d+)', api), re.search(r'#define OPT_MIC_CHANNEL (\d+)', source)
    check(chan_api and chan_host and chan_api.group(1) == chan_host.group(1),
          'nn_audio_in.c reads the Microphone channel under another id than vk_api.h HOS_OPT_MIC_CHANNEL')
    check('{TAB_AUDIO, "Microphone channel", &opts.mic_channel, 0, 8, 1, tx_mic_channel,' in menu_src,
          'the Audio tab has no Microphone channel row')
    # (Windows: the microphone through WASAPI's raw stream, every channel, before SDL's own recording, which opens the
    # processed one whatever SDL_AUDIO_DEVICE_RAW_STREAM says: a Scarlett Solo's microphone, on its second channel, was lost)
    sdl_src = (ROOT / 'host' / 'hos_sdl.c').read_text(encoding='utf-8')
    mic_open = sdl_src[sdl_src.index('void *hos_sdl_mic_open('):]
    check('props.Options = AUDCLNT_STREAMOPTIONS_RAW' in sdl_src and 'was_channels(id)' in sdl_src and
          0 <= mic_open.find('was_open(id, freq, channels, sdl_format)') < mic_open.find('OpenAudioDeviceStream'),
          'hos_sdl.c no longer opens a Windows microphone raw, with all its channels, before SDL\'s processed stream')
    check(re.search(r'id == HOS_OPT_MIC_GAIN\) return std::clamp\(opts\.mic_gain, 0, 400\)',
                    (ROOT / 'gpu' / 'vk' / 'vk_replay.cpp').read_text(encoding='utf-8')),
          'the renderer does not answer the Microphone volume')
    check(re.search(r'\{TAB_AUDIO, "Microphone volume", &opts\.mic_gain, 0, 400, 10, tx_percent,', menu_src),
          'the Audio tab has no Microphone volume row from 0 to 400 %')
    check('{TAB_AUDIO, "Test microphone", nullptr,' in menu_src and 'int (*mic_test)(int on, float *level, float *hz, int *channel, int *channels);' in api,
          'the Audio tab has no Test microphone row, or the host no mic_test')
    check(re.search(r'hos_prompts_live_parts,\s*hos_mic_test,', (ROOT / 'host' / 'rx_backend.c').read_text(encoding='utf-8')),
          'the host table does not give the menu hos_mic_test (in MkwVkHost order, after prompts_live)')
    check('mic_test_tick(open_now.load() && page == 0 && cur_tab == TAB_AUDIO);' in menu_src,
          'the menu does not let the microphone test go when it closes or leaves the Audio tab')
    with tempfile.TemporaryDirectory(prefix='audio-in-') as t:
        folder = Path(t)
        for name, text in (('hos.h', HOS_H), ('windows.h', WINDOWS_H), ('hos_sdl.h', sdl_h), ('nn_audio_in.c', source),
                           ('fixture.c', FIXTURE)):
            (folder / name).write_text(text, encoding='utf-8')
        exe = folder / 'fixture'
        subprocess.run([a.cc, '-std=gnu11', '-include', ENV_ON_H, '-Wall', '-Wextra', '-Werror', '-I', str(folder), str(folder / 'fixture.c'),
                        '-o', str(exe), '-lm'], check=True)
        subprocess.run([str(exe)], check=True)
        # (the menu's side: the row's choice by name, gpu/vk/vk_menu.cpp)
        menu = (ROOT / 'gpu' / 'vk' / 'vk_menu.cpp').read_text(encoding='utf-8')
        fixture = MENU_FIXTURE.replace('@TEXT@', through_function(menu, 'constexpr int kMaxMics', 'const char* tx_mic('))
        fixture = fixture.replace('@REFRESH@', block(menu, 'void mic_tell_host()', 'void save()'))
        (folder / 'menu.cpp').write_text(fixture, encoding='utf-8')
        menu_exe = folder / 'menu'
        subprocess.run([a.cxx, '-std=c++17', '-include', ENV_ON_H, '-Wall', '-Wextra', '-Werror', str(folder / 'menu.cpp'), '-o', str(menu_exe)],
                       check=True)
        subprocess.run([str(menu_exe)], check=True)
        # (the Test microphone's note names and meter, gpu/vk/vk_menu.cpp)
        note = NOTE_FIXTURE.replace('@NOTE@', through_function(menu, 'std::string note_name(', 'std::string note_name('))
        note = note.replace('@METER@', re.search(r'^float mic_meter\(.*\}$', menu, re.M).group(0))
        (folder / 'note.cpp').write_text(note, encoding='utf-8')
        subprocess.run([a.cxx, '-std=c++17', '-Wall', '-Wextra', '-Werror', str(folder / 'note.cpp'), '-o', str(folder / 'note')],
                       check=True)
        subprocess.run([str(folder / 'note')], check=True)


if __name__ == '__main__':
    main()
