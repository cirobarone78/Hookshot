"""Interrupt the real nonlocal-jump assembly after rsp changes, without game data."""
import argparse
from pathlib import Path
import shutil
import platform
import subprocess
import sys
import tempfile
import unittest


RUN_ALL_ARGS = ["--cc", "gcc"]
RUN_ALL_SKIP = {"windows": "Linux sampler signals and nonlocal-jump assembly"}

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--cc", default="cc")
args, remaining = parser.parse_known_args()
sys.argv = [sys.argv[0], *remaining]

@unittest.skipUnless(sys.platform.startswith('linux') and platform.machine() == 'x86_64' and shutil.which(args.cc), 'Linux C compiler required')
class LongjmpUnwindTests(unittest.TestCase):
    def test_signal_at_stack_switch(self):
        source = (Path(__file__).resolve().parents[1] / 'host/hos_setjmp.c').read_text().split('#else', 1)[1]
        start = source.index('__attribute__((naked, noreturn))')
        function = source[start:source.index('\n}', start)+2]
        function = function.replace('"jmpq *72(%rdi)\\n\\t"', '"int3\\n\\t"\n        "jmpq *72(%rdi)\\n\\t"')
        prefix = r'''
#define _GNU_SOURCE
#include <stdint.h>
#include <signal.h>
#include <unistd.h>
#include <unwind.h>
#include <sys/resource.h>
static _Unwind_Reason_Code visit(struct _Unwind_Context *c, void *p) {
    (void)c; (void)p; return _URC_NO_REASON;
}
static volatile sig_atomic_t sampled;
static void trap(int sig) { (void)sig; _Unwind_Backtrace(visit, 0); sampled = 1; }
static void finish(void) { _exit(sampled ? 0 : 1); }
'''
        suffix = r'''
int main(void) {
    struct rlimit limit={0,0}; setrlimit(RLIMIT_CORE,&limit);
    struct sigaction sa={0}; sa.sa_handler=trap; sigaction(SIGTRAP,&sa,0);
    static uintptr_t stack[4096], buf[32];
    stack[2048]=0x12345000; /* Local value, not a native return address. */
    buf[8]=(uintptr_t)&stack[2048]; buf[9]=(uintptr_t)finish;
    __asm__ volatile("stmxcsr %0" : "=m"(*(unsigned int*)((char*)buf+240)));
    __asm__ volatile("fnstcw %0" : "=m"(*(unsigned short*)((char*)buf+244)));
    recomp_sj_longjmp((void**)buf,1);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            for name, fn in [('fixed', function), ('negative', function.replace('".cfi_undefined %rip\\n\\t"', ''))]:
                with self.subTest(name=name):
                    c=Path(directory)/(name+'.c'); exe=c.with_suffix('')
                    c.write_text(prefix+fn+suffix)
                    subprocess.run([args.cc,'-O2','-fasynchronous-unwind-tables',str(c),'-o',str(exe)],check=True)
                    result=subprocess.run([str(exe)],timeout=10)
                    self.assertEqual(result.returncode, 0 if name=='fixed' else -11)


if __name__ == '__main__': unittest.main()
