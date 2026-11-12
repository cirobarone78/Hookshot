"""HOS_HLE_STATS=1 counts every HLE function's calls (host/hos.h's HLE macro), every host call and every call of the sdk's
NVN exports (host/nvn_native.c nvn2_dispatch), and logs every 5 s how often each ran (host/hos_hostcall.c), in the lines
scripts/cpu_report.py --calls reads. Off (the default) nothing is counted and host calls keep their direct path. The real
macro and the real host-call and dispatch code are compiled with stubs for the rest of the runtime; the report is read
with cpu_report.py's own parser, with another thread's line logged in between. Six broken variants must fail.

python -I -B tests/test_hle_stats.py [--cxx clang++]
"""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
# (env_on, the switches' rule, before the code cut out of the sources)
ENV_ON_H = str(ROOT / "gpu" / "vk" / "compat" / "hookshot_env.h")
LONG_NAME = "_ZN2nn5audio42SetI3dl2ReverbLateReverbDecayHighFrequencyRatioEPNS0_15I3dl2ReverbTypeEf"
MANY = 200   # (host calls called once each: more rows than any fixed cap)


def cut(source, start, end, what):
    if start not in source:
        raise SystemExit("FAIL: %s: the anchor %r is gone: update the test" % (what, start))
    i = source.index(start)
    if end not in source[i:]:
        raise SystemExit("FAIL: %s: the anchor %r is gone: update the test" % (what, end))
    return source[i:source.index(end, i)]


def hle_macro(header):
    """hos.h's counter type, switch and HLE macro (the macro's continued lines and the one after)"""
    part = cut(header, "typedef struct HleCount", "#define HLE(sym)", "host/hos.h")
    rest = header[header.index("#define HLE(sym)"):].split("\n")
    n = 0
    while rest[n].endswith("\\"):
        n += 1
    return part + "\n".join(rest[:n + 1]) + "\n"


HARNESS = r"""
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef int32_t LONG;   /* (as Windows' LONG and host/posix/windows.h's) */
typedef uint32_t ULONG;
typedef unsigned long DWORD;
typedef void *PVOID;
#define WINAPI
typedef struct { int x; } SRWLOCK;
#define SRWLOCK_INIT {0}
static void AcquireSRWLockExclusive(SRWLOCK *l) { (void)l; }
static void ReleaseSRWLockExclusive(SRWLOCK *l) { (void)l; }
/* (wrapping, as the interlocked operations do) */
static LONG InterlockedIncrement(volatile LONG *p) { return *p = (LONG)((ULONG)*p + 1); }
static long InterlockedIncrement(volatile long *p) { return *p = (long)((unsigned long)*p + 1); }
static long InterlockedExchange(volatile long *p, long v) { long o = *p; *p = v; return o; }
static void *InterlockedCompareExchangePointer(void *volatile *p, void *x, void *c) { void *v = *p; if (v == c) *p = x; return v; }
static DWORD GetCurrentThreadId(void) { return 1; }
static void Sleep(DWORD ms) { (void)ms; }
typedef DWORD (*Start)(void *);
static Start started;
static void *CreateThread(void *a, size_t s, Start fn, void *p, DWORD f, DWORD *id) { (void)a; (void)s; (void)p; (void)f; (void)id; started = fn; return (void *)1; }
static void hos_log(const char *fmt, ...) {
    va_list a;
    va_start(a, fmt);
    vprintf(fmt, a);
    va_end(a);
    printf("\n");
    if (strstr(fmt, "calls of")) puts("vcores: another thread's line");   /* (logged between a report's head and rows) */
}
static void hos_fatal(void *c, const char *m) { (void)c; puts(m); exit(3); }
static int hos_self(void) { return 0; }
static const char *hos_thread_name(int t) { (void)t; return "main"; }
typedef struct { uint64_t x[31]; } Ctx;
typedef void (*A64Fn)(Ctx *c);
void hos_setjmp_return(Ctx *c, uint64_t target) { (void)c; (void)target; }
int hos_trace;
HLE_MACRO
HOSTCALL
uint64_t hos_hostcall(const char *name, HostFn fn, void *user);
static void submit(Ctx *c, void *user);
static uint64_t nvn_native_proc(const char *name) { return hos_hostcall(name, submit, NULL); }
DISPATCH
HLE(_ZN2nn2os9LockMutexEPNS0_9MutexTypeE) { c->x[0] += 1; }
HLE(_ZN2nn2os11UnlockMutexEPNS0_9MutexTypeE) { c->x[0] += 2; }
HLE(LONG_NAME) { c->x[0] += 4; }
static int submits;
static void submit(Ctx *c, void *user) { (void)c; (void)user; submits++; }
static void call_host(Ctx *c, uint64_t addr) {   /* (as lifted code does: the direct function a64_lookup gave, else a64_call_miss) */
    const A64Fn direct = a64_lookup_host(addr);
    if (direct) direct(c);
    else a64_call_miss(c, addr);
}
int main(int argc, char **argv) {
    const int on = argc > 1;
    if (on) hos_hle_stats_start();   /* (hos_main.c: before the game, so before any host-call lookup) */
    if (on != (started != NULL)) { puts("FAIL: the 5 s thread started without HOS_HLE_STATS, or not with it"); return 1; }
    Ctx c = {{0}};
    for (int i = 0; i < 30; i++) imp__ZN2nn2os9LockMutexEPNS0_9MutexTypeE(&c);
    for (int i = 0; i < 10; i++) imp__ZN2nn2os11UnlockMutexEPNS0_9MutexTypeE(&c);
    imp_LONG_NAME(&c);
    if (c.x[0] != 30 + 20 + 4) { puts("FAIL: an HLE function's body did not run once a call"); return 1; }
    const uint64_t addr = hos_hostcall("nvnQueueSubmit", submit, NULL);
    printf("direct %d\n", a64_lookup_host(addr) != NULL);
    for (int i = 0; i < 7; i++) call_host(&c, addr);
    static void *k[2];   /* (gen/nvn2_exports.c: an sdk NVN export's cache) */
    for (int i = 0; i < 3; i++) nvn2_dispatch(&c, "nvnQueueSubmit", k);
    for (int i = 0; i < MANY; i++) {
        char name[16];
        snprintf(name, sizeof name, "h%03d", i);
        call_host(&c, hos_hostcall(name, submit, NULL));
    }
    if (submits != 10 + MANY) { puts("FAIL: a host call did not run"); return 1; }
    hos_hle_report();
    puts("---");
    imp__ZN2nn2os11UnlockMutexEPNS0_9MutexTypeE(&c);
    calls[0].calls = calls[0].before = 0x7FFFFFFE;   /* (nvnQueueSubmit's count passes the 32-bit maximum) */
    for (int i = 0; i < 3; i++) call_host(&c, addr);
    hos_hle_report();
    return 0;
}
"""


