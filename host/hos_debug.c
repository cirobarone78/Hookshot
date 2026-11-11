/* Opt-in local runtime API: HOS_DEBUG_SOCKET=<abstract Unix socket name>.
   SOCK_SEQPACKET preserves command boundaries. One bounded command/reply per connection, same UID only.
   The endpoint has no desktop input dependency. Acknowledged input means Npad consumed it, not that a menu reacted.
   Frame intervals measure completed native presents, including minimized rendering, not displayed frames. */
#ifdef __linux__
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "hos_debug.h"
#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/uio.h>
#include <sys/un.h>
#include <unistd.h>

extern int64_t hos_now_ns(void);
extern void hos_log(const char *format, ...);
#define SAMPLES 120
static int enabled; /* published once, before starting game threads */
static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;
static struct {
    int mode, n, next;
    uint64_t frame, input_polls, sequence, applied_sequence, buttons, observed_buttons;
    int64_t last_present, last_poll, hold_ns, until;
    int32_t sticks[4], observed_sticks[4];
    double ms[SAMPLES], longest_ms;
    uint64_t frames_over_50ms, frames_over_100ms;
} state;
/* Set only after the guest image is loaded. All accesses use mu; the reserved window lives until process exit. */
static struct { uintptr_t base; uint64_t size, image_base, image_end; } memory;
static struct {
    uint64_t sequence, caller;
    int allowed, phase; /* 0 idle, 1 pending, 2 executing, 3 dispatched, 4 canceled, 5 rejected */
    int64_t deadline;
    int kind, result, handoff;
    uint32_t key, actor_id;
    uint64_t actor;
    char value[64], thread[48], dispatched_thread[48];
} guest;
#define MEMORY_READ_MAX 256

/* Called only from a real guest SDK poll, never the socket server. The callback owns
   ABI/context preservation. Dispatched means the setter ran, not that a map loaded. */
void hos_debug_guest_poll(void *context, const char *thread, uint64_t caller, int allowed, HosDebugStringCall call) {
    if (!enabled) return;
    pthread_mutex_lock(&mu);
    guest.allowed |= allowed; /* The job migrates between workers; admission stays enabled once the selected one polls. */
    guest.caller = caller;
    size_t i = 0;
    for (; thread && thread[i] && i < sizeof guest.thread - 1; ++i) {
        unsigned char c = (unsigned char)thread[i];
        guest.thread[i] = c >= 32 && c < 127 && c != '"' && c != '\\' ? c : '?';
    }
    guest.thread[i] = 0;
    if (guest.phase != 1) { pthread_mutex_unlock(&mu); return; }
    if (hos_now_ns() >= guest.deadline || state.mode != HOS_DEBUG_EXCLUSIVE) {
        guest.phase = 4;
        pthread_mutex_unlock(&mu);
        return;
    }
    if (!allowed || !call) { pthread_mutex_unlock(&mu); return; }
    const int kind = guest.kind;
    const uint32_t key = guest.key, actor_id = guest.actor_id;
    const uint64_t actor = guest.actor;
    char value[64];
    memcpy(value, guest.value, sizeof value);
    memcpy(guest.dispatched_thread, guest.thread, sizeof guest.thread);
    guest.phase = 2;
    pthread_mutex_unlock(&mu);
    const int dispatched = call(context, kind, key, value, actor, actor_id);
    pthread_mutex_lock(&mu);
    guest.result = dispatched;
    if (dispatched == HOS_DEBUG_DEFER) {
        guest.phase = guest.handoff || state.mode != HOS_DEBUG_EXCLUSIVE ||
                      hos_now_ns() >= guest.deadline ? 4 : 1;
    } else {
        guest.phase = dispatched > 0 ? 3 : 5;
    }
    pthread_mutex_unlock(&mu);
}

