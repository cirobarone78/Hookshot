// Shader/pipeline pools count physical cores, not SMT siblings. Keep each pool's existing smaller limit.
#pragma once

#include <algorithm>
#include <atomic>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <thread>
#include <vector>

#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#elif defined(__linux__)
#include <cerrno>
#include <sched.h>
#include <set>
#endif

namespace mkwvk {

void logf(const char* fmt, ...);

inline unsigned compile_core_count_detect() {
#ifdef _WIN32
    DWORD bytes = 0;
    if (GetLogicalProcessorInformationEx(RelationProcessorCore, nullptr, &bytes) ||
        GetLastError() != ERROR_INSUFFICIENT_BUFFER || !bytes) return 0;
    std::vector<unsigned char> data(bytes);
    auto* info = reinterpret_cast<SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX*>(data.data());
    if (!GetLogicalProcessorInformationEx(RelationProcessorCore, info, &bytes)) return 0;
    // Affinity masks describe one group. Apply the process mask on single-group systems; on larger machines
    // count the core records across all groups, rather than truncating at 64 logical processors.
    DWORD_PTR allowed = 0, system = 0;
    const bool restricted = GetActiveProcessorGroupCount() == 1 &&
                            GetProcessAffinityMask(GetCurrentProcess(), &allowed, &system);
    unsigned cores = 0;
    for (size_t at = 0; at < bytes;) {
        constexpr size_t masks_at = offsetof(SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX, Processor) +
                                    offsetof(PROCESSOR_RELATIONSHIP, GroupMask);
        if (bytes - at < masks_at) return 0;
        const auto* e = reinterpret_cast<const SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX*>(data.data() + at);
        if (e->Size < masks_at || e->Size > bytes - at) return 0;
        if (e->Relationship == RelationProcessorCore) {
            const auto& p = e->Processor;
            if (!p.GroupCount || p.GroupCount > (e->Size - masks_at) / sizeof(GROUP_AFFINITY)) return 0;
            for (WORD g = 0; g < p.GroupCount; g++)
                if (p.GroupMask[g].Mask & (restricted ? allowed : ~KAFFINITY(0))) {
                    cores++;
                    break;   // one core, even if it names more than one group
                }
        }
        at += e->Size;
    }
    return cores;
#elif defined(__linux__)
    // sched_getaffinity also excludes offline CPUs and restrictions from taskset/cpusets. Grow the mask for
    // kernels configured with more than CPU_SETSIZE processors, without assuming CPU numbers are contiguous.
    for (size_t bits = CPU_SETSIZE; bits <= 1024 * 1024; bits *= 2) {
        std::vector<unsigned long> mask(bits / (8 * sizeof(unsigned long)));
        const size_t bytes = mask.size() * sizeof(unsigned long);
        const auto* set = reinterpret_cast<const cpu_set_t*>(mask.data());
        if (sched_getaffinity(0, bytes, reinterpret_cast<cpu_set_t*>(mask.data())) != 0) {
            if (errno == EINVAL) continue;
            return 0;
        }
        std::set<unsigned> cores;
        unsigned unreadable = 0;
        for (size_t cpu = 0; cpu < bits; cpu++) {
            if (!CPU_ISSET_S(cpu, bytes, set)) continue;
            // The first sibling CPU identifies a core across packages/dies. Try the older name too if the
            // current file cannot be read. An isolated missing record counts as its own core, not a reason
            // to discard the readable topology of every other CPU.
            unsigned first = 0;
            bool read = false;
            for (const char* name : {"core_cpus_list", "thread_siblings_list"}) {
                char path[160];
                std::snprintf(path, sizeof path, "/sys/devices/system/cpu/cpu%zu/topology/%s", cpu, name);
                if (FILE* f = std::fopen(path, "r")) {
                    read = std::fscanf(f, "%u", &first) == 1;
                    std::fclose(f);
                }
                if (read) break;
            }
            if (read) cores.insert(first);
            else unreadable++;
        }
        // No usable records is unknown topology. Preserve the caller's previous pool budget in that case.
        return cores.empty() ? 0 : static_cast<unsigned>(cores.size()) + unreadable;
    }
#endif
    return 0;   // unknown topology (including unsupported platforms): retain the caller's previous budget
}

// limit is the pool's existing budget, including usable_cpus()/half_cpus() and its own ceiling.
inline unsigned compile_worker_count(unsigned limit) {
    static const bool logical = [] {
        const char* value = std::getenv("RX_VK_COMPILE_LOGICAL");
        return value && std::atoi(value) != 0;
    }();
    static const unsigned cores = logical ? 0 : compile_core_count_detect();
    const unsigned workers = cores ? std::min(cores, std::max(1u, limit)) : std::max(1u, limit);
    static std::atomic<bool> warned{false};
    if (!cores && !logical && !warned.exchange(true))
        logf("vk: CPU topology not readable, using %u workers", workers);
    return workers;
}

} // namespace mkwvk
