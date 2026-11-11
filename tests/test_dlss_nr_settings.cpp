#include "../gpu/vk/dlss_nr_settings.h"
#include <cassert>
#include <cstdio>
using namespace mkwvk::dlss_nr;
int main() {
    Edits edits;
    Settings a;
    a.intensity = 100;
    assert(!edits.observe(a, 0, false));
    a.intensity = 150;
    assert(!edits.observe(a, 300, false));
    assert(!edits.observe(a, 649, false));
    assert(!edits.observe(a, 900, true)); // Holding a still slider must not recreate the feature.
    assert(edits.observe(a, 901, false));
    edits.commit(901);
    assert(edits.applied.intensity == 150);
    a.tone = 50;
    assert(!edits.observe(a, 1000, false));
    assert(!edits.observe(a, 2899, false)); // Avoid flooding the driver's feature pool.
    assert(edits.observe(a, 2901, false));
    a = edits.applied; // Reverting an edit must cancel the pending recreation.
    assert(!edits.observe(a, 3000, false));
    assert(!edits.observe(a, 4000, false));
    a.intensity = 900; a.structure = -12; a.skin = -5; a.style = 99; a.preset = -1;
    assert(!edits.observe(a, 4100, false));
    assert(edits.observe(a, 4450, false));
    edits.commit(4450);
    assert(edits.applied.intensity == 200 && edits.applied.structure == 0);
    assert(edits.applied.skin == -100 && edits.applied.style == 2 && edits.applied.preset == 0);
    assert(!edits.observe(a, 6500, false)); // Clamping must not cause an endless rebuild loop.
    std::puts("NR edit coalescing, drag, rate limit, cancellation and bounds: PASS");
}
