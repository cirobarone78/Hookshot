// (hookshot) The shader preparation's parts that run behind the game (vk_prepare_play.h; the rules in prepare_play.h): Compile shaders
// on Most (the default) or Later.
//
// Before the game, All runs the whole preparation: every program of the seed translated with all its compute variants and their
// pipelines, the state lists' notes (prepare_run), the predicted pipelines for the driver's cache (predict_run), the noted ones
// (precompile_run): ~11 minutes on an RTX 3090 with a 12-core CPU, before the title. Most does the programs (the compute programs play
// is not known to dispatch at their base variant) and the noted pipelines before the game, and the rest behind it; Later does all of it
// behind the game. Behind the game the work runs in the same order and into the same files, on a few idle-priority threads, while
// what the frame being shown needs is made first by the back end's own workers; it stops at the window's close and goes on at the
// next start from where it got to (hookshot_prepare_play.txt). Done, the folder has what All gives it, and its starts are a prepared
// folder's until an update changes the shaders.
#include "vk_prepare_play.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <memory>
#include <mutex>
#include <set>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#ifdef _WIN32
#include <windows.h>
#include <io.h>
#else
#include <sched.h>
#include <unistd.h>
#endif

#include "prepare_play.h"
#include "hookshot_env.h"   // (env_on)
#include "vk_draw.h"
#include "vk_internal.h"
#include "vk_jobs.h"
#include "vk_menu.h"
#include "vk_paths.h"
#include "vk_texture.h"   // (texture_frame_no)

