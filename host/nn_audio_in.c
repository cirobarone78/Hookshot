/* (hookshot) nn::audio's input streams: the microphone, as the ocarina's "play with your voice / an instrument" option uses it.

   The game lists the virtual input devices once at its start (ListVirtualInputDevices) and opens two input streams only if
   there is one: one on the default virtual device, one on the "true raw" one (GetTrueRawAudioInputDevice), both 48 kHz,
   mono, 16-bit (its StreamFormat: {PcmInt16, 1 channel, 48000}). With the ocarina's microphone mode on it starts them
   (StartInputStream when GetInputStreamState is not 2), reads up to 256 frames a frame (GetInputStreamFilledFrameCount,
   ReadInputStream) and works the notes out itself. Without these the stubs listed no device: the game never opened a
   stream, and the ocarina never heard anything.

   Here there is always one device of each kind (as on the console, whose microphone is always there). The started streams
   of one format share a source: one microphone opened once, through SDL3, or SDL2 as the Linux AppImage carries
   (host/hos_sdl.c), converted to that format; what it records goes to each stream's own buffer, the newest capacity's
   worth kept. Which one is the Insert menu's choice (gpu/vk/vk_menu.cpp, Gameplay: Microphone), told by hos_mic_select:
   off, the system's default, or a microphone by its name. One that is not there, does not open, stops sending, or is no
   longer listed (pulled out: looked for every 5 s, as one pulled out can go on sending zeros): the default stands in for
   it (silence when there is none either) and it is tried again, found by its name in a list made then (it may come back
   under another id), after 3 s, then twice as long each time up to a minute; once it gives sound again the waits start
   over. Off, or no SDL: silence at the stream's rate, so the game's reads go on as they
   would. A change in the menu takes effect at the next read. HOS_MIC_LOG=1: a line a second while a stream runs (its
   frames and level).

   (hookshot) The menu's Microphone volume (HOS_OPT_MIC_GAIN, 0 to 400 %) scales what the microphone gives before the game
   reads it, clipped at full scale: a quiet hum or a soft instrument the ocarina missed reaches it louder. Its Test
   microphone (hos_mic_test) opens the chosen microphone on its own while the menu shows the test, at that volume, and
   tells the menu its level and the pitch it hears: the player sees what the ocarina would get without starting a song.

   (hookshot) One channel, not a mix: for the game's mono streams the microphone is opened with the device's own channels
   (host/hos_sdl.c hos_sdl_mic_channels, Windows' raw stream) and one of them is given to the game, the menu's Microphone
   channel, or on Auto the louder of the first two (an audio interface's inputs; the loopbacks of what the PC plays come
   after them). SDL's mix of a Focusrite Scarlett Solo's four channels to mono was its silent first one and a quarter of
   the microphone on its second: the ocarina heard nothing. */
#include "hos.h"
#include "hos_sdl.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#ifndef HOOKSHOT_ENV_H   /* (env_on: the switches' one rule) */
#include "../gpu/vk/compat/hookshot_env.h"
#endif

#define MIC_MAGIC 0x4D494349u   /* "MICI": the high word of our handle in the game's InputStreamType */
#define MAX_STREAMS 4
#define MAX_DEVICES 16
#define QUIET_NS 2000000000LL   /* a microphone that gives nothing this long is taken as gone */
#define RETRY_NS 3000000000LL   /* a chosen microphone that is not there: tried again after this, */
#define RETRY_MAX_NS 60000000000LL   /* twice as long each time up to this */
#define CHECK_NS 5000000000LL   /* an open microphone looked for in a list made now this often (one pulled out may go on
                                   sending zeros: SDL3 on Windows) */
#define OPT_MIC_GAIN 29         /* HOS_OPT_MIC_GAIN (gpu/vk/vk_api.h): the menu's Microphone volume, in percent */
#define OPT_MIC_CHANNEL 30      /* HOS_OPT_MIC_CHANNEL: the menu's Microphone channel, 0 Auto, 1.. that one */
#define MAX_MIC_CH 8
#define GAIN_MAX 400
#define TEST_RATE 48000         /* the test's format: the game's (48 kHz, mono, 16-bit) */
#define TEST_WINDOW 2048        /* the newest samples the test's pitch is found in (43 ms) */
int rx_option(int id, int otherwise);   /* (host/rx_backend.c: the renderer's menu answers) */
enum { STATE_STOPPED = 1, STATE_STARTED = 2 };   /* (the game starts a stream whose state is not 2, stops one whose is) */
/* nn::audio::SampleFormat */
enum { FMT_PCM8 = 1, FMT_PCM16 = 2, FMT_PCM24 = 3, FMT_PCM32 = 4, FMT_FLOAT = 5 };

/* the channel given to the game, of a microphone opened with several */
typedef struct {
    int ch;                      /* the channels it was opened with (1: as the stream asks, nothing to pick) */
    int picked;                  /* the one given now, from 0 */
    float energy[MAX_MIC_CH];    /* (each one's loudness of late: Auto's) */
} Pick;