static void guest_info(char *out, size_t cap) {
    static const char *phases[] = {"idle", "pending", "executing", "dispatched", "canceled", "rejected"};
    pthread_mutex_lock(&mu);
    if (guest.phase == 1 && hos_now_ns() >= guest.deadline) guest.phase = 4;
    snprintf(out, cap, "{\"ok\":true,\"sequence\":%" PRIu64 ",\"phase\":\"%s\","
             "\"allowed\":%s,\"thread\":\"%s\",\"dispatched_thread\":\"%s\",\"caller\":\"0x%" PRIx64 "\",\"rejection_reason\":%s,\"pending_reason\":%s}",
             guest.sequence, phases[guest.phase], guest.allowed ? "true" : "false", guest.thread,
             guest.dispatched_thread, guest.caller,
             guest.phase != 5 ? "null" : guest.result == HOS_DEBUG_EVENT_REJECTED ?
             "\"event_helper_returned_false\"" : "\"adapter_rejected\"",
             guest.phase == 1 && guest.result == HOS_DEBUG_DEFER ? "\"awaiting_readiness\"" : "null");
    pthread_mutex_unlock(&mu);
}

void hos_debug_memory_window(void *base, uint64_t size, uint64_t image_base, uint64_t image_end) {
    if (!enabled || !base || !size || size > UINTPTR_MAX - (uintptr_t)base ||
        image_base > image_end || image_end > size) return;
    pthread_mutex_lock(&mu);
    memory.base = (uintptr_t)base;
    memory.size = size;
    memory.image_base = image_base;
    memory.image_end = image_end;
    pthread_mutex_unlock(&mu);
}

static void memory_info(char *out, size_t cap) {
    pthread_mutex_lock(&mu);
    const __typeof__(memory) m = memory;
    pthread_mutex_unlock(&mu);
    snprintf(out, cap, "{\"ok\":true,\"ready\":%s,\"guest_size\":\"0x%" PRIx64 "\","
             "\"image_base\":\"0x%" PRIx64 "\",\"image_end\":\"0x%" PRIx64 "\","
             "\"max_read_bytes\":%d,\"writable\":false,\"consistent_snapshot\":false}",
             m.base ? "true" : "false", m.size, m.image_base, m.image_end, MEMORY_READ_MAX);
}

static void memory_read(uint64_t address, size_t length, char *out, size_t cap) {
    pthread_mutex_lock(&mu);
    const __typeof__(memory) m = memory;
    pthread_mutex_unlock(&mu);
    if (!m.base) { snprintf(out, cap, "{\"ok\":false,\"error\":\"guest memory is not ready\"}"); return; }
    if (!length || length > MEMORY_READ_MAX || address >= m.size || length > m.size - address) {
        snprintf(out, cap, "{\"ok\":false,\"error\":\"read outside guest window\"}");
        return;
    }
    unsigned char data[MEMORY_READ_MAX];
    struct iovec local = {data, length}, remote = {(void *)(m.base + (uintptr_t)address), length};
    /* The kernel safely handles guard/unmapped pages and concurrent mapping changes. A failed or partial
       read returns no data; ordinary memcpy could fault the game. These live bytes are not an atomic snapshot. */
    const ssize_t got = process_vm_readv(getpid(), &local, 1, &remote, 1, 0);
    if (got != (ssize_t)length) {
        snprintf(out, cap, "{\"ok\":false,\"error\":\"guest range is not fully readable\"}");
        return;
    }
    char hex[MEMORY_READ_MAX * 2 + 1];
    static const char digits[] = "0123456789abcdef";
    for (size_t i = 0; i < length; ++i) {
        hex[i * 2] = digits[data[i] >> 4];
        hex[i * 2 + 1] = digits[data[i] & 15];
    }
    hex[length * 2] = 0;
    snprintf(out, cap, "{\"ok\":true,\"address\":\"0x%" PRIx64 "\",\"length\":%zu,"
             "\"data_hex\":\"%s\",\"consistent_snapshot\":false}", address, length, hex);
}

