"""Physical-core compilation limits: real detector plus Windows/Linux topology fixtures, without a game or GPU.

The production detector is compiled against OS stand-ins to cover SMT, hybrid/no-SMT, processor groups, restricted
affinity, sparse CPU IDs, large Linux masks and unavailable topology. A native probe checks the installed OS too.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]
ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "gpu/vk/vk_compile_threads.h"


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


COMMON = r'''
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <algorithm>
#include <atomic>
#include <cerrno>
#include <cstddef>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <set>
#include <string>
#include <vector>
// OS headers can be pulled in by <atomic>; keep stand-ins separate from native API declarations.
namespace fixture {
unsigned warnings = 0, warned_workers = 0;
void logf(const char* fmt, ...) {
    if (std::strcmp(fmt, "vk: CPU topology not readable, using %u workers")) std::abort();
    va_list args; va_start(args, fmt); warned_workers = va_arg(args, unsigned); va_end(args);
    warnings++;
}
#define CHECK(ok) do { if (!(ok)) { std::fprintf(stderr, "failed line %d\n", __LINE__); std::exit(1); } } while (0)
'''

WINDOWS = r'''
#define _WIN32 1
using DWORD = uint32_t;
using WORD = uint16_t;
using KAFFINITY = uintptr_t;
using DWORD_PTR = uintptr_t;
constexpr int RelationProcessorCore = 0, ERROR_INSUFFICIENT_BUFFER = 122;
struct GROUP_AFFINITY { KAFFINITY Mask; WORD Group; WORD Reserved[3]; };
struct PROCESSOR_RELATIONSHIP {
    unsigned char Flags, EfficiencyClass, Reserved[20];
    WORD GroupCount;
    GROUP_AFFINITY GroupMask[1];
};
struct SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX {
    int Relationship;
    DWORD Size;
    PROCESSOR_RELATIONSHIP Processor;
};
std::vector<SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX> records;
WORD groups = 1;
DWORD_PTR allowed = ~DWORD_PTR(0);
bool fail = false, short_buffer = false;
int GetLastError() { return fail ? 5 : ERROR_INSUFFICIENT_BUFFER; }
void* GetCurrentProcess() { return nullptr; }
WORD GetActiveProcessorGroupCount() { return groups; }
bool GetProcessAffinityMask(void*, DWORD_PTR* a, DWORD_PTR* s) { *a = allowed; *s = ~DWORD_PTR(0); return true; }
bool GetLogicalProcessorInformationEx(int, SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX* out, DWORD* bytes) {
    if (fail) return false;
    *bytes = static_cast<DWORD>(records.size() * sizeof(records[0]));
    if (!out) return false;
    std::memcpy(out, records.data(), *bytes);
    if (short_buffer) *bytes = 1;
    return true;
}
void add(KAFFINITY mask, WORD group = 0) {
    SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX e{};
    e.Size = sizeof e;
    e.Processor.GroupCount = 1;
    e.Processor.GroupMask[0] = {mask, group, {0, 0, 0}};
    records.push_back(e);
}
'''

WINDOWS_MAIN = r'''
int main(int argc, char**) {
    if (argc > 1) {
        FAIL_TOPOLOGY;
        CHECK(compile_core_count_detect() == 0);
        CHECK(compile_worker_count(64) == 64);
        CHECK(compile_worker_count(2) == 2); // preserve the old background minimum on unknown topology
        CHECK(compile_worker_count(4) == 4);
        CHECK(compile_worker_count(0) == 1);
        const bool logical = std::getenv("RX_VK_COMPILE_LOGICAL") != nullptr;
        CHECK(warnings == (logical ? 0u : 1u));
        if (!logical) CHECK(warned_workers == 64);
        return 0;
    }
    // Eight cores with SMT, then affinity restricted to two siblings of the SAME core.
    for (int i = 0; i < 8; i++) add(KAFFINITY(3) << (2 * i));
    CHECK(compile_core_count_detect() == 8);
    CHECK(compile_worker_count(64) == 8);
    CHECK(compile_worker_count(4) == 4);
    CHECK(compile_worker_count(0) == 1);
    allowed = 3; CHECK(compile_core_count_detect() == 1);
    allowed = 6; CHECK(compile_core_count_detect() == 2);
    allowed = ~DWORD_PTR(0);
    records.clear();
    // Hybrid: 8 P cores with SMT + 16 E cores without it = 24 physical, 32 logical.
    for (int i = 0; i < 8; i++) add(KAFFINITY(3) << (2 * i));
    for (int i = 16; i < 32; i++) add(KAFFINITY(1) << i);
    CHECK(compile_core_count_detect() == 24);
    // No SMT: keep all 8 cores, rather than blindly halving hardware_concurrency.
    records.clear();
    for (int i = 0; i < 8; i++) add(KAFFINITY(1) << i);
    CHECK(compile_core_count_detect() == 8);
    records.clear(); groups = 2; allowed = 1;
    for (WORD group = 0; group < 2; group++)
        for (int i = 0; i < 32; i++) add(KAFFINITY(3) << (2 * i), group);
    CHECK(compile_core_count_detect() == 64);  // >64 logical CPUs, not truncated to one group
    short_buffer = true; CHECK(compile_core_count_detect() == 0); short_buffer = false;
    records[0].Size = 0; CHECK(compile_core_count_detect() == 0);
    records[0].Size = sizeof(records[0]); records[0].Processor.GroupCount = 200;
    CHECK(compile_core_count_detect() == 0);
    fail = true; CHECK(compile_core_count_detect() == 0);
}
'''

LINUX = r'''
#undef _WIN32
#define __linux__ 1
constexpr size_t CPU_SETSIZE = 1024;
struct cpu_set_t {};
std::vector<unsigned> allowed;
std::map<unsigned, std::string> siblings;
bool fail_affinity = false, old_kernel = false, missing = false;
size_t required_bits = 1024;
unsigned missing_cpu = ~0u;
int sched_getaffinity(int, size_t bytes, cpu_set_t* out) {
    if (fail_affinity) { errno = EPERM; return -1; }
    if (bytes * 8 < required_bits) { errno = EINVAL; return -1; }
    auto* words = reinterpret_cast<unsigned long*>(out);
    for (unsigned cpu : allowed) words[cpu / (8 * sizeof(unsigned long))] |= 1ul << (cpu % (8 * sizeof(unsigned long)));
    return 0;
}
bool CPU_ISSET_S(size_t cpu, size_t, const cpu_set_t* in) {
    const auto* words = reinterpret_cast<const unsigned long*>(in);
    return (words[cpu / (8 * sizeof(unsigned long))] >> (cpu % (8 * sizeof(unsigned long)))) & 1;
}
FILE* topology_fopen(const char* path, const char*) {
    unsigned cpu = 0;
    CHECK(std::sscanf(path, "/sys/devices/system/cpu/cpu%u/", &cpu) == 1);
    if (cpu == missing_cpu || missing || (old_kernel && std::strstr(path, "core_cpus_list"))) return nullptr;
    FILE* f = std::tmpfile(); CHECK(f);
    const auto& text = siblings[cpu];
    std::fwrite(text.data(), 1, text.size(), f);
    std::rewind(f);
    return f;
}
'''

LINUX_MAIN = r'''
int main(int argc, char**) {
    if (argc > 1) {
        FAIL_TOPOLOGY;
        CHECK(compile_core_count_detect() == 0);
        CHECK(compile_worker_count(64) == 64);
        CHECK(compile_worker_count(2) == 2); // preserve the old background minimum on unknown topology
        CHECK(compile_worker_count(4) == 4);
        CHECK(compile_worker_count(0) == 1);
        const bool logical = std::getenv("RX_VK_COMPILE_LOGICAL") != nullptr;
        CHECK(warnings == (logical ? 0u : 1u));
        if (!logical) CHECK(warned_workers == 64);
        return 0;
    }
    // Eight physical cores, nonadjacent SMT siblings.
    for (unsigned cpu = 0; cpu < 16; cpu++) {
        allowed.push_back(cpu);
        siblings[cpu] = std::to_string(cpu % 8) + "," + std::to_string(cpu % 8 + 8);
    }
    CHECK(compile_core_count_detect() == 8);
    CHECK(compile_worker_count(64) == 8);
    CHECK(compile_worker_count(3) == 3);
    CHECK(compile_worker_count(0) == 1);
    allowed = {8, 9, 10, 11, 12, 13, 14, 15}; CHECK(compile_core_count_detect() == 8);
    allowed = {0, 8}; CHECK(compile_core_count_detect() == 1);
    allowed = {0, 9}; CHECK(compile_core_count_detect() == 2);
    // Two packages can reuse core_id; the global sibling-list CPU IDs still distinguish them.
    allowed = {0, 64, 128, 192};
    siblings[0] = siblings[128] = "0,128";
    siblings[64] = siblings[192] = "64,192";
    CHECK(compile_core_count_detect() == 2);
    old_kernel = true; CHECK(compile_core_count_detect() == 2); old_kernel = false;
    allowed = {1025, 2049}; required_bits = 4096;
    siblings[1025] = siblings[2049] = "1025,2049";
    CHECK(compile_core_count_detect() == 1);  // grow sched_getaffinity mask; sparse CPU IDs
    siblings[2049] = "2049"; CHECK(compile_core_count_detect() == 2);
    missing_cpu = 2049; CHECK(compile_core_count_detect() == 2); missing_cpu = ~0u;
    missing = true; CHECK(compile_core_count_detect() == 0); missing = false;
    siblings[1025] = "invalid"; CHECK(compile_core_count_detect() == 2);
    siblings[2049] = "invalid"; CHECK(compile_core_count_detect() == 0);
    allowed.clear(); CHECK(compile_core_count_detect() == 0);
    fail_affinity = true; CHECK(compile_core_count_detect() == 0);
    fail_affinity = false; required_bits = 2 * 1024 * 1024;
    CHECK(compile_core_count_detect() == 0); // kernel mask exceeds the bounded allocation
}
'''


def linux_fixture(text):
    # <atomic> may include the native scheduler API. Keep the fake CPU types/functions separate from it.
    for name in ("CPU_SETSIZE", "CPU_ISSET_S", "cpu_set_t", "sched_getaffinity"):
        text = text.replace(name, "fake_" + name)
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    source = HEADER.read_text(encoding="utf-8")
    detector = block(source, "inline unsigned compile_core_count_detect(")
    count = block(source, "inline unsigned compile_worker_count(")
    # Compiler pools take their existing affinity-aware budgets through the cap. Cache readers keep usable_cpus().
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    for marker in ("void state_list_prepare(", "bool warm_libraries(", "bool prepare_run(",
                   "void precompile_run(", "void predict_run("):
        body = block(draw, marker)
        if "compile_worker_count(" not in body:
            raise SystemExit(f"uncapped shader/pipeline pool: {marker}")
    for filename, marker in (("vk_jobs.cpp", "void start("),):
        body = block((ROOT / "gpu/vk" / filename).read_text(encoding="utf-8"), marker)
        if "compile_worker_count(" not in body:
            raise SystemExit(f"uncapped shader/pipeline pool: {filename} {marker}")
    cache = (ROOT / "gpu/vk/vk_progcache.cpp").read_text(encoding="utf-8")
    for marker in ("size_t program_cache_load_some(", "void program_cache_each("):
        reader = block(cache, marker)
        if "compile_worker_count(" in reader or "usable_cpus()" not in reader:
            raise SystemExit("cache readers must keep the logical usable-CPU budget")
    with tempfile.TemporaryDirectory(prefix="compile-threads-") as folder:
        folder = Path(folder)
        native = 'namespace mkwvk { void logf(const char*, ...) {} }\n#include "vk_compile_threads.h"\n#include <cstdio>\nint main() { std::printf("%u\\n", mkwvk::compile_worker_count(std::min(64u, std::max(1u, std::thread::hardware_concurrency())))); }\n'
        fixtures = {
            "windows": COMMON + WINDOWS + detector + count + WINDOWS_MAIN.replace("FAIL_TOPOLOGY", "fail = true"),
            "linux": COMMON + linux_fixture(LINUX + detector.replace("std::fopen", "topology_fopen")) + count + LINUX_MAIN.replace("FAIL_TOPOLOGY", "fail_affinity = true"),
            "unknown": COMMON + "\n#undef _WIN32\n#undef __linux__\n" + detector + count + r"""
