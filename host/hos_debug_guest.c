/* Opt-in local scene-binding investigation. No game addresses are compiled in.
   The configured setter is invoked on the selected guest thread at an Npad SDK
   boundary, with a separate scratch stack frame and the original Ctx restored. */
#ifdef __linux__
#define _GNU_SOURCE
#include "hos.h"
#include "hos_debug.h"
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/uio.h>
#include <unistd.h>

static pthread_once_t once = PTHREAD_ONCE_INIT;
static uint64_t function, manager_pointer, event_function;
static char required_thread[48];
static int configured;
static uint64_t scalar_functions[4]; /* bool setter/getter, int setter/getter */

/* Local ABI/layout recipe. None of these offsets or functions is title data in
   the host: an image-bound opt-in supplies them and all guest accesses are bounded. */
enum { EC_CTOR, EC_SUBMIT, EC_ASSIGN, EC_DESTROY, EC_MANAGER, EC_SIZE,
       EC_NAME, EC_CAPACITY, EC_LINK0, EC_LINK1, EC_ACTOR_ID, EC_ACTOR_HOLDER,
       EC_HOLDER_ACTOR, EC_HOLDER_ID, EC_COUNT };
static uint64_t ec[EC_COUNT];
static int event_context_ready;
enum { EG_ROOT, EG_ACTOR, EG_COMPONENT, EG_OWNER, EG_OWNER_ACTOR,
       EG_ACTOR_ID, EG_HOLDER, EG_HOLDER_ACTOR, EG_HOLDER_ID,
       EG_FLAG0, EG_MASK0, EG_FLAG1, EG_MASK1, EG_COUNT };
static uint64_t eg[EG_COUNT];
static int event_guard; /* absent, valid, or invalid (-1, fail closed) */
enum { ES_CONTAINER, ES_STATE, ES_VALUE, ES_ALIAS_VALUE, ES_ALIAS_OFFSET, ES_FIXED };
static uint64_t es[ES_FIXED + 16];
static unsigned event_state_count;

static int guest_read(uint64_t address, void *data, size_t size) {
    if (address >= HOS_SPACE_END || size > HOS_SPACE_END - address) return 0;
    struct iovec local = {data, size}, remote = {GP(address), size};
    return process_vm_readv(getpid(), &local, 1, &remote, 1, 0) == (ssize_t)size;
}
static int guest_write(uint64_t address, const void *data, size_t size) {
    if (address >= HOS_SPACE_END || size > HOS_SPACE_END - address) return 0;
    struct iovec local = {(void *)data, size}, remote = {GP(address), size};
    if (process_vm_writev(getpid(), &local, 1, &remote, 1, 0) != (ssize_t)size) return 0;
    HOS_WRITTEN(GP(address), size);
    return 1;
}
static void configure_event_guard(void) {
    const char *p = getenv("HOS_DEBUG_EVENT_GUARD");
    const char *state = getenv("HOS_DEBUG_EVENT_STATE_GUARD");
    event_state_count = 0;
    event_guard = 0;
    if (!p) {
        if (state) event_guard = -1;
        return;
    }
    event_guard = -1;
    for (int i = 0; i < EG_COUNT; ++i) {
        uint64_t value = 0;
        int digits = 0;
        while ((*p >= '0' && *p <= '9') || (*p >= 'a' && *p <= 'f')) {
            if (++digits > 16) return;
            value = (value << 4) | (uint64_t)(*p <= '9' ? *p - '0' : *p - 'a' + 10);
            p++;
        }
        if (!digits || *p != (i + 1 == EG_COUNT ? 0 : ':')) return;
        eg[i] = value;
        if (*p) p++;
    }
    if (eg[EG_ROOT] < hos_image_base || eg[EG_ROOT] > hos_image_end - 8 || (eg[EG_ROOT] & 7)) return;
    for (int i = EG_ACTOR; i < EG_COUNT; ++i)
        if (eg[i] > 4096) return;
    if (!eg[EG_MASK0] || eg[EG_MASK0] > 255 || !eg[EG_MASK1] || eg[EG_MASK1] > 255) return;
    if (state) {
        unsigned count = 0;
        for (;;) {
            uint64_t value = 0;
            int digits = 0;
            while ((*state >= '0' && *state <= '9') || (*state >= 'a' && *state <= 'f')) {
                if (++digits > 8) return;
                value = (value << 4) | (uint64_t)(*state <= '9' ? *state - '0' : *state - 'a' + 10);
                state++;
            }
            if (!digits || (*state && *state != ':') || count == ES_FIXED + 16) return;
            if (count < ES_FIXED && count != ES_ALIAS_VALUE && value > 4096) return;
            es[count++] = value;
            if (!*state) break;
            state++;
        }
        if (count <= ES_FIXED) return;
        event_state_count = count - ES_FIXED;
    }
    event_guard = 1;
}