void hos_debug_present(uint64_t frame) {
    if (!enabled) return;
    const int64_t now = hos_now_ns();
    pthread_mutex_lock(&mu);
    if (state.last_present && now > state.last_present) {
        const double ms = (now - state.last_present) / 1e6;
        state.ms[state.next] = ms;
        if (ms > state.longest_ms) state.longest_ms = ms;
        state.frames_over_50ms += ms > 50;
        state.frames_over_100ms += ms > 100;
        state.next = (state.next + 1) % SAMPLES;
        if (state.n < SAMPLES) state.n++;
    }
    state.last_present = now;
    state.frame = frame;
    pthread_mutex_unlock(&mu);
}

int hos_debug_input(uint64_t *buttons, int32_t stick[4]) {
    if (!enabled) return HOS_DEBUG_LEGACY;
    const int64_t now = hos_now_ns();
    pthread_mutex_lock(&mu);
    const int mode = state.mode;
    /* A cancellation/handoff is consumed by the next neutral poll as well. */
    if (!state.hold_ns) state.applied_sequence = state.sequence;
    if (mode != HOS_DEBUG_PLAYER && state.hold_ns) {
        /* Start a hold on its first Npad poll: loading the scene cannot consume the entire press. */
        if (!state.until) {
            state.until = now + state.hold_ns;
            state.applied_sequence = state.sequence;
        }
        if (now < state.until) {
            *buttons |= state.buttons;
            memcpy(stick, state.sticks, sizeof state.sticks);
        } else state.hold_ns = 0;
    }
    pthread_mutex_unlock(&mu);
    return mode;
}

void hos_debug_observe_input(uint64_t buttons, const int32_t stick[4]) {
    if (!enabled) return;
    pthread_mutex_lock(&mu);
    state.last_poll = hos_now_ns();
    state.input_polls++;
    state.observed_buttons = buttons;
    memcpy(state.observed_sticks, stick, sizeof state.observed_sticks);
    pthread_mutex_unlock(&mu);
}

static const char *mode_name(int mode) {
    return mode == HOS_DEBUG_EXCLUSIVE ? "exclusive" : mode == HOS_DEBUG_SHARED ? "shared" : "player";
}
static int compare_double(const void *a, const void *b) {
    const double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}
static void status(char *out, size_t cap) {
    pthread_mutex_lock(&mu);
    const __typeof__(state) s = state;
    pthread_mutex_unlock(&mu);
    const int64_t now = hos_now_ns();
    char timing[400] = "\"fps\":null,\"frame_ms_mean\":null,\"frame_ms_max\":null,\"frame_ms_p95\":null";
    double samples[SAMPLES], total = 0;
    for (int i = 0; i < s.n; i++) total += (samples[i] = s.ms[i]);
    if (s.n) {
        qsort(samples, (size_t)s.n, sizeof *samples, compare_double);
        snprintf(timing, sizeof timing, "\"fps\":%.3f,\"frame_ms_mean\":%.3f,\"frame_ms_max\":%.3f,\"frame_ms_p95\":%.3f",
                 1000 * s.n / total, total / s.n, samples[s.n - 1], samples[(s.n * 95 + 99) / 100 - 1]);
    }
    char age[64] = "null", poll_age[64] = "null";
    if (s.last_present) snprintf(age, sizeof age, "%.3f", (now - s.last_present) / 1e6);
    if (s.last_poll) snprintf(poll_age, sizeof poll_age, "%.3f", (now - s.last_poll) / 1e6);
    snprintf(out, cap, "{\"ok\":true,\"protocol\":1,\"pid\":%ld,\"presents\":%" PRIu64 ","
             "\"telemetry_source\":\"native present hook\",\"sample_intervals\":%d,%s,\"last_present_age_ms\":%s,"
             "\"longest_frame_ms_total\":%.3f,\"frames_over_50ms\":%" PRIu64 ",\"frames_over_100ms\":%" PRIu64 ","
             "\"control\":\"%s\",\"input_sequence\":%" PRIu64 ",\"applied_sequence\":%" PRIu64 ","
             "\"input_polls\":%" PRIu64 ",\"last_input_age_ms\":%s,\"buttons\":%" PRIu64 ",\"sticks\":[%d,%d,%d,%d]}",
             (long)getpid(), s.frame, s.n, timing, age, s.longest_ms, s.frames_over_50ms, s.frames_over_100ms,
             mode_name(s.mode), s.sequence, s.applied_sequence,
             s.input_polls, poll_age, s.observed_buttons, s.observed_sticks[0], s.observed_sticks[1],
             s.observed_sticks[2], s.observed_sticks[3]);
}