typedef struct {
    int used, users;             /* (users: the started streams reading it) */
    Pick pick;                   /* (the microphone's channels, and the one the game gets) */
    int format, channels, rate, frame_bytes;
    long gen;                    /* the menu's choice it follows (sel_gen) */
    int mode;                    /* 0 off, 1 the system's default, 2 the microphone named want */
    char want[128];
    uint32_t want_id;            /* (its id when chosen or last opened, 0 unknown: of two with one name, the one chosen) */
    void *mic;                   /* the SDL device, NULL: silence */
    int standin;                 /* (mic is the default, standing in for want) */
    int64_t heard_ns;            /* (the last time the microphone gave anything) */
    int64_t check_ns;            /* (when the wanted one, open, is next looked for in a fresh list) */
    int64_t retry_ns, retry_wait;   /* (the wanted microphone not open: when to try again, and the wait after that) */
    int64_t silence_from_ns, silence_made;   /* (silence: counted from here, frames of it made) */
    int failures;                /* (in a row, since it last gave sound: logged at the first) */
} Source;

typedef struct {
    int used, started, raw;
    int format, channels, rate, frame_bytes, capacity;   /* (capacity: frames the stream holds, the open's last argument) */
    int source;                  /* the source it reads while started (-1 none) */
    uint8_t *ring;               /* what was recorded for it and not read: capacity's worth at most, the oldest dropped */
    int ring_start, ring_len;
    int64_t frames_read, log_next_ns;
    int peak;                    /* (the loudest sample since the last log line, 16-bit) */
} InStream;

static InStream streams[MAX_STREAMS];
static Source sources[MAX_STREAMS];
static SRWLOCK lock = SRWLOCK_INIT;        /* the streams and the sources (the game's threads) */
static SRWLOCK list_lock = SRWLOCK_INIT;   /* the device list (the menu's thread too): never held while listing them */
static uint32_t dev_ids[MAX_DEVICES];
static char dev_names[MAX_DEVICES][128];
static int dev_count = -1;   /* (-1: not listed yet) */
static long sel_gen = 1;     /* the menu's choice (hos_mic_select), under list_lock: */
static int sel_mode = 1;     /* (before the menu says: the system's default) */
static char sel_name[128];
static int sel_index = -1;
static int log_on = -1;

/* ---- the devices, for the menu (gpu/vk/vk_api.h: MkwVkHost mic_count, mic_name) ---- */
int hos_mic_count(void) {   /* (lists them again: a microphone plugged in since shows; SDL asked without a lock held) */
    uint32_t ids[MAX_DEVICES];
    char names[MAX_DEVICES][128];
    const int n = hos_sdl_mic_list(ids, names, MAX_DEVICES);
    AcquireSRWLockExclusive(&list_lock);
    memcpy(dev_ids, ids, sizeof ids), memcpy(dev_names, names, sizeof names), dev_count = n;
    ReleaseSRWLockExclusive(&list_lock);
    return n;
}
const char *hos_mic_name(int index) {
    static char name[128];
    AcquireSRWLockShared(&list_lock);
    snprintf(name, sizeof name, "%s", index >= 0 && index < dev_count ? dev_names[index] : "");
    ReleaseSRWLockShared(&list_lock);
    return name;
}
void hos_mic_select(int mode, const char *name, int index) {   /* (the row's choice: taken at the streams' next read) */
    AcquireSRWLockExclusive(&list_lock);
    sel_mode = mode, sel_index = index, sel_gen++;
    snprintf(sel_name, sizeof sel_name, "%s", name ? name : "");
    ReleaseSRWLockExclusive(&list_lock);
}

/* ---- the sources: one microphone (or silence) for the started streams of one format ---- */
static uint16_t sdl_format(int f) {   /* (SDL_AudioFormat: little-endian, signed) */
    return f == FMT_PCM8 ? 0x8008 : f == FMT_PCM32 ? 0x8020 : f == FMT_FLOAT ? 0x8120 : 0x8010;
}
static int sample_bytes(int f) { return f == FMT_PCM8 ? 1 : f == FMT_PCM16 ? 2 : f == FMT_PCM24 ? 3 : 4; }

/* the menu's Microphone volume now, in percent (no menu: 100, as it comes) */
static int gain_percent(void) {
    const int g = rx_option(OPT_MIC_GAIN, 100);
    return g < 0 ? 0 : g > GAIN_MAX ? GAIN_MAX : g;
}
/* bytes of samples in format f scaled by percent, clipped at full scale (100: left as they are) */
static void amplify(uint8_t *p, int bytes, int f, int percent) {
    if (percent == 100) return;
    if (f == FMT_PCM8)
        for (int i = 0; i < bytes; i++) {
            const int v = ((int8_t *)p)[i] * percent / 100;
            ((int8_t *)p)[i] = (int8_t)(v > 127 ? 127 : v < -128 ? -128 : v);
        }
    else if (f == FMT_PCM16)
        for (int i = 0; i < bytes / 2; i++) {
            int16_t s;
            memcpy(&s, p + 2 * i, 2);
            const int v = s * percent / 100;
            s = (int16_t)(v > 32767 ? 32767 : v < -32768 ? -32768 : v);
            memcpy(p + 2 * i, &s, 2);
        }
    else if (f == FMT_PCM32)
        for (int i = 0; i < bytes / 4; i++) {
            int32_t s;
            memcpy(&s, p + 4 * i, 4);
            const int64_t v = (int64_t)s * percent / 100;
            s = (int32_t)(v > INT32_MAX ? INT32_MAX : v < INT32_MIN ? INT32_MIN : v);
            memcpy(p + 4 * i, &s, 4);
        }
    else if (f == FMT_FLOAT)
        for (int i = 0; i < bytes / 4; i++) {
            float s;
            memcpy(&s, p + 4 * i, 4);
            s = s * (float)percent / 100.0f;
            s = s > 1.0f ? 1.0f : s < -1.0f ? -1.0f : s;
            memcpy(p + 4 * i, &s, 4);
        }
}

