"""AMD Anti-Lag 2 (gpu/vk/vk_antilag.cpp): compiles its actual frame calls against the Vulkan headers with a recording
vkAntiLagUpdateAMD, and checks that the device and the present path call them, with frame generation's display thread
too (each set's first present gives its game frame's present stage). No GPU or driver required.

python -I -B tests/test_antilag.py --headers <Vulkan-Headers/include> [--cxx g++]
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}", "--headers", "{vulkan_headers}"]

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--headers", type=Path, required=True)
p.add_argument("--cxx", default="g++")
a = p.parse_args()
source = (ROOT / "gpu" / "vk" / "vk_antilag.cpp").read_text(encoding="utf-8")


def block(text, marker):
    """From marker to the brace closing its first one"""
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


# the wiring: the device asks for the extension and its feature, the present gives the present stage before
# vkQueuePresentKHR, and the input stage comes after the present (with Reflex's sleep)
main = (ROOT / "gpu" / "vk" / "vk_main.cpp").read_text(encoding="utf-8")
for call in ("antilag_device_extensions(want, exts);", "antilag_device_features(tail);", "antilag_device_created();"):
    if call not in main:
        raise SystemExit("vk_main.cpp no longer calls " + call)
if main.index("antilag_device_features(tail);") > main.index("vkGetPhysicalDeviceFeatures2(dev.physical, &f);"):
    raise SystemExit("vk_main.cpp: Anti-Lag 2's feature joins the chain after the features were queried")
replay = (ROOT / "gpu" / "vk" / "vk_replay.cpp").read_text(encoding="utf-8")
# (present ahead, #1720: present_image's present is its end, present_out, which present_commit also runs)
present = block(replay, "static void present_out(uint32_t index, std::unique_lock<std::mutex>& qk, uint64_t antilag_frame) {")
call = "antilag_present(antilag_frame);"
if call not in present or present.index(call) > present.index("vkQueuePresentKHR("):
    raise SystemExit("present_out: Anti-Lag 2's present stage is not given before vkQueuePresentKHR")
do_present = block(replay, "void do_present(")
if "reflex_sleep(); antilag_input();" not in do_present:
    raise SystemExit("do_present: Anti-Lag 2's input stage is not given after the present")
if "present_image(src, sw, sh, crop, direct_view, antilag_frame());" not in do_present:
    raise SystemExit("do_present: its own present does not carry the frame's index")
if "present_defer_into->antilag_frame = antilag_frame;" not in replay or "present_out(p.index, qk, p.antilag_frame);" not in replay:
    raise SystemExit("present ahead: the deferred present loses the frame's index")
# frame generation: the index goes with the set, and only its first present (k 0) gives the present stage
framegen = (ROOT / "gpu" / "vk" / "vk_framegen.cpp").read_text(encoding="utf-8")
if "antilag_frame()});" not in block(framegen, "void framegen_queue("):
    raise SystemExit("framegen_queue: the set does not carry its game frame's index")
if block(framegen, "void display_main()").count("j.set->frame[k].view, k ? 0 : j.antilag_frame);") != 2:
    raise SystemExit("display_main: a set's presents (direct and present ahead) do not give the present stage at its first")

functions = "\n".join(block(source, m) + (";" if m.startswith("struct") else "") for m in (
    "struct AntiLag {", "AntiLag& al()", "void update(", "bool on()", "void stage(", "uint64_t antilag_frame()",
    "void antilag_present(", "void antilag_input()"))
fixture = r'''
#include <vulkan/vulkan_core.h>
#include <cstdio>
#include <mutex>
#include <vector>
struct {VkDevice device=VK_NULL_HANDLE;} dev;
int want=1;
bool wanted(){return want>0;}
template<class... T> void logf(const char*,T...){}
struct Call{VkAntiLagModeAMD mode;int stage;uint64_t frame;};
std::vector<Call> calls;
void VKAPI_CALL record(VkDevice,const VkAntiLagDataAMD* d){
    calls.push_back({d->mode,d->pPresentationInfo?(int)d->pPresentationInfo->stage:-1,
                     d->pPresentationInfo?d->pPresentationInfo->frameIndex:0});
}
''' + functions + r'''
#define CHECK(c) do{if(!(c)){std::printf("FAIL line %d: %s\n",__LINE__,#c);return 1;}}while(0)
int main(){
    // not available: nothing is ever called
    antilag_input();antilag_present(1);CHECK(calls.empty()&&antilag_frame()==0);
    al().ready=true;al().update=record;
    // before the first input stage: no frame, and a present gives nothing
    CHECK(antilag_frame()==0);antilag_present(antilag_frame());CHECK(calls.empty());
    // a frame without frame generation: its input stage, then its present stage, with one index, mode On
    antilag_input();uint64_t f=antilag_frame();CHECK(f!=0);antilag_present(f);
    CHECK(calls.size()==2&&calls[0].stage==VK_ANTI_LAG_STAGE_INPUT_AMD&&calls[1].stage==VK_ANTI_LAG_STAGE_PRESENT_AMD);
    CHECK(calls[0].frame==f&&calls[1].frame==f&&calls[0].mode==VK_ANTI_LAG_MODE_ON_AMD&&calls[1].mode==VK_ANTI_LAG_MODE_ON_AMD);
    // frame generation: the set's present comes after the game's next input stage, with its own frame's index
    calls.clear();antilag_input();const uint64_t g=antilag_frame();antilag_input();antilag_present(g);
    CHECK(calls.size()==3&&calls[1].frame==g+1&&calls[2].stage==VK_ANTI_LAG_STAGE_PRESENT_AMD&&calls[2].frame==g);
    // a made frame's present (0) gives nothing
    calls.clear();antilag_present(0);CHECK(calls.empty());
    // the row off: Off once, then nothing, and no frame to stamp
    calls.clear();want=0;antilag_input();antilag_present(g+1);antilag_input();
    CHECK(calls.size()==1&&calls[0].mode==VK_ANTI_LAG_MODE_OFF_AMD&&calls[0].stage==-1&&antilag_frame()==0);
    // on again: a set made before gives nothing; the next frame's stages go out
    calls.clear();want=1;antilag_present(g+1);CHECK(calls.empty());
    antilag_input();f=antilag_frame();antilag_present(f);
    CHECK(calls.size()==2&&calls[1].stage==VK_ANTI_LAG_STAGE_PRESENT_AMD&&calls[1].frame==f&&f>g+1);
    std::puts("PASS: Anti-Lag 2's stages with one index a frame, with frame generation's later presents too; Off told once");
}
'''
with tempfile.TemporaryDirectory(prefix="antilag-") as tmp:
    cpp, exe = Path(tmp) / "fixture.cpp", Path(tmp) / "fixture.exe"
    cpp.write_text(fixture, encoding="utf-8")
    subprocess.run([a.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-missing-field-initializers",
                    "-pthread", "-I" + str(a.headers), str(cpp), "-o", str(exe)], check=True)
    raise SystemExit(subprocess.run([str(exe)]).returncode)
