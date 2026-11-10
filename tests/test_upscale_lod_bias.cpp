#include "../gpu/vk/upscale_lod_bias.h"

#include <cstdio>

#define CHECK(name, condition) do { if (!(condition)) { std::fprintf(stderr, "FAIL %s at line %d\n", name, __LINE__); return 1; } } while (0)

int main() {
    namespace ul = mkwvk::upscale_lod;
    // the upscalers' modes at a 3840 wide picture (upscaler_rows.h's shares): log2 of the scale, to the nearest quarter level
    CHECK("Quality (67%): half a level", ul::steps(2560, 3840, 1.0f) == 2 && ul::bias(2) == -0.5f);
    CHECK("Balanced (58%): three quarters", ul::steps(2240, 3840, 1.0f) == 3 && ul::bias(3) == -0.75f);
    CHECK("Performance (50%): a level", ul::steps(1920, 3840, 1.0f) == 4 && ul::bias(4) == -1.0f);
    CHECK("Ultra Performance (33%): a level and a half", ul::steps(1280, 3840, 1.0f) == 6 && ul::bias(6) == -1.5f);
    CHECK("the game's 75%: half a level", ul::steps(2880, 3840, 1.0f) == 2);
    // never a bias toward the smaller mips, and none where nothing is scaled up
    CHECK("DLAA (the scene is the picture's size): none", ul::steps(3840, 3840, 1.0f) == 0 && ul::bias(0) == 0.0f);
    CHECK("a scene larger than the picture: none", ul::steps(3840, 1920, 1.0f) == 0);
    CHECK("no upscaler drawing (sizes of 0): none", ul::steps(0, 3840, 1.0f) == 0 && ul::steps(1920, 0, 1.0f) == 0 &&
                                                        ul::steps(0, 0, 1.0f) == 0);
    for (uint32_t w = 1; w <= 3840; w += 7) {
        const int s = ul::steps(w, 3840, 1.0f);
        CHECK("within the steps", s >= 0 && s <= ul::kMaxSteps);
        CHECK("a smaller scene never has less bias", s >= ul::steps(w + 7, 3840, 1.0f));
        CHECK("the bias is never positive", ul::bias(s) <= 0.0f && ul::bias(s) >= -2.0f);
    }
    CHECK("held to two levels", ul::steps(100, 3840, 1.0f) == ul::kMaxSteps && ul::bias(ul::kMaxSteps) == -2.0f);
    CHECK("steps out of range are held too", ul::bias(-3) == 0.0f && ul::bias(1000) == -2.0f);
    // RX_VK_UPSCALE_LOD_BIAS
    CHECK("unset: the guides' bias", ul::strength(nullptr) == 1.0f && ul::strength("") == 1.0f);
    CHECK("0: none", ul::strength("0") == 0.0f && ul::steps(1920, 3840, ul::strength("0")) == 0);
    CHECK("a number scales it", ul::strength("0.5") == 0.5f && ul::steps(1920, 3840, ul::strength("0.5")) == 2 &&
                                    ul::steps(1920, 3840, ul::strength("1.5")) == 6);
    CHECK("held to 0..2", ul::strength("-1") == 0.0f && ul::strength("9") == 2.0f);
    CHECK("not a number: as unset", ul::strength("on") == 1.0f && ul::strength("nan") == 1.0f);
    CHECK("a negative strength: none", ul::steps(1920, 3840, -1.0f) == 0);
    std::puts("upscale LOD bias: ok");
    return 0;
}