/* a sample of format f as -1 to 1 (for the loudness alone) */
static float sample_value(const uint8_t *p, int f) {
    if (f == FMT_PCM8) return (int8_t)p[0] / 128.0f;
    if (f == FMT_FLOAT) {
        float v;
        memcpy(&v, p, 4);
        return v;
    }
    if (f == FMT_PCM32) {
        int32_t v;
        memcpy(&v, p, 4);
        return (float)v / 2147483648.0f;
    }
    int16_t v;
    memcpy(&v, p, 2);
    return v / 32768.0f;
}
/* the menu's Microphone channel now: 0 Auto, 1.. that one */
static int channel_choice(void) {
    const int c = rx_option(OPT_MIC_CHANNEL, 0);
    return c < 0 || c > MAX_MIC_CH ? 0 : c;
}
/* frames of in (p->ch channels of format f) to out, one channel: the one chosen (choice 1..), or on Auto (0, or one past
   the device's) the louder of the first two, kept until the other is twice as loud over the last reads (no flipping on
   noise). Returns out's bytes */
static int pick_channel(Pick *p, int choice, const uint8_t *in, int frames, int f, uint8_t *out) {
    const int sb = sample_bytes(f);
    if (p->ch <= 1) {   /* (one channel: as it is) */
        p->picked = 0;
        memcpy(out, in, (size_t)frames * sb);
        return frames * sb;
    }
    for (int c = 0; c < p->ch && frames > 0; c++) {
        float sum = 0;
        for (int i = 0; i < frames; i++) {
            const float v = sample_value(in + ((size_t)i * p->ch + c) * sb, f);
            sum += v * v;
        }
        p->energy[c] = p->energy[c] * 0.7f + sum / frames * 0.3f;
    }
    int c = p->picked;
    if (choice >= 1 && choice <= p->ch) {
        c = choice - 1;
    } else {
        const int first = p->ch < 2 ? p->ch : 2;
        if (c >= first) c = 0;
        for (int k = 0; k < first; k++)
            if (p->energy[k] > 2 * p->energy[c]) c = k;
    }
    p->picked = c;
    for (int i = 0; i < frames; i++) memcpy(out + (size_t)i * sb, in + ((size_t)i * p->ch + c) * sb, (size_t)sb);
    return frames * sb;
}
/* the channels to open a microphone with for a stream of `channels`: a mono one gets the device's own (one picked) */
static void pick_reset(Pick *p, int channels, uint32_t id) {
    const int n = channels == 1 ? hos_sdl_mic_channels(id) : channels;
    memset(p, 0, sizeof *p);
    p->ch = channels == 1 && n > 1 && n <= MAX_MIC_CH ? n : 1;
}

static void push(InStream *s, const uint8_t *in, int n) {   /* (into the stream's ring: the oldest dropped when full) */
    const int cap = s->capacity * s->frame_bytes;
    if (n > cap) {   /* (the newest capacity's worth) */
        if (in) in += n - cap;
        n = cap;
    }
    const int drop = s->ring_len + n - cap;
    if (drop > 0) s->ring_start = (s->ring_start + drop) % cap, s->ring_len -= drop;
    const int at = (s->ring_start + s->ring_len) % cap, first = n < cap - at ? n : cap - at;
    if (in) memcpy(s->ring + at, in, (size_t)first), memcpy(s->ring, in + first, (size_t)(n - first));
    else memset(s->ring + at, 0, (size_t)first), memset(s->ring, 0, (size_t)(n - first));   /* (silence) */
    s->ring_len += n;
}
static void push_all(const Source *src, const uint8_t *in, int n) {
    for (int i = 0; i < MAX_STREAMS; i++)
        if (streams[i].used && streams[i].started && &sources[streams[i].source] == src) push(&streams[i], in, n);
}

/* a device's name is the wanted one: the same, or its start when the wanted one is the menu's kept name (cut at kMicNameKept
   bytes, 60, at a character's start: 57 to 60 bytes; gpu/vk/vk_menu.cpp mic_key) */
static int same_name(const char *name, const char *want) {
    const size_t n = strlen(want);
    return !strcmp(name, want) || (n >= 57 && !strncmp(name, want, n));
}
/* the SDL id of the wanted microphone in a list: the one it was chosen or last opened as while a device of its name has that
   id, else the first of its name */
static int pick(const uint32_t *ids, char (*names)[128], int n, const Source *src, uint32_t *id) {
    int first = -1;
    for (int i = 0; i < n; i++)
        if (same_name(names[i], src->want)) {
            if (src->want_id && ids[i] == src->want_id) return *id = ids[i], 1;
            if (first < 0) first = i;
        }
    if (first >= 0) *id = ids[first];
    return first >= 0;
}
/* always in a list made now: a microphone plugged in again has another id, and SDL2's ids are places in its list, which move
   as devices come and go (the menu's list can be hours old) */
