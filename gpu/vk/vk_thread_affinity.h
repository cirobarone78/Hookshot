#pragma once
#include <cstdint>
#include <windows.h>
#ifndef _WIN32
#include <pthread.h>
#include <sched.h>
#endif

namespace mkwvk {
// pthreads inherit the creating thread's CPU mask, unlike Windows threads.
// Background work started by the pinned renderer must be able to use the other
// allowed cores. Never widen beyond the process's launch allowance.
inline bool background_thread_affinity(uint64_t reserved) {
#ifndef _WIN32
    DWORD_PTR allowed = 0, system = 0;
    if (!GetProcessAffinityMask(GetCurrentProcess(), &allowed, &system)) return false;
    const DWORD_PTR others = allowed & ~(DWORD_PTR)reserved;
    const DWORD_PTR mask = others ? others : allowed;
    cpu_set_t target;
    CPU_ZERO(&target);
    for (unsigned i = 0; i < sizeof(mask) * 8; ++i)
        if ((mask >> i) & 1) CPU_SET(i, &target);
    // Native pthreads have no Win32 handle to allocate or retain on exit.
    return pthread_setaffinity_np(pthread_self(), sizeof target, &target) == 0;
#else
    (void)reserved;
    return true;
#endif
}
} // namespace mkwvk
