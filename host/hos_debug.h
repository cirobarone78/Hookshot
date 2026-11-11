/* Optional local diagnostics. Linux uses a same-user abstract Unix socket; other targets keep their normal path. */
#ifndef HOS_DEBUG_H
#define HOS_DEBUG_H
#include <stdint.h>

enum { HOS_DEBUG_LEGACY = -1, HOS_DEBUG_PLAYER, HOS_DEBUG_EXCLUSIVE, HOS_DEBUG_SHARED };
/* Callback: positive = dispatched, zero = adapter rejected, -1 = event helper
   returned false. DEFER is permitted only before invoking a guest operation or
   changing guest state; the original deadline still applies. A rejected operation
   must never return DEFER. kind: 0 string/event, 1 bool, 2 signed 32-bit integer. */
enum { HOS_DEBUG_EVENT_REJECTED = -1, HOS_DEBUG_DEFER = -2 };
typedef int (*HosDebugStringCall)(void *context, int kind, uint32_t key, const char *value, uint64_t actor, uint32_t actor_id);
#ifdef __linux__
void hos_debug_guest_poll(void *context, const char *thread, uint64_t caller, int allowed, HosDebugStringCall call);
void hos_debug_init(void);
void hos_debug_memory_window(void *base, uint64_t size, uint64_t image_base, uint64_t image_end);
void hos_debug_present(uint64_t frame);
int hos_debug_input(uint64_t *buttons, int32_t stick[4]);
void hos_debug_observe_input(uint64_t buttons, const int32_t stick[4]);
#else
static inline void hos_debug_init(void) {}
static inline void hos_debug_memory_window(void *base, uint64_t size, uint64_t image_base, uint64_t image_end) {
    (void)base; (void)size; (void)image_base; (void)image_end;
}
static inline void hos_debug_present(uint64_t frame) { (void)frame; }
static inline int hos_debug_input(uint64_t *buttons, int32_t stick[4]) {
    (void)buttons; (void)stick; return HOS_DEBUG_LEGACY;
}
static inline void hos_debug_observe_input(uint64_t buttons, const int32_t stick[4]) {
    (void)buttons; (void)stick;
}
#endif
#endif
