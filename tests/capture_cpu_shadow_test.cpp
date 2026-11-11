// Authored inputs. The .inc files contain the production capture operations.
#include <cassert>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <new>
#include <vector>
#include "vk_capture_cpu.h"

// Deterministic pressure fallback: only the non-throwing snapshot allocation fails.
void* operator new[](size_t size, const std::nothrow_t&) noexcept {
    if (getenv("CAPTURE_TEST_ALLOC_FAIL")) return nullptr;
    try { return ::operator new[](size); }
    catch (const std::bad_alloc&) { return nullptr; }
}

struct Capture {
    std::vector<uint32_t> pages, copied, slots, late;
    mkwvk::CaptureCpuSnapshot cpu;
    void* map;
    int alloc = 0;
    size_t nbytes = 12288;
    uint64_t late_value = 0;
};
uint8_t guest[12288];
bool waited = false;
bool all_valid = getenv("CAPTURE_TEST_ALL_VALID") != nullptr;
struct Host { void* (*guest_base)(); };
void* base() { return guest; }
Host host_value{base};
Host* host = &host_value;
constexpr int kPageShift = 12;
constexpr unsigned VK_MEMORY_PROPERTY_HOST_CACHED_BIT=8;
unsigned allocation_memory_flags(int) { return getenv("CAPTURE_TEST_CACHED") ? 14 : 6; }
struct { void mark(const char*){} void finish(){} } trace, allocation;
double st_tk_late = 0;
unsigned st_tk_late_n = 0;
void flush_mapped(int, size_t) {}
void copy_pages(uint32_t* pages, int64_t n, uint8_t* out, uint8_t* ok) {
    for (int i = 0; i < n; i++) {
        if (i == 1 && !all_valid) continue; // an inaccessible page must never become a valid captured page
        memcpy(out + i * 4096, guest + pages[i] * 4096, 4096);
        ok[i] = 1;
    }
}
void vk_timeline_wait(uint64_t value) {
    assert(value == 9);
    waited = true;
    memset(guest + 8192, 0x66, 4096); // authored GPU write-back becomes visible only after its wait
}
bool guarded_copy(void* dst, const void* src, size_t size) {
    assert(waited);
    memcpy(dst, src, size);
    return true;
}
int main() {
    std::vector<std::pair<void*, const void*>> pairs;
    uint8_t mapped[12288];
    memset(mapped, 0x99, sizeof mapped);
    memset(guest, 0x33, sizeof guest);
    auto c = std::make_unique<Capture>();
    c->map = mapped;
    c->pages = {0, 1, 2};
    uint32_t* pages = c->pages.data();
    int64_t n = 3;
    std::vector<uint8_t> ok(3);
#include "capture_copy.inc"
    assert((c->copied == (all_valid ? std::vector<uint32_t>{0, 1, 2} : std::vector<uint32_t>{0, 2})));
    assert((c->slots == (all_valid ? std::vector<uint32_t>{0, 1, 2} : std::vector<uint32_t>{0, 2})));
    assert(mapped[0] == 0x33 && mapped[4096] == (all_valid ? 0x33 : 0x99) && mapped[8192] == 0x33);
    memset(guest, 0x55, sizeof guest); // post-submit CPU writes cannot change ordinary captured pages
    c->late_value = 9;
    c->late = {2};
#include "capture_late.inc"
    assert(waited);
    for (int i = 0; i < 4096; i++) {
        assert(mapped[i] == 0x33 && mapped[4096 + i] == (all_valid ? 0x33 : 0x99) && mapped[8192 + i] == 0x66);
    }
    struct Page { std::unique_ptr<uint8_t[]> b{new uint8_t[4096]}; } slot;
    for (size_t i = 0; i < c->copied.size(); i++) {
#include "capture_shadow.inc"
        for (int k = 0; k < 4096; k++) assert(slot.b[k] == (c->copied[i] == 2 ? 0x66 : 0x33));
    }
    const char* option = getenv("RX_VK_CAPTURE_CPU_UNCACHED");
    assert(bool(c->cpu) == ((option && atoi(option) != 0) && !getenv("CAPTURE_TEST_ALLOC_FAIL") && !getenv("CAPTURE_TEST_CACHED")));
    c.reset();
    assert(mkwvk::CaptureCpuSnapshot::live_bytes() == 0);
}