static int find_device(const Source *src, uint32_t *id) {
    uint32_t ids[MAX_DEVICES];
    char names[MAX_DEVICES][128];
    const int n = hos_sdl_mic_list(ids, names, MAX_DEVICES);
    return pick(ids, names, n, src, id);
}
static const char *wanted(const Source *src) { return src->mode == 2 ? src->want : "the default microphone"; }
static void close_mic(Source *src, int64_t now) {
    if (src->mic) {
        hos_sdl_mic_close(src->mic);
        src->silence_from_ns = now, src->silence_made = 0;   /* (silence from here) */
    }
    src->mic = NULL, src->standin = 0;
}
static void use(Source *src, void *mic, int standin, int64_t now) {   /* (a microphone opened: in place of the one before) */
    close_mic(src, now);
    src->mic = mic, src->standin = standin, src->heard_ns = now;
}
/* the wanted microphone could not be had: said once until it gives sound again, tried again later, each wait twice the last */
static void missed(Source *src, int64_t now, const char *why) {
    if (!src->failures++)
        hos_log("audio in: %s %s: %s, tried again from time to time", wanted(src), why,
                src->standin ? "the default microphone stands in" : "silence");
    src->retry_ns = now + src->retry_wait;
    src->retry_wait = src->retry_wait * 2 < RETRY_MAX_NS ? src->retry_wait * 2 : RETRY_MAX_NS;
}
/* microphone id for the source's streams: a mono stream's with the device's own channels (src->pick, once it opens) */
static void *open_mic(Source *src, uint32_t id) {
    Pick pick;
    pick_reset(&pick, src->channels, id);
    void *mic = hos_sdl_mic_open(id, src->rate, pick.ch > 1 ? pick.ch : src->channels, sdl_format(src->format));
    if (mic) src->pick = pick;
    return mic;
}
static void stand_in(Source *src, int64_t now) {   /* (the default, while the wanted one cannot be had) */
    if (src->standin) return;
    void *standin = open_mic(src, 0);
    if (standin) use(src, standin, 1, now);
    else close_mic(src, now);
}
/* the wanted microphone, open, is gone (pulled out, stalled): the default stands in for a named one, tried again later */
static void lost(Source *src, int64_t now, const char *why) {
    close_mic(src, now);
    if (src->mode == 2) stand_in(src, now);
    missed(src, now, why);
}
/* the wanted microphone opened; a named one that cannot be: the default stands in */
static void connect(Source *src) {
    const int64_t now = hos_now_ns();
    if (src->mode <= 0) {
        close_mic(src, now);
        return;
    }
    uint32_t id = 0;   /* (the system's default) */
    void *mic = NULL;
    const int found = src->mode == 1 || find_device(src, &id);
    if (found) mic = open_mic(src, id);
    if (mic) {
        if (!src->failures && src->pick.ch > 1)
            hos_log("audio in: %s open (%d Hz, its %d channels, one given to the game: %s)", wanted(src), src->rate,
                    src->pick.ch, channel_choice() ? "the menu's" : "Auto, the louder of the first two");
        else if (!src->failures)
            hos_log("audio in: %s open (%d Hz, %d channel%s)", wanted(src), src->rate, src->channels,
                    src->channels == 1 ? "" : "s");
        use(src, mic, 0, now);
        if (src->mode == 2) src->want_id = id;   /* (under the id it has now: the menu's next word of it is the same choice) */
        src->check_ns = now + CHECK_NS;
        return;
    }
    if (src->mode == 2) stand_in(src, now);
    else close_mic(src, now);
    missed(src, now, found ? "did not open" : "is not plugged in");
    if (src->failures == 1 && found) hos_log("audio in: (%s)", hos_sdl_error());
}
/* the menu's choice now: opened again only when it is another microphone */
static void choose(Source *src) {
    AcquireSRWLockShared(&list_lock);
    const long gen = sel_gen;
    const int mode = sel_mode, listed = mode == 2 && sel_index >= 0 && sel_index < dev_count && same_name(dev_names[sel_index], sel_name);
    char want[128];
    snprintf(want, sizeof want, "%s", listed ? dev_names[sel_index] : mode == 2 ? sel_name : "");   /* (the whole name when listed) */
    const uint32_t want_id = listed ? dev_ids[sel_index] : 0;
    ReleaseSRWLockShared(&list_lock);
    if (gen == src->gen) return;
    const int same = src->gen && mode == src->mode && (same_name(want, src->want) || same_name(src->want, want)) &&
                     (!want_id || want_id == src->want_id);
    src->gen = gen;
    if (same) {
        if (strlen(want) > strlen(src->want)) snprintf(src->want, sizeof src->want, "%s", want);
        if (mode == 2 && sel_index < 0 && src->mic && !src->standin) src->check_ns = 0;   /* (the menu sees it unplugged: look now) */
        return;
    }
    src->mode = mode, src->want_id = want_id;
    snprintf(src->want, sizeof src->want, "%s", want);
    src->failures = 0, src->retry_wait = RETRY_NS;
    if (mode <= 0) hos_log("audio in: the microphone is off in the menu: silence");
    connect(src);
}
/* what the source has recorded since, into its streams: the microphone's, or silence at the rate when there is none */
static void pump(Source *src) {
    const int64_t now = hos_now_ns();
    if (src->mode > 0 && (!src->mic || src->standin) && now >= src->retry_ns) connect(src);   /* (the wanted one again) */
    if (src->mode == 2 && src->mic && !src->standin && now >= src->check_ns) {   /* (still plugged in?) */
        uint32_t id;
        src->check_ns = now + CHECK_NS;
        if (!find_device(src, &id)) lost(src, now, "was unplugged");
    }
    if (src->mic) {
        int most = 0;   /* (the largest stream's capacity: more than that backlog is dropped before it reaches them) */
        for (int i = 0; i < MAX_STREAMS; i++)
            if (streams[i].used && streams[i].started && &sources[streams[i].source] == src) {
                const int bytes = streams[i].capacity * streams[i].frame_bytes;
                if (bytes > most) most = bytes;
            }
        /* (fb: the microphone's frame, all its channels when one is picked of several; the streams get one) */
        const int fb = src->pick.ch > 1 ? sample_bytes(src->format) * src->pick.ch : src->frame_bytes;
        most = most / src->frame_bytes * fb;
        uint8_t buf[4096], one[4096];
        const int chunk = (int)sizeof buf - (int)sizeof buf % fb, gain = gain_percent(), choice = channel_choice();
        int heard = 0, avail = hos_sdl_mic_available(src->mic);
        for (int drop = avail - most; drop > 0;) {   /* (the game stopped reading a while) */
            const int got = hos_sdl_mic_read(src->mic, buf, drop < chunk ? drop - drop % fb : chunk);
            if (got <= 0) break;
            drop -= got, avail -= got, heard = 1;
        }
        while (avail > 0) {
            const int got = hos_sdl_mic_read(src->mic, buf, avail < chunk ? avail - avail % fb : chunk);
            if (got <= 0) break;
            avail -= got, heard = 1;
            uint8_t *out = buf;
            int n = got;
            if (src->pick.ch > 1) n = pick_channel(&src->pick, choice, buf, got / fb, src->format, one), out = one;
            amplify(out, n, src->format, gain);   /* (the menu's Microphone volume) */
            push_all(src, out, n);
        }
        if (heard) {
            src->heard_ns = now;
            if (src->failures && !src->standin) {   /* (the wanted one gives sound again: the waits start over) */
                hos_log("audio in: %s is back", wanted(src));
                src->failures = 0, src->retry_wait = RETRY_NS;
            }
        } else if (now - src->heard_ns > QUIET_NS) {   /* (pulled out, or its driver stopped) */
            if (src->standin) close_mic(src, now);   /* (the stand-in gone quiet too: silence until the next try) */
            else lost(src, now, "stopped sending");
        }
        return;
    }
    const int64_t since = now - src->silence_from_ns;   /* (in seconds and the rest: no overflow however long) */
    int64_t due = since / 1000000000LL * src->rate + since % 1000000000LL * src->rate / 1000000000LL - src->silence_made;
    src->silence_made += due;
    if (src->silence_made >= src->rate) {   /* (whole seconds into the start: no overflow however long it stays silent) */
        const int64_t secs = src->silence_made / src->rate;
        src->silence_from_ns += secs * 1000000000LL, src->silence_made -= secs * src->rate;
    }
    if (due > src->rate) due = src->rate;   /* (more than a second is past every stream's capacity anyway) */
    if (due > 0) push_all(src, NULL, (int)due * src->frame_bytes);
}
static void pump_all(void) {
    for (int i = 0; i < MAX_STREAMS; i++)
        if (sources[i].used) {
            choose(&sources[i]);
            pump(&sources[i]);
        }
}

