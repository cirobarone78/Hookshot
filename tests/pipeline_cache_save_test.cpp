// The actual save function, with authored cache bytes and Vulkan/file API spies. No driver is loaded.
#include <atomic>
#include <chrono>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <limits>
#include <new>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#ifdef _WIN32
#include <windows.h>
#else
constexpr int MOVEFILE_REPLACE_EXISTING = 1;
void Sleep(unsigned ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); }
#endif

// Arm only the allocating thread, after the query/copy API or immediately before thread construction.
// Real std::vector, std::string and std::thread allocations still run; nothing models their failure handling.
thread_local bool fail_next_new = false;
std::atomic<int> allocation_failures{0};
void* operator new(std::size_t n) {
    if (fail_next_new) {
        fail_next_new = false;
        ++allocation_failures;
        throw std::bad_alloc();
    }
    if (void* p = std::malloc(n ? n : 1)) return p;
    throw std::bad_alloc();
}
// Keep the replacement allocator boundary: GCC must not inline free into a caller of operator new.
[[gnu::noinline]] void operator delete(void* p) noexcept { std::free(p); }
void operator delete(void* p, std::size_t) noexcept { ::operator delete(p); }
void* operator new[](std::size_t n) { return ::operator new(n); }
void operator delete[](void* p) noexcept { ::operator delete(p); }
void operator delete[](void* p, std::size_t) noexcept { ::operator delete(p); }

using VkResult = int;
constexpr VkResult VK_SUCCESS = 0, VK_ERROR_UNKNOWN = -13;
struct { int device = 1; } dev;
int pcache = 2;
std::string pcache_path;
std::atomic<int64_t> pcache_built_since_save{32};
std::atomic<std::size_t> pcache_saved_size{0};
bool pcache_no_save = false;   // (RX_VK_PCACHE_LOAD=0: pcache_init; never set here)
// The size the driver gives for the cache's data; a case grows it for pipelines taken in between saves.
std::atomic<std::size_t> cache_size{64};
enum Fault { NONE, VECTOR_ALLOC, VECTOR_LENGTH, TMP_ALLOC, QUERY_FAIL, EMPTY, COPY_FAIL, SHORT_WRITE, BLOCK_COPY, REPLACE_FAIL };
std::atomic<Fault> fault{NONE};
std::atomic<int> queries{0}, copies{0}, writes{0}, replacements{0}, save_errors{0}, start_errors{0};
std::atomic<bool> copy_blocked{false}, allow_copy{false};

#define CHECK(c) do { if (!(c)) { std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #c); return 1; } } while (0)

void logf(const char* fmt, ...) {
    char line[512];
    va_list args;
    va_start(args, fmt);
    std::vsnprintf(line, sizeof line, fmt, args);
    va_end(args);
    std::fprintf(stderr, "%s\n", line);
    if (std::strstr(line, "pipeline cache save failed:")) ++save_errors;
    if (std::strstr(line, "could not start pipeline cache save:")) ++start_errors;
}

// The copy's gate (vk_draw.cpp cache_copy_begin: the copy held apart from pipeline builds on the drivers that need it, vk_vendor.h
// pcache_apart). gate_open false: builds kept it for the save's whole try; a forced save waits, so it always gets it.
// gate_stuck: a build never ends (a compile stuck in the driver): even a forced save gives up, after its bounded wait.
// The fake decides at once what the real gate decides by its deadline: a forced save (kCopyWaitForced) gets the gate unless a
// build is stuck; any other save (one try in play, kCopyWaitStart before it) gets it only while gate_open.
std::atomic<bool> gate_open{true}, gate_held{false}, gate_stuck{false};
std::atomic<int> gate_tries{0}, gate_waits{0}, gate_ends{0}, gate_last_wait{-1};
constexpr int kCopyWaitForced = 30000, kCopyWaitStart = 2000;
bool cache_copy_begin(int wait_ms) {
    const bool wait = wait_ms == kCopyWaitForced;
    gate_last_wait = wait_ms;
    ++(wait ? gate_waits : gate_tries);
    if (gate_stuck || (!wait && !gate_open)) return false;
    if (gate_held.exchange(true)) std::abort();   // (two copies at once)
    return true;
}
void cache_copy_end() {
    if (!gate_held.exchange(false)) std::abort();
    ++gate_ends;
}

