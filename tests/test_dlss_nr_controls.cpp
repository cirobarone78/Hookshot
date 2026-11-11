#include "../gpu/vk/dlss_nr_controls.h"
#include <cassert>
#include <cstdio>
using namespace mkwvk::dlss_nr;
int main() {
    const Settings old_defaults;
    assert(look(Balanced).model == old_defaults && look(Balanced).color == 100);
    assert(look(Faithful).model.intensity == old_defaults.intensity && look(Faithful).color == 0);
    assert(identify(look(Faithful).model, 0) == Faithful);
    assert(identify(look(Intense).model, 100) == Intense);
    Settings custom = old_defaults; custom.tone = 160;
    assert(identify(custom, 100) == Custom);
    assert(identify(old_defaults, 50) == Custom);
    assert(step_preset(0) == 1 && step_preset(1) == 0);
    assert(step_preset(2) == 1 && step_preset(3) == 1); // Legacy aliases map to the other verified choice on edit.
    Comparison c;
    assert(c.override_for(false, false) == -1);
    c.enter(true);
    assert(c.override_for(false, false) == 1);
    assert(c.override_for(true, true) == 0);
    assert(c.override_for(false, true) == 1); // Releasing Hold restores without a persistent enable write.
    c.toggle();
    assert(c.override_for(false, true) == 0 && c.override_for(true, true) == 0);
    c.toggle();
    assert(c.override_for(false, false) == 1);
    for(int i=0;i<1000;++i) c.toggle();
    assert(c.on);
    c.leave();
    assert(c.override_for(true,true) == -1);
    c.enter(false); // Compare Original -> temporarily enable -> exit returns control to saved Original.
    c.toggle(); assert(c.override_for(false,false) == 1);
    c.leave(); assert(c.override_for(false,false) == -1);
    c.enter(true);
    c.shortcut(true, true, false); assert(!c.on);
    for(int i=0;i<1000;++i) c.shortcut(true, true, false);
    assert(!c.on); // Autorepeat/held key must not toggle the model repeatedly.
    c.shortcut(false, false, false);
    c.shortcut(false, true, false); assert(c.on); // Queued short tap, missed by polling.
    c.shortcut(false, false, false);
    c.shortcut(true, true, true); assert(c.on && c.override_for(true,true)==0);
    c.shortcut(false, false, true); assert(c.on && c.override_for(false,true)==1);
    std::puts("NR legacy defaults, profiles/custom edits, verified preset selection, Toggle/Hold/exit: PASS");
}