/* ---- (hookshot) the menu's Test microphone: the chosen microphone opened on its own, in the game's format, at the
   Microphone volume; its level and the pitch it hears for the menu (gpu/vk/vk_api.h: MkwVkHost mic_test) ---- */
static struct {
    void *mic;
    long gen;            /* the menu's choice it was opened for (sel_gen; 0 none) */
    int state;           /* what hos_mic_test says for that choice: 1 listening, 0 off, -1 did not open, -2 not plugged in */
    Pick pick;           /* (its channels, and the one listened to: as the game's streams get them) */
    int16_t win[TEST_WINDOW];   /* the newest samples, at the volume: the pitch is found in them */
    int win_len;
    float level, hz;
    int64_t level_ns, pitch_ns;
} test;
static SRWLOCK test_lock = SRWLOCK_INIT;

/* the pitch of x (n samples at rate) in Hz, 0 when there is no steady note: the normalized square difference (McLeod's
   method), its first peak past the first dip that comes near its highest, for periods of 1500 Hz down to 60 Hz. A hum, a
   whistle, a recorder or an ocarina is a steady note there; speech and noise are not */
float hos_mic_pitch(const int16_t *x, int n, int rate) {
    static float nsdf[TEST_WINDOW / 2 + 2];
    const int lo = rate / 1500 > 2 ? rate / 1500 : 2;
    int hi = rate / 60;
    if (n > TEST_WINDOW) x += n - TEST_WINDOW, n = TEST_WINDOW;
    if (hi > n / 2) hi = n / 2;
    if (hi <= lo + 2) return 0;
    float best = 0;
    int dipped = 0;
    for (int lag = 1; lag <= hi + 1 && lag < n; lag++) {
        double r = 0, m = 0;
        for (int i = 0; i + lag < n; i++) {
            const double a = x[i], b = x[i + lag];
            r += a * b, m += a * a + b * b;
        }
        nsdf[lag] = m > 0 ? (float)(2 * r / m) : 0;
        if (nsdf[lag] < 0) dipped = 1;
        if (dipped && lag >= lo && lag <= hi && nsdf[lag] > best) best = nsdf[lag];
    }
    if (best < 0.6f) return 0;
    dipped = 0;
    for (int lag = 2; lag <= hi; lag++) {
        if (nsdf[lag] < 0) dipped = 1;
        if (!dipped || lag < lo || nsdf[lag] < 0.9f * best || nsdf[lag] < nsdf[lag - 1] || nsdf[lag] < nsdf[lag + 1]) continue;
        const float a = nsdf[lag - 1], b = nsdf[lag], c = nsdf[lag + 1], d = a - 2 * b + c;
        const float shift = d < 0 ? 0.5f * (a - c) / d : 0;   /* (the parabola's top through the three) */
        return (float)rate / ((float)lag + shift);
    }
    return 0;
}