static int guard_pointer(uint64_t base, uint64_t offset, uint64_t *value) {
    return base && base < HOS_SPACE_END - 8192 &&
           guest_read(base + offset, value, 8) && *value && *value < HOS_SPACE_END - 8192;
}

/* Optional enum state, with one alias selecting an alternate value field.
   A null state is idle. Changed samples defer; malformed pointers fail closed. */
static int event_state_readiness(uint64_t component) {
    if (!event_state_count) return 1;
    uint64_t container, state, check;
    uint32_t primary = 0, value = 0, confirm;
    if (!guard_pointer(component, es[ES_CONTAINER], &container) ||
        !guest_read(container + es[ES_STATE], &state, 8) || state >= HOS_SPACE_END - 8192) return 0;
    if (state) {
        if (!guest_read(state + es[ES_VALUE], &primary, 4)) return 0;
        value = primary;
        if (primary == es[ES_ALIAS_VALUE] && !guest_read(state + es[ES_ALIAS_OFFSET], &value, 4)) return 0;
    }
    if (!guard_pointer(component, es[ES_CONTAINER], &check)) return 0;
    if (check != container) return HOS_DEBUG_DEFER;
    if (!guest_read(container + es[ES_STATE], &check, 8)) return 0;
    if (check != state) return HOS_DEBUG_DEFER;
    if (!state) return 1;
    if (!guest_read(state + es[ES_VALUE], &confirm, 4)) return 0;
    if (confirm != primary) return HOS_DEBUG_DEFER;
    if (primary == es[ES_ALIAS_VALUE]) {
        if (!guest_read(state + es[ES_ALIAS_OFFSET], &confirm, 4)) return 0;
        if (confirm != value) return HOS_DEBUG_DEFER;
    }
    for (unsigned i = 0; i < event_state_count; ++i)
        if (value == es[ES_FIXED + i]) return HOS_DEBUG_DEFER;
    return 1;
}

/* Read-only and on the selected guest worker, before request construction. Never
   use the event helper itself as a probe: even a refused helper may change state. */