VkResult vkGetPipelineCacheData(int device, int cache, std::size_t* n, void* data) {
    if (device != dev.device || cache != pcache) std::abort();
    if (!gate_held) std::abort();   // (every read of the cache's data inside the gate)
    if (!data) {
        ++queries;
        if (fault == QUERY_FAIL) return VK_ERROR_UNKNOWN;
        *n = fault == VECTOR_LENGTH ? (std::numeric_limits<std::size_t>::max)() : fault == EMPTY ? 0 : cache_size.load();
        if (fault == VECTOR_ALLOC) fail_next_new = true;
    } else {
        ++copies;
        if (fault == COPY_FAIL) return VK_ERROR_UNKNOWN;
        if (fault == BLOCK_COPY) {
            copy_blocked = true;
            while (!allow_copy.load()) Sleep(1);
        }
        std::memset(data, 'N', *n);
        if (fault == TMP_ALLOC) fail_next_new = true;
    }
    return VK_SUCCESS;
}

std::size_t save_fwrite(const void* p, std::size_t size, std::size_t n, FILE* f) {
    ++writes;
    if (fault == SHORT_WRITE) return 0;
    return std::fwrite(p, size, n, f);
}
int save_replace(const char* from, const char* to, unsigned flags) {
    if (flags != MOVEFILE_REPLACE_EXISTING || to != pcache_path) std::abort();
    ++replacements;
    if (fault == REPLACE_FAIL) return 0;
#ifdef _WIN32
    return MoveFileExA(from, to, flags);
#else
    return std::rename(from, to) == 0;
#endif
}

// The play generations' part of a save (gpu/vk/vk_draw.cpp, tests/test_pipeline_play_cache.py): at each save, after the
// cache's own part, whatever that did.
std::atomic<int> play_saves{0};
std::atomic<int> play_saves_forced{0};   // (of them, the forced saves: the play files' copy gets the forced wait then)
void play_cache_save(bool forced) { ++play_saves, play_saves_forced += forced; }
std::atomic<bool> in_play{false};
bool play_cache_in_use() { return in_play.load(); }

#define fwrite save_fwrite
#define MoveFileExA save_replace
#include "pipeline_cache_save.inc"
#undef MoveFileExA
#undef fwrite

bool wait_until(const std::atomic<int>& n, int target) {
    const auto end = std::chrono::steady_clock::now() + std::chrono::seconds(3);
    while (n.load() < target && std::chrono::steady_clock::now() < end) Sleep(1);
    return n.load() >= target;
}
bool old_file() {
    FILE* f = std::fopen(pcache_path.c_str(), "rb");
    if (!f) return false;
    char data[4]{};
    const auto n = std::fread(data, 1, sizeof data, f);
    std::fclose(f);
    return n == 3 && std::memcmp(data, "old", 3) == 0;
}
bool new_file() {
    FILE* f = std::fopen(pcache_path.c_str(), "rb");
    if (!f) return false;
    char data[257]{};
    const auto n = std::fread(data, 1, sizeof data, f);
    std::fclose(f);
    if (n != cache_size) return false;
    for (std::size_t i = 0; i < n; ++i) if (data[i] != 'N') return false;
    return true;
}

