"""Real NR menu persistence/transactions extracted from vk_menu.cpp; no game/GPU."""
RUN_ALL_ARGS = ["--cxx", "{cxx}"]

import argparse
from pathlib import Path
import re
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
def block(text, marker):
    start=text.index(marker)
    end=text.index('{',start)+1
    depth=1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}')
        end+=1
    return text[start:end]

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--cxx',default='g++')
    a=p.parse_args()
    menu=(ROOT/'gpu/vk/vk_menu.cpp').read_text(encoding='utf-8')
    assert re.search(r'"DLSS model".*?hn_dlss_model, false, true\},\s*'
                     r'\{TAB_GRAPHICS, "DLSS 5 Neural Rendering"', menu, re.S)
    options=block((ROOT/'gpu/vk/vk_menu.h').read_text(encoding='utf-8'),'struct Options {')+';'
    tabs=block(menu, "enum MenuTab {")+";"
    controls=block((ROOT/'gpu/vk/vk_dlss.h').read_text(encoding='utf-8'),'struct DlssNrControls {')+';'
    fixture=r"""
#include <algorithm>
#include <atomic>
#include <cassert>
#include <climits>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <string>
#include "gpu/vk/dlss_nr_controls.h"
#include "gpu/vk/dlss_nr_support.h"
using namespace mkwvk;
"""
    # Keep NR helper types/functions in their production namespace.
    fixture=fixture.replace('using namespace mkwvk;','namespace mkwvk {\n'+options+'\n'+controls+r"""
Options opts, saved;
int saved_value(int* value) { return *value; }
DlssNrControls published;
std::atomic<bool> open_now{true};
bool menu_refresh=false;
TABS
int page=0,cur_tab=TAB_DLSS5;
constexpr int VK_F8=0x77;
struct Host { bool (*take_key_press)(int); } *host=nullptr;
void logf(const char*,...) {}
int saves=0,override_value=-1;
void save();
void dlss_nr_publish(const DlssNrControls& v) { published=v; }
void dlss_nr_compare(int v) { override_value=v; }
dlss_nr::Issue dlss_nr_check(bool=false) { return dlss_nr::Issue::none; }
dlss_nr::Issue dlss_nr_issue() { return dlss_nr::Issue::none; }
""")
    fixture=fixture.replace("TABS",tabs)
    for marker in ['bool nr_slider(','dlss_nr::Settings nr_model(','void nr_look(','void nr_publish(','const char* nr_ini_key(']:
        fixture+=block(menu,marker)+'\n'
    fixture+=r"""
struct Row { int* value; int lo, hi; };
Row rows[] = {{&opts.dlss5_group, 0, 1}, {&opts.dlss5_intensity, 0, 200}, {&opts.dlss5_debug, 0, 5}};
const char* ini_key(const Row& r) { return nr_ini_key(r.value); }
int parse_output(const char* text) { return atoi(text); }
"""+block(menu, 'bool nr_prepare_row(')+r"""
void load_line(const char* input) {
    char line[128]; snprintf(line, sizeof line, "%s", input);
    char* eq = strchr(line, '='); assert(eq); *eq = 0;
"""+block(menu[menu.index('void menu_init() {'):], 'for (Row& r : rows) {')+'\n}\n'
    save_rows=block(block(menu,"void save() {"),"for (const Row& r : rows) {")
    start=menu.index('dlss_nr::Comparison nr_comparison;')
    end=menu.index('void nr_compare_enter()',start)
    fixture+=menu[start:end]
    fixture+=block(menu,'void nr_compare_enter() {')+'\n'+block(menu,'void nr_compare_leave(bool commit) {')+r"""
void save() { ++saves; saved=opts; }
struct Out { unsigned w, h; };
Out player_custom_output{}; constexpr int kCustomOutput = 6;
bool env_holds(const int*) { return false; }
Out output_at(int) { return {2048, 1152}; }
void save_rows_to(FILE* f) {
SAVE_ROWS
}
} // namespace mkwvk
using namespace mkwvk;
int main() {
    static_assert(TAB_DLSS5 >= TAB_COUNT && TAB_DLSS5 != TAB_MOTION);
    opts.show_fps = 0;
    opts.dlss5 = 1;
    opts.dlss5_intensity = 45;
    load_line("dlss5_stats=1"); // An obsolete overlay preference cannot enable FPS or change NR.
    assert(opts.show_fps == 0 && opts.dlss5 == 1 && opts.dlss5_intensity == 45);
    for (int current : {0, 1}) for (int dir : {-1, 1}) {
        opts.dlss5_group=current;
        int next=current+dir;
        assert(nr_prepare_row(rows[0], next, dir));
        assert(next==(dir<0 ? 0 : 1)); // A named group is selected, never toggled away by a second click.
    }
    for (const char* legacy : {"dlss5_group=0", "dlss5_group=2", "dlss5_group=3", "dlss5_group=-9", "dlss5_group=9999999999999"}) {
        opts.dlss5_group=1; load_line(legacy); assert(opts.dlss5_group==0);
    }
    load_line("dlss5_group=1"); assert(opts.dlss5_group==1);
    load_line("dlss5_intensity=999"); assert(opts.dlss5_intensity==200);
    load_line("dlss5_intensity=invalid"); assert(opts.dlss5_intensity==200);
    load_line("dlss5_intensity=35");
    load_line("dlss5_debug=5"); assert(opts.dlss5_debug == 0);
    opts.dlss5=1; opts.dlss5_profile=dlss_nr::Balanced;
    opts.dlss5_debug=4; opts.dlss5_compare_mode=1;
    assert(nr_slider(&opts.dlss5_intensity) && !nr_slider(&opts.dlss5_profile));
    assert(std::string(nr_ini_key(&opts.dlss5_intensity))=="dlss5_intensity");
    assert(std::string(nr_ini_key(&opts.dlss5_compare_mode))=="dlss5_compare_mode");
    assert(std::string(nr_ini_key(&opts.dlss5_compare_top))=="dlss5_compare_top");
    assert(nr_ini_key(&opts.rumble)==nullptr);
    nr_compare_enter();
    assert(nr_comparison.active && override_value==1 && opts.dlss5_debug==0);
    opts.dlss5_intensity=80; opts.dlss5_color=0; nr_comparison.toggle();
    assert(nr_persisted_value(&opts.dlss5_intensity)==35);
    assert(nr_persisted_value(&opts.dlss5_color)==100);
    assert(nr_persisted_value(&opts.dlss5)==1);
    nr_compare_leave(false);
    assert(!nr_comparison.active && open_now && cur_tab==TAB_DLSS5 && page==0);
    assert(opts.dlss5_intensity==35 && opts.dlss5_color==100 && opts.dlss5==1 && saves==0);
    assert(opts.dlss5_debug==4 && opts.dlss5_compare_mode==1 && override_value==-1);
    nr_compare_enter();
    opts.dlss5_intensity=45; opts.dlss5_profile=dlss_nr::Custom;
    nr_comparison.toggle();
    nr_compare_leave(true);
    assert(saves==1 && saved.dlss5==0 && saved.dlss5_intensity==45);
    assert(saved.dlss5_profile==dlss_nr::Original && saved.dlss5_debug==4);
    assert(open_now && !nr_comparison.active && published.model.intensity==45 && !published.requested);
    FILE* ini=tmpfile(); assert(ini); save_rows_to(ini); rewind(ini);
    char persisted[512]{}; fread(persisted,1,sizeof persisted-1,ini); fclose(ini);
    assert(strstr(persisted,"dlss5_intensity=45") && !strstr(persisted,"dlss5_debug"));
    std::puts("NR group migration, keys, temporary save masking, Cancel restore and Save commit: PASS");
}
"""
    fixture=fixture.replace("SAVE_ROWS",save_rows)
    with tempfile.TemporaryDirectory(prefix='nr-menu-') as tmp:
        src=Path(tmp)/'menu.cpp'; exe=Path(tmp)/'menu.exe'
        src.write_text(fixture,encoding='utf-8')
        subprocess.run([a.cxx,'-std=c++20','-Wall','-Wextra','-Werror','-I'+str(ROOT),str(src),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)
        # Execute production row visibility and parent/submenu navigation with minimal host stand-ins.
        nav_start=menu.index("        if (press[5] && pending) pending = nullptr, changed = true; // Cancel")
        nav_end=menu.index("        const int tab_count",nav_start)
        nav=menu[nav_start:nav_end]
        entry=re.search(r'    \{TAB_GRAPHICS, "DLSS 5 Neural Rendering"[^\n]+',menu).group(0)
        opening=re.search(r'        else if \(press\[7\] && is_nr_row\(r\)\)[^\n]+',menu).group(0).replace("else if", "if",1)
        visibility=r"""
#include <algorithm>
#include <atomic>
#include <cassert>
#include <cstring>
namespace mkwvk {
TABS
OPTIONS
ROW;
Options opts;
bool built=false;
bool dlss_built() { return built; }
bool cheats_on() { return true; }
bool reflex_available() { return false; }
bool antilag_available() { return false; }
unsigned upscalers_available() { return 1; }
constexpr int DLSS_OK=0;
int dlss_why() { return DLSS_OK; }
namespace ur { bool upscaler_shown(unsigned) { return true; } bool model_shown(bool v) { return v; } }
Row rows[] = {
ENTRY
    {TAB_DLSS5,"Common",&opts.dlss5,0,1,1,nullptr,"",nullptr,false,true,-1,false,0},
    {TAB_DLSS5,"Base",&opts.dlss5,0,1,1,nullptr,"",nullptr,false,true,-1,false,1},
    {TAB_DLSS5,"General",&opts.dlss5,0,1,1,nullptr,"",nullptr,false,true,-1,false,3},
    {TAB_DLSS5,"Quality",&opts.dlss5,0,1,1,nullptr,"",nullptr,false,true,-1,false,4}
};
IS_NR
VISIBILITY
int cur_tab=TAB_GRAPHICS,tab_selected[TAB_DLSS5+1]{};
bool press[8]{},changed=false,tab_left=false,tab_right=false,open_now=true,tune_mode=false;
const Row* pending=nullptr;
int page=0,ask_sel=0;
bool restart_ask() { return false; }
void navigation() {
NAV
}
void enter(const Row& r) {
OPENING
}
}
using namespace mkwvk;
int main() {
    static_assert(TAB_COUNT==5 && TAB_DLSS5>=TAB_COUNT && TAB_MOTION>=TAB_COUNT);
    for(int i=0;i<5;i++) assert(!row_shown(i)); // No SDK: no dead submenu entry or controls.
    built=true;
    assert(row_shown(0) && row_shown(1) && row_shown(2) && !row_shown(3) && !row_shown(4));
    opts.dlss5_advanced=1;
    assert(row_shown(1) && !row_shown(2) && row_shown(3) && !row_shown(4));
    opts.dlss5_group=1;
    assert(!row_shown(3) && row_shown(4));
    press[7]=true;enter(rows[0]);assert(cur_tab==TAB_DLSS5 && !press[7]);
    press[5]=true;navigation();assert(cur_tab==TAB_GRAPHICS && open_now && !press[5]);
    cur_tab=TAB_MOTION;press[5]=true;navigation();assert(cur_tab==TAB_CONTROLS && open_now && !press[5]);
    cur_tab=TAB_DLSS5;tab_right=true;navigation();assert(cur_tab==TAB_AUDIO);
    tab_right=false;tab_left=true;cur_tab=TAB_DLSS5;navigation();assert(cur_tab==TAB_DEBUG);
}
"""
        for key,value in {"TABS":tabs,"OPTIONS":options,"ROW":block(menu,"struct Row {"),"ENTRY":entry,
                          "IS_NR":block(menu,"bool is_nr_row("),"VISIBILITY":block(menu,"bool row_shown("),
                          "NAV":nav,"OPENING":opening}.items():
            visibility=visibility.replace(key,value)
        src.write_text(visibility,encoding="utf-8")
        subprocess.run([a.cxx,"-std=c++20","-Wall","-Wextra","-Werror",str(src),"-o",str(exe)],check=True)
        subprocess.run([str(exe)],check=True)
if __name__=='__main__':main()