static int event_readiness(void) {
    if (event_guard < 0) return 0;
    uint64_t root, actor, component, owner, holder, back, check;
    uint32_t identity, holder_id, confirm_id;
    unsigned char first, second;
    if (!guard_pointer(eg[EG_ROOT], 0, &root) ||
        !guard_pointer(root, eg[EG_ACTOR], &actor) ||
        !guard_pointer(actor, eg[EG_COMPONENT], &component) ||
        !guard_pointer(component, eg[EG_OWNER], &owner) ||
        !guard_pointer(owner, eg[EG_OWNER_ACTOR], &back) || back != actor ||
        !guard_pointer(actor, eg[EG_HOLDER], &holder) ||
        !guard_pointer(holder, eg[EG_HOLDER_ACTOR], &back) || back != actor ||
        !guest_read(actor + eg[EG_ACTOR_ID], &identity, 4) ||
        !guest_read(holder + eg[EG_HOLDER_ID], &holder_id, 4) || identity != holder_id ||
        !guest_read(owner + eg[EG_FLAG0], &first, 1) ||
        !guest_read(owner + eg[EG_FLAG1], &second, 1)) return 0;
    int readiness = (first & eg[EG_MASK0]) || (second & eg[EG_MASK1]) ?
                    HOS_DEBUG_DEFER : event_state_readiness(component);
    /* Reject torn identity/chain reads rather than reusing a stale component. */
    if (!guard_pointer(eg[EG_ROOT], 0, &check) || check != root ||
        !guard_pointer(root, eg[EG_ACTOR], &check) || check != actor ||
        !guard_pointer(actor, eg[EG_COMPONENT], &check) || check != component ||
        !guard_pointer(component, eg[EG_OWNER], &check) || check != owner ||
        !guard_pointer(owner, eg[EG_OWNER_ACTOR], &check) || check != actor ||
        !guard_pointer(actor, eg[EG_HOLDER], &check) || check != holder ||
        !guard_pointer(holder, eg[EG_HOLDER_ACTOR], &check) || check != actor ||
        !guest_read(actor + eg[EG_ACTOR_ID], &confirm_id, 4) || confirm_id != identity ||
        !guest_read(holder + eg[EG_HOLDER_ID], &confirm_id, 4) || confirm_id != identity) return 0;
    return readiness;
}
static void configure_event_context(void) {
    const char *p = getenv("HOS_DEBUG_EVENT_CONTEXT");
    if (!p) return;
    for (int i = 0; i < EC_COUNT; ++i) {
        uint64_t value = 0;
        int digits = 0;
        while ((*p >= '0' && *p <= '9') || (*p >= 'a' && *p <= 'f')) {
            if (++digits > 16) return;
            value = (value << 4) | (uint64_t)(*p <= '9' ? *p - '0' : *p - 'a' + 10);
            p++;
        }
        if (!digits || *p != (i + 1 == EC_COUNT ? 0 : ':')) return;
        ec[i] = value;
        if (*p) p++;
    }
    for (int i = EC_CTOR; i <= EC_DESTROY; ++i)
        if (ec[i] < hos_image_base || ec[i] >= hos_image_end || (ec[i] & 3)) return;
    if (ec[EC_MANAGER] < hos_image_base || ec[EC_MANAGER] > hos_image_end - 8 || (ec[EC_MANAGER] & 7)) return;
    if (ec[EC_SIZE] < 64 || ec[EC_SIZE] > 16384) return;
    for (int i = EC_NAME; i <= EC_LINK1; ++i)
        if (ec[i] > ec[EC_SIZE] - 24) return;
    for (int i = EC_ACTOR_ID; i < EC_COUNT; ++i)
        if (ec[i] > 4096) return;
    event_context_ready = 1;
}

