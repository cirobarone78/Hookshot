/* (hookshot) Allocations of the game's "OptimizeChangeBank" thread tried again when their heap has no room, instead of the
   game going on with a null pointer and crashing a few frames later.

   The OptimizeChangeBank thread rebuilds a model's material block (f_804566e0, "gsys::ModelResource(MatBlock)") and takes
   memory for it from heaps its caller names (its second argument's +8 for the CPU's part, +16 for the GPU's). When a heap is
   full neither allocation is checked:
   - the CPU part, a 0x4198-byte buffer from the heap's tryAlloc (main+0x456904, vtable +0x30), is stored null and the bump
     allocator over it hands out guest address 0: the next store, in f_8044cb30, writes guest 0x8 (issue 1697: "CRASH:
     exception 0xc0000005 (write ..., guest 0x8)", thread OptimizeChangeBanc, lr 0x80456d48, every time a few frames after
     loading that player's save, since 2.0.12);
   - the GPU part, f_80522050 (main+0x456f18), leaves the material block with no memory pool (main+0x457248), and the block
     is written to guest address 0 two calls later (TomShafford/Hookshot's crash at backflip + attack).
   Both are tried again: the GPU memory after a few 2 ms waits (the game frees a block once the GPU is done with it), then
   in each parent heap up to the root that has room, then in the game's default heap; the CPU buffer in each parent heap
   that has room. A block made in a parent heap is freed by sead's free, which finds the heap that holds it. Each failure
   is logged with its heap's name, size and free space.

   The GPU part is ported from TomShafford/Hookshot 55d68e8cd6 and 65c1998222 (GPL-3.0, a Hookshot fork), by TomShafford.

   A sead heap here (vtable 0x84c172c8, the heap class of these): +0x20 its name, +0x28 its memory, +0x30 its size, +0x38 its
   parent, vtable +0x30 tryAlloc(size, alignment), vtable +0x80 its free size (ExpHeap: the free list summed, main+0x834916d0).

   HOS_GPU_ALLOC_RETRY=0: neither is tried again (as shipped).
   HOS_GPU_ALLOC_TEST_FAIL=<n> or <gpu>,<cpu> (a test): the first n allocations of each kind (or that many of the GPU memory
   and of the CPU buffer) are refused by the heap they name, as a full heap would, so the retry runs (with
   HOS_GPU_ALLOC_RETRY=0: the game's crash, as shipped). */
#include "hos.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { HEAP_NAME = 0x20, HEAP_START = 0x28, HEAP_SIZE = 0x30, HEAP_PARENT = 0x38, VT_TRY_ALLOC = 0x30, VT_FREE_SIZE = 0x80 };

