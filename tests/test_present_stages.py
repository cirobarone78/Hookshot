"""Exercise the production stage collector with a deterministic clock and log sink."""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ['--cxx', '{cxx}']

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cxx', default='g++')
    args = parser.parse_args()
    source = (ROOT / 'gpu/vk/vk_replay.cpp').read_text()
    collector = source[source.index('struct PresentStageSample {'):source.index('std::mutex present_image_mu;')]
    fixture = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdarg>
#include <string>
#include <vector>
static int64_t clock_ns;
static int clock_reads;
static std::vector<std::string> logs;
int64_t prof_now() { ++clock_reads; return clock_ns; }
void logf(const char* format, ...) {
    char text[256]; va_list args; va_start(args, format);
    vsnprintf(text, sizeof(text), format, args); va_end(args);
    logs.emplace_back(text);
}
''' + collector + r'''
int main() {
    for (int i = 0; i < 120; ++i) {
        PresentStageSample s(false, 0);
        s.mark(PresentStageSample::Present);
    }
    assert(clock_reads == 0 && logs.empty());
    for (int i = 0; i < 120; ++i) {
        clock_ns = 0;
        PresentStageSample s(true, 0);
        clock_ns = 1000000; s.mark(PresentStageSample::Lock);
        // Half the calls leave after acquisition, without an accepted present.
        clock_ns = 3000000; s.mark(PresentStageSample::Acquire);
        if (i % 2 == 0) continue;
        clock_ns = 6000000; s.mark(PresentStageSample::Present);
        s.shown = true;
    }
    assert(logs.size() == 11);
    assert(logs[0].find("120 calls, 60 accepted presents") != std::string::npos);
    assert(logs[1] == "vk: present stage lock 1.000/1.000");
    assert(logs[4] == "vk: present stage acquire 2.000/2.000");
    assert(logs[9] == "vk: present stage present 1.500/3.000");
    logs.clear();
    for (int i = 0; i < 120; ++i) { PresentStageSample s(true, 0); }
    assert(logs[0].find("120 calls, 0 accepted presents") != std::string::npos);
    assert(logs[9] == "vk: present stage present 0.000/0.000");
}
'''
    with tempfile.TemporaryDirectory(prefix='present-stages-') as tmp:
        folder = Path(tmp)
        (folder / 'test.cpp').write_text(fixture)
        exe = folder / 'test.exe'
        subprocess.run([args.cxx, '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                        str(folder / 'test.cpp'), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print('PASS: disabled clock, early returns, stage means/maxima and batch reset')


if __name__ == '__main__':
    main()
