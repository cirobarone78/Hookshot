/* (hookshot) How much of the shader preparation runs before play, and what a draw does when its shader is not ready: the plain rules,
   with no Vulkan and no game, so that tests/test_prepare_play.py can run them (vk_prepare_play.cpp and vk_draw.cpp use them).

   "Compile shaders" (the builders' choice, the Insert menu's row, compile_shaders= in hookshot_options.ini, RX_VK_COMPILE_SHADERS):
   - All: everything before play, as it always was: every program translated with all its compute variants, the state lists' and the
     noted pipelines, the predicted pipelines.
   - Most (the default): before play, every program translated (the compute programs on the shipped list of those play dispatches
     with all their variants, the others with their base variant), the state lists and the noted pipelines. The predicted pipelines
     and the other compute variants are built behind the game while it is played.
   - Later: nothing before play; all of it behind the game.
   Behind the game the work runs on a few idle-priority threads, in the order the preparation has before the game, goes on at the next
   start where it stopped, and stops once the folder has what All gives it, until an update changes the shaders.

   "When a shader isn't ready" (the menu's row, shader_miss=, RX_VK_SHADER_MISS): Wait, Wait briefly then skip (the default), Skip. A
   draw that writes memory (global memory, storage buffers or images) always waits, whatever the choice: left out, the game's state
   would be wrong from then on.

   This file: the two choices, the threads the work behind the game gets, which draws wait, the frame's wait budget, the hold of the
   picture after an area's load, the record that lets the next start go on where this one stopped, and the overlay's percentage. */
#pragma once

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

