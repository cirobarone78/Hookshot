// Authored fixture. Exercise the external layer's actual mapping implementation
// without a game, Vulkan device, window, command buffer or GPU submission.
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>
/* PROTOCOL */

static void Log(const char*, ...) {}
static unsigned maps, unmaps;
static bool failOutput;
static void* tracked_mmap(void* address, size_t size, int protection, int flags,
                          int fd, off_t offset) {
    ++maps;
    if (failOutput && offset == off_t(kHeaderBytes + kMaxFrame)) {
        errno = ENOMEM;
        return MAP_FAILED;
    }
    return mmap(address, size, protection, flags, fd, offset);
}
static int tracked_munmap(void* address, size_t size) {
    ++unmaps;
    return munmap(address, size);
}
#define mmap tracked_mmap
#define munmap tracked_munmap
/* MAPPING */
#undef mmap
#undef munmap

#ifndef HAS_SHM_CLOSE
// Test cleanup for the original source, which has no device teardown cleanup.
static void ShmClose(ShmMap& s) {
    if (s.inPixels) tracked_munmap(s.inPixels, s.mappedFrameBytes);
    if (s.outPixels) tracked_munmap(s.outPixels, s.mappedFrameBytes);
    if (s.hdr) tracked_munmap(s.hdr, kHeaderBytes);
    if (s.fd >= 0) close(s.fd);
    s = ShmMap{};
}
#endif

static ShmMap transport() {
    char path[] = "/dev/shm/hookshot-map-test-XXXXXX";
    ShmMap s;
    s.fd = mkstemp(path);
    assert(s.fd >= 0);
    assert(unlink(path) == 0);
    assert(ftruncate(s.fd, kHeaderBytes + 2 * kMaxFrame) == 0);
    s.hdr = static_cast<ShmHeader*>(mmap(nullptr, kHeaderBytes,
        PROT_READ | PROT_WRITE, MAP_SHARED, s.fd, 0));
    assert(s.hdr != MAP_FAILED);
    return s;
}

int main() {
    static_assert(sizeof(void*) == 8, "This local patch targets native 64-bit Hookshot");
    auto s = transport();
    assert(ShmMapFrames(s, 640 * 360 * 4));
    auto* input = s.inPixels;
    auto* output = s.outPixels;
    assert(reinterpret_cast<uintptr_t>(input) % 65536 == 0);
    assert(reinterpret_cast<uintptr_t>(output) % 65536 == 0);
    input[0] = 0x25;
    output[0] = 0x73;
    const unsigned originalMaps = maps, originalUnmaps = unmaps;
    for (size_t bytes : {size_t(1920 * 1080 * 4), size_t(3840 * 2160 * 8),
                         size_t(1280 * 720 * 4), kMaxFrame, size_t(640 * 360 * 4)}) {
        assert(ShmMapFrames(s, bytes));
        // An unmap/remap at the SAME address is still an invalid imported lifetime.
        assert(maps == originalMaps && unmaps == originalUnmaps);
        assert(s.inPixels == input && s.outPixels == output);
        assert(input[0] == 0x25 && output[0] == 0x73);
    }
    assert(!ShmMapFrames(s, kMaxFrame + 1));
    assert(maps == originalMaps && unmaps == originalUnmaps);
    assert(s.mappedFrameBytes >= kMaxFrame);
    input[kMaxFrame - 1] = 0x44;
    output[kMaxFrame - 1] = 0x55;
    unsigned char value = 0;
    assert(pread(s.fd, &value, 1, kHeaderBytes + kMaxFrame - 1) == 1 && value == 0x44);
    assert(pread(s.fd, &value, 1, kHeaderBytes + 2 * kMaxFrame - 1) == 1 && value == 0x55);
    // The maximum is a virtual reservation, not half a gigabyte of committed RAM.
    struct stat st{};
    assert(fstat(s.fd, &st) == 0 && st.st_blocks * 512 < 1024 * 1024);
    const int fd = s.fd;
    ShmClose(s);
    assert(fcntl(fd, F_GETFD) == -1 && errno == EBADF);
    assert(s.fd == -1 && !s.hdr && !s.inPixels && !s.outPixels);
    assert(unmaps == originalUnmaps + 3);
    ShmClose(s);
    assert(unmaps == originalUnmaps + 3);

    s = transport();
    failOutput = true;
    const unsigned beforeFailure = unmaps;
    assert(!ShmMapFrames(s, 640 * 360 * 4));
    assert(!s.inPixels && !s.outPixels && !s.mappedFrameBytes);
    assert(unmaps == beforeFailure + 1);  // discard only the partial input map
    failOutput = false;
    assert(ShmMapFrames(s, 1920 * 1080 * 4));
    ShmClose(s);
    puts("stable imports, shared pixels, sparse reservation, bounds, failure recovery and teardown: OK");
}