def load_parser():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("cpu_report", ROOT / "scripts" / "cpu_report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse(hle_calls, folder, block):
    """the report as cpu_report.py reads it: (head numbers, {name: calls in the 5 s}, names in printed order)"""
    head = re.search(r"hle: (\d+) calls of (\d+) functions in ([0-9.]+) s", block)
    (folder / "game.log").write_text(block, encoding="utf-8")
    rates, secs = hle_calls(str(folder), blocks=1)
    order = [name.strip() for line in block.splitlines() if re.search(r"hle:( \d+ [^;]+;)+\s*$", line)
             for _, name in re.findall(r"(\d+) ([^;]+?)(?:;|$)", line.split("hle: ", 1)[1])]
    rows = {k: round(v * secs) for k, v in rates.items()} if rates else {}
    return head and (int(head.group(1)), int(head.group(2)), float(head.group(3))), rows, order


def check(hle_calls, folder, out, on):
    """what is wrong with one run's output, or None"""
    first, _, second = out.partition("---\n")
    direct = "direct 1" in first
    head, rows, order = parse(hle_calls, folder, first)
    if not on:
        if not direct:
            return "off: a host call lost its direct path"
        if head != (0, 0, 5.0) or rows:
            return "off: something was counted: %r %r" % (head, rows)
        return None
    if direct:
        return "on: a host call kept its direct path (not counted)"
    want = {"_ZN2nn2os9LockMutexEPNS0_9MutexTypeE": 30, "_ZN2nn2os11UnlockMutexEPNS0_9MutexTypeE": 10,
            "nvnQueueSubmit": 10, LONG_NAME[:64]: 1}
    want.update(("h%03d" % i, 1) for i in range(MANY))
    if head != (51 + MANY, 4 + MANY, 5.0) or rows != want:
        missing = {k: (rows.get(k), v) for k, v in want.items() if rows.get(k) != v}
        return "on: the first report reads %r, %d rows; wrong or missing: %r" % (head, len(rows), dict(list(missing.items())[:6]))
    counts = [want[n] for n in order]
    if counts != sorted(counts, reverse=True):
        return "on: not the most called first: %r" % order[:6]
    head, rows, _ = parse(hle_calls, folder, second)
    if head != (4, 2, 5.0) or rows != {"_ZN2nn2os11UnlockMutexEPNS0_9MutexTypeE": 1, "nvnQueueSubmit": 3}:
        return "on: the second report is not the calls since the first (3 across the 32-bit wrap): %r %r" % (head, rows)
    return None


def run(compiler, folder, hle_calls, sources, tag):
    """None when both runs read right, else what went wrong"""
    header, hostcall, dispatch = sources
    src = (HARNESS.replace("HLE_MACRO", hle_macro(header)).replace("HOSTCALL", hostcall).replace("DISPATCH", dispatch)
           .replace("LONG_NAME", LONG_NAME).replace("MANY", str(MANY)))
    (folder / (tag + ".cpp")).write_text(src, encoding="utf-8")
    exe = folder / (tag + (".exe" if os.name == "nt" else ""))
    subprocess.run([compiler, "-std=c++17", "-include", ENV_ON_H, "-O1", "-w", str(folder / (tag + ".cpp")), "-o",
                    str(exe)], check=True, timeout=120)
    for on in (False, True):
        result = subprocess.run([str(exe)] + (["on"] if on else []), capture_output=True, text=True, timeout=30)
        if result.returncode:
            return result.stdout.strip()[-300:] or "exit %d" % result.returncode
        wrong = check(hle_calls, folder, result.stdout, on)
        if wrong:
            return wrong
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    compiler = shutil.which(args.cxx)
    if not compiler:
        raise SystemExit("C++ compiler not found: " + args.cxx)
    report = load_parser()
    hle_calls = report.hle_calls
    # (an HLE body the compiler did not inline is the symbol hle_<sym> in the linker map: the report names it as its
    # imp_<sym> entry, so its samples meet its call counts)
    with tempfile.TemporaryDirectory(prefix="hle-map-") as temporary:
        path = Path(temporary) / "hookshot.map"
        path.write_text("Preferred load address is 0000000140000000\n"
                        " 0001:00001000       hle__ZN2nn2os9LockMutexEPNS0_9MutexTypeE 0000000140002000 f   nn_os_sync.o\n"
                        " 0001:00001100       imp__ZN2nn2os9LockMutexEPNS0_9MutexTypeE 0000000140002100 f   nn_os_sync.o\n",
                        encoding="utf-8")
        names = [n for n, _ in report.load_map(str(path))[1]]
    if names != ["imp__ZN2nn2os9LockMutexEPNS0_9MutexTypeE"] * 2:
        raise SystemExit("FAIL: cpu_report.py names an HLE body not inlined %r, not as its imp_ entry" % names)
    header = (ROOT / "host" / "hos.h").read_text(encoding="utf-8")
    hostcall = cut((ROOT / "host" / "hos_hostcall.c").read_text(encoding="utf-8"), "#define HOS_HOSTCALL_BASE",
                   "/* Call guest code from inside a host function", "host/hos_hostcall.c")
    dispatch = cut((ROOT / "host" / "nvn_native.c").read_text(encoding="utf-8"), "static void nvn2_counted(",
                   "/* nvnBootstrapLoader", "host/nvn_native.c")
    main_c = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    if not re.search(r'if \(env_on\("HOS_HLE_STATS"\)\) \{\s*void hos_hle_stats_start\(void\);\s*hos_hle_stats_start\(\);',
                     main_c):
        raise SystemExit("FAIL: host/hos_main.c no longer starts the counters on HOS_HLE_STATS (env_on)")
    if main_c.index('env_on("HOS_HLE_STATS")') > main_c.index("if (!reserve_guest())"):
        raise SystemExit("FAIL: host/hos_main.c starts the counters after the game's memory is set up")

    real = (header, hostcall, dispatch)
    edits = (("an HLE macro that never counts", 0, "if (hos_hle_stats) hos_hle_counted(", "if (0) hos_hle_counted("),
             ("an HLE macro that counts with the switch off", 0, "if (hos_hle_stats) hos_hle_counted(", "if (1) hos_hle_counted("),
             ("host calls kept direct with the switch on", 1, '|| hos_trace || hos_hle_stats || env_on("HOS_HOSTCALL_SLOW")',
              '|| hos_trace || env_on("HOS_HOSTCALL_SLOW")'),
             ("NVN exports not counted", 2, "&& hos_hle_stats) fn = nvn2_counted", "&& 0) fn = nvn2_counted"),
             ("a report capped at 150 rows", 1, "for (int i = 0; i < n; i++) {", "for (int i = 0; i < n && i < 150; i++) {"),
             ("a count compared signed (skipped across the wrap)", 1,
              "const unsigned long d = (ULONG)now - (ULONG)calls[i].before;",
              "const unsigned long d = now > calls[i].before ? (ULONG)now - (ULONG)calls[i].before : 0;"))
    with tempfile.TemporaryDirectory(prefix="hle-stats-") as temporary:
        folder = Path(temporary)
        wrong = run(compiler, folder, hle_calls, real, "real")
        if wrong:
            raise SystemExit("FAIL: " + wrong)
        for i, (what, which, old, new) in enumerate(edits):
            if old not in real[which]:
                raise SystemExit("FAIL: the broken variant '%s' lost its anchor %r: update the test" % (what, old))
            broken = list(real)
            broken[which] = broken[which].replace(old, new, 1)
            if not run(compiler, folder, hle_calls, broken, "broken%d" % i):
                raise SystemExit("FAIL: the check passed " + what)
    print("PASS: HOS_HLE_STATS off counts nothing and keeps host calls direct; on, every HLE function, host call and NVN "
          "export call is counted, and each 5 s report, read by cpu_report.py with another line in between, has every "
          "function's calls since the last (across the 32-bit wrap), most called first, names cut at 64 characters; "
          "%d broken variants caught" % len(edits))


if __name__ == "__main__":
    main()
