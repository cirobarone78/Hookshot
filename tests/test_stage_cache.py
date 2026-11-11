"""Shader lowering reuse must compare bytes, including constants, even on hash collisions."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''
#include "vk_stage_cache.h"
#include <cassert>
int main() {
    uint8_t ctl[4] = {1, 2, 3, 4};
    std::vector<uint8_t> a{1, 2, 3}, b{1, 2, 4};
    mkwvk::StageCache<int, 4> cache(1024, 2);
    assert(!cache.find(7, ctl, a));
    cache.insert(7, ctl, a, 42, 0);
    assert(*cache.find(7, ctl, a) == 42);
    assert(!cache.find(7, ctl, b)); // code or constant changed, same hash
    ctl[0] = 9;
    assert(!cache.find(7, ctl, a)); // control/workgroup/header changed
    cache.insert(7, ctl, a, 43, 0);
    assert(*cache.find(7, ctl, a) == 43);
    ctl[0] = 1;
    assert(*cache.find(7, ctl, a) == 42); // collision entries stay distinct
    cache.insert(8, ctl, b, 44, 2000); // too large: does not evict others
    assert(*cache.find(7, ctl, a) == 42);
    cache.insert(8, ctl, b, 44, 0); // count limit evicts bounded cache
    assert(!cache.find(7, ctl, a));
    assert(*cache.find(8, ctl, b) == 44);
    assert(cache.bytes() <= 1024);
    mkwvk::StageCache<int, 4> tiny(1);
    tiny.insert(7, ctl, a, 42, 0);
    assert(!tiny.find(7, ctl, a));
    mkwvk::StageCache<int, 4> budget(200);
    budget.insert(1, ctl, a, 1, 100);
    budget.insert(2, ctl, a, 2, 100);
    assert(!budget.find(1, ctl, a));
    assert(*budget.find(2, ctl, a) == 2);
}
'''
with tempfile.TemporaryDirectory() as tmp:
    source = Path(tmp) / 'test.cpp'
    exe = Path(tmp) / ('test.exe' if os.name == 'nt' else 'test')
    source.write_text(SOURCE)
    subprocess.run([os.environ.get('CXX', 'g++'), '-std=c++20', '-Wall', '-Wextra', '-Werror',
                    '-I' + str(ROOT / 'gpu/vk'), str(source), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('PASS: exact stage identity, collisions, oversized input and bounded eviction')

# Exercise the production read path, not just the container: every lookup must
# obtain current input bytes from the read callback before skipping lowering.
shader = (ROOT / 'gpu/vk/vk_shader.cpp').read_text()
start = shader.index('Code read_code(')
end = shader.index('\n}\n', start) + 2
read_code = shader[start:end]
PREFIX = r'''
#include "vk_stage_cache.h"
#include <cassert>
#include <cstdio>
#include <cstdlib>
using namespace mkwvk;
constexpr uint32_t kControlSize = 4;
struct Code { bool ok = false; std::vector<uint64_t> code; std::vector<uint8_t> c1; };
struct nvn_stage_data { uint64_t control, data; };
uint8_t control[4] = {1,2,3,4};
std::vector<uint8_t> bytes{1,2,3};
bool readable = true;
int reads = 0, lowered = 0;
struct Host {
    bool gpu_read(uint64_t address, void* out, size_t size) {
        ++reads;
        if (!readable) return false;
        std::memcpy(out, address % 2 ? control : bytes.data(), size);
        return true;
    }
} instance, *host = &instance;
bool control_end(const uint8_t*, uint32_t* end) { *end = 3; return true; }
uint64_t code_key(const uint8_t*, const uint8_t*, uint32_t) { return 7; } // collision on purpose
void logf(const char*, ...) {}
Code parse_code(const uint8_t* ctl, const std::vector<uint8_t>& area) {
    ++lowered;
    return {true, {area[0], ctl[0]}, area};
}
'''
SUFFIX = r'''
int main() {
    const bool enabled = !std::getenv("RX_VK_STAGE_CACHE") || std::atoi(std::getenv("RX_VK_STAGE_CACHE")) != 0;
    auto first = read_code({1,2});
    assert(first.ok && lowered == 1);
    auto shared = read_code({3,4});
    assert(shared.code == first.code && lowered == (enabled ? 1 : 2) && reads == 4);
    bytes[0] = 9;
    auto changed = read_code({1,2});
    assert(changed.code[0] == 9 && lowered == (enabled ? 2 : 3));
    control[0] = 8;
    assert(read_code({1,2}).code[1] == 8 && lowered == (enabled ? 3 : 4));
    readable = false;
    assert(!read_code({1,2}).ok && lowered == (enabled ? 3 : 4));
}
'''
with tempfile.TemporaryDirectory() as tmp:
    source = Path(tmp) / 'read.cpp'
    exe = Path(tmp) / ('read.exe' if os.name == 'nt' else 'read')
    source.write_text(PREFIX + read_code + SUFFIX)
    subprocess.run([os.environ.get('CXX', 'g++'), '-std=c++20', '-Wall', '-Wextra', '-Werror',
                    '-I' + str(ROOT / 'gpu/vk'), str(source), '-o', str(exe)], check=True)
    env = {k: v for k, v in os.environ.items() if k not in ('RX_VK_STAGE_CACHE', 'RX_VK_DUMP_STAGES')}
    for enabled in ('0', '1'):
        subprocess.run([str(exe)], env=dict(env, RX_VK_STAGE_CACHE=enabled), check=True)
print('PASS: production reads current bytes, reuses lowering across addresses, refuses unreadable stages; A/B off path')