/* Decimal integers only, with no overflow, trailing junk, or silent narrowing. */
static int number(const char *s, int64_t low, int64_t high, int64_t *out) {
    if (!s || !*s) return 0;
    char *end;
    errno = 0;
    const long long value = strtoll(s, &end, 10);
    if (errno || *end || value < low || value > high) return 0;
    *out = (int64_t)value;
    return 1;
}
static int address_number(const char *s, uint64_t *out) {
    if (!s || strncmp(s, "0x", 2) || !s[2]) return 0;
    uint64_t value = 0;
    for (const char *p = s + 2; *p; ++p) {
        const unsigned digit = *p >= '0' && *p <= '9' ? (unsigned)(*p - '0') :
                               *p >= 'a' && *p <= 'f' ? (unsigned)(*p - 'a' + 10) :
                               *p >= 'A' && *p <= 'F' ? (unsigned)(*p - 'A' + 10) : 16;
        if (digit > 15 || value > (UINT64_MAX - digit) / 16) return 0;
        value = value * 16 + digit;
    }
    *out = value;
    return 1;
}
static void command(char *line, char *out, size_t cap) {
    char *args[9], *save = NULL;
    int n = 0;
    for (char *p = strtok_r(line, " \t\r\n", &save); p; p = strtok_r(NULL, " \t\r\n", &save)) {
        if (n == 9) { n = -1; break; }
        args[n++] = p;
    }
    snprintf(out, cap, "{\"ok\":false,\"error\":\"invalid command\"}");
    if (n == 1 && !strcmp(args[0], "status")) { status(out, cap); return; }
    if (n == 2 && !strcmp(args[0], "guest") && !strcmp(args[1], "info")) {
        guest_info(out, cap);
        return;
    }
    if (n == 3 && !strcmp(args[0], "guest") && !strcmp(args[1], "cancel")) {
        int64_t sequence;
        if (!number(args[2], 1, INT64_MAX, &sequence)) return;
        pthread_mutex_lock(&mu);
        int canceled = guest.sequence == (uint64_t)sequence && guest.phase == 1;
        if (canceled) guest.phase = 4;
        pthread_mutex_unlock(&mu);
        snprintf(out, cap, "{\"ok\":true,\"canceled\":%s}", canceled ? "true" : "false");
        return;
    }
    int64_t guest_wait_ms = 2000;
    if ((n == 5 || n == 7) && !strcmp(args[0], "guest") && !strcmp(args[1], "event") &&
        !strcmp(args[n - 2], "wait")) {
        if (!number(args[n - 1], 2000, 10000, &guest_wait_ms)) return;
        n -= 2;
    }
    if (n >= 3 && !strcmp(args[0], "guest") && ((n == 4 && (!strcmp(args[1], "string") || !strcmp(args[1], "bool") || !strcmp(args[1], "int"))) ||
                                                    ((n == 3 || n == 5) && !strcmp(args[1], "event")))) {
        int kind = !strcmp(args[1], "bool") ? 1 : !strcmp(args[1], "int") ? 2 : 0;
        uint64_t key = 0; /* Zero selects the separately configured event helper. */
        char value[64] = {0};
        if (n == 4 && (!address_number(args[2], &key) || !key || key > UINT32_MAX)) return;
        uint64_t actor = 0, actor_id = 0;
        if (n == 5 && (!address_number(args[3], &actor) || !actor || actor >= (1ULL << 39) ||
                      !address_number(args[4], &actor_id) || actor_id > UINT32_MAX)) return;
        if (kind) {
            int64_t scalar;
            if (!number(args[3], kind == 1 ? 0 : INT32_MIN, kind == 1 ? 1 : INT32_MAX, &scalar)) return;
            snprintf(value, sizeof value, "%lld", (long long)scalar);
        } else {
            const char *hex = args[n == 4 ? 3 : 2];
            const size_t length = !strcmp(hex, "-") ? 0 : strlen(hex);
            if (!key && !length) return;
            if (length > 126 || (length & 1)) return;
            for (size_t i = 0; i < length; i += 2) {
                char byte[5] = {'0', 'x', hex[i], hex[i + 1], 0};
                uint64_t v;
                if (!address_number(byte, &v) || !v) return;
                value[i / 2] = (char)v;
            }
        }
        pthread_mutex_lock(&mu);
        if (guest.phase == 1 && hos_now_ns() >= guest.deadline) guest.phase = 4;
        if (!guest.allowed || state.mode != HOS_DEBUG_EXCLUSIVE || guest.phase == 1 || guest.phase == 2) {
            pthread_mutex_unlock(&mu);
            snprintf(out, cap, "{\"ok\":false,\"error\":\"guest dispatch disabled, busy or not exclusive\"}");
            return;
        }
        guest.kind = kind;
        guest.key = (uint32_t)key;
        guest.actor = actor;
        guest.actor_id = (uint32_t)actor_id;
        guest.dispatched_thread[0] = 0;
        guest.result = guest.handoff = 0;
        memcpy(guest.value, value, sizeof value);
        guest.deadline = hos_now_ns() + guest_wait_ms * 1000000LL;
        guest.phase = 1;
        uint64_t sequence = ++guest.sequence;
        pthread_mutex_unlock(&mu);
        snprintf(out, cap, "{\"ok\":true,\"sequence\":%" PRIu64 ",\"phase\":\"pending\"}", sequence);
        return;
    }
    if (n == 2 && !strcmp(args[0], "memory") && !strcmp(args[1], "info")) {
        memory_info(out, cap);
        return;
    }
    if (n == 4 && !strcmp(args[0], "memory") && !strcmp(args[1], "read")) {
        uint64_t address;
        int64_t length;
        if (!address_number(args[2], &address) || !number(args[3], 1, MEMORY_READ_MAX, &length)) return;
        memory_read(address, (size_t)length, out, cap);
        return;
    }
    if (n == 2 && !strcmp(args[0], "cancel")) {
        int64_t seq;
        if (!number(args[1], 1, INT64_MAX, &seq)) return;
        pthread_mutex_lock(&mu);
        const int canceled = state.sequence == (uint64_t)seq;
        if (canceled) {
            state.hold_ns = state.until = 0;
            state.sequence++;
        }
        pthread_mutex_unlock(&mu);
        snprintf(out, cap, "{\"ok\":true,\"canceled\":%s}", canceled ? "true" : "false");
        return;
    }
    if (n == 2 && !strcmp(args[0], "control")) {
        const int mode = !strcmp(args[1], "player") ? HOS_DEBUG_PLAYER :
                         !strcmp(args[1], "exclusive") ? HOS_DEBUG_EXCLUSIVE :
                         !strcmp(args[1], "shared") ? HOS_DEBUG_SHARED : -1;
        if (mode < 0) return;
        pthread_mutex_lock(&mu);
        state.mode = mode;
        if (mode != HOS_DEBUG_EXCLUSIVE && guest.phase == 2) guest.handoff = 1;
        if (mode != HOS_DEBUG_EXCLUSIVE && guest.phase == 1) guest.phase = 4;
        state.hold_ns = state.until = 0;
        state.buttons = 0;
        memset(state.sticks, 0, sizeof state.sticks);
        state.sequence++; /* invalidate any pending client wait */
        pthread_mutex_unlock(&mu);
        snprintf(out, cap, "{\"ok\":true,\"control\":\"%s\",\"injected_input_cleared\":true}", mode_name(mode));
        return;
    }
    if (n == 7 && !strcmp(args[0], "input")) {
        int64_t v[6];
        if (!number(args[1], 0, 65535, &v[0]) || !number(args[6], 1, 60000, &v[5])) return;
        for (int i = 1; i <= 4; i++) if (!number(args[i + 1], -32767, 32767, &v[i])) return;
        pthread_mutex_lock(&mu);
        if (state.mode == HOS_DEBUG_PLAYER) {
            pthread_mutex_unlock(&mu);
            snprintf(out, cap, "{\"ok\":false,\"error\":\"player owns input; select exclusive or shared explicitly\"}");
            return;
        }
        state.buttons = (uint64_t)v[0];
        for (int i = 0; i < 4; i++) state.sticks[i] = (int32_t)v[i + 1];
        state.hold_ns = v[5] * 1000000;
        state.until = 0;
        const uint64_t seq = ++state.sequence;
        pthread_mutex_unlock(&mu);
        snprintf(out, cap, "{\"ok\":true,\"sequence\":%" PRIu64 ",\"duration_ms\":%lld}", seq, (long long)v[5]);
    }
}