namespace prepare_play {

// ---- the choices ----
enum class Level { All = 0, Most = 1, Later = 2 };
enum class Miss { Wait = 0, Briefly = 1, Skip = 2 };
/// key=<n> from hookshot_options.ini's text, else fallback (the last line of that key counts)
inline int ini_int(const char* ini_text, const char* key, int fallback) {
    int v = fallback;
    const size_t n = strlen(key);
    for (const char* line = ini_text; line && *line;) {
        if (!strncmp(line, key, n) && line[n] == '=') v = atoi(line + n + 1);
        const char* nl = strchr(line, '\n');
        if (!nl) break;
        line = nl + 1;
    }
    return v;
}
/// The Compile shaders choice: the file's compile_shaders= (0 All, 1 Most, 2 Later), the environment's RX_VK_COMPILE_SHADERS over it
/// (a number or all/most/later). Most when neither says
inline Level level_of(const char* ini_text, const char* env) {
    int v = ini_int(ini_text, "compile_shaders", 1);
    if (env && *env) {
        if (!strcmp(env, "all")) v = 0;
        else if (!strcmp(env, "most")) v = 1;
        else if (!strcmp(env, "later")) v = 2;
        else v = atoi(env);
    }
    return (Level)std::clamp(v, 0, 2);
}
/// When a shader isn't ready: the file's shader_miss= (0 Wait, 1 Wait briefly, 2 Skip), RX_VK_SHADER_MISS over it. Wait briefly when
/// neither says
inline Miss miss_of(const char* ini_text, const char* env) {
    int v = ini_int(ini_text, "shader_miss", 1);
    if (env && *env) v = atoi(env);
    return (Miss)std::clamp(v, 0, 2);
}

// ---- the threads ----
/// How many threads the preparation behind the game gets. logical, cores: the CPUs this process may run on (its affinity)
/// and the physical cores among them. The game keeps about two threads busy and the renderer one, and the back end's own
/// workers build what the frame needs: the preparation takes what is left over, at most 8 (the driver's compiles scale with
/// physical cores, not hardware threads). A small CPU (6 cores or fewer: a Steam Deck has 4) gets one thread. With memory
/// short it stops: avail_gb, what the system says is available, under 3 GB none, under 6 GB one; psi_full, the share of the
/// last 10 s every task waited on memory (Linux /proc/pressure/memory "full avg10", 0 elsewhere), over 10 none
inline unsigned workers(unsigned logical, unsigned cores, double avail_gb, double psi_full) {
    if (logical == 0) logical = 1;
    if (cores == 0 || cores > logical) cores = logical;
    if (avail_gb >= 0 && avail_gb < 3.0) return 0;
    if (psi_full > 10.0) return 0;
    unsigned n;
    if (cores <= 6) n = 1;
    else n = std::min({cores - 3, logical > 6 ? logical - 6 : 1u, 6u});   // (below normal priority, not idle: at most 6)
    if (n < 1) n = 1;
    if (avail_gb >= 0 && avail_gb < 6.0) n = 1;
    return n;
}
/// The number of threads to start: the most workers() can allow on this CPU (memory and pressure decide each moment how many
/// of them run)
inline unsigned workers_started(unsigned logical, unsigned cores) { return workers(logical, cores, 1e9, 0); }

// ---- which draws may be left out ----
enum class Act { Wait, Bounded, LeaveOut };
/// A draw whose pipeline is not ready. skippable: its targets hold a picture from an earlier frame (what shows for a frame when it is
/// left out) and none of its stages writes memory; a draw that is not skippable always waits (one into targets made this frame would
/// show nothing there; one that writes memory would leave the game's state wrong). always_env: RX_VK_PIPE_SKIP=0 (waited for, over
/// all). hidden: the frame is not shown (an area's first frames after its load, Hold below): what it lacks costs nothing and every
/// pipeline it needs is asked for at once, built side by side. left_us: what the frame's wait budget has left.
inline Act decide(Miss miss, bool always_env, bool hidden, bool skippable, int64_t left_us) {
    if (always_env || miss == Miss::Wait || !skippable) return Act::Wait;
    if (hidden || miss == Miss::Skip) return Act::LeaveOut;
    return left_us > 0 ? Act::Bounded : Act::LeaveOut;
}

/// Wait briefly's budget for a frame, in microseconds: a share of the frame time the game is capped at (a fixed budget would take
/// far more of a 144 fps frame than of a 60 fps one). target_ms: the cap's frame time (0: none, the console's 60 then). share: 0.15
/// by default (2.5 ms of a 60 fps frame: the measurement is in the PR), RX_VK_SHADER_WAIT_SHARE over it
inline int64_t budget_us(double target_ms, double share = 0.15) {
    if (target_ms <= 0) target_ms = 1000.0 / 60.0;
    return (int64_t)(target_ms * 1000.0 * share);
}
/// The wait budget of a frame, shared by the threads that record it: full again at each new frame
class Budget {
public:
    /// What the frame `now` has left (the whole budget at its first call)
    int64_t left(uint64_t now, int64_t per_frame_us) {
        uint64_t f = frame_.load(std::memory_order_acquire);
        if (f != now && frame_.compare_exchange_strong(f, now, std::memory_order_acq_rel))
            left_.store(per_frame_us, std::memory_order_release);
        return left_.load(std::memory_order_acquire);
    }
    void spend(int64_t us) { left_.fetch_sub(us, std::memory_order_acq_rel); }

private:
    std::atomic<uint64_t> frame_{~0ull};
    std::atomic<int64_t> left_{0};
};

// ---- the hold after an area's load ----
/// An area's first frames after its load are rendered as usual but not shown: the last picture shown (the loading screen's,
/// or black) stays, every pipeline those hidden frames ask for is built first, and the picture comes back once a few frames
/// in a row lacked nothing (or the cap ran out). A load's own frames that lack something are not shown either. Only while
/// the preparation runs behind the game. The game itself runs on as always: its clock and sound do not wait, only the picture
/// does.
/// A load is seen by the draws: frames of few draws (a loading screen draws 2-10, a menu 15-70) for a while, then a frame of
/// many (an area draws 700 and more). A load's own hidden frames are capped as a hold is (cap_ns from the first one hidden): a
/// pause menu, the title or a dark room also draws few, and must not freeze on a pipeline that takes seconds
struct Hold {
    // (settings)
    int64_t cap_ns = 3000000000LL;   // the longest a hold lasts
    int clean_needed = 8;            // frames in a row that lacked nothing before the picture comes back (the temporal
                                     // history's few frames made good)
    int quiet_draws = 150, quiet_frames = 15, busy_draws = 400;
    // (state)
    int quiet = 0;
    bool loading = false, holding = false;
    int clean = 0;
    int64_t since = 0;
    int64_t hidden = 0;   // frames hidden by the current (or last) hold
    int64_t load_since = -1;   // (the first of a load's frames hidden; -1 none yet)
    /// A present: its frame's draws and the draws it left out or found not ready (misses); now_ns; enabled: the preparation
    /// runs behind the game. True: this frame is hidden
    bool frame(int64_t draws, int64_t misses, int64_t now_ns, bool enabled) {
        if (!enabled) {
            quiet = 0, loading = false, holding = false, load_since = -1;
            return false;
        }
        if (holding) {
            clean = misses == 0 ? clean + 1 : 0;
            if (clean >= clean_needed || now_ns - since >= cap_ns) {
                holding = false;
                return false;
            }
            hidden++;
            return true;
        }
        if (draws < quiet_draws) {
            if (++quiet >= quiet_frames) loading = true;
            if (loading && misses > 0) {   // (a load's frame lacking something: the last picture stays, up to the cap)
                if (load_since < 0) load_since = now_ns;
                if (now_ns - load_since < cap_ns) return hidden++, true;
            }
            return false;
        }
        quiet = 0;
        load_since = -1;
        if (loading && draws >= busy_draws) {
            loading = false;
            if (misses == 0) return false;   // (the area's first frame lacked nothing: nothing to hold)
            holding = true, since = now_ns, clean = 0, hidden = 1;
            return true;
        }
        if (draws >= busy_draws) loading = false;
        return false;
    }
};

// ---- the progress record: the next start goes on where this one stopped ----
/// The parts of the preparation, in their order. Before play All does every one; Most the programs (with the listed compute programs'
/// variants alone) and the noted pipelines, and leaves the other compute variants and the predicted pipelines to the game's time;
/// Later leaves all of them to it
enum Part { kPrograms = 0, kComputeRest = 1, kPredicted = 2, kNoted = 3, kDone = 4, kParts = 4 };
/// hookshot_prepare_play.txt beside the game: what the work behind the game has done, for which translator and seed (another starts
/// again). part: the one under way (kDone: all of it). at: how many of its items, in order, are done
struct Progress {
    uint64_t stamp = 0;
    int phase = 0;
    uint64_t at = 0;
    uint64_t list = 0;   // (the part's item list, hashed: a list that changed since (play notes more pipelines) starts the part again)
};
inline std::string progress_text(const Progress& p) {
    char b[128];
    snprintf(b, sizeof b, "stamp=%016llx\nphase=%d\nat=%llu\nlist=%016llx\n", (unsigned long long)p.stamp, p.phase,
             (unsigned long long)p.at, (unsigned long long)p.list);
    return b;
}
/// Where a part resumes: at the record's item when the record is of this part and of the same list, else at its first
inline uint64_t resume_at(const Progress& p, int part, uint64_t list) {
    return p.phase == part && p.list == list ? p.at : 0;
}
/// A list's hash (FNV-1a over its keys, in order)
inline uint64_t list_hash(const uint64_t* keys, size_t n) {
    uint64_t h = 0xcbf29ce484222325ull;
    for (size_t i = 0; i < n; i++)
        for (int b = 0; b < 64; b += 8) h = (h ^ ((keys[i] >> b) & 0xff)) * 0x100000001b3ull;
    return h;
}
/// The record from its text, for this stamp: another stamp's, or none, starts at the beginning (phase -1: no record)
inline Progress progress_parse(const char* text, uint64_t stamp) {
    Progress p;
    p.stamp = stamp, p.phase = -1;
    if (!text) return p;
    const char* a = strstr(text, "stamp="), *b = strstr(text, "phase="), *c = strstr(text, "at=");
    if (!a || !b || !c) return p;
    const unsigned long long s = strtoull(a + 6, nullptr, 16), at = strtoull(c + 3, nullptr, 10);
    const int phase = atoi(b + 6);
    if (s != stamp || phase < 0 || phase > kDone) return p;
    p.phase = phase, p.at = phase == kDone ? 0 : at;
    if (const char* d = strstr(text, "list=")) p.list = strtoull(d + 5, nullptr, 16);
    return p;
}
/// The part the work behind the game starts at, for a level and a record (phase -1: none): Most starts at the other compute variants
/// (the programs are translated before play), Later at the programs; never before where the record got to
inline int first_part(Level level, int recorded) {
    const int from = level == Level::Later ? kPrograms : kComputeRest;
    return std::max(from, recorded);
}
/// What a start on Most finds left to do behind the game, from the record (phase -1: none, or unreadable): with no record, all of
/// what Most leaves (a folder prepared before these choices, or a lost record: the parts redo quickly from the caches); a driver
/// change since (driver_changed) needs the predicted pipelines again. kDone: nothing
inline int most_left(int recorded, bool driver_changed) {
    int left = recorded < 0 ? kComputeRest : recorded;
    if (driver_changed && left > kPredicted) left = kPredicted;
    return left;
}
/// In a part whose items finish out of order (several threads), how many from the first are all done: done[i] for each item
inline uint64_t done_prefix(const std::atomic<uint8_t>* done, uint64_t n, uint64_t from) {
    uint64_t k = from;
    while (k < n && done[k].load(std::memory_order_acquire)) k++;
    return k;
}

/// The overlay's percentage over the parts the work behind the game does (from first on): each weighted by its count and its cost
/// (a program 1, a compute program's variants 4, a predicted pipeline 2, a noted one 2), the counts guessed before a part has its own
inline int percent(int first, int phase, uint64_t done, uint64_t total, const uint64_t counts[kParts]) {
    static const double cost[kParts] = {1, 4, 2, 2};
    double all = 0, before = 0;
    for (int k = first; k < kParts; k++) all += cost[k] * (double)counts[k];
    for (int k = first; k < std::min(phase, (int)kParts); k++) before += cost[k] * (double)counts[k];
    if (phase >= kDone) return 100;
    if (all <= 0) return 0;
    const double in = total && phase >= first ? cost[phase] * (double)counts[phase] * std::min(1.0, (double)done / (double)total) : 0;
    return std::clamp((int)((before + in) * 100.0 / all), 0, 99);
}

} // namespace prepare_play