static int retry_on(void) {
    static int on = -1;
    if (on < 0) on = !getenv("HOS_GPU_ALLOC_RETRY") || atoi(getenv("HOS_GPU_ALLOC_RETRY")) != 0;
    return on;
}
/* HOS_GPU_ALLOC_TEST_FAIL: 1 while this kind's first n allocations are refused (kind 0 the GPU memory, 1 the CPU buffer) */
static int test_fail(int kind) {
    static long left[2] = {-1, -1};
    if (left[kind] < 0) {   /* ("<n>": both kinds; "<gpu>,<cpu>": each its own) */
        const char *e = getenv("HOS_GPU_ALLOC_TEST_FAIL"), *comma = e ? strchr(e, ',') : NULL;
        left[kind] = !e ? 0 : kind && comma ? atol(comma + 1) : atol(e);
    }
    return __atomic_load_n(&left[kind], __ATOMIC_RELAXED) > 0 && __atomic_sub_fetch(&left[kind], 1, __ATOMIC_RELAXED) >= 0;
}
static int readable(uint64_t a) { return a >= 0x80000000ULL && a < (1ULL << 39) - 0x100; }
static int guest_string(Ctx *c, uint64_t at, char *out, int n) {   /* (a guest C string: 1 if it reads as one) */
    int i = 0, ok = readable(at);
    for (; ok && i < n - 1; i++) {
        const char ch = (char)recomp_load8(c, at + i);
        if (!ch) break;
        if (ch < 32 || ch >= 127) ok = 0;
        out[i] = ch;
    }
    if (!ok || i < 2) i = 0, out[i++] = '?', ok = 0;
    out[i] = 0;
    return ok;
}
/* A guest function called as the game would, every register and flag as before but x0: its result */
static uint64_t guest_call(Ctx *c, uint64_t fn, uint64_t a0, uint64_t a1, uint64_t a2, uint64_t lr) {
    uint64_t x[31];
    const uint8_t n = c->n, z = c->z, cf = c->c, v = c->v;
    memcpy(x, c->x, sizeof x);
    c->x[0] = a0, c->x[1] = a1, c->x[2] = a2, c->x[30] = lr;
    a64_icall(c, fn);
    const uint64_t r = c->x[0];
    memcpy(c->x, x, sizeof x);
    c->n = n, c->z = z, c->c = cf, c->v = v;
    return r;
}
static uint64_t heap_method(Ctx *c, uint64_t heap, unsigned slot) {   /* (0: none) */
    if (!readable(heap)) return 0;
    const uint64_t vt = recomp_load64(c, heap);
    return readable(vt) ? recomp_load64(c, vt + slot) : 0;
}
static uint64_t free_size(Ctx *c, uint64_t heap) {   /* (the heap's own getFreeSize; ~0: unknown) */
    const uint64_t fn = heap_method(c, heap, VT_FREE_SIZE);
    return fn && a64_lookup(fn) ? guest_call(c, fn, heap, 0, 0, c->x[30]) : ~0ULL;
}
static void describe(Ctx *c, uint64_t heap, char *out, int n) {
    char name[48], kb[32];
    if (!readable(heap)) { snprintf(out, n, "heap %#llx", (unsigned long long)heap); return; }
    if (!guest_string(c, recomp_load64(c, heap + HEAP_NAME), name, sizeof name))
        guest_string(c, recomp_load64(c, heap + HEAP_START), name, sizeof name);
    const uint64_t f = free_size(c, heap);
    if (f == ~0ULL) snprintf(kb, sizeof kb, "?");
    else snprintf(kb, sizeof kb, "%llu", (unsigned long long)(f >> 10));
    snprintf(out, n, "heap %#llx \"%s\" (%llu KB, %s KB free)", (unsigned long long)heap, name,
             (unsigned long long)(recomp_load64(c, heap + HEAP_SIZE) >> 10), kb);
}
static int tell(void) {   /* (the first 60 failures logged) */
    static volatile long told;
    return __atomic_fetch_add(&told, 1, __ATOMIC_RELAXED) < 60;
}

/* ---- the GPU memory: f_80522050(x0 the memory block, x1 the request: +0 the count, +8 the heap, +0x20 what it is for; x2
   the size of one). nx2/oot_patches.py renames the game's function f_80522050_game and makes f_80522050 call this ---- */