static void test_close(void) {
    if (test.mic) hos_sdl_mic_close(test.mic);
    test.mic = NULL, test.win_len = 0, test.level = test.hz = 0;
}
/* the menu's choice now, opened for the test (a choice that did not open: tried again only once it changes) */
static void test_open(void) {
    Source want;   /* (find_device's: the wanted name, and its id while the menu's list has it) */
    memset(&want, 0, sizeof want);
    AcquireSRWLockShared(&list_lock);
    const long gen = sel_gen;
    const int mode = sel_mode, listed = mode == 2 && sel_index >= 0 && sel_index < dev_count && same_name(dev_names[sel_index], sel_name);
    snprintf(want.want, sizeof want.want, "%s", listed ? dev_names[sel_index] : sel_name);
    want.want_id = listed ? dev_ids[sel_index] : 0;
    ReleaseSRWLockShared(&list_lock);
    if (gen == test.gen) return;
    test_close();
    test.gen = gen;
    if (mode <= 0) {
        test.state = 0;
        return;
    }
    uint32_t id = 0;   /* (the system's default) */
    if (mode == 2 && !find_device(&want, &id)) {
        test.state = -2;
        return;
    }
    pick_reset(&test.pick, 1, id);
    test.mic = hos_sdl_mic_open(id, TEST_RATE, test.pick.ch, sdl_format(FMT_PCM16));
    test.state = test.mic ? 1 : -1;
    test.level_ns = test.pitch_ns = hos_now_ns();
    if (test.mic) hos_log("audio in: the menu's test listens to %s", mode == 2 ? want.want : "the default microphone");
    else hos_log("audio in: the menu's test: %s did not open (%s)", mode == 2 ? want.want : "the default microphone",
                 hos_sdl_error());
}
/* on: the test listens (opened at the first call, again when the menu's choice changes), and says its level (0 to 1, the
   loudest of late, falling back over half a second) and pitch (Hz, 0 none) at the Microphone volume, of the channel the
   game would get (*channel, from 1, of *channels); off: closed. Returns 1 listening, 0 the microphone is off in the menu,
   -1 it did not open, -2 the chosen one is not plugged in */
int hos_mic_test(int on, float *level, float *hz, int *channel, int *channels) {
    AcquireSRWLockExclusive(&test_lock);
    if (!on) {
        test_close();
        test.gen = 0, test.state = 0;
    } else {
        test_open();
    }
    if (test.mic) {
        const int gain = gain_percent();
        const int64_t now = hos_now_ns();
        int16_t all[4096], buf[4096];   /* (what it recorded, every channel; the one picked) */
        const int fb = 2 * test.pick.ch, chunk = (int)sizeof all - (int)sizeof all % fb, choice = channel_choice();
        int peak = 0, avail = hos_sdl_mic_available(test.mic);
        while (avail >= fb) {
            const int got = hos_sdl_mic_read(test.mic, all, avail < chunk ? avail - avail % fb : chunk);
            if (got < fb) break;
            avail -= got;
            const int bytes = pick_channel(&test.pick, choice, (const uint8_t *)all, got / fb, FMT_PCM16, (uint8_t *)buf);
            amplify((uint8_t *)buf, bytes, FMT_PCM16, gain);
            const int n = bytes / 2;
            for (int i = 0; i < n; i++) {
                const int v = buf[i] < 0 ? -buf[i] : buf[i];
                if (v > peak) peak = v;
            }
            if (n >= TEST_WINDOW) {
                memcpy(test.win, buf + n - TEST_WINDOW, sizeof test.win), test.win_len = TEST_WINDOW;
            } else {
                const int keep = test.win_len + n > TEST_WINDOW ? TEST_WINDOW - n : test.win_len;
                memmove(test.win, test.win + test.win_len - keep, (size_t)keep * 2);
                memcpy(test.win + keep, buf, (size_t)n * 2), test.win_len = keep + n;
            }
        }
        const float fall = (float)(now - test.level_ns) / 5e8f;   /* (full scale to none in half a second) */
        test.level = test.level - fall > 0 ? test.level - fall : 0;
        if (peak / 32767.0f > test.level) test.level = peak / 32767.0f;
        test.level_ns = now;
        if (now - test.pitch_ns >= 50000000LL) {   /* (twenty times a second at most) */
            test.pitch_ns = now;
            test.hz = test.win_len == TEST_WINDOW && test.level > 0.02f ? hos_mic_pitch(test.win, TEST_WINDOW, TEST_RATE) : 0;
        }
    }
    if (level) *level = test.level;
    if (hz) *hz = test.mic ? test.hz : 0;
    if (channel) *channel = test.mic ? test.pick.picked + 1 : 0;
    if (channels) *channels = test.mic ? test.pick.ch : 0;
    const int state = test.state;
    ReleaseSRWLockExclusive(&test_lock);
    return state;
}

