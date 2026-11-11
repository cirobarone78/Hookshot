"""Execute NR menu actions and capability locking without a game or GPU."""
RUN_ALL_ARGS = ["--cxx", "{cxx}"]
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
    menu = (ROOT / 'gpu/vk/vk_menu.cpp').read_text(encoding='utf-8')
    dlss = (ROOT / 'gpu/vk/vk_dlss.cpp').read_text(encoding='utf-8')
    assert '"%d–%d of %d"' in menu
    assert '"%s · %s"' in menu
    assert 'nr_toolbar_preview' not in menu
    start = menu.index('else if (r.tab == TAB_DLSS5 && !strcmp(r.name, "Compare"))')
    end = menu.index('else if (press[7] && is_nr_row(r))', start)
    action = menu[start:end].replace('else if', 'if', 1)
    fixture = r'''
#include <cassert>
#include <cstring>
#include <mutex>
#include <thread>
#include "gpu/vk/dlss_nr_support.h"
using namespace mkwvk;
enum { TAB_DLSS5, TAB_GRAPHICS };
struct Row { int tab; const char* name; int* value; };
struct { int dlss5=1, dlss5_profile=0, dlss5_history=1, dlss5_debug=1; } opts;
namespace mkwvk::dlss_nr { enum { Balanced, Original }; }
int entered=0, retried=0, saved=0, published=0;
void nr_compare_enter() { ++entered; }
void dlss_nr_retry() { ++retried; }
void nr_look(int) {}
void nr_publish() { ++published; }
void save() { ++saved; }
bool activate(Row& r, bool right, bool confirm) {
    bool press[8]{}; press[4]=right; press[7]=confirm; bool changed=false;
ACTION
    return changed;
}
struct State { std::mutex mu; bool nr_failed=false, nr_rejected=false; } state;
State& st() { return state; }
dlss_nr::Issue issue=dlss_nr::Issue::missing_runtime;
dlss_nr::Issue dlss_nr_issue() { return issue; }
void nr_issue_set(dlss_nr::Issue v) { issue=v; }
int probes=0;
dlss_nr::Issue nr_check_locked(bool) { ++probes; return dlss_nr::Issue::none; }
CHECK
int main() {
    for (const char* name : {"Compare", "Retry detection", "Reset NR settings"}) {
        Row r{TAB_DLSS5,name,nullptr};
        assert(!activate(r,false,false));
        assert(activate(r,true,false));
        assert(activate(r,false,true));
        assert(activate(r,true,true)); // simultaneous inputs execute once
    }
    assert(entered==3 && retried==6 && saved==3 && published==3);
    assert(opts.dlss5_history==0 && opts.dlss5_debug==0);
    // The periodic check cannot block behind an NR rebuild on another thread.
    state.mu.lock();
    std::thread periodic([] { assert(dlss_nr_check(false)==dlss_nr::Issue::missing_runtime); });
    periodic.join(); state.mu.unlock();
    assert(probes==0);
    assert(dlss_nr_check(true)==dlss_nr::Issue::none && probes==1);
    state.nr_failed=true; issue=dlss_nr::Issue::render_failed;
    assert(dlss_nr_check(false)==issue && probes==1);
}
'''.replace('ACTION', action).replace('CHECK', block(dlss, 'dlss_nr::Issue dlss_nr_check(bool refresh)'))
    with tempfile.TemporaryDirectory(prefix='nr-actions-') as tmp:
        src=Path(tmp)/'test.cpp'; exe=Path(tmp)/'test.exe'
        src.write_text(fixture, encoding='utf-8')
        subprocess.run([args.cxx, '-std=c++20', '-Wall', '-Wextra', '-Werror', '-pthread', '-I'+str(ROOT), str(src), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True, timeout=10)
    print('PASS: NR Right/confirm actions and nonblocking periodic capability check')

if __name__ == '__main__':
    main()
