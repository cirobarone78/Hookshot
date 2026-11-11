"""Exercise the production host pin policy with restricted process allowances."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


compiler = shutil.which('g++')
if not compiler:
    print('SKIP: needs g++')
    raise SystemExit(0)
source = (ROOT / 'host/hos_thread.c').read_text()
fixture = r'''
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cstdio>
#include <cassert>
#undef __linux__
#if TEST_LINUX
#define __linux__ 1
#endif
using DWORD_PTR = uint64_t;
using SRWLOCK = int;
#define SRWLOCK_INIT 0
#define THREAD_PRIORITY_LOWEST -2
#define THREAD_PRIORITY_BELOW_NORMAL -1
#define THREAD_PRIORITY_NORMAL 0
#define THREAD_PRIORITY_ABOVE_NORMAL 1
#define THREAD_PRIORITY_HIGHEST 2
static uint64_t reserved, allowed, applied;
static uint64_t hos_reserved_cpus() { return reserved; }
static void *GetCurrentProcess() { return nullptr; }
static int GetProcessAffinityMask(void *, DWORD_PTR *p, DWORD_PTR *s) { *p = *s = allowed; return 1; }
static void SetThreadAffinityMask(void *, DWORD_PTR m) { assert(m && !(m & ~allowed)); applied = m; }
static void SetThreadPriority(void *, int) {}
static void AcquireSRWLockExclusive(SRWLOCK *) {}
static void ReleaseSRWLockExclusive(SRWLOCK *) {}
typedef struct { char pat[40]; long long value; } NameSpec;
'''
for marker in ('static int parse_name_specs(', 'static const NameSpec *match_name_spec(',
               'static int render_thread_on_reserved(', 'void hos_thread_pin('):
    fixture += '\n' + block(source, marker)
fixture += r'''
int main(int argc, char **argv) {
    assert(argc == 5);
    allowed = strtoull(argv[1], nullptr, 16);
    reserved = strtoull(argv[2], nullptr, 16);
    applied = allowed;
    assert(!render_thread_on_reserved(nullptr));
    hos_thread_pin(nullptr, argv[3]);
    assert(applied == strtoull(argv[4], nullptr, 16));
}
'''
env = {k: v for k, v in os.environ.items() if k not in ('HOS_PIN', 'HOS_PIN_RENDER', 'RX_VK_ASYNC', 'HOS_PRIO')}
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    (path / 'test.cpp').write_text(fixture)
    for linux in (0, 1):
        executable = path / f'test-{linux}'
        subprocess.run([compiler, '-std=c++17', '-O2', f'-DTEST_LINUX={linux}', str(path / 'test.cpp'),
                        '-o', str(executable)], check=True)
        cases = [
            ('ffff', '8080', 'Presentation Thread', '8080' if linux else '7f7f', {}),
            ('ffff', '8080', 'MainThread', '7f7f', {}),
            ('ffff', '8080', 'Presentation Thread', '7f7f', {'HOS_PIN_RENDER': '0'}),
            ('ffff', '8080', 'Presentation Thread', '7f7f', {'RX_VK_ASYNC': '1'}),
            ('ffff', '8080', 'Presentation Thread', '8080' if linux else '7f7f', {'RX_VK_ASYNC': '0'}),
            ('7f7f', '8080', 'Presentation Thread', '7f7f', {}),
            ('ffff', '0', 'Presentation Thread', 'ffff', {}),
            ('80', '8080', 'Presentation Thread', '80', {}),
            ('ffff', '8080', 'Presentation Thread', '1', {'HOS_PIN': 'Presentation Thread=1'}),
        ]
        for allowed, reserved, name, expected, settings in cases:
            subprocess.run([str(executable), allowed, reserved, name, expected], env=env | settings, check=True)
print('PASS: Linux sync pin, async/opt-out, restricted allowance, explicit override and non-Linux policy')