namespace mkwvk {
// (vk_draw.cpp)
bool prepare_needed();
void precompile_into_cache(void (*progress)(size_t done, size_t total), const std::unordered_set<uint64_t>* only);
bool compute_rest_run(void (*progress)(size_t done, size_t total));
std::unordered_set<uint64_t> computes_listed();
int64_t pcache_unsaved();
bool predict_gave_up();
uint64_t prepare_play_seed_id();
void prep_pcache_init();
void pipeline_cache_save(bool force);
double menu_frame_target_ms();

namespace {
using clock_t_ = std::chrono::steady_clock;
void checkpoint(int k);
void areas_take_posted();

std::string beside(const char* name) {
    char exe[MAX_PATH];
    const DWORD n = game_module_path(exe, MAX_PATH);
    std::string dir(exe, n);
    return dir.substr(0, dir.find_last_of("\\/") + 1) + name;
}
std::string read_text(const std::string& path) {
    std::string s;
    if (FILE* f = fopen(path.c_str(), "rb")) {
        char b[4096];
        for (size_t n; (n = fread(b, 1, sizeof b, f)) > 0;) s.append(b, n);
        fclose(f);
    }
    return s;
}
bool write_text(const std::string& path, const std::string& text) {
    const std::string tmp = path + ".tmp";
    FILE* f = fopen(tmp.c_str(), "wb");
    if (!f) return false;
    bool ok = fwrite(text.data(), 1, text.size(), f) == text.size();
    ok = fflush(f) == 0 && ok;
#ifdef _WIN32
    ok = FlushFileBuffers((HANDLE)_get_osfhandle(_fileno(f))) && ok;   // (on the disk before it is renamed over the last record)
#else
    ok = fsync(fileno(f)) == 0 && ok;
#endif
    ok = fclose(f) == 0 && ok;
    std::error_code ec;
    if (ok) std::filesystem::rename(tmp, path, ec);
    return ok && !ec;
}

std::atomic<bool> running{false}, finished_once{false};
prepare_play::Level level = prepare_play::Level::Most;   // (prepare_play_begin's)
std::atomic<bool> stop_done{false};
std::thread runner;

// ---- the CPUs and memory ----
void cpus_usable(unsigned* logical, unsigned* cores) {
    *logical = std::max(1u, std::thread::hardware_concurrency());
    *cores = *logical;
#ifdef _WIN32
    DWORD_PTR proc = 0, sys = 0;
    if (GetProcessAffinityMask(GetCurrentProcess(), &proc, &sys) && proc) {
        unsigned n = 0;
        for (DWORD_PTR m = proc; m; m &= m - 1) n++;
        *logical = n;
    }
    DWORD len = 0;
    GetLogicalProcessorInformation(nullptr, &len);
    std::vector<SYSTEM_LOGICAL_PROCESSOR_INFORMATION> info(len / sizeof(SYSTEM_LOGICAL_PROCESSOR_INFORMATION) + 1);
    if (len && GetLogicalProcessorInformation(info.data(), &len)) {
        unsigned c = 0;
        for (size_t i = 0; i < len / sizeof(SYSTEM_LOGICAL_PROCESSOR_INFORMATION); i++)
            if (info[i].Relationship == RelationProcessorCore && (info[i].ProcessorMask & proc)) c++;
        if (c) *cores = std::min(c, *logical);
    }
#else
    cpu_set_t set;
    CPU_ZERO(&set);
    if (sched_getaffinity(0, sizeof set, &set) == 0) {
        std::set<std::pair<int, int>> seen;   // (package, core) of each CPU this process may run on
        unsigned n = 0;
        for (int c = 0; c < CPU_SETSIZE; c++) {
            if (!CPU_ISSET(c, &set)) continue;
            n++;
            int core = c, pkg = 0;
            char path[128];
            snprintf(path, sizeof path, "/sys/devices/system/cpu/cpu%d/topology/core_id", c);
            if (FILE* f = fopen(path, "r")) { if (fscanf(f, "%d", &core) != 1) core = c; fclose(f); }
            snprintf(path, sizeof path, "/sys/devices/system/cpu/cpu%d/topology/physical_package_id", c);
            if (FILE* f = fopen(path, "r")) { if (fscanf(f, "%d", &pkg) != 1) pkg = 0; fclose(f); }
            seen.insert({pkg, core});
        }
        if (n) *logical = n, *cores = std::max<unsigned>(1, (unsigned)seen.size());
    }
#endif
}
/// Memory available now (GB, -1 unknown) and the pressure (Linux PSI "full avg10", 0 elsewhere)
void memory_now(double* avail_gb, double* psi) {
    *avail_gb = -1, *psi = 0;
#ifdef _WIN32
    MEMORYSTATUSEX m{sizeof m};
    if (GlobalMemoryStatusEx(&m)) *avail_gb = m.ullAvailPhys / 1073741824.0;
#else
    if (FILE* f = fopen("/proc/meminfo", "r")) {
        char line[128];
        while (fgets(line, sizeof line, f))
            if (!strncmp(line, "MemAvailable:", 13)) *avail_gb = atof(line + 13) / 1048576.0;
        fclose(f);
    }
    if (FILE* f = fopen("/proc/pressure/memory", "r")) {
        char line[160];
        while (fgets(line, sizeof line, f))
            if (!strncmp(line, "full", 4))
                if (const char* a = strstr(line, "avg10=")) *psi = atof(a + 6);
        fclose(f);
    }
#endif
}
unsigned logical_cpus = 1, physical_cores = 1;
/// RX_VK_PREPARE_THREADS=<n>: the threads the preparation in play gets, over prepare_play.h's choice (memory still stops them)
unsigned threads_wanted() {
    static const int forced = getenv("RX_VK_PREPARE_THREADS") ? atoi(getenv("RX_VK_PREPARE_THREADS")) : 0;
    return forced > 0 ? (unsigned)forced : prepare_play::workers_started(logical_cpus, physical_cores);
}
std::atomic<unsigned> allowed{1};
std::atomic<int64_t> allowed_at{0};
void allowed_refresh() {
    const int64_t now = std::chrono::duration_cast<std::chrono::milliseconds>(clock_t_::now().time_since_epoch()).count();
    int64_t at = allowed_at.load(std::memory_order_relaxed);
    if (now - at < 1000 || !allowed_at.compare_exchange_strong(at, now)) return;
    double gb, psi;
    memory_now(&gb, &psi);
    // (memory short: none or one; otherwise the threads chosen for this CPU, RX_VK_PREPARE_THREADS over them)
    const unsigned by_memory = prepare_play::workers(logical_cpus, physical_cores, gb, psi);
    const unsigned n = by_memory == 0 ? 0u : gb >= 0 && gb < 6.0 ? 1u : threads_wanted();
    const unsigned was = allowed.exchange(n);
    if (n != was) logf("vk: behind the game: %u threads now (memory available %.1f GB, pressure %.1f)", n, gb, psi);
}

// ---- the workers' slots ----
std::atomic<int> slots{0};
std::atomic<bool> pausing{false};
std::mutex gate_mu;   // (a slot taken and a checkpoint's pause, one at a time: a worker past the check cannot build while it saves)
std::atomic<bool> saving_now{false};   // (the checkpoint's own save: the one pipeline cache save allowed while the work runs)
struct Slot {
    bool held = false;
    ~Slot() {
        if (held) slots--;
    }
};
thread_local Slot slot;
thread_local bool direct_cache = false;

// ---- what is done (resume) ----
struct Phase {
    std::unique_ptr<std::atomic<uint8_t>[]> done;
    size_t n = 0;
    uint64_t from = 0;   // (done by an earlier start: skipped)
    uint64_t list = 0, list_recorded = 0;   // (the part's item list now, and the one the record's position is in)
};
Phase phases[prepare_play::kParts];
std::mutex phase_mu;
prepare_play::Progress progress_rec;
std::string progress_path() { return beside("hookshot_prepare_play.txt"); }
std::atomic<int> phase_now{0};
std::atomic<size_t> phase_done{0}, phase_total{0};
uint64_t counts[prepare_play::kParts]{};   // (the parts' sizes for the overlay: guesses, then each part's own)
int first_part = 0;   // (the first part this start does behind the game: the overlay counts from it)
auto started_at = clock_t_::now();
auto last_checkpoint = clock_t_::now();

// ---- the draws ----
prepare_play::Budget budget;
std::atomic<int64_t> st_left_out{0}, st_waited{0}, st_wait_us{0}, st_misses{0}, st_hidden{0}, st_hidden_holds{0};
prepare_play::Hold hold;
std::atomic<bool> holding{false};
std::atomic<bool> loading_now{false};   // (frames of a load: what they lack is asked for, the frame not shown)

// ---- the areas: what each needed, learned as it is played (and shipped, when there is a list) ----
struct Areas {
    std::mutex mu;
    std::unordered_map<uint64_t, std::unordered_set<uint64_t>> pipes;   // (area -> pipelines met there)
    std::unordered_map<uint64_t, std::unordered_set<uint64_t>> next;    // (area -> areas reached from it)
    std::unordered_map<uint64_t, std::string> names;
    std::string pending;   // (lines not written yet)
    uint64_t current = 0;
    clock_t_::time_point learn_until{};
    std::vector<uint64_t> met;   // (pipelines met while learning, not yet taken in)
    std::vector<std::vector<uint64_t>> wanted;   // (the areas to build first, newest last)
} areas;
std::mutex met_mu;   // (the draw's side: try_lock only)
struct Posted { std::string current, next; bool fresh = false; };
std::mutex posted_mu;   // (the game's thread: held for two strings' copy)
Posted posted;
std::vector<uint64_t> met_now;
std::atomic<bool> learning{false};
uint64_t area_hash(const char* name) {
    uint64_t h = 0xcbf29ce484222325ull;
    for (const char* p = name; *p; p++) h = (h ^ (uint8_t)*p) * 0x100000001b3ull;
    return h ? h : 1;
}
void areas_load(const std::string& path) {
    const std::string t = read_text(path);
    for (size_t at = 0; at < t.size();) {
        size_t nl = t.find('\n', at);
        if (nl == std::string::npos) nl = t.size();
        const std::string line = t.substr(at, nl - at);
        at = nl + 1;
        unsigned long long a = 0, b = 0;
        char name[96];
        if (sscanf(line.c_str(), "p %llx %llx", &a, &b) == 2) areas.pipes[a].insert(b);
        else if (sscanf(line.c_str(), "n %llx %llx", &a, &b) == 2) areas.next[a].insert(b);
        else if (sscanf(line.c_str(), "a %llx %95s", &a, name) == 2) areas.names[a] = name;
    }
}
std::string areas_path() { return beside("hookshot_area_pipelines.txt"); }
void areas_flush() {
    std::string out;
    {
        std::lock_guard lk(areas.mu);
        out.swap(areas.pending);
    }
    if (out.empty()) return;
    if (FILE* f = fopen(areas_path().c_str(), "ab")) fwrite(out.data(), 1, out.size(), f), fclose(f);
}
/// The pipelines met while learning, into the current area's set
void areas_take_met() {
    std::vector<uint64_t> got;
    {
        std::lock_guard lk(met_mu);
        got.swap(met_now);
    }
    std::lock_guard lk(areas.mu);
    if (clock_t_::now() > areas.learn_until) learning = false;
    if (!areas.current) return;
    auto& set = areas.pipes[areas.current];
    char b[64];
    for (const uint64_t k : got)
        if (set.insert(k).second) {
            snprintf(b, sizeof b, "p %016llx %016llx\n", (unsigned long long)areas.current, (unsigned long long)k);
            areas.pending += b;
        }
}
/// An area to build first: its pipelines and its neighbours', in the prefetch's queue
void areas_want(uint64_t area) {
    std::lock_guard lk(areas.mu);
    std::vector<uint64_t> list;
    std::unordered_set<uint64_t> seen;
    const auto add = [&](uint64_t a) {
        if (auto it = areas.pipes.find(a); it != areas.pipes.end())
            for (const uint64_t k : it->second)
                if (seen.insert(k).second) list.push_back(k);
    };
    add(area);
    if (auto it = areas.next.find(area); it != areas.next.end())
        for (const uint64_t n : it->second) add(n);
    if (!list.empty()) areas.wanted.push_back(std::move(list));
}

/// The area the game posted (mkwvk_area_state), taken in on the prefetch thread: a next area's pipelines first, the area's names and
/// neighbours learned
void areas_take_posted() {
    std::string current, next;
    {
        std::lock_guard lk(posted_mu);
        if (!posted.fresh) return;
        posted.fresh = false;
        current = posted.current, next = posted.next;
    }
    const uint64_t cur = !current.empty() ? area_hash(current.c_str()) : 0;
    const uint64_t nxt = !next.empty() ? area_hash(next.c_str()) : 0;
    static uint64_t last_cur = 0, last_next = 0;
    if (nxt && nxt != last_next && nxt != cur) {   // (a load is coming: its area first)
        logf("vk: behind the game: the next area is %s: its pipelines first", next.c_str());
        areas_want(nxt);
    }
    last_next = nxt;
    if (cur && cur != last_cur) {
        {
            std::lock_guard lk(areas.mu);
            char b[160];
            if (!areas.names.count(cur)) {
                areas.names[cur] = current;
                snprintf(b, sizeof b, "a %016llx %.95s\n", (unsigned long long)cur, current.c_str());
                areas.pending += b;
            }
            if (last_cur && areas.next[last_cur].insert(cur).second) {
                snprintf(b, sizeof b, "n %016llx %016llx\n", (unsigned long long)last_cur, (unsigned long long)cur);
                areas.pending += b;
            }
            areas.current = cur;
            areas.learn_until = std::chrono::steady_clock::now() + std::chrono::seconds(20);
        }
        if (!last_cur) areas_want(cur);   // (the first area known, the save's: it and its neighbours first)
        learning = true;
        logf("vk: behind the game: in area %s", current.c_str());
        last_cur = cur;
    }
}

// ---- the overlay and the log ----
void progress_cb(size_t done, size_t total) {
    phase_done.store(done, std::memory_order_relaxed), phase_total.store(total, std::memory_order_relaxed);
    if (total && phase_now < prepare_play::kParts && counts[phase_now.load()] != total) counts[phase_now.load()] = total;
    // (on the preparation's own thread: the learned areas written, a checkpoint now and then)
    areas_take_met();
    areas_flush();
    const auto now = clock_t_::now();
    static auto log_at = now;
    if (now >= log_at) {
        log_at = now + std::chrono::seconds(10);
        int64_t lo, w, hid;
        double ms;
        prep_stats(&lo, &w, &ms, &hid);
        char t[64];
        prep_overlay_text(t, sizeof t);
        logf("vk: behind the game: %s (part %d: %zu of %zu), %u threads; draws left out %lld, waited for %lld (%.0f ms), "
             "frames held %lld", t, phase_now.load(), done, total, allowed.load(), (long long)lo, (long long)w, ms, (long long)hid);
    }
    // (every 5 minutes, once enough was built: the pipeline cache saved while no worker builds into it, then where the work got to.
    // Never the position without the save: a start after a crash would skip items whose pipelines were not kept)
    // (the predicted pipelines go to the driver's own cache alone, not ours: their position needs no save of ours)
    if (now - last_checkpoint > std::chrono::seconds(300) && phase_now < prepare_play::kParts &&
        (pcache_unsaved() >= 256 || phase_now == prepare_play::kPredicted)) {
        last_checkpoint = now;
        checkpoint(phase_now.load());
    }
}
void record(int phase, uint64_t at, uint64_t list = 0) {
    prepare_play::Progress r = progress_rec;
    r.phase = phase, r.at = at, r.list = list;
    write_text(progress_path(), prepare_play::progress_text(r));
}
/// The workers paused (none in a build), the start's pipeline cache saved, the workers let go. False: they did not pause in time
bool pause_and_save() {
    {
        std::lock_guard lk(gate_mu);
        pausing = true;
    }
    const auto t0 = clock_t_::now();
    while (slots.load() > 0 && clock_t_::now() - t0 < std::chrono::seconds(5)) std::this_thread::sleep_for(std::chrono::milliseconds(5));
    const bool paused = slots.load() == 0;
    if (paused) {
        saving_now = true;
        pipeline_cache_save(true);
        saving_now = false;
    }
    pausing = false;
    return paused;
}
/// A checkpoint in part k: the cache saved, then the part's position (its items done from the first, in order) recorded
void checkpoint(int k) {
    if (!pause_and_save()) return;   // (a worker still in a long compile: the next one)
    std::lock_guard lk(phase_mu);
    Phase& p = phases[k];
    record(k, p.done ? prepare_play::done_prefix(p.done.get(), p.n, 0) : p.from, p.list);
}

/// The record of a finished phase's preparation (hookshot_prepared.bin.play) moved over hookshot_prepared.bin once everything is done
void record_in_place() {
    const std::string rec = beside("hookshot_prepared.bin");
    std::error_code ec;
    if (std::filesystem::exists(rec + ".play", ec)) std::filesystem::rename(rec + ".play", rec, ec);
    if (ec) logf("vk: behind the game: hookshot_prepared.bin not written (%s)", ec.message().c_str());
}

/// The prefetch: the pipelines of the areas asked for, built first (one thread, below normal priority); and the game's area, posted
/// by mkwvk_area_state, taken in here (the game's thread only posts it)
void prefetch_loop() {
    prep_thread_begin(THREAD_PRIORITY_BELOW_NORMAL);
    while (running.load() && !prepare_stopped()) {
        areas_take_posted();
        std::vector<uint64_t> list;
        {
            std::lock_guard lk(areas.mu);
            if (!areas.wanted.empty()) list = std::move(areas.wanted.back()), areas.wanted.clear();
        }
        if (list.empty()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
            continue;
        }
        const std::unordered_set<uint64_t> only(list.begin(), list.end());
        const auto t0 = clock_t_::now();
        precompile_into_cache(nullptr, &only);
        logf("vk: behind the game: %zu pipelines of the area and its neighbours built first, in %.1f s", only.size(),
             std::chrono::duration<double>(clock_t_::now() - t0).count());
    }
}

void run() {
    prep_thread_begin(THREAD_PRIORITY_BELOW_NORMAL);
    started_at = last_checkpoint = clock_t_::now();
    std::thread prefetcher(prefetch_loop);
    {
        size_t g[3];
        prepare_guess(g);
        counts[prepare_play::kPrograms] = g[0];
        counts[prepare_play::kComputeRest] = g[0] / 10;   // (about one program in ten is a compute program)
        counts[prepare_play::kPredicted] = g[1];
        counts[prepare_play::kNoted] = level == prepare_play::Level::Later ? g[2] : 0;
    }
    const int from = std::max(progress_rec.phase, 0);
    first_part = from;
    logf("vk: behind the game (Compile shaders: %s): the shaders not prepared before it are prepared now, from part %d item %llu, "
         "on up to %u threads of %u CPUs (%u cores), idle priority", level == prepare_play::Level::Later ? "Later" : "Most", from,
         (unsigned long long)progress_rec.at, threads_wanted(), logical_cpus, physical_cores);
    bool ok = true;
    const auto part = [&](int k, const auto& fn) {
        if (!ok || from > k) return;
        phase_now = k;
        phase_done = phase_total = 0;
        ok = fn() && !prepare_stopped();
        // (the cache saved with the workers paused (the prefetch may be building), then the part recorded done; a save that could
        // not pause leaves the part to the next start, which goes through it quickly)
        if (ok && pause_and_save()) record(k + 1, 0);
    };
    part(prepare_play::kPrograms, [] { prepare_run(progress_cb, false, true); return true; });
    part(prepare_play::kComputeRest, [] { compute_rest_run(progress_cb); return true; });
    part(prepare_play::kPredicted, [] {
        predict_run(progress_cb);
        // (the prediction gave up on workers stuck in the driver (its watchdog): not done, the next start does it again)
        if (predict_gave_up()) logf("vk: behind the game: the predicted pipelines were not all built (the driver stopped answering)");
        return !predict_gave_up();
    });
    if (level == prepare_play::Level::Later) part(prepare_play::kNoted, [] { precompile_into_cache(progress_cb, nullptr); return true; });
    else if (ok) record(prepare_play::kDone, 0);   // (Most: the noted pipelines were built before the game)
    running = false;   // (the draws' rules for it end here; the prefetch too)
    prefetcher.join();
    areas_take_met();
    areas_flush();
    if (ok) {
        record_in_place();
        record(prepare_play::kDone, 0);
        phase_now = prepare_play::kDone;
        int64_t lo, w, hid;
        double ms;
        prep_stats(&lo, &w, &ms, &hid);
        logf("vk: behind the game: the shaders are all prepared, in %.0f s; meanwhile %lld draws were left out, %lld waited for (%.0f ms), "
             "%lld frames held. From now on it plays as a folder prepared with All",
             std::chrono::duration<double>(clock_t_::now() - started_at).count(), (long long)lo, (long long)w, ms, (long long)hid);
        finished_once = true;
    } else {
        // (stopped: the record stays at the last checkpoint, whose pipelines are in the saved cache; what was built since is in the
        // driver's own cache, and quick to build again. No save here: at a close it would hold the quit for seconds)
        const prepare_play::Progress r = prepare_play::progress_parse(read_text(progress_path()).c_str(), progress_rec.stamp);
        logf("vk: behind the game: stopped (the window was closed) in part %d: the next start goes on from part %d item %llu",
             phase_now.load(), r.phase, (unsigned long long)r.at);
    }
    stop_done = true;
}

} // namespace

namespace {
std::string options_text() { return read_text(beside("hookshot_options.ini")); }
}   // namespace
prepare_play::Level prepare_level() {
    static const prepare_play::Level l = prepare_play::level_of(options_text().c_str(), getenv("RX_VK_COMPILE_SHADERS"));
    return l;
}
void prep_record(int part) {
    if (!running.load()) progress_rec = prepare_play::progress_parse(read_text(progress_path()).c_str(), prepare_play_seed_id());
    record(part, 0);
}
int prep_recorded() {
    const prepare_play::Progress r = prepare_play::progress_parse(read_text(progress_path()).c_str(), prepare_play_seed_id());
    return r.phase;
}
void prep_programs_prepared() {
    // (Most or Later translated the programs with the unlisted compute programs at their base variant: what is left is recorded, so
    // that the work behind the game, or a later start on All, does it. All translated everything: its record waits for the rest of
    // its preparation, prep_all_done)
    if (running.load() || prepare_level() == prepare_play::Level::All) return;
    const int had = prep_recorded();
    if (had < prepare_play::kComputeRest) prep_record(prepare_play::kComputeRest);
}
void prep_all_done() {
    // (All prepared everything, the predicted pipelines too: said in the record, so a later start on Most knows there is nothing
    // left (with no record it does the parts Most leaves, which a folder prepared with All has)
    if (prep_recorded() != prepare_play::kDone) prep_record(prepare_play::kDone);
}
void prep_driver_changed() {
    // (prepare_run before the game remade the driver's part for a new driver: on Most the predicted pipelines, built behind the game,
    // are the old driver's too. Behind the game (Later) its own parts go on as they are)
    if (running.load() || prepare_level() == prepare_play::Level::All) return;
    const int had = prep_recorded();
    const int left = prepare_play::most_left(had, true);
    if (left != had) {
        logf("vk: a new GPU driver: the predicted pipelines are built again behind the game");
        prep_record(left);
    }
}
bool prep_cache_save_ok() {
    // (while the work behind the game runs, only its own saves, made while its workers are paused (saving_now): another reading the
    // cache while they build into it crashed Intel's driver. The play cache's own saves go on: they are another cache)
    return !running.load() || saving_now.load();
}
bool prep_compute_every(uint64_t key) {
    if (!key) return prepare_level() == prepare_play::Level::All;
    static const std::unordered_set<uint64_t> listed = computes_listed();
    return listed.count(key) != 0;
}

bool prepare_play_begin() {
    level = prepare_level();
    if (level == prepare_play::Level::All || env_on("HOOKSHOT_PREPARE_ONLY")) return false;
    progress_rec = prepare_play::progress_parse(read_text(progress_path()).c_str(), prepare_play_seed_id());
    if (level == prepare_play::Level::Most) {
        // (after the part before the game: the programs are prepared. No record (a folder prepared before these choices, or the record
        // lost): what Most leaves is done again, quickly from the caches; kDone: nothing left)
        const int left = prepare_play::most_left(progress_rec.phase, false);
        if (left >= prepare_play::kDone) return false;
        if (left != progress_rec.phase) progress_rec.phase = left, progress_rec.at = 0, progress_rec.list = 0;
    } else {
        // (Later: prepared, all of it, for this translator and seed: a prepared folder's start)
        if (!prepare_needed() && (progress_rec.phase < 0 || progress_rec.phase >= prepare_play::kDone)) {
            std::error_code ec;
            std::filesystem::remove(beside("hookshot_prepared.bin.play"), ec);
            return false;
        }
        if (prepare_needed() && progress_rec.phase > prepare_play::kPrograms) progress_rec.phase = 0, progress_rec.at = 0;
        // (the record of the last preparation set aside until all of it is done: a start that ends halfway still prepares)
        const std::string rec = beside("hookshot_prepared.bin");
        std::error_code ec;
        if (prepare_needed() && std::filesystem::exists(rec, ec)) std::filesystem::rename(rec, rec + ".play", ec);
    }
    progress_rec.phase = prepare_play::first_part(level, progress_rec.phase);
    cpus_usable(&logical_cpus, &physical_cores);
    allowed = threads_wanted();
    allowed_at = 0;
    allowed_refresh();
    for (int k = 0; k < prepare_play::kParts; k++) phases[k] = Phase{};
    if (progress_rec.phase < prepare_play::kParts)
        phases[progress_rec.phase].from = progress_rec.at, phases[progress_rec.phase].list_recorded = progress_rec.list;
    areas_load(areas_path());
    prep_pcache_init();
    running = true;
    runner = std::thread(run);
    runner.detach();
    return true;
}
bool prepare_play_running() { return running.load(std::memory_order_relaxed); }
bool prepare_play_close() {
    if (!running.load()) return true;
    logf("vk: the window was closed while shaders were prepared behind the game: stopping, what is done is kept");
    prepare_stop();
    // (each worker stops before its next pipeline or variant: what keeps one is a compile already in the driver, seconds on some)
    const auto t0 = clock_t_::now();
    while (!stop_done.load() && clock_t_::now() - t0 < std::chrono::seconds(20)) std::this_thread::sleep_for(std::chrono::milliseconds(10));
    if (stop_done.load()) return true;
    // (a worker still in the driver's compile of a pipeline. The marker that says the driver's part began and did not end is there to
    // leave out a driver that crashes in it; this is a close, not a crash, and with the marker kept the next start left every compute
    // pipeline out for good)
    std::error_code ec;
    std::filesystem::remove(beside("hookshot_prepared.bin.warming"), ec);
    logf("vk: behind the game: a worker is still in the driver after 20 s: the process ends without tearing the device down under it "
         "(what is done is kept; the rest at the next start)");
    return false;
}

void prep_thread_begin(int normal_priority) {
    if (!running.load()) {
        if (normal_priority != THREAD_PRIORITY_NORMAL) SetThreadPriority(GetCurrentThread(), normal_priority);
        return;
    }
    // (below normal, as the preparation before the game: behind the game's threads and the back end's workers, which build what the
    // frame needs, but never starved. These workers take locks play's threads take too (the program cache's, a program's layout, the
    // notes'), for one record or one call at a time; at idle priority (Windows' IDLE, nice 19) a holder could wait seconds for a CPU
    // while the frame waited for it. Fewer of them instead (prepare_play.h workers))
    SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_BELOW_NORMAL);
    direct_cache = true;
}
unsigned prep_threads(unsigned normal) {
    if (!running.load()) return normal;
    return std::max(1u, std::min(normal, threads_wanted()));
}
void prep_gate() {
    if (!running.load(std::memory_order_relaxed)) return;
    for (;;) {
        if (prepare_stopped()) return;
        allowed_refresh();
        // (the frame's own work first: a translation or a pipeline a draw is waiting for, or left out for)
        const bool go = !pausing.load(std::memory_order_relaxed) && jobs_pending() == 0;
        if (slot.held) {
            if (go && slots.load() <= (int)allowed.load()) return;
            slot.held = false, slots--;
        } else if (go) {
            std::lock_guard lk(gate_mu);   // (pausing read again under it: a checkpoint that paused sees this slot, or this sees it)
            if (!pausing.load() && slots.load() < (int)allowed.load()) {
                slots++;
                slot.held = true;
                return;
            }
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(go ? 20 : 2));
    }
}
void prep_phase_items(int phase, size_t n, uint64_t list) {
    if (!running.load() || phase < 0 || phase >= prepare_play::kParts) return;
    std::lock_guard lk(phase_mu);
    Phase& p = phases[phase];
    p.list = list;
    if (p.from && p.list_recorded != list) {   // (the list changed since the record: its positions are another list's)
        logf("vk: behind the game: part %d's list changed since the last start: it starts again", phase);
        p.from = 0;
    }
    p.n = n;
    p.done.reset(new std::atomic<uint8_t>[n ? n : 1]);
    for (size_t i = 0; i < n; i++) p.done[i].store(i < p.from ? 1 : 0, std::memory_order_relaxed);
}
bool prep_item_skip(int phase, size_t i) {
    if (!running.load(std::memory_order_relaxed) || phase < 0 || phase >= prepare_play::kParts) return false;
    return i < phases[phase].from;
}
void prep_item_done(int phase, size_t i) {
    if (!running.load(std::memory_order_relaxed) || phase < 0 || phase >= prepare_play::kParts) return;
    Phase& p = phases[phase];
    if (p.done && i < p.n) p.done[i].store(1, std::memory_order_release);
}
const char* prep_record_suffix() { return running.load() && level == prepare_play::Level::Later ? ".play" : ""; }
bool prep_direct_cache() { return direct_cache; }
bool prep_building() { return running.load(std::memory_order_relaxed) && slots.load(std::memory_order_relaxed) > 0; }

