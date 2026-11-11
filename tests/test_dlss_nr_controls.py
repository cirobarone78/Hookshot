"""Behavioral tests of NR profiles and temporary comparison state, without a GPU."""
RUN_ALL_ARGS = ["--cxx", "{cxx}"]

import argparse
from pathlib import Path
import subprocess
import tempfile

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--cxx', default='g++')
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='nr-controls-') as tmp:
        exe=Path(tmp)/'nr-controls.exe'
        subprocess.run([args.cxx,'-std=c++20','-Wall','-Wextra','-Werror',str(Path(__file__).with_suffix('.cpp')),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)

if __name__ == '__main__':
    main()