static int event_actor_call(void *context, const char *value, uint64_t actor, uint32_t actor_id) {
    Ctx *c = context;
    if (!event_context_ready || actor >= HOS_SPACE_END - 8192) return 0;
    uint64_t holder, actual_actor, manager;
    uint32_t actual_id, holder_id;
    if (!guest_read(actor + ec[EC_ACTOR_ID], &actual_id, 4) || actual_id != actor_id ||
        !guest_read(actor + ec[EC_ACTOR_HOLDER], &holder, 8) || !holder || holder >= HOS_SPACE_END - 8192 ||
        !guest_read(holder + ec[EC_HOLDER_ACTOR], &actual_actor, 8) || actual_actor != actor ||
        !guest_read(holder + ec[EC_HOLDER_ID], &holder_id, 4) || holder_id != actor_id ||
        !guest_read(ec[EC_MANAGER], &manager, 8) || !manager || manager >= HOS_SPACE_END) return 0;
    A64Fn ctor = a64_lookup(ec[EC_CTOR]), submit = a64_lookup(ec[EC_SUBMIT]);
    A64Fn assign = a64_lookup(ec[EC_ASSIGN]), destroy = a64_lookup(ec[EC_DESTROY]);
    if (!ctor || !submit || !assign || !destroy) return 0;
    uint64_t size = (ec[EC_SIZE] + 127) & ~15ULL;
    if (c->x[31] < size + 256 || c->x[31] >= HOS_SPACE_END || (c->x[31] & 15)) return 0;
    Ctx saved = *c;
    uint64_t scratch = c->x[31] - size, request = scratch + 64;
    unsigned char zero[16384] = {0};
    if (!guest_write(request, zero, ec[EC_SIZE])) return 0;
    c->x[31] = scratch;
    c->x[0] = request;
    ctor(c);
    int accepted = 0;
    uint64_t name;
    uint32_t capacity;
    size_t length = strlen(value) + 1;
    if (!guest_read(request + ec[EC_NAME], &name, 8) ||
        !guest_read(request + ec[EC_CAPACITY], &capacity, 4) || capacity < length ||
        name < request || name >= request + ec[EC_SIZE] || length > request + ec[EC_SIZE] - name ||
        !guest_write(name, value, length)) goto cleanup;
    /* Original ActorLink assignment owns reference tracking. Never memcpy a live
       link or retain a raw caller-supplied actor pointer across engine frames. */
    c->x[0] = request + ec[EC_LINK0];
    c->x[1] = actor;
    c->x[2] = 0;
    assign(c);
    c->x[0] = manager;
    c->x[1] = request;
    submit(c);
    accepted = (c->x[0] & 1) ? 1 : HOS_DEBUG_EVENT_REJECTED;
cleanup:
    c->x[0] = request + ec[EC_LINK1];
    destroy(c);
    c->x[0] = request + ec[EC_LINK0];
    destroy(c);
    *c = saved;
    return accepted;
}

static void configure(void) {
    const char *setting = getenv("HOS_DEBUG_SCENE_CALL");
    char build[41], extra;
    unsigned long long f, m;
    if (!setting || sscanf(setting, "%40[0-9a-f]:%llx:%llx:%47s%c", build, &f, &m, required_thread, &extra) != 4)
        return;
    if (strcmp(build, hos_main_build_id) || f < hos_image_base || f >= hos_image_end ||
        (f & 3) || m < hos_image_base || m > hos_image_end - 8 || (m & 7)) return;
    function = f;
    manager_pointer = m;
    configured = 1;
    configure_event_guard();
    configure_event_context();
    setting = getenv("HOS_DEBUG_SCALAR_CALLS");
    unsigned long long scalar[4];
    if (setting && sscanf(setting, "%llx:%llx:%llx:%llx%c", &scalar[0], &scalar[1], &scalar[2], &scalar[3], &extra) == 4) {
        int valid = 1;
        for (int i = 0; i < 4; ++i)
            if (scalar[i] < hos_image_base || scalar[i] >= hos_image_end || (scalar[i] & 3)) valid = 0;
        if (valid) for (int i = 0; i < 4; ++i) scalar_functions[i] = scalar[i];
    }
    setting = getenv("HOS_DEBUG_SCENE_EVENT");
    if (setting && sscanf(setting, "%llx%c", &f, &extra) == 1 &&
        f >= hos_image_base && f < hos_image_end && !(f & 3)) event_function = f;
}

/* Validate the key through the original getter, then enqueue the original setter.
   Writes may apply on a later engine frame; the client must verify readback. */
