/* Real API/server with an authored host clock, presents and Npad polls; no game or desktop. */
#define _GNU_SOURCE
#include "hos_debug.h"
#include <inttypes.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <stdatomic.h>
#include <sys/mman.h>
#include <unistd.h>
#include <pthread.h>
#include <sched.h>
static _Atomic int64_t now = 1000000000;
int64_t hos_now_ns(void) { return atomic_load(&now); }
void hos_log(const char *format, ...) { (void)format; }
static int calls;
static _Atomic int busy, blocked;
static pthread_t probe;
static int guest_call(void *context, int kind, uint32_t key, const char *value, uint64_t actor, uint32_t actor_id) {
    if (kind) return key == 17 && !strcmp(value, "1") && !actor && !actor_id;
    if (actor ? (key || actor != 0x1234 || actor_id != 42) : actor_id != 0) return 0;
    if (!key && !strcmp(value, "reject")) return HOS_DEBUG_EVENT_REJECTED;
    if (context != &calls || (key != 17 && key != 0) || strcmp(value, "fixture")) return 0;
    if (busy == 2) {
        blocked = 1;
        while (busy == 2) sched_yield();
        return HOS_DEBUG_DEFER;
    }
    if (busy) return HOS_DEBUG_DEFER;
    calls++;
    return 1;
}
static void *blocked_poll(void *unused) {
    (void)unused;
    hos_debug_guest_poll(&calls, "fixture-thread", 0x100, 1, guest_call);
    return NULL;
}
int main(void) {
    setbuf(stdout, NULL);
    const size_t page = (size_t)sysconf(_SC_PAGESIZE);
    unsigned char *window = mmap(NULL, page * 3, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (window == MAP_FAILED) return 3;
    for (size_t i = 0; i < page * 3; ++i) window[i] = (unsigned char)i;
    if (mprotect(window + page, page, PROT_NONE)) return 3;
    hos_debug_init();
    puts("ready");
    char line[128];
    uint64_t frame = 0;
    while (fgets(line, sizeof line, stdin)) {
        int64_t ns;
        if (sscanf(line, "advance %" SCNd64, &ns) == 1) {
            atomic_fetch_add(&now, ns);
            puts("ok");
        } else if (!strcmp(line, "guest-block\n")) {
            busy = 2; blocked = 0;
            if (pthread_create(&probe, NULL, blocked_poll, NULL)) return 4;
            while (!blocked) sched_yield();
            puts("ok");
        } else if (!strcmp(line, "guest-unblock\n")) {
            busy = 0;
            pthread_join(probe, NULL);
            printf("%d\n", calls);
        } else if (!strcmp(line, "busy\n") || !strcmp(line, "ready\n")) {
            busy = !strcmp(line, "busy\n");
            puts("ok");
        } else if (!strcmp(line, "guest-poll\n") || !strcmp(line, "guest-other\n")) {
            hos_debug_guest_poll(&calls, "fixture-thread", 0x100, !strcmp(line, "guest-poll\n"), guest_call);
            printf("%d\n", calls);
        } else if (!strcmp(line, "frame\n")) {
            hos_debug_present(++frame);
            puts("ok");
        } else if (!strcmp(line, "poll\n")) {
            uint64_t buttons = 0;
            int32_t stick[4] = {0};
            const int mode = hos_debug_input(&buttons, stick);
            hos_debug_observe_input(buttons, stick);
            printf("{\"mode\":%d,\"buttons\":%" PRIu64 ",\"sticks\":[%d,%d,%d,%d]}\n",
                   mode, buttons, stick[0], stick[1], stick[2], stick[3]);
        } else if (!strcmp(line, "memory-ready\n")) {
            hos_debug_memory_window(window, page * 3, 0x100, 0x800);
            printf("{\"page\":%zu,\"size\":%zu}\n", page, page * 3);
        } else if (!strcmp(line, "memory-change\n")) {
            memset(window, 0xa5, 32);
            puts("ok");
        } else if (!strcmp(line, "memory-unmap\n")) {
            if (munmap(window + page * 2, page)) return 3;
            puts("ok");
        } else return 2;
    }
    munmap(window, page * 3);
    return 0;
}