/* ---- the streams ---- */
static InStream *stream_of(uint64_t obj) {
    if (!obj) return NULL;
    const uint64_t h = G64(obj);
    const int i = (int)(h & 0xFFFF) - 1;
    if ((uint32_t)(h >> 32) != MIC_MAGIC || i < 0 || i >= MAX_STREAMS || !streams[i].used) return NULL;
    return &streams[i];
}
static void attach(InStream *s) {   /* (the source of its format, made when there is none) */
    int free_at = -1;
    for (int i = 0; i < MAX_STREAMS; i++) {
        const Source *src = &sources[i];
        if (src->used && src->format == s->format && src->channels == s->channels && src->rate == s->rate) {
            s->source = i, sources[i].users++;
            return;
        }
        if (!src->used && free_at < 0) free_at = i;
    }
    Source *src = &sources[free_at];   /* (as many sources as streams: one is free) */
    memset(src, 0, sizeof *src);
    src->used = 1, src->users = 1, src->silence_from_ns = hos_now_ns(), src->retry_wait = RETRY_NS;
    src->format = s->format, src->channels = s->channels, src->rate = s->rate, src->frame_bytes = s->frame_bytes;
    s->source = free_at;
    choose(src);
}
static void detach(InStream *s) {
    if (s->source < 0) return;
    Source *src = &sources[s->source];
    s->source = -1;
    if (--src->users > 0) return;
    close_mic(src, hos_now_ns());
    memset(src, 0, sizeof *src);
}
static void note_read(InStream *s, const uint8_t *p, int frames) {
    s->frames_read += frames;
    if (log_on < 0) log_on = env_on("HOS_MIC_LOG");
    if (!log_on) return;
    if (s->format == FMT_PCM16)
        for (int i = 0; i < frames * s->channels; i++) {
            int v = ((const int16_t *)p)[i];
            if (v < 0) v = -v;
            if (v > s->peak) s->peak = v;
        }
    const int64_t now = hos_now_ns();
    if (now >= s->log_next_ns) {
        hos_log("audio in: stream %d: %lld frames read, peak %d of 32767 in the last second", (int)(s - streams),
                (long long)s->frames_read, s->peak);
        s->peak = 0, s->log_next_ns = now + 1000000000LL;
    }
}

/* ListVirtualInputDevices(AudioDeviceName *names, int count): one (256 bytes, a name) */
HLE(_ZN2nn5audio23ListVirtualInputDevicesEPNS0_15AudioDeviceNameEi) {
    if ((int)ARG(1) <= 0 || !ARG(0)) { RET(0); return; }
    memset(GP(ARG(0)), 0, 256);
    memcpy(GP(ARG(0)), "MainAudioIn", 11);
    RET(1);
}
HLE(_ZN2nn5audio28GetDefaultVirtualInputDeviceEPNS0_15AudioDeviceNameE) {
    if (ARG(0)) memset(GP(ARG(0)), 0, 256), memcpy(GP(ARG(0)), "MainAudioIn", 11);
    RET(0);
}
HLE(_ZN2nn5audio26GetTrueRawAudioInputDeviceEPNS0_15AudioDeviceNameE) {
    if (ARG(0)) memset(GP(ARG(0)), 0, 256), memcpy(GP(ARG(0)), "RawAudioIn", 10);
    RET(0);
}
HLE(_ZN2nn5audio41IsVirtualInputDeviceStreamFormatSupportedERKNS0_15AudioDeviceNameERKNS0_12StreamFormatE) { RET(1); }

/* OpenInputStream(InputStreamType *, void *work, size_t, const AudioDeviceName &, const StreamFormat &, int frames).
   StreamFormat: {SampleFormat, channel count, sample rate} (the game's: {2, 1, 48000}). (The overload with an
   os::SystemEvent is not here: OoT does not import it, and a stub of it logs its first call, where an event never signalled
   could leave a waiter blocked) */
