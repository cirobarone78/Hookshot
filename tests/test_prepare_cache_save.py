"""Exercise the Builder's state-list import and cache save with game-free call stubs."""
import argparse, subprocess, tempfile
from pathlib import Path
RUN_ALL_ARGS = ["--cxx", "{cxx}"]


def block(source, marker):
    start = source.index(marker)
    at = source.index('{', start) + 1
    end, depth = at, 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[at:end - 1]


p=argparse.ArgumentParser();p.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--cxx',default='clang++');a=p.parse_args()
body=block((a.source/'gpu/vk/vk_main.cpp').read_text(encoding='utf-8'), 'if (prepare_only()) {')
already_prepared=block((a.source/'gpu/vk/vk_draw.cpp').read_text(encoding='utf-8'),
                       'if (why == PrepareWhy::None && !getenv("RX_VK_PREPARE_AGAIN")) {')
cpp=r"""
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>
using std::size_t;
std::vector<int> calls;
void state_list_run(){calls.push_back(6);}
void state_list_prepare(void*){std::exit(7);}
int seed_open(){std::exit(8);}
void logf(const char*,...){std::exit(9);}
bool warm_libraries(void(*)(size_t,size_t)){std::exit(10);}
struct PreparedFor {int warmed=1;};
void prepared_write(const std::string&, PreparedFor){std::exit(11);}
bool fresh_seed=true;
bool reuse_seed(void(*progress)(size_t,size_t),bool background,bool refresh_states){
 const PreparedFor already{};
 PreparedFor prepared_for=already;
 const int warmed=already.warmed;
 const bool libraries=false;
 const std::string warming="warming",path="prepared";
 """+already_prepared+r"""
}
bool prepare_run(void(*)(size_t,size_t),bool background=false,bool refresh_states=false){
 if(background||!refresh_states)std::exit(3);
 calls.push_back(1);
 return fresh_seed || reuse_seed(nullptr,background,refresh_states);
}
void predict_run(void(*)(size_t,size_t)){calls.push_back(5);}
void precompile_run(void(*)(size_t,size_t)){calls.push_back(2);}
void pipeline_cache_save(bool force){if(!force)std::exit(2);calls.push_back(3);}
std::string skipped_path(){return "sentinel";}
int fake_remove(const char*){calls.push_back(4);return 0;}
#define remove fake_remove
bool run(){
"""+body+r"""
}
int main(){
 if(!run()||calls!=std::vector<int>{1,5,2,3,4})return 1;
 fresh_seed=false;
 calls.clear();
 if(!run()||calls!=std::vector<int>{1,6,2,3,4})return 2;
 calls.clear();
 if(reuse_seed(nullptr,false,false)||!calls.empty())return 3;
 std::puts("PASS: Builder imports states even with a prepared seed, then compiles and saves the cache");
}
"""
with tempfile.TemporaryDirectory(prefix='prepare-cache-') as tmp:
    src=Path(tmp)/'fixture.cpp';exe=Path(tmp)/'fixture.exe';src.write_text(cpp)
    subprocess.run([a.cxx,'-std=c++20',str(src),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
