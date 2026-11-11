"""Exercise the production guest-call adapter with an authored context and callee."""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]

RUN_ALL_SKIP = {'windows': 'Linux runtime API and Unix session isolation'}

ROOT = Path(__file__).resolve().parents[1]
STUB = r'''
#include <stdint.h>
#include <string.h>
#include <assert.h>
typedef struct { uint64_t x[32], vreg[32][2], extra[80]; } Ctx;
typedef void (*A64Fn)(Ctx *);
typedef struct { const char *name; } HosThread;
static unsigned char memory[65536];
static const uint64_t hos_image_base = 0x100, hos_image_end = 0x800;
static const char hos_main_build_id[] = "1111111111111111111111111111111111111111";
#define GP(p) (memory + (p))
#define HOS_SPACE_END 65536ULL
#define HOS_WRITTEN(p,n) ((void)(p), (void)(n))
static HosThread thread = {"main"};
static HosThread *hos_self(void) { return &thread; }
static const char *hos_thread_name(HosThread *t) { return t->name; }
#include <sys/uio.h>
#include <unistd.h>
static uint64_t change_after_read, replacement_value;
static size_t replacement_size;
static ssize_t fixture_readv(pid_t pid, const struct iovec *local, unsigned long lc,
                            const struct iovec *remote, unsigned long rc, unsigned long flags) {
    ssize_t result = process_vm_readv(pid, local, lc, remote, rc, flags);
    if (change_after_read && rc == 1 && remote[0].iov_base == GP(change_after_read)) {
        memcpy(GP(change_after_read), &replacement_value, replacement_size);
        change_after_read = 0;
    }
    return result;
}
#define process_vm_readv fixture_readv
static int calls, observed_allowed;
static void target(Ctx *c) {
    uint64_t p;
    assert(c->x[0] == 1024 && c->x[2] == 17);
    assert(c->x[31] == 3072 - 128 && c->x[1] == c->x[31]);
    memcpy(&p, GP(c->x[1]), 8);
    assert(!strcmp((char *)GP(p), "fixture"));
    calls++;
    memset(c, 0xa5, sizeof *c); /* All registers/flags/TLS-like fields must be restored. */
}
static int event_result = 1;
static void event_target(Ctx *c) {
    uint64_t p;
    memcpy(&p, GP(c->x[0]), 8);
    assert(!strcmp((char *)GP(p), "fixture"));
    assert(c->x[1] == c->x[31] + 80);
    for (int i = 0; i < 12; ++i) assert(memory[c->x[1] + i] == 0);
    assert(c->vreg[0][0] == 0 && c->vreg[0][1] == 0);
    calls++;
    memset(c, 0xa5, sizeof *c);
    c->x[0] = event_result;
}
static uint64_t authored_request;
static int destroys;
static void request_ctor(Ctx *c) {
    authored_request = c->x[0];
    uint64_t name = authored_request + 64;
    uint32_t capacity = 64;
    memcpy(GP(authored_request), &name, 8);
    memcpy(GP(authored_request + 8), &capacity, 4);
}
static void link_assign(Ctx *c) {
    assert(c->x[0] == authored_request + 160 && c->x[1] == 2048 && c->x[2] == 0);
    memcpy(GP(c->x[0]), &c->x[1], 8);
}
static void request_submit(Ctx *c) {
    uint64_t actor;
    assert(c->x[0] == 1024 && c->x[1] == authored_request);
    memcpy(&actor, GP(authored_request + 160), 8);
    assert(actor == 2048);
    assert(!strcmp((char*)GP(authored_request + 64), "fixture"));
    calls++;
    c->x[0] = event_result;
}
static void link_destroy(Ctx *c) {
    assert(c->x[0] == authored_request + (destroys % 2 ? 160 : 192));
    destroys++;
}
static int32_t scalar_value;
static int scalar_writes, scalar_missing, scalar_ignore;
static void scalar_get(Ctx *c) {
    assert(c->x[0] == 1024 && c->x[2] == 17);
    memcpy(GP(c->x[1]), &scalar_value, 4);
    c->x[0] = !scalar_missing;
}
static void scalar_set(Ctx *c) {
    assert(c->x[0] == 1024 && c->x[2] == 17);
    scalar_writes++;
    if (!scalar_ignore) scalar_value = (int32_t)c->x[1];
}
static A64Fn a64_lookup(uint64_t address) {
    switch (address) {
    case 0x120: return scalar_set;
    case 0x124: return scalar_get;
    case 0x100: return target;
    case 0x108: return event_target;
    case 0x110: return request_ctor;
    case 0x114: return request_submit;
    case 0x118: return link_assign;
    case 0x11c: return link_destroy;
    default: return 0;
    }
}
'''
MAIN = r'''
void hos_debug_guest_poll(void *c, const char *name, uint64_t caller, int allowed, HosDebugStringCall fn) {
    (void)c; (void)name; (void)caller; (void)fn;
    observed_allowed = allowed;
}
int main(void) {
    uint64_t manager = 1024;
    memcpy(GP(0x200), &manager, 8);
    Ctx c, saved;
    memset(&c, 0x37, sizeof c);
    c.x[31] = 3072;
    saved = c;
    setenv("HOS_DEBUG_SCENE_CALL", "1111111111111111111111111111111111111111:100:200:main", 1);
    setenv("HOS_DEBUG_SCALAR_CALLS", "120:124:120:124", 1);
    configure();
    assert(configured);
    assert(string_call(&c, 0, 17, "fixture", 0, 0) == 1 && calls == 1);
    assert(!memcmp(&c, &saved, sizeof c));
    assert(string_call(&c, 1, 17, "1", 0, 0) && scalar_value == 1);
    assert(string_call(&c, 1, 17, "0", 0, 0) && scalar_value == 0);
    assert(string_call(&c, 2, 17, "-2147483648", 0, 0) && scalar_value == INT32_MIN);
    assert(string_call(&c, 2, 17, "2147483647", 0, 0) && scalar_value == INT32_MAX);
    assert(!memcmp(&c, &saved, sizeof c));
    int writes = scalar_writes;
    assert(!string_call(&c, 1, 17, "2", 0, 0));
    assert(!string_call(&c, 2, 17, "2147483648", 0, 0));
    assert(!string_call(&c, 2, 17, "junk", 0, 0));
    assert(!string_call(&c, 2, 17, "1", 2048, 42));
    scalar_missing = 1;
    assert(!string_call(&c, 2, 17, "1", 0, 0));
    assert(scalar_writes == writes);
    scalar_missing = 0; scalar_ignore = 1;
    assert(string_call(&c, 2, 17, "1", 0, 0)); /* Dispatch is not readback. */
    assert(!memcmp(&c, &saved, sizeof c));
    scalar_ignore = 0;
    scalar_functions[0] = 0;
    assert(!string_call(&c, 1, 17, "1", 0, 0));
    scalar_functions[0] = 0x120;
    c.x[31]++;
    assert(!string_call(&c, 0, 17, "fixture", 0, 0) && calls == 1);
    c = saved;
    function = 0x104;
    assert(!string_call(&c, 0, 17, "fixture", 0, 0) && calls == 1);
    function = 0x100;
    manager = 0;
    memcpy(GP(0x200), &manager, 8);
    assert(!string_call(&c, 0, 17, "fixture", 0, 0) && calls == 1);
    assert(!string_call(&c, 0, 0, "fixture", 0, 0) && calls == 1);
    event_function = 0x108;
    assert(string_call(&c, 0, 0, "fixture", 0, 0) && calls == 2);
    assert(!memcmp(&c, &saved, sizeof c));
    event_result = 0;
    assert(string_call(&c, 0, 0, "fixture", 0, 0) == HOS_DEBUG_EVENT_REJECTED && calls == 3);
    assert(!memcmp(&c, &saved, sizeof c));
    manager = 1024;
    memcpy(GP(0x200), &manager, 8);
    uint64_t holder = 2304, actor = 2048;
    uint32_t identity = 42;
    memcpy(GP(actor), &identity, 4);
    memcpy(GP(actor + 8), &holder, 8);
    memcpy(GP(holder), &actor, 8);
    memcpy(GP(holder + 8), &identity, 4);
    setenv("HOS_DEBUG_EVENT_CONTEXT", "110:114:118:11c:200:100:0:8:a0:c0:0:8:0:8", 1);
    configure_event_context();
    assert(event_context_ready);
    event_result = 1;
    assert(string_call(&c, 0, 0, "fixture", actor, identity) && calls == 4 && destroys == 2);
    assert(!memcmp(&c, &saved, sizeof c));
    assert(!string_call(&c, 0, 0, "fixture", actor, identity + 1) && calls == 4);
    event_result = 0;
    assert(string_call(&c, 0, 0, "fixture", actor, identity) == HOS_DEBUG_EVENT_REJECTED && calls == 5 && destroys == 4);
    assert(!memcmp(&c, &saved, sizeof c));
    uint64_t missing = 0;
    memcpy(GP(holder), &missing, 8);
    assert(!string_call(&c, 0, 0, "fixture", actor, identity) && calls == 5);
    /* Read-only readiness guard, with an authored singleton/component chain. */
    uint64_t component = 4096, owner = 8192;
    memcpy(GP(0x208), &manager, 8);
    memcpy(GP(manager), &actor, 8);
    memcpy(GP(actor + 16), &component, 8);
    memcpy(GP(component), &owner, 8);
    memcpy(GP(owner + 24), &actor, 8);
    memcpy(GP(holder), &actor, 8);
    setenv("HOS_DEBUG_EVENT_GUARD", "208:0:10:0:18:0:8:0:8:20:8:21:4", 1);
    configure_event_guard();
    assert(event_guard == 1 && event_readiness() == 1);
    unsigned char before_memory[sizeof memory];
    for (int flag = 0; flag < 2; ++flag) {
        memory[owner + 32 + flag] = flag ? 4 : 8;
        memcpy(before_memory, memory, sizeof memory);
        assert(string_call(&c, 0, 0, "fixture", 0, 0) == HOS_DEBUG_DEFER);
        assert(string_call(&c, 0, 0, "fixture", actor, identity) == HOS_DEBUG_DEFER);
        assert(calls == 5 && !memcmp(&c, &saved, sizeof c));
        assert(!memcmp(memory, before_memory, sizeof memory));
        memory[owner + 32 + flag] = 0;
    }
    memory[owner + 32] = 1; /* Unrelated bits do not block. */
    assert(event_readiness() == 1);
    memcpy(GP(owner + 24), &missing, 8);
    assert(event_readiness() == 0);
    memcpy(GP(owner + 24), &actor, 8);
    uint32_t changed_id = identity + 1;
    memcpy(GP(holder + 8), &changed_id, 4);
    assert(event_readiness() == 0);
    memcpy(GP(holder + 8), &identity, 4);
    uint64_t bad_pointer = UINT64_MAX;
    memcpy(GP(component), &bad_pointer, 8);
    assert(event_readiness() == 0);
    memcpy(GP(component), &owner, 8);
    uint64_t state_container = 12288, active_state = 16384;
    uint32_t state_value = 7, alias = 99, allowed_state = 9;
    memcpy(GP(component + 32), &state_container, 8);
    memcpy(GP(state_container + 16), &active_state, 8);
    memcpy(GP(active_state + 4), &state_value, 4);
    setenv("HOS_DEBUG_EVENT_STATE_GUARD", "20:10:4:63:8:7:8", 1);
    configure_event_guard();
    assert(event_guard == 1 && event_state_count == 2);
    memcpy(before_memory, memory, sizeof memory);
    assert(string_call(&c, 0, 0, "fixture", 0, 0) == HOS_DEBUG_DEFER && calls == 5);
    assert(string_call(&c, 0, 0, "fixture", actor, identity) == HOS_DEBUG_DEFER && calls == 5);
    assert(!memcmp(memory, before_memory, sizeof memory) && !memcmp(&c, &saved, sizeof c));
    memcpy(GP(active_state + 4), &alias, 4);
    memcpy(GP(active_state + 8), &state_value, 4);
    assert(event_readiness() == HOS_DEBUG_DEFER);
    memcpy(GP(active_state + 8), &allowed_state, 4);
    assert(event_readiness() == 1);
    memcpy(GP(active_state + 4), &allowed_state, 4);
    memcpy(GP(active_state + 8), &state_value, 4);
    assert(event_readiness() == 1); /* Alternate field only applies to the alias. */
    memcpy(GP(state_container + 16), &missing, 8);
    assert(event_readiness() == 1); /* Null current state is idle. */
    memcpy(GP(state_container + 16), &bad_pointer, 8);
    assert(event_readiness() == 0);
    memcpy(GP(state_container + 16), &active_state, 8);
    change_after_read = state_container + 16;
    replacement_value = 0;
    replacement_size = 8;
    assert(event_readiness() == HOS_DEBUG_DEFER && !change_after_read);
    change_after_read = state_container + 16;
    replacement_value = active_state;
    assert(event_readiness() == HOS_DEBUG_DEFER && !change_after_read);
    change_after_read = active_state + 4;
    replacement_value = 10; /* Even allowed-to-allowed changes must defer. */
    replacement_size = 4;
    assert(event_readiness() == HOS_DEBUG_DEFER && !change_after_read);
    memcpy(GP(active_state + 4), &alias, 4);
    memcpy(GP(active_state + 8), &allowed_state, 4);
    change_after_read = active_state + 8;
    assert(event_readiness() == HOS_DEBUG_DEFER && !change_after_read);
    assert(calls == 5 && !memcmp(&c, &saved, sizeof c));
    const char *invalid_states[] = {
        "", "20:10:4:63:8", "20:10:4:63:8:7:", "1001:10:4:63:8:7",
        "20:10:4:100000000:8:7", "20:10:4:63:8:100000000",
        "20:10:4:63:8:0:1:2:3:4:5:6:7:8:9:a:b:c:d:e:f:10"
    };
    for (unsigned i = 0; i < sizeof invalid_states / sizeof *invalid_states; ++i) {
        setenv("HOS_DEBUG_EVENT_STATE_GUARD", invalid_states[i], 1);
        configure_event_guard();
        assert(event_guard == -1 && event_readiness() == 0 && calls == 5);
    }
    unsetenv("HOS_DEBUG_EVENT_STATE_GUARD");
    configure_event_guard();
    assert(event_guard == 1 && event_state_count == 0);
    event_result = 1;
    assert(string_call(&c, 0, 0, "fixture", 0, 0) == 1 && calls == 6);
    setenv("HOS_DEBUG_EVENT_GUARD", "208:0:10:0:18:0:8:0:8:20:8:21:100", 1);
    configure_event_guard();
    assert(event_guard == -1 && string_call(&c, 0, 0, "fixture", 0, 0) == 0 && calls == 6);
    const char *invalid_guards[] = {
        "208:0:10", /* Truncated. */
        "209:0:10:0:18:0:8:0:8:20:8:21:4", /* Unaligned root. */
        "ffffffffffffffff:0:10:0:18:0:8:0:8:20:8:21:4", /* Outside image. */
        "208:0:1001:0:18:0:8:0:8:20:8:21:4", /* Offset exceeds limit. */
        "208:0:10:0:18:0:8:0:8:20:0:21:4", /* Empty mask. */
        "208:0:10:0:18:0:8:0:8:20:8:21:4:0" /* Trailing field. */
    };
    for (unsigned i = 0; i < sizeof invalid_guards / sizeof *invalid_guards; ++i) {
        setenv("HOS_DEBUG_EVENT_GUARD", invalid_guards[i], 1);
        configure_event_guard();
        assert(event_guard == -1);
        assert(string_call(&c, 0, 0, "fixture", 0, 0) == 0 && calls == 6);
    }
    unsetenv("HOS_DEBUG_EVENT_GUARD");
    setenv("HOS_DEBUG_EVENT_STATE_GUARD", "20:10:4:63:8:7", 1);
    configure_event_guard();
    assert(event_guard == -1); /* A state profile cannot stand alone. */
    unsetenv("HOS_DEBUG_EVENT_STATE_GUARD");
    configure_event_guard();
    assert(event_guard == 0);
    configured = 0;
    setenv("HOS_DEBUG_SCENE_CALL", "2222222222222222222222222222222222222222:100:200:main", 1);
    configure();
    assert(!configured);
    setenv("HOS_DEBUG_SCENE_CALL", "1111111111111111111111111111111111111111:100:200:main", 1);
    setenv("HOS_DEBUG_SOCKET", "fixture", 1);
    hos_debug_scene_poll(&c);
    assert(observed_allowed);
    thread.name = "worker";
    hos_debug_scene_poll(&c);
    assert(!observed_allowed);
    return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="cc")
    args = parser.parse_args()
    source = (ROOT / 'host/hos_debug_guest.c').read_text().replace('#include "hos.h"', STUB)
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / 'check.c'
        path.write_text(source + MAIN)
        exe = path.with_suffix('')
        subprocess.run([args.cc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-pthread',
                        '-I' + str(ROOT / 'host'), str(path), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print('PASS: production guest string adapter preserves context, builds guest pointers and gates build/thread')


if __name__ == '__main__':
    main()