HLE(_ZN2nn5audio15OpenInputStreamEPNS0_15InputStreamTypeEPvmRKNS0_15AudioDeviceNameERKNS0_12StreamFormatEi) {
    const uint64_t obj = ARG(0), name = ARG(3), format = ARG(4);
    const int frames = (int)ARG(5);
    AcquireSRWLockExclusive(&lock);
    int i = 0;
    while (i < MAX_STREAMS && streams[i].used) i++;
    if (!obj || !format || i == MAX_STREAMS) {
        ReleaseSRWLockExclusive(&lock);
        hos_log("audio in: an input stream did not open (%s)", i == MAX_STREAMS ? "too many" : "no stream or format");
        RET(0x1F3);   /* (a failure: the game leaves the stream alone) */
        return;
    }
    InStream *s = &streams[i];
    memset(s, 0, sizeof *s);
    s->format = (int)G32(format), s->channels = (int)G32(format + 4), s->rate = (int)G32(format + 8);
    if (s->format < FMT_PCM8 || s->format > FMT_FLOAT || s->format == FMT_PCM24) s->format = FMT_PCM16;
    if (s->channels < 1 || s->channels > 8) s->channels = 1;
    if (s->rate < 8000 || s->rate > 192000) s->rate = 48000;
    s->frame_bytes = sample_bytes(s->format) * s->channels;
    /* (hookshot) at most 10 s: the ring's byte offsets are ints (a larger frame count from the game overflowed them) */
    s->capacity = frames > 0 && frames <= s->rate * 10 ? frames : frames > 0 ? s->rate * 10 : s->rate / 10;
    s->ring = (uint8_t *)malloc((size_t)s->capacity * s->frame_bytes);
    if (!s->ring) {
        ReleaseSRWLockExclusive(&lock);
        RET(0x1F3);
        return;
    }
    s->used = 1, s->source = -1;
    s->raw = name && !memcmp(GP(name), "RawAudioIn", 10);
    G64(obj) = (uint64_t)MIC_MAGIC << 32 | (uint64_t)(i + 1);
    ReleaseSRWLockExclusive(&lock);
    hos_log("audio in: stream %d opened%s: format %d, %d channel%s, %d Hz, %d frames", i, s->raw ? " (raw)" : "", s->format,
            s->channels, s->channels == 1 ? "" : "s", s->rate, s->capacity);
    RET(0);
}
HLE(_ZN2nn5audio16CloseInputStreamEPNS0_15InputStreamTypeE) {
    AcquireSRWLockExclusive(&lock);
    InStream *s = stream_of(ARG(0));
    if (s) {
        if (s->started) detach(s);
        free(s->ring);
        memset(s, 0, sizeof *s);
        G64(ARG(0)) = 0;
    }
    ReleaseSRWLockExclusive(&lock);
}
HLE(_ZN2nn5audio16StartInputStreamEPNS0_15InputStreamTypeE) {
    AcquireSRWLockExclusive(&lock);
    InStream *s = stream_of(ARG(0));
    if (s && !s->started) {
        s->started = 1, s->ring_start = s->ring_len = 0;
        attach(s);
    }
    ReleaseSRWLockExclusive(&lock);
    RET(s ? 0 : 0x1F3);
}
HLE(_ZN2nn5audio15StopInputStreamEPNS0_15InputStreamTypeE) {
    AcquireSRWLockExclusive(&lock);
    InStream *s = stream_of(ARG(0));
    if (s && s->started) {
        s->started = 0;
        detach(s);
        hos_log("audio in: stream %d stopped (%lld frames read)", (int)(s - streams), (long long)s->frames_read);
    }
    ReleaseSRWLockExclusive(&lock);
    RET(0);
}
HLE(_ZN2nn5audio16PurgeInputStreamEPNS0_15InputStreamTypeE) {   /* (what was recorded and not read: gone) */
    AcquireSRWLockExclusive(&lock);
    InStream *s = stream_of(ARG(0));
    if (s) {
        if (s->started) pump_all();   /* (what the source had for it so far goes too) */
        s->ring_start = s->ring_len = 0;
    }
    ReleaseSRWLockExclusive(&lock);
    RET(0);
}
HLE(_ZN2nn5audio19GetInputStreamStateEPKNS0_15InputStreamTypeE) {
    AcquireSRWLockExclusive(&lock);
    InStream *s = stream_of(ARG(0));
    RET(s && s->started ? STATE_STARTED : STATE_STOPPED);
    ReleaseSRWLockExclusive(&lock);
}
static int filled(InStream *s) {
    if (!s->started) return 0;
    pump_all();
    return s->ring_len / s->frame_bytes;
}
HLE(_ZN2nn5audio30GetInputStreamFilledFrameCountEPKNS0_15InputStreamTypeE) {
    AcquireSRWLockExclusive(&lock);
    InStream *s = stream_of(ARG(0));
    RET(s ? filled(s) : 0);
    ReleaseSRWLockExclusive(&lock);
}
HLE(_ZN2nn5audio28GetInputStreamFreeFrameCountEPKNS0_15InputStreamTypeE) {
    AcquireSRWLockExclusive(&lock);
    InStream *s = stream_of(ARG(0));
    RET(s ? s->capacity - filled(s) : 0);
    ReleaseSRWLockExclusive(&lock);
}
HLE(_ZN2nn5audio32GetInputStreamCapacityFrameCountEPKNS0_15InputStreamTypeE) {
    AcquireSRWLockExclusive(&lock);
    InStream *s = stream_of(ARG(0));
    RET(s ? s->capacity : 0);
    ReleaseSRWLockExclusive(&lock);
}
/* ReadInputStream(InputStreamType *, void *buffer, int frames): the frames read */
HLE(_ZN2nn5audio15ReadInputStreamEPNS0_15InputStreamTypeEPvi) {
    AcquireSRWLockExclusive(&lock);
    InStream *s = stream_of(ARG(0));
    int frames = 0;
    if (s && ARG(1) && (int)ARG(2) > 0) {
        const int have = filled(s);
        frames = (int)ARG(2) < have ? (int)ARG(2) : have;
        const int cap = s->capacity * s->frame_bytes, n = frames * s->frame_bytes;
        uint8_t *dst = (uint8_t *)hos_guest_range(ARG(1), (uint64_t)n);   /* (hookshot: only into guest memory) */
        if (!dst) frames = 0;
        else {
            const int first = n < cap - s->ring_start ? n : cap - s->ring_start;
            memcpy(dst, s->ring + s->ring_start, (size_t)first);
            memcpy(dst + first, s->ring, (size_t)(n - first));
            s->ring_start = (s->ring_start + n) % cap, s->ring_len -= n;
            HOS_WRITTEN(dst, (size_t)n);
            note_read(s, dst, frames);
        }
    }
    ReleaseSRWLockExclusive(&lock);
    RET(frames);
}
/* GetInputStreamStatistics(InputStreamType *, bool reset): a structure returned through x8; the game checks its second
   64-bit word (frames lost?) against 1. Nothing lost */
HLE(_ZN2nn5audio24GetInputStreamStatisticsEPNS0_15InputStreamTypeEb) {
    if (c->x[8]) memset(GP(c->x[8]), 0, 16);
}
HLE(_ZN2nn5audio18SetInputStreamGainEPNS0_15InputStreamTypeEfNS_8TimeSpanE) { (void)c; }   /* (the device's level as the system has it) */
HLE(_ZN2nn5audio18GetInputStreamGainEPKNS0_15InputStreamTypeE) {
    const float one = 1.0f;
    c->vreg[0][0] = c->vreg[0][1] = 0;
    memcpy(&c->vreg[0][0], &one, 4);
}
