"""Exercise the production pool-import reporting block without a GPU or game.

Failed/cooldown imports must never be labelled as successful imports. A long
cooldown must not flood the log or inflate the actual-attempt counter.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, default=ROOT)
parser.add_argument('--cxx', default=None)
args, remaining = parser.parse_known_args()


class ImportReportingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = args.cxx or shutil.which('g++') or shutil.which('clang++')
        if not compiler:
            raise unittest.SkipTest('no C++ compiler')
        source = (args.source / 'gpu/vk/vk_memory.cpp').read_text()
        start = source.index('        Pool p;\n        bool ok = false;')
        end = source.index('        for (uint64_t k : overlapped)', start)
        block = source[start:end]
        # Scheduler pauses must not turn the fixture's instantaneous imports into
        # "slow" imports and produce unrelated timing reports.
        block = block.replace('std::chrono::steady_clock::now()', 'TestClock::now()')
        fixture = r'''
#include <chrono>
#include <cstdint>
#include <cstdarg>
#include <cstdio>
#include <string>
#include <vector>
struct TestClock {
    static auto now() { return std::chrono::steady_clock::time_point{}; }
};
struct Pool {};
struct Range { uint64_t lo = 0x1234, hi = 0x5678; } range;
bool import_cooling = false, succeed = true;
int import_result = 0, failures = 0;
constexpr int VK_SUCCESS = 0;
const char* import_stage = "vkAllocateMemory(host pointer)";
bool import_pool(uint64_t, uint64_t, Pool&) { return succeed; }
std::vector<std::string> lines;
void logf(const char* format, ...) {
    char text[1024]; va_list ap; va_start(ap, format);
    vsnprintf(text, sizeof text, format, ap); va_end(ap);
    lines.emplace_back(text);
}
void* attempt() {
    const uint64_t lo = 0x1000, hi = 0x6000;
    const uint64_t spanned_lo = lo, spanned_hi = hi;
    auto plan = [](bool) {}; // no extra span in these reporting fixtures
''' + block + r'''
    return &range;
}
int fail(const char* why) { std::fprintf(stderr, "%s (%zu log lines)\n", why, lines.size()); return 1; }
int main(int argc, char** argv) {
    if (argc != 2) return 2;
    const std::string mode = argv[1];
    if (mode == "cooldown") {
        import_cooling = true; succeed = false;
        for (int n = 0; n < 1000000; ++n)
            if (attempt()) return fail("cooldown unexpectedly succeeded");
        if (!lines.empty()) return fail("cooldown flooded the import log");
        import_cooling = false; succeed = true;
        for (int n = 0; n < 256; ++n)
            if (!attempt()) return fail("valid import failed");
        if (lines.size() != 1 || lines[0].find("256 attempts, 256 succeeded, 0 failed, 1000000 deferred") == std::string::npos)
            return fail("cooldown counted as attempted or successful imports");
    } else if (mode == "failure") {
        succeed = false; import_result = -2;
        for (int n = 0; n < 256; ++n)
            if (attempt()) return fail("failed import unexpectedly succeeded");
        if (lines.empty() || lines.size() > 17) return fail("failure log not bounded");
        for (const auto& line : lines) {
            if (line.find("import failed") == std::string::npos ||
                line.find("vkAllocateMemory(host pointer)") == std::string::npos ||
                line.find("VkResult -2") == std::string::npos)
                return fail("failure misreported or Vulkan failure context lost");
        }
        if (lines.back().find("256 attempts, 0 succeeded, 256 failed, 0 deferred") == std::string::npos)
            return fail("wrong failed-attempt totals");
    } else if (mode == "recovery") {
        succeed = false; import_result = -2;
        for (int n = 0; n < 32; ++n) attempt();
        import_cooling = true;
        for (int n = 0; n < 1000000; ++n) attempt();
        import_cooling = false; succeed = true; import_result = 0;
        import_stage = "complete";
        for (int n = 0; n < 224; ++n)
            if (!attempt()) return fail("recovery rejected");
        if (lines.back().find("256 attempts, 224 succeeded, 32 failed, 1000000 deferred") == std::string::npos)
            return fail("recovered imports changed earlier failure totals");
    } else return 2;
    return 0;
}
'''
        cls.tmp = tempfile.TemporaryDirectory(prefix='hookshot-import-report-')
        cls.addClassCleanup(cls.tmp.cleanup)
        folder = Path(cls.tmp.name)
        src = folder / 'fixture.cpp'
        src.write_text(fixture)
        cls.binary = folder / 'fixture.exe'
        built = subprocess.run([compiler, '-std=c++20', '-O1', '-Wall', '-Wextra', '-Werror',
                                str(src), '-o', str(cls.binary)], capture_output=True, text=True)
        if built.returncode:
            raise AssertionError(built.stderr)

    def check(self, mode):
        run = subprocess.run([str(self.binary), mode], capture_output=True, text=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_cooldown_is_neither_success_nor_attempt(self):
        self.check('cooldown')

    def test_allocation_failure_preserves_stage_and_result(self):
        self.check('failure')

    def test_recovery_preserves_counts(self):
        self.check('recovery')


if __name__ == '__main__':
    unittest.main(argv=[__file__, *remaining])
