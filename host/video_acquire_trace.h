/* Opt-in movie delivery timing. Wall times, not GPU or display timestamps.
   The caller captures decoder state under its lock and logs after unlocking. */
#ifndef HOS_VIDEO_ACQUIRE_TRACE_H
#define HOS_VIDEO_ACQUIRE_TRACE_H
#include <stdint.h>
typedef struct {
    int enabled;
    int64_t start, locked, ready, selected, end;
    int64_t pts, acquire, decode_ns;
    uintptr_t decoder;
    int slot, queued, skipped, repeated, eos, waits;
} VideoAcquireTrace;

static VideoAcquireTrace video_acquire_trace_begin(int enabled) {
    VideoAcquireTrace t = {0};
    t.enabled = enabled;
    t.slot = -1;
    if (enabled) t.start = hos_now_ns();
    return t;
}

static void video_acquire_trace_end(VideoAcquireTrace *t) {
    if (!t->enabled) return;
    hos_log("video-acquire: start_ns=%lld end_ns=%lld lock_ns=%lld ready_ns=%lld select_ns=%lld "
            "acquire=%lld pts_ns=%lld slot=%d queued=%d skipped=%d repeated=%d eos=%d "
            "decoder=%llu decode_ns=%lld waits=%d",
            (long long)t->start, (long long)t->end, (long long)t->locked,
            (long long)t->ready, (long long)t->selected, (long long)t->acquire,
            (long long)t->pts, t->slot, t->queued, t->skipped, t->repeated, t->eos,
            (unsigned long long)t->decoder, (long long)t->decode_ns, t->waits);
}
#endif