prepare_play::Miss shader_miss() {
    static const char* env = getenv("RX_VK_SHADER_MISS");
    return (prepare_play::Miss)std::clamp(env && *env ? atoi(env) : opts.shader_miss, 0, 2);
}
prepare_play::Act prep_miss_act(bool skippable, bool allow_hidden) {
    static const bool always_env = getenv("RX_VK_PIPE_SKIP") && atoi(getenv("RX_VK_PIPE_SKIP")) == 0;
    // (hidden: the frames held after a load, and a load's own (Hold): what they lack is asked for, not waited for)
    static const bool hold_off = getenv("RX_VK_PREPARE_HOLD") && atoi(getenv("RX_VK_PREPARE_HOLD")) == 0;
    const bool hidden = allow_hidden && !hold_off &&
                        (holding.load(std::memory_order_relaxed) || loading_now.load(std::memory_order_relaxed));
    const prepare_play::Act act = prepare_play::decide(shader_miss(), always_env, hidden, skippable, prep_miss_budget_left());
    if (act == prepare_play::Act::LeaveOut) st_left_out++;
    return act;
}
int64_t prep_miss_budget_left() {
    // (RX_VK_SHADER_WAIT_US=<us a frame>: the budget itself; RX_VK_SHADER_WAIT_SHARE=<share of the capped frame> over the default)
    static const int64_t env_us = getenv("RX_VK_SHADER_WAIT_US") ? atoll(getenv("RX_VK_SHADER_WAIT_US")) : -1;
    static const double share = getenv("RX_VK_SHADER_WAIT_SHARE") ? atof(getenv("RX_VK_SHADER_WAIT_SHARE")) : 0.15;
    const int64_t per_frame = env_us >= 0 ? env_us : prepare_play::budget_us(menu_frame_target_ms(), share);
    return budget.left(texture_frame_no(), per_frame);
}
void prep_miss_spend(int64_t us) {
    budget.spend(us);
    st_waited++, st_wait_us += us;
}
void prep_note_miss() { st_misses.fetch_add(1, std::memory_order_relaxed); }
void prep_pipeline_met(uint64_t key) {
    if (!learning.load(std::memory_order_relaxed)) return;
    std::unique_lock lk(met_mu, std::try_to_lock);   // (never waits: a key missed is learned another time)
    if (lk.owns_lock() && met_now.size() < 100000) met_now.push_back(key);
}
bool prep_present_hidden(int64_t draws_total, bool framegen) {
    static int64_t last_draws = 0, last_misses = 0;
    const int64_t draws = draws_total - last_draws, misses = st_misses.load() - last_misses;
    last_draws = draws_total, last_misses = st_misses.load();
    static const bool off = getenv("RX_VK_PREPARE_HOLD") && atoi(getenv("RX_VK_PREPARE_HOLD")) == 0;
    static const bool set = [] {
        if (const char* e = getenv("RX_VK_PREPARE_HOLD_MS")) hold.cap_ns = (int64_t)atoll(e) * 1000000;
        if (const char* e = getenv("RX_VK_PREPARE_HOLD_CLEAN")) hold.clean_needed = std::max(1, atoi(e));
        return true;
    }();
    (void)set;
    const int64_t now = std::chrono::duration_cast<std::chrono::nanoseconds>(clock_t_::now().time_since_epoch()).count();
    const bool was = hold.holding;
    const bool hidden = hold.frame(draws, misses, now, running.load() && !off && !framegen);
    if (hold.holding && !was) {
        st_hidden_holds++;
        logf("vk: behind the game: an area's first frames are held until their pipelines are ready (frame of %lld draws, %lld "
             "not ready)", (long long)draws, (long long)misses);
    }
    if (!hold.holding && was)
        logf("vk: behind the game: the picture is back after %lld held frames (%.0f ms)", (long long)hold.hidden,
             (now - hold.since) / 1e6);
    holding.store(hold.holding, std::memory_order_relaxed);
    loading_now.store(hold.loading && running.load(), std::memory_order_relaxed);
    if (hidden) st_hidden++;
    return hidden;
}
bool prep_overlay_text(char* out, size_t n) {
    if (!running.load(std::memory_order_relaxed)) return false;
    const int pc = prepare_play::percent(first_part, phase_now.load(), phase_done.load(), phase_total.load(), counts);
    snprintf(out, n, "Shaders: %d%%", pc);
    return true;
}
void prep_stats(int64_t* left_out, int64_t* waited, double* wait_ms, int64_t* hidden) {
    *left_out = st_left_out.load(), *waited = st_waited.load(), *wait_ms = st_wait_us.load() / 1000.0, *hidden = st_hidden.load();
}

} // namespace mkwvk

// (hookshot) The game's area, from the host (host/hos_main.c, read now and then while Link is about): current: the map shown,
// next: one reserved for the next load ("" none). Looked up by name, so an executable and a back end of different versions
// still run. Only while shaders are prepared behind the game: the area's pipelines (and its neighbours') are built first, and what the area
// needs is learned for the next time
extern "C"
#ifdef _WIN32
__declspec(dllexport)
#else
__attribute__((visibility("default")))
#endif
void mkwvk_area_state(const char* current, const char* next) {
    using namespace mkwvk;
    if (!running.load() || !current) return;
    // (the game's thread: the names posted, nothing more; the preparation's prefetch thread takes them in, areas_take_posted)
    std::lock_guard lk(posted_mu);
    posted.current = current;
    posted.next = next ? next : "";
    posted.fresh = true;
}
extern "C"
#ifdef _WIN32
__declspec(dllexport)
#else
__attribute__((visibility("default")))
#endif
int mkwvk_area_wanted(void) {
    return mkwvk::prepare_play_running() ? 1 : 0;
}
