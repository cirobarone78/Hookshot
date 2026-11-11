"""A required analysis window must fail before either rendering backend starts."""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / 'host/rx_backend.c').read_text()
start = source.index('int rx_start(void *hwnd) {')
function = source[start:source.index('\n}\n', start) + 3]
fixture = r'''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
static const char *required;
static int loads, starts, fatals, web, flushes;
static const char *test_getenv(const char *name) {
    return strcmp(name, "HOS_REQUIRE_WINDOW") == 0 ? required : NULL;
}
#define getenv test_getenv
#define _stricmp strcmp
static void hos_fatal(void *ctx, const char *fmt, ...) { (void)ctx; (void)fmt; fatals++; }
static void hos_log(const char *fmt, ...) { (void)fmt; }
typedef struct { int (*start)(void *); } MkwVkRenderer;
static int renderer_start(void *window) { (void)window; starts++; return 1; }
static MkwVkRenderer renderer = {renderer_start};
static const MkwVkRenderer *vk;
static const MkwVkRenderer *load_vulkan(const char *dll) { (void)dll; loads++; return &renderer; }
static int wgr_start(void *window) { (void)window; web++; return 1; }
static void flush_early(void) { flushes++; }
FUNCTION
int main(void) {
    required = "1";
    assert(rx_start(NULL) == 0);
    assert(fatals == 1 && loads == 0 && starts == 0 && web == 0 && flushes == 0);
    assert(rx_start((void *)1) == 1);
    assert(starts == 1 && fatals == 1 && vk == &renderer);
    required = "0";
    assert(rx_start(NULL) == 1);
    required = NULL;
    assert(rx_start(NULL) == 1);
    assert(starts == 3 && loads == 3 && flushes == 3 && fatals == 1);
    return 0;
}
'''.replace('FUNCTION', function)
parser = argparse.ArgumentParser()
parser.add_argument('--cc', default='clang')
a = parser.parse_args()
with tempfile.TemporaryDirectory(prefix='require-window-') as tmp:
    p = Path(tmp); (p / 'test.c').write_text(fixture)
    subprocess.run([a.cc, '-std=c11', '-Wall', '-Wextra', '-Werror', str(p/'test.c'), '-o', str(p/'test.exe')], check=True)
    subprocess.run([str(p/'test.exe')], check=True)
print('required window rejects offscreen fallback; optional offscreen start preserved')
