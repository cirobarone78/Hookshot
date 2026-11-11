"""Exercise the production progress-poll flush with batching on and off."""
import os
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / 'gpu/vk/vk_replay.cpp').read_text()
a = source.index('void queue_flush_poll() {')
function = source[a:source.index('\n} // namespace', a)]
prefix = r'''
#include <cassert>
#include <chrono>
#include <cstdlib>
#include <mutex>
#include <vector>
struct Mutex {
    int locks = 0;
    void lock() { ++locks; }
    void unlock() {}
};
struct { Mutex present_mu; } dev;
struct { std::vector<int> cbs; } pend;
bool enabled = false;
bool batch_on() { return enabled; }
auto pend_since = std::chrono::steady_clock::now();
int flush_reason = 0, flushes = 0;
constexpr int FR_POLL = 7;
void queue_flush_locked() {
    assert(enabled && !pend.cbs.empty());
    assert(flush_reason == FR_POLL);
    ++flushes;
    pend.cbs.clear();
}
'''
suffix = r'''
int main() {
    queue_flush_poll();
    assert(dev.present_mu.locks == 0 && flushes == 0);
    enabled = true;
    queue_flush_poll();
    assert(dev.present_mu.locks == 1 && flushes == 0);
    pend.cbs.push_back(1);
    // A future origin guarantees this batch is younger than any positive limit.
    pend_since = std::chrono::steady_clock::now() + std::chrono::hours(1);
    queue_flush_poll();
    bool immediate = std::atoll(std::getenv("RX_VK_BATCH_POLL_US")) <= 0;
    assert(flushes == (immediate ? 1 : 0));
    assert(pend.cbs.empty() == immediate);
    if (pend.cbs.empty()) pend.cbs.push_back(2);
    pend_since = std::chrono::steady_clock::now() - std::chrono::hours(1);
    queue_flush_poll();
    assert(flushes == (immediate ? 2 : 1) && pend.cbs.empty());
    assert(dev.present_mu.locks == 3);
}
'''
with tempfile.TemporaryDirectory() as tmp:
    cpp = Path(tmp) / 'test.cpp'
    exe = Path(tmp) / 'test'
    cpp.write_text(prefix + function + suffix)
    subprocess.run([os.environ.get('CXX', 'g++'), '-std=c++17', str(cpp), '-o', str(exe)], check=True)
    for delay in ('2000', '0', '-1'):
        subprocess.run([str(exe)], env={**os.environ, 'RX_VK_BATCH_POLL_US': delay}, check=True)
print('batch progress polling: passed')
