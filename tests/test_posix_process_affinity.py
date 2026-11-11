"""A thread pin must not narrow the process mask or prevent a sibling's pin."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

if sys.platform != 'linux':
    print('SKIP: Linux affinity compatibility');raise SystemExit(0)
cpus=sorted(c for c in os.sched_getaffinity(0) if c<64)[:2]
if len(cpus)<2 or not shutil.which('gcc') or not shutil.which('g++') or not shutil.which('taskset'):
    print('SKIP: needs gcc/g++/taskset and two allowed CPUs below 64');raise SystemExit(0)
root=Path(__file__).resolve().parents[1]
source=r'''
#define _GNU_SOURCE
#include <windows.h>
#include <assert.h>
#include <pthread.h>
#include <sched.h>
#include <stdint.h>
static DWORD_PTR process, first, second;
int background(uint64_t reserved);
static void* worker(void* ignored) {
    (void)ignored;
    DWORD_PTR p=0,s=0;
    assert(GetProcessAffinityMask(GetCurrentProcess(),&p,&s));
    assert(p==process); /* inherited one-CPU thread mask is not the process mask */
    assert(background(first));
    assert(SetThreadAffinityMask(GetCurrentThread(),second)==second);
    cpu_set_t current;CPU_ZERO(&current);
    assert(!pthread_getaffinity_np(pthread_self(),sizeof current,&current));
    assert(CPU_COUNT(&current)==1 && CPU_ISSET(__builtin_ctzll(second),&current));
    assert(GetProcessAffinityMask(GetCurrentProcess(),&p,&s) && p==process);
    assert(background(process)); /* all allowed CPUs reserved: retain a usable mask */
    assert(!pthread_getaffinity_np(pthread_self(),sizeof current,&current));
    assert(CPU_COUNT(&current)==2);
    assert(CPU_ISSET(__builtin_ctzll(first),&current) && CPU_ISSET(__builtin_ctzll(second),&current));
    assert(background(0));
    return NULL;
}
int main(void) {
    DWORD_PTR system=0;
    assert(GetProcessAffinityMask(GetCurrentProcess(),&process,&system));
    assert(__builtin_popcountll(process)==2);
    first=process & -process;second=process ^ first;
    assert(SetThreadAffinityMask(GetCurrentThread(),first)==process);
    DWORD_PTR p=0,s=0;
    assert(GetProcessAffinityMask(GetCurrentProcess(),&p,&s) && p==process);
    pthread_t t;assert(!pthread_create(&t,NULL,worker,NULL));assert(!pthread_join(t,NULL));
    assert(SetThreadAffinityMask(GetCurrentThread(),process)==first);
    return 0;
}
'''
with tempfile.TemporaryDirectory() as d:
    p=Path(d);(p/'test.c').write_text(source)
    flags=['-O2','-ffunction-sections','-fdata-sections','-I'+str(root/'host/posix')]
    for src,obj in [(p/'test.c',p/'test.o'),(root/'host/posix/win32_posix.c',p/'shim.o')]:
        subprocess.run(['gcc',*flags,'-c',str(src),'-o',str(obj)],check=True)
    (p/'helper.cpp').write_text('#include "vk_thread_affinity.h"\nextern "C" int background(uint64_t r) { return mkwvk::background_thread_affinity(r); }\n')
    subprocess.run(['g++','-std=c++17',*flags,'-I'+str(root/'gpu/vk'),str(p/'helper.cpp'),str(p/'test.o'),str(p/'shim.o'),
                    '-Wl,--gc-sections','-pthread','-ldl','-o',str(p/'test')],check=True)
    subprocess.run(['taskset','-c',','.join(map(str,cpus)),str(p/'test')],check=True)
print('PASS: launch restriction, main/child thread isolation and sibling CPU selection')