int run(const std::string& name) {
    if (name == "success") {
        pcache_built_since_save = 31;
        pipeline_cache_save(false);
        CHECK(queries == 0 && old_file());
        pcache_built_since_save = 32;
        pipeline_cache_save(false);
        CHECK(wait_until(copies, 1));
        cache_size = 96;  // Pipelines taken in meanwhile: the forced save has new data to write.
        pipeline_cache_save(true);  // Wait for the worker, then preserve the existing forced-save behavior.
        CHECK(queries == 2 && writes == 2 && replacements == 2 && new_file());
        CHECK(save_errors == 0 && start_errors == 0);
        pcache = 0;
        pipeline_cache_save(true);
        CHECK(queries == 2);
    } else if (name == "force-vector" || name == "async-vector" || name == "force-length" ||
               name == "force-string" || name == "async-string") {
        fault = name == "force-length" ? VECTOR_LENGTH : name.find("string") != std::string::npos ? TMP_ALLOC : VECTOR_ALLOC;
        const bool async = name.starts_with("async");
        pipeline_cache_save(!async);
        CHECK(wait_until(save_errors, 1));
        CHECK(wait_until(play_saves, 1));  // The play part all the same.
        CHECK(old_file() && replacements == 0 && start_errors == 0);
        CHECK(allocation_failures == (fault == VECTOR_LENGTH ? 0 : 1));
        fault = NONE;
        pipeline_cache_save(true);
        CHECK(new_file() && replacements == 1 && queries == 2);  // No stuck busy flag after the failure.
    } else if (name == "thread-start") {
        fail_next_new = true;
        pipeline_cache_save(false);  // The real std::thread's state allocation, before it can run the worker.
        CHECK(!fail_next_new && allocation_failures == 1 && start_errors == 1 && save_errors == 0);
        CHECK(queries == 0 && old_file());
        pipeline_cache_save(true);
        CHECK(new_file() && queries == 1 && replacements == 1);
    } else if (name == "api-results") {
        for (Fault f : {QUERY_FAIL, EMPTY, COPY_FAIL}) {
            fault = f;
            pipeline_cache_save(true);
            CHECK(old_file() && replacements == 0 && save_errors == 0 && start_errors == 0);
        }
        fault = NONE;
        pipeline_cache_save(true);
        CHECK(new_file() && replacements == 1);
    } else if (name == "short-write") {
        fault = SHORT_WRITE;
        pipeline_cache_save(true);
        CHECK(writes == 1 && replacements == 0 && old_file());
        fault = NONE;
        pipeline_cache_save(true);
        CHECK(new_file() && replacements == 1);
    } else if (name == "forced-wait") {
        fault = BLOCK_COPY;
        pipeline_cache_save(false);
        const auto end = std::chrono::steady_clock::now() + std::chrono::seconds(3);
        while (!copy_blocked.load() && std::chrono::steady_clock::now() < end) Sleep(1);
        CHECK(copy_blocked);
        std::atomic<bool> started{false}, finished{false};
        std::thread waiter([&] { started = true; pipeline_cache_save(true); finished = true; });
        while (!started.load()) Sleep(1);
        Sleep(20);
        const bool waited = !finished.load() && queries == 1;
        cache_size = 96;  // Taken in while the first save copied: the waiter has new data to write.
        allow_copy = true;
        waiter.join();
        CHECK(waited && finished && queries == 2 && replacements == 2 && new_file());
    } else if (name == "unchanged") {
        pcache_saved_size = 64;  // As pcache_init leaves it: the driver's size for the data read from the file.
        pipeline_cache_save(true);  // At exit, nothing taken in.
        CHECK(queries == 1 && copies == 0 && writes == 0 && old_file());
        CHECK(play_saves == 1);  // What play made is saved apart, the cache unchanged or not.
        pcache_built_since_save = 32;  // In play: the precompile's pipelines, all found in the cache, still count.
        pipeline_cache_save(false);
        CHECK(wait_until(queries, 2));
        pipeline_cache_save(true);  // After the worker.
        CHECK(queries == 3 && copies == 0 && writes == 0 && replacements == 0 && old_file());
        cache_size = 96;
        for (Fault f : {SHORT_WRITE, REPLACE_FAIL}) {  // Not in place: tried again at the next save.
            fault = f;
            pipeline_cache_save(true);
            CHECK(old_file() && pcache_saved_size == 64);
        }
        fault = NONE;
        pipeline_cache_save(true);
        CHECK(queries == 6 && copies == 3 && writes == 3 && replacements == 2 && new_file() && pcache_saved_size == 96);
        pipeline_cache_save(true);  // Written: nothing new since.
        CHECK(queries == 7 && copies == 3 && writes == 3 && replacements == 2 && new_file());
        cache_size = 80;  // A different size of any kind is data the file lacks.
        pipeline_cache_save(true);
        CHECK(copies == 4 && replacements == 3 && new_file());
        CHECK(save_errors == 0 && start_errors == 0 && play_saves == 8);
    } else if (name == "in-play-try") {
        // In play a save only tries once (no 2 s wait): it would mostly find too little growth to write anyway.
        in_play = true;
        pcache_built_since_save = 32;
        pipeline_cache_save(false);
        CHECK(wait_until(play_saves, 1));
        CHECK(gate_last_wait == 0);
        in_play = false;
        pcache_built_since_save = 32;
        pipeline_cache_save(false);  // Before play: tried for up to 2 s.
        CHECK(wait_until(play_saves, 2));
        CHECK(gate_last_wait == kCopyWaitStart);
        pipeline_cache_save(true);
        CHECK(gate_last_wait == kCopyWaitForced);
        CHECK(play_saves == 3 && play_saves_forced == 1);  // (the play files: forced only with the forced save)
    } else if (name == "in-play") {
        // In play the cache is not written at a save for a little growth: what play makes is in the play files.
        pcache_saved_size = 64;
        cache_size = 96;
        in_play = true;
        pcache_built_since_save = 32;
        pipeline_cache_save(false);
        CHECK(wait_until(play_saves, 1));
        CHECK(copies == 0 && writes == 0 && replacements == 0);
        pipeline_cache_save(true);  // Waits for the worker; a forced save (Restart now) writes it once.
        CHECK(play_saves == 2 && copies == 1 && writes == 1 && replacements == 1 && new_file() && pcache_saved_size == 96);
        // Grown past the threshold (64 MB), it is written in play too.
        cache_size = 96 + (64u << 20);
        pcache_built_since_save = 32;
        pipeline_cache_save(false);
        CHECK(wait_until(play_saves, 3));
        pipeline_cache_save(true);
        CHECK(copies == 2 && writes == 2 && replacements == 2 && pcache_saved_size == 96 + (64u << 20));
        CHECK(save_errors == 0 && start_errors == 0);
    } else if (name == "put-off") {
        gate_open = false;   // Pipelines were being built into the cache for the whole try.
        pcache_built_since_save = 32;
        pipeline_cache_save(false);
        CHECK(wait_until(play_saves, 1));  // The play part all the same: its generation has no builds.
        CHECK(gate_tries == 1 && gate_ends == 0 && queries == 0 && copies == 0 && writes == 0 && old_file());
        CHECK(save_errors == 0 && start_errors == 0);
        pipeline_cache_save(true);  // At exit: it waits for the builds, then copies.
        CHECK(gate_waits == 1 && gate_ends == 1 && !gate_held && new_file() && replacements == 1);
        gate_open = true;
        cache_size = 96;
        pcache_built_since_save = 32;
        pipeline_cache_save(false);
        CHECK(wait_until(replacements, 2));
        pipeline_cache_save(true);  // After the worker: nothing new.
        CHECK(gate_tries == 2 && gate_waits == 2 && gate_ends == 3 && !gate_held && new_file());
        // A compile stuck in the driver: a forced save gives up after its bounded wait instead of waiting (and stalling every
        // build behind its lock) for good; nothing is copied or written, and the next save point tries again.
        gate_stuck = true;
        cache_size = 112;
        const int before = replacements;
        pipeline_cache_save(true);
        CHECK(gate_waits == 3 && gate_ends == 3 && !gate_held && replacements == before && pcache_built_since_save >= 32);
        gate_stuck = false;
    } else {
        CHECK(false);
    }
    CHECK(!gate_held);  // Never left held, whatever failed in between.
    std::printf("PASS: %s\n", name.c_str());
    return 0;
}

int main(int argc, char** argv) {
    // An old detached worker would terminate the process. The original-source negative runs in its own bounded child.
    std::set_terminate([] { std::fputs("uncaught worker exception\n", stderr); std::_Exit(86); });
    if (argc == 2 && std::strcmp(argv[1], "terminate-control") == 0) std::terminate();
    if (argc == 2 && std::strcmp(argv[1], "uncaught-thread-control") == 0) {
#ifdef _MSC_VER
        std::fputs("MSVC-target uncaught-thread control\n", stderr);
#endif
        std::thread worker([] { throw std::bad_alloc(); });
        worker.join();
        return 2;
    }
    if (argc != 3) return 2;
    pcache_path = std::string(argv[2]) + "/authored-pipeline-cache-with-a-path-longer-than-small-string-storage.bin";
    FILE* f = std::fopen(pcache_path.c_str(), "wb");
    if (!f) return 2;
    std::fwrite("old", 1, 3, f);
    std::fclose(f);
    try {
        return run(argv[1]);
    } catch (const std::exception& e) {
        std::fprintf(stderr, "uncaught caller exception: %s\n", e.what());
        return 87;
    }
}