int main() {
    CHECK(compile_core_count_detect() == 0);
    CHECK(compile_worker_count(64) == 64);
    CHECK(compile_worker_count(2) == 2);
    CHECK(compile_worker_count(0) == 1);
    const bool logical = std::getenv("RX_VK_COMPILE_LOGICAL") != nullptr;
    CHECK(warnings == (logical ? 0u : 1u));
    if (!logical) CHECK(warned_workers == 64);
}
""",
            "native": native,
        }
        for name, text in fixtures.items():
            if name != "native":
                text = text.replace("int main()", "int fixture_main(int, char**)").replace(
                    "int main(int argc, char**)", "int fixture_main(int argc, char**)")
                end = text.rfind("}")
                text = text[:end] + "    return 0;\n" + text[end:]
                text += "\n} // namespace fixture\nint main(int argc, char** argv) { return fixture::fixture_main(argc, argv); }\n"
            src = folder / (name + ".cpp")
            exe = folder / (name + ".exe")
            src.write_text(text, encoding="utf-8")
            subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-pthread", "-I", str(HEADER.parent),
                            str(src), "-o", str(exe)], check=True)
            env = {k: v for k, v in os.environ.items() if k != "RX_VK_COMPILE_LOGICAL"}
            result = subprocess.run([str(exe)], check=True, capture_output=True, text=True, timeout=15, env=env)
            if name == "native":
                actual = int(result.stdout)
                if not 1 <= actual <= min(64, os.cpu_count() or 1):
                    raise SystemExit(f"invalid native physical-core count: {actual}")
                if hasattr(os, "sched_getaffinity"):
                    cores = set()
                    for cpu in os.sched_getaffinity(0):
                        topology = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology")
                        siblings = topology / "core_cpus_list"
                        if not siblings.exists():
                            siblings = topology / "thread_siblings_list"
                        if not siblings.exists():
                            break
                        cores.add(siblings.read_text().strip())
                    else:
                        if actual != min(64, len(cores)):
                            raise SystemExit(f"native topology mismatch: {actual} workers, {len(cores)} cores")
                print(f"PASS: native compilation limit {actual} physical cores ({os.cpu_count()} logical CPUs)")
                logical = subprocess.run([str(exe)], check=True, capture_output=True, text=True, timeout=15,
                                         env=dict(env, RX_VK_COMPILE_LOGICAL="1"))
                if int(logical.stdout) != min(64, os.cpu_count() or 1):
                    raise SystemExit(f"logical-CPU A/B override mismatch: {logical.stdout}")
            else:
                for logical_env in ({}, {"RX_VK_COMPILE_LOGICAL": "1"}):
                    subprocess.run([str(exe), "fallback"], check=True, capture_output=True, text=True,
                                   timeout=15, env=dict(env, **logical_env))
                print(f"PASS: {name} topology fixtures and once-only fallback warning")


if __name__ == "__main__":
    main()
