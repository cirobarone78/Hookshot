#pragma once
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <new>

namespace mkwvk {
// CPU copies of uncached submit buffers. Claim the budget before allocating so
// concurrent submitters cannot exceed it; failure leaves the mapped path usable.
class CaptureCpuSnapshot {
    inline static std::atomic<uint64_t> live{0};
    std::unique_ptr<uint8_t[]> data;
    uint64_t size = 0;
public:
    static constexpr uint64_t max_capture = 128ull << 20;
    static constexpr uint64_t max_total = 256ull << 20;
    CaptureCpuSnapshot() = default;
    CaptureCpuSnapshot(const CaptureCpuSnapshot&) = delete;
    CaptureCpuSnapshot& operator=(const CaptureCpuSnapshot&) = delete;
    ~CaptureCpuSnapshot() { reset(); }
    void reset() {
        data.reset();
        if (size) live.fetch_sub(size, std::memory_order_relaxed);
        size = 0;
    }
    bool allocate(uint64_t bytes) {
        reset();
        if (!bytes || bytes > max_capture) return false;
        uint64_t used = live.load(std::memory_order_relaxed);
        for (;;) {
            if (used > max_total - bytes) return false;
            if (live.compare_exchange_weak(used, used + bytes, std::memory_order_relaxed)) break;
        }
        data.reset(new (std::nothrow) uint8_t[(size_t)bytes]);
        if (!data) {
            live.fetch_sub(bytes, std::memory_order_relaxed);
            return false;
        }
        size = bytes;
        return true;
    }
    uint8_t* get() const { return data.get(); }
    explicit operator bool() const { return data != nullptr; }
    static uint64_t live_bytes() { return live.load(std::memory_order_relaxed); }
};
} // namespace mkwvk