static void *serve(void *arg) {
    const int server = (int)(intptr_t)arg;
    for (;;) {
        const int client = accept4(server, NULL, NULL, SOCK_CLOEXEC);
        if (client < 0) { if (errno == EINTR) continue; break; }
        struct ucred peer;
        socklen_t size = sizeof peer;
        const struct timeval timeout = {0, 250000};
        if (getsockopt(client, SOL_SOCKET, SO_PEERCRED, &peer, &size) == 0 && peer.uid == geteuid() &&
            setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof timeout) == 0 &&
            setsockopt(client, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof timeout) == 0) {
            char line[512], reply[2048];
            const ssize_t n = recv(client, line, sizeof line - 1, MSG_TRUNC);
            if (n > 0 && (size_t)n < sizeof line && !memchr(line, 0, (size_t)n)) {
                line[n] = 0;
                command(line, reply, sizeof reply);
            } else snprintf(reply, sizeof reply, "{\"ok\":false,\"error\":\"invalid packet\"}");
            send(client, reply, strlen(reply), MSG_NOSIGNAL);
        }
        close(client);
    }
    close(server);
    return NULL;
}

void hos_debug_init(void) {
    const char *name = getenv("HOS_DEBUG_SOCKET");
    if (!name || !*name) return;
    struct sockaddr_un addr = {.sun_family = AF_UNIX};
    const size_t len = strlen(name);
    if (len >= sizeof addr.sun_path - 1) { hos_log("debug: socket name too long; API disabled"); return; }
    memcpy(addr.sun_path + 1, name, len); /* abstract namespace: no stale file after exit */
    const int fd = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
    if (fd < 0) { hos_log("debug: socket failed (%d); API disabled", errno); return; }
    if (bind(fd, (struct sockaddr *)&addr, (socklen_t)(offsetof(struct sockaddr_un, sun_path) + 1 + len)) || listen(fd, 8)) {
        hos_log("debug: socket bind/listen failed (%d); API disabled", errno);
        close(fd);
        return;
    }
    const char *mode = getenv("HOS_DEBUG_CONTROL");
    const int initial_mode = mode && !strcmp(mode, "exclusive") ? HOS_DEBUG_EXCLUSIVE : HOS_DEBUG_PLAYER;
    state.mode = initial_mode;
    pthread_t thread;
    if (pthread_create(&thread, NULL, serve, (void *)(intptr_t)fd)) { close(fd); return; }
    pthread_detach(thread);
    enabled = 1;
    hos_log("debug: local API @%s, same UID only, control=%s", name, mode_name(initial_mode));
}
#endif
