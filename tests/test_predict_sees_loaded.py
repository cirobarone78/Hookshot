"""The prediction sees the programs the preparation has read in.

predict_pipelines (gpu/vk/vk_predict.cpp) learns each pipeline note's vertex layout and targets from the kept program the note
names, through program_cache_each, which listed the records of disk_records. program_cache_load and program_cache_load_some take a
key's records out of disk_records as they read the program in, and a first start's preparation reads in every program the state
list names (state_list_prepare) just before the prediction: no note found its program, and every new build logged "predicted 0
pipelines from 1261 notes for 0 program variants". The records taken out are kept in disk_taken, and program_cache_each lists both.
This checks the source: both take-out sites keep what they take, and program_cache_each walks disk_taken too.
python -I -B tests/test_predict_sees_loaded.py
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]


def body(text, marker):
    start = text.index(marker)
    at = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[at] == "{") - (text[at] == "}")
        at += 1
    return text[start:at]



def check_numeric_inputs(cxx):
    source = (ROOT / "gpu/vk/vk_predict.cpp").read_text(encoding="utf-8")
    source = source.replace('#include "vk_draw.h"', '').replace('#include "vk_shader.h"', '')
    fixture = r"""#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <vector>
#include <utility>
#include <initializer_list>
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)
namespace mkwvk {
constexpr uint32_t VK_SHADER_STAGE_VERTEX_BIT=1, VK_SHADER_STAGE_FRAGMENT_BIT=16,
                   VK_SHADER_STAGE_TASK_BIT_EXT=64, VK_SHADER_STAGE_MESH_BIT_EXT=128;
struct Stream { uint32_t stride=0, divisor=0; };
struct State { uint32_t vattr[16]{}; int nvattr=16; Stream vstream[16]{}; };
struct PipeNote { State s; uint32_t topo=3,samples=1,n=1,color_format[8]{},has_depth=0,depth_format=0;
                  uint64_t prog=0,variant=0,key=0; };
struct KeptProgram { uint64_t key,variant=0; std::vector<std::pair<uint32_t,std::vector<uint32_t>>> stages; };
std::vector<KeptProgram> kept;
template<class F> void program_cache_each(F fn) { for (const auto& k:kept) fn(k); }
}
""" + source + r"""
using namespace mkwvk;
// Authored declaration words only: exercise predictor inspection, not a Vulkan shader or game input.
std::vector<uint32_t> input(unsigned kind,unsigned base,bool grouped=false) {
    std::vector<uint32_t> w{0x07230203,0x10000,0,base+10,0};
    auto op=[&](uint32_t code,std::initializer_list<uint32_t> a) {
        w.push_back(((uint32_t)a.size()+1)<<16|code);w.insert(w.end(),a);
    };
    op(71,{base+4,30,6});
    if(grouped) {
        op(73,{base+9});op(71,{base+9,31,2});op(74,{base+9,base+4});
    }
    if(kind==0) op(22,{base,32});
    else if(kind==3) op(22,{base,64});
    else op(21,{base,32,kind==1 ? 1u:0u});
    op(23,{base+1,base,4});op(32,{base+2,1,base+1});op(59,{base+2,base+4,1});
    return w;
}
void trial(unsigned donor,unsigned target,bool expected,bool exact=false,bool grouped=false) {
    auto d=input(donor,10,exact && grouped),t=exact ? d:input(target,40,grouped);
    kept={{1,0,{{VK_SHADER_STAGE_VERTEX_BIT,d}}},{2,0,{{VK_SHADER_STAGE_VERTEX_BIT,t}}}};
    std::vector<std::unique_ptr<PipeNote>> notes;
    auto n=std::make_unique<PipeNote>();n->prog=1;n->s.vattr[6]=77;n->s.vstream[0].stride=16;
    notes.push_back(std::move(n));size_t programs=0;
    auto predicted=predict_pipelines(notes,&programs);
    CHECK(predicted.size()==(expected?1u:0u));
    CHECK(programs==(expected?1u:0u));
    if(expected) { CHECK(predicted[0]->prog==2);CHECK(predicted[0]->s.vattr[6]==77);
                  CHECK(predicted[0]->s.vstream[0].stride==16); }
}
int main() {
    trial(2,0,false); // same locations, UINT donor must not feed FLOAT target
    trial(0,0,true);  // different SPIR-V IDs, same numeric class shares fallback
    trial(2,2,true);trial(1,1,true);
    trial(1,2,false);trial(0,1,false); // S32, U32 and F32 are distinct
    trial(3,3,false); // unsupported64-bit inputs must not share fallback
    trial(3,3,true,true); // exact module still works for unknown representations
    trial(0,0,false,false,true); // grouped Component decoration is not a plain location input
    trial(0,0,true,true,true);   // the identical grouped module keeps exact matching
    std::puts("PASS: numeric32 predictor fallback, canonical IDs, unsupported exact-only");
}
"""
    with tempfile.TemporaryDirectory(prefix="predict-inputs-") as tmp:
        cpp=Path(tmp)/"fixture.cpp";exe=Path(tmp)/"fixture.exe"
        cpp.write_text(fixture,encoding="utf-8")
        subprocess.run([cxx,"-std=c++20","-Wall","-Wextra","-Werror",str(cpp),"-o",str(exe)],check=True)
        subprocess.run([str(exe)],check=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx",default="g++")
    args=p.parse_args()
    src = (ROOT / "gpu" / "vk" / "vk_shader.cpp").read_text(encoding="utf-8")
    load = body(src, "void program_cache_load(uint64_t key,")
    some = body(src, "size_t program_cache_load_some(")
    each = body(src, "void program_cache_each(")
    if "disk_records.erase(" not in load or "disk_taken[" not in load:
        raise SystemExit("program_cache_load takes records out of disk_records without keeping them for the prediction")
    if "disk_records.erase(" not in some or "disk_taken[" not in some:
        raise SystemExit("program_cache_load_some takes records out of disk_records without keeping them for the prediction")
    if "disk_taken" not in each:
        raise SystemExit("program_cache_each lists disk_records alone: the programs read in already never reach the prediction")
    print("PASS: the prediction sees the programs read in already")
    check_numeric_inputs(args.cxx)


if __name__ == "__main__":
    main()
