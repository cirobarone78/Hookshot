"""Check diagnostic capture aspect, bounds and thumbnail color without a game or GPU."""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ['--cxx', '{cxx}']

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cxx', default='g++')
    parser.add_argument('--sanitize', action='store_true')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='hookshot-capture-') as tmp:
        exe = Path(tmp) / 'capture_test.exe'
        flags = ['-fsanitize=address,undefined', '-fno-omit-frame-pointer'] if args.sanitize else []
        subprocess.run([args.cxx, '-std=c++17', '-O1', '-Wall', '-Wextra', '-Werror', *flags,
                        str(ROOT / 'tests/capture_size_test.cpp'), '-o', str(exe)], check=True)
        subprocess.run([exe], check=True)


if __name__ == '__main__':
    main()