static int gpu_alloc_in(Ctx *c, void (*game)(Ctx *), uint64_t a0, uint64_t a1, uint64_t a2, uint64_t lr, uint64_t heap,
                        uint64_t in) {
    recomp_store64(c, a1 + 8, in);
    c->x[0] = a0, c->x[1] = a1, c->x[2] = a2, c->x[30] = lr;
    game(c);
    recomp_store64(c, a1 + 8, heap);
    return (int)(c->x[0] & 1);
}
void hos_oot_gpu_alloc(Ctx *c, void (*game)(Ctx *)) {
    const uint64_t a0 = c->x[0], a1 = c->x[1], a2 = c->x[2], lr = c->x[30];
    const int on = retry_on() && readable(a1);
    const int refused = readable(a1) && recomp_load64(c, a1 + 8) && test_fail(0);
    if (refused && !on) {   /* (the failure alone, as a full heap gives it) */
        hos_log("oot: GPU memory refused by HOS_GPU_ALLOC_TEST_FAIL, not tried again (HOS_GPU_ALLOC_RETRY=0) (lr %#llx)",
                (unsigned long long)lr);
        c->x[0] = 0;
        return;
    }
    if (!refused) {
        game(c);
        if (!on || (c->x[0] & 1)) return;
    }
    const uint64_t count = recomp_load64(c, a1), heap = recomp_load64(c, a1 + 8), what = recomp_load64(c, a1 + 0x20);
    char name[64], where[160];
    guest_string(c, what, name, sizeof name);
    describe(c, heap, where, sizeof where);
    const int say = tell();
    if (say)
        hos_log("oot: GPU memory for %s, %#llx bytes from %s, %s (lr %#llx)", name, (unsigned long long)(count * a2), where,
                refused ? "refused by HOS_GPU_ALLOC_TEST_FAIL" : "failed", (unsigned long long)lr);
    int ok = 0, waits = 0;
    for (; !refused && waits < 3 && !ok; waits++) {   /* (frees in flight) */
        hos_sleep_ns(2000000);
        ok = gpu_alloc_in(c, game, a0, a1, a2, lr, heap, heap);
    }
    if (ok) {
        if (say) hos_log("oot: GPU memory: made after %d waits of 2 ms", waits);
        return;
    }
    /* (the heaps it was made in: their parents up to the root, the free left in them after their children) */
    uint64_t h = heap;
    for (int up = 0; up < 8 && readable(h) && !ok; up++) {
        const uint64_t parent = recomp_load64(c, h + HEAP_PARENT);
        if (!readable(parent) || parent == h) break;
        h = parent;
        const uint64_t f = free_size(c, h);
        if (f != ~0ULL && f < count * a2 + 0x2000) continue;
        ok = gpu_alloc_in(c, game, a0, a1, a2, lr, heap, h);
        if (say) {
            describe(c, h, where, sizeof where);
            hos_log("oot: GPU memory: %s in its parent %s", ok ? "made" : "not made either", where);
        }
    }
    if (!ok && heap) {   /* (the game's own default when no heap is named: the thread's heap, or the root) */
        ok = gpu_alloc_in(c, game, a0, a1, a2, lr, heap, 0);
        if (say) hos_log("oot: GPU memory: %s in the game's default heap", ok ? "made" : "not made either");
    }
    if (!ok && say) hos_log("oot: GPU memory: no heap had room: the game goes on without it (and crashes writing to it)");
}

/* ---- the CPU buffer: the heap's tryAlloc at main+0x456904 gave x0 = 0 (or HOS_GPU_ALLOC_TEST_FAIL refused it: nx2/oot_patches.py
   then made no call). Tried in each parent with room; x0 the block, or 0 still ---- */
int hos_oot_heap_refuse(void) { return test_fail(1); }
void hos_oot_heap_retry(Ctx *c, uint64_t heap, uint64_t size, uint64_t align, uint64_t lr) {
    if (!retry_on()) {
        hos_log("oot: model buffer, %#llx bytes from heap %#llx, failed: not tried again (HOS_GPU_ALLOC_RETRY=0) (lr %#llx)",
                (unsigned long long)size, (unsigned long long)heap, (unsigned long long)lr);
        return;
    }
    char where[160];
    const int say = tell();
    describe(c, heap, where, sizeof where);
    if (say) hos_log("oot: model buffer, %#llx bytes from %s, failed (lr %#llx)", (unsigned long long)size, where,
                     (unsigned long long)lr);
    uint64_t h = heap, got = 0;
    for (int up = 0; up < 8 && readable(h) && !got; up++) {
        const uint64_t parent = recomp_load64(c, h + HEAP_PARENT);
        if (!readable(parent) || parent == h) break;
        h = parent;
        const uint64_t f = free_size(c, h), fn = heap_method(c, h, VT_TRY_ALLOC);
        if ((f != ~0ULL && f < size + 0x2000) || !fn || !a64_lookup(fn)) continue;
        got = guest_call(c, fn, h, size, align, lr);
        if (say) {
            describe(c, h, where, sizeof where);
            hos_log("oot: model buffer: %s in its parent %s", got ? "made" : "not made either", where);
        }
    }
    if (!got && say) hos_log("oot: model buffer: no heap had room: the game goes on without it (and crashes writing to it)");
    c->x[0] = got;
}
