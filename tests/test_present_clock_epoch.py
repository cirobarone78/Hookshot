"""Presentation timestamps must use the host clock epoch, not calibrated TSC."""
import argparse
from pathlib import Path
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cxx', default='g++')
    args = parser.parse_args()
    clock = block((ROOT / 'gpu/vk/vk_framegen.h').read_text(), 'inline int64_t present_trace_now()')
    convert = block((ROOT / 'gpu/vk/vk_internal.h').read_text(), 'inline int64_t perf_ticks_to_ns(')
    fixture = r'''
#include <cstdint>
#include <cassert>
struct LARGE_INTEGER { int64_t QuadPart; };
int frequency_reads = 0, counter_reads = 0;
int64_t host_counter = 1234567890123LL;
void QueryPerformanceFrequency(LARGE_INTEGER* v) { ++frequency_reads; v->QuadPart=1000000000LL; }
void QueryPerformanceCounter(LARGE_INTEGER* v) { ++counter_reads; v->QuadPart=host_counter; }
int64_t prof_now() { assert(false && "TSC epoch is unrelated to the host clock"); return 0; }
''' + convert + '\n' + clock + r'''
int main() {
 assert(present_trace_now()==host_counter);
 host_counter+=12345678;
 assert(present_trace_now()==host_counter);
 assert(frequency_reads==1 && counter_reads==2);
}
'''
    with tempfile.TemporaryDirectory(prefix='present-clock-') as temp:
        source = Path(temp) / 'test.cpp'
        exe = Path(temp) / 'test'
        source.write_text(fixture)
        subprocess.run([args.cxx, '-std=c++17', '-O2', str(source), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    framegen = (ROOT / 'gpu/vk/vk_framegen.cpp').read_text()
    replay = (ROOT / 'gpu/vk/vk_replay.cpp').read_text()
    for field in ('slot->sync.worker_ns', 'slot->sync.finished_ns', 'const int64_t source_ns',
                  'native.recorded->sync.queued_ns'):
        assert field + ' = present_trace_now();' in framegen
    for field in ('present_begin_ns', 'present_end_ns'):
        assert replay.count('sync->' + field + ' = present_trace_now();') == 2
    print('PASS: host counter epoch and all native async trace sites')


if __name__ == '__main__':
    main()