static int scalar_call(void *context, int kind, uint32_t key, const char *value) {
    if ((kind != 1 && kind != 2) || !key) return 0;
    char *end;
    long long requested = strtoll(value, &end, 10);
    if (!*value || *end || requested < (kind == 1 ? 0 : INT32_MIN) || requested > (kind == 1 ? 1 : INT32_MAX)) return 0;
    if (!scalar_functions[(kind - 1) * 2] || !scalar_functions[(kind - 1) * 2 + 1]) return 0;
    A64Fn setter = a64_lookup(scalar_functions[(kind - 1) * 2]);
    A64Fn getter = a64_lookup(scalar_functions[(kind - 1) * 2 + 1]);
    Ctx *c = context;
    uint64_t manager;
    if (!setter || !getter || !guest_read(manager_pointer, &manager, 8) || !manager || manager >= HOS_SPACE_END ||
        c->x[31] < 256 || c->x[31] >= HOS_SPACE_END || (c->x[31] & 15)) return 0;
    Ctx saved = *c;
    uint64_t scratch = c->x[31] - 128;
    int32_t observed = 0;
    if (!guest_write(scratch + 64, &observed, 4)) return 0;
    /* Resolve/read first: unknown keys must not cause writes. */
    c->x[31] = scratch; c->x[0] = manager; c->x[1] = scratch + 64; c->x[2] = key;
    getter(c);
    int accepted = 0;
    if (!(c->x[0] & 1)) goto done;
    *c = saved; c->x[31] = scratch; c->x[0] = manager; c->x[1] = (uint32_t)requested; c->x[2] = key;
    setter(c);
    accepted = 1;
done:
    *c = saved;
    return accepted;
}

static int string_call(void *context, int kind, uint32_t key, const char *value, uint64_t actor, uint32_t actor_id) {
    if (kind) return !actor && !actor_id && scalar_call(context, kind, key, value);
    if (!key && event_guard) {
        int readiness = event_readiness();
        if (readiness != 1) return readiness;
    }
    if (actor) return key ? 0 : event_actor_call(context, value, actor, actor_id);
    Ctx *c = context;
    Ctx saved = *c;
    uint64_t manager = 0;
    struct iovec local = {&manager, sizeof manager}, remote = {GP(manager_pointer), sizeof manager};
    if (c->x[31] < 256 || c->x[31] >= HOS_SPACE_END || (c->x[31] & 15)) return 0;
    if (key && (process_vm_readv(getpid(), &local, 1, &remote, 1, 0) != sizeof manager ||
        !manager || manager >= HOS_SPACE_END)) return 0;
    if (!key && !event_function) return 0;
    A64Fn target = a64_lookup(key ? function : event_function);
    if (!target) return 0;
    /* No guest values above the original SP are touched. The callee grows down
       from scratch; string/ref storage is above its SP. The setter copies it. */
    uint64_t scratch = c->x[31] - 128;
    unsigned char data[96] = {0};
    uint64_t text = scratch + 16;
    memcpy(data, &text, sizeof text);
    memcpy(data + 16, value, strlen(value) + 1);
    local = (struct iovec){data, sizeof data};
    remote = (struct iovec){GP(scratch), sizeof data};
    if (process_vm_writev(getpid(), &local, 1, &remote, 1, 0) != sizeof data) return 0;
    HOS_WRITTEN(GP(scratch), sizeof data);
    c->x[31] = scratch;
    c->x[0] = manager;
    c->x[1] = scratch;
    c->x[2] = key;
    if (!key) {
        c->x[0] = scratch;
        c->x[1] = scratch + 80; /* Zero position; helper owns request construction/destruction. */
        c->vreg[0][0] = c->vreg[0][1] = 0;
    }
    target(c);
    int accepted = (key || (c->x[0] & 1)) ? 1 : HOS_DEBUG_EVENT_REJECTED;
    *c = saved;
    return accepted;
}

void hos_debug_scene_poll(Ctx *c) {
    if (!getenv("HOS_DEBUG_SOCKET")) return;
    pthread_once(&once, configure);
    HosThread *thread = hos_self();
    const char *name = thread ? hos_thread_name(thread) : "";
    hos_debug_guest_poll(c, name, c->x[30], configured && !strcmp(name, required_thread), string_call);
}
#endif
