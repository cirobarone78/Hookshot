"""Run production capture fragments against authored pages, without a GPU or game."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ['--cxx', '{cxx}']

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cxx', default='g++')
    args = parser.parse_args()
    source = (ROOT / 'gpu/vk/vk_memory.cpp').read_text()
    start = source.index('            static const bool cpu_shadow =')
    copy = source[start:source.index('            c->nbytes =', start)]
    start = source.index('    if (c->late_value && c->map) {')
    late = source[start:source.index('    std::lock_guard lk(pools_mu);', start)]
    # Stop before the pool-lock timing scope; it is outside the extracted operation.
    late = late.split('    const auto tl =')[0]
    shadow = next(line.strip() for line in source.splitlines()
                  if 'pairs.push_back({slot.b.get(), (c->cpu' in line)
    with tempfile.TemporaryDirectory(prefix='capture-cpu-') as temporary:
        folder = Path(temporary)
        for name, code in (('copy', copy), ('late', late), ('shadow', shadow + '\nfor (auto pair : pairs) std::memcpy(pair.first, pair.second, 4096); pairs.clear();')):
            (folder / ('capture_' + name + '.inc')).write_text(code)
        executable = folder / 'fixture.exe'
        subprocess.run([args.cxx, '-std=c++20', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-I' + str(folder), '-I' + str(ROOT / 'gpu/vk'), str(ROOT / 'tests/capture_cpu_shadow_test.cpp'),
                        '-o', str(executable)], check=True)
        for mode, fail_allocation, cached in ((None, False, False), ('0', False, False), ('1', False, False), ('1', True, False), ('1', False, True)):
            env = dict(os.environ)
            env.pop('RX_VK_CAPTURE_CPU_UNCACHED', None)
            env.pop('CAPTURE_TEST_ALLOC_FAIL', None)
            env.pop('CAPTURE_TEST_CACHED', None)
            if cached: env['CAPTURE_TEST_CACHED']='1'
            if fail_allocation:
                env['CAPTURE_TEST_ALLOC_FAIL'] = '1'
            if mode is not None:
                env['RX_VK_CAPTURE_CPU_UNCACHED'] = mode
            subprocess.run([str(executable)], env=env, check=True)
            subprocess.run([str(executable)], env={**env, "CAPTURE_TEST_ALL_VALID": "1"}, check=True)
    print('PASS: submit bytes, failed page, guest mutation, ordered write-back and GPU/shadow agreement')


if __name__ == '__main__':
    main()
