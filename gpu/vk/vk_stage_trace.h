#pragma once
// Opt-in diagnostic wall/CPU intervals. Adjacent stages are exclusive within one
// operation; concurrent operations must not be added as frame-critical-path time.
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <optional>
#include <thread>
#include <functional>
#include <ctime>

namespace mkwvk {
#ifndef MKWVK_TRACE_WALL
inline int64_t trace_wall_ns() {
#ifdef _WIN32
    LARGE_INTEGER t, f;
    QueryPerformanceCounter(&t); QueryPerformanceFrequency(&f);
    return int64_t((long double)t.QuadPart * 1000000000 / f.QuadPart);
#else
    timespec t{}; clock_gettime(CLOCK_MONOTONIC, &t);
    return int64_t(t.tv_sec) * 1000000000 + t.tv_nsec;
#endif
}
#define MKWVK_TRACE_WALL() trace_wall_ns()
#endif
#ifndef MKWVK_TRACE_CPU
inline int64_t trace_cpu_ns() {
#ifdef _WIN32
    FILETIME created, exited, kernel, user;
    if (!GetThreadTimes(GetCurrentThread(), &created, &exited, &kernel, &user)) return -1;
    return int64_t((uint64_t(kernel.dwHighDateTime) << 32 | kernel.dwLowDateTime) +
                   (uint64_t(user.dwHighDateTime) << 32 | user.dwLowDateTime)) * 100;
#else
    timespec t{};
    if (clock_gettime(CLOCK_THREAD_CPUTIME_ID, &t)) return -1;
    return int64_t(t.tv_sec) * 1000000000 + t.tv_nsec;
#endif
}
#define MKWVK_TRACE_CPU() trace_cpu_ns()
#endif
struct StageTraceSink {
    std::mutex mu;
    FILE* file = nullptr;
    uint64_t rows = 0, row_limit = 1000000;
    int64_t flushed = 0;
    char buffer[65536];
    StageTraceSink() {
        const char* path = std::getenv("RX_VK_STAGE_TRACE");
        if (!path || !*path) return;
        if (const char* limit = std::getenv("RX_VK_STAGE_TRACE_ROWS")) {
            char* end = nullptr;
            const auto n = std::strtoull(limit, &end, 10);
            if (end != limit && !*end && n > 0 && n <= 10000000) row_limit = n;
        }
        file = std::fopen(path, "w");
        if (!file) { std::fprintf(stderr, "vk: cannot open stage trace %s\n", path); return; }
        std::setvbuf(file, buffer, _IOFBF, sizeof buffer);
        std::fputs("operation,submission,thread,stage,start_ns,end_ns,wall_ns,cpu_ns,dirty_pages,copied_pages,late_pages,source_memory_flags,trace_row_limit\n", file);
    }
    ~StageTraceSink() { if (file) std::fclose(file); }
};
inline StageTraceSink& stage_trace_sink() { static StageTraceSink sink; return sink; }
struct StageTrace {
    struct Row { const char* name; int64_t start, end, cpu; };
    StageTraceSink& sink;
    const char* operation;
    uint64_t submission, dirty, copied, late;
    uint32_t memory_flags = 0;
    std::array<Row, 16> rows{};
    size_t count = 0;
    int64_t wall = 0, cpu = 0;
    bool active;
    bool finished = false;
    int64_t minimum_wall_ns = 0;
    StageTrace(const char* op, uint64_t id, uint64_t d = 0, uint64_t c = 0, uint64_t l = 0)
        : sink(stage_trace_sink()), operation(op), submission(id), dirty(d), copied(c), late(l), active(sink.file != nullptr) {
        if (active) { wall = MKWVK_TRACE_WALL(); cpu = MKWVK_TRACE_CPU(); }
    }
    void mark(const char* name) {
        if (!active || finished || count == rows.size()) return;
        const int64_t next = MKWVK_TRACE_WALL(), next_cpu = MKWVK_TRACE_CPU();
        rows[count++] = {name, wall, next, cpu >= 0 && next_cpu >= cpu ? next_cpu - cpu : -1};
        wall = next; cpu = next_cpu;
    }
    void finish() {
        if (finished) return;
        mark("tail");
        finished = true;
    }
    ~StageTrace() {
        if (!active) return;
        finish();
        if (minimum_wall_ns > 0 && (!count || rows[count-1].end - rows[0].start < minimum_wall_ns)) return;
        // Called after the instrumented operation's locks have been released.
        std::lock_guard lock(sink.mu);
        const auto tid = std::hash<std::thread::id>{}(std::this_thread::get_id());
        for (size_t i = 0; i < count && sink.rows < sink.row_limit; ++i, ++sink.rows) {
            const auto& r = rows[i];
            std::fprintf(sink.file, "%s,%llu,%llu,%s,%lld,%lld,%lld,%lld,%llu,%llu,%llu,%u,%llu\n",
                operation, (unsigned long long)submission, (unsigned long long)tid, r.name,
                (long long)r.start, (long long)r.end, (long long)(r.end-r.start), (long long)r.cpu,
                (unsigned long long)dirty, (unsigned long long)copied, (unsigned long long)late, memory_flags, (unsigned long long)sink.row_limit);
        }
        if (wall - sink.flushed >= 1000000000) { std::fflush(sink.file); sink.flushed = wall; }
    }
};
// Fine-grained hot-path diagnostics are separately opt-in. Only complete slow
// operations are emitted; absent rows do not mean the operation did not run.
struct SlowStageTrace {
    std::optional<StageTrace> trace;
    explicit SlowStageTrace(const char* operation) {
        static const int64_t minimum = [] {
            const char* value = std::getenv("RX_VK_SLOW_STAGE_US");
            if (!value) return int64_t(0);
            char* end = nullptr;
            const auto us = std::strtoll(value, &end, 10);
            return end != value && !*end && us > 0 && us <= 10000000 ? int64_t(us) * 1000 : int64_t(0);
        }();
        if (minimum && stage_trace_sink().file) {
            trace.emplace(operation, 0);
            trace->minimum_wall_ns = minimum;
        }
    }
    void mark(const char* name) { if (trace) trace->mark(name); }
};
} // namespace mkwvk
