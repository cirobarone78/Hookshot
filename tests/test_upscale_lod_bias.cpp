#include "../gpu/vk/upscale_lod_bias.h"

#include <cstdio>

#define CHECK(name, condition) do { if (!(condition)) { std::fprintf(stderr, "FAIL %s at line %d\n", name, __LINE__); return 1; } } while (0)

int main() {
    namespace ul = mkwvk::upscale_lod;
    // the game's own 3/4 and above: its -0.5 covers it, nothing more
    CHECK("the game's 75%: none", ul::steps(2880, 3840) == 0 && ul::bias(0) == 0.0f);
    CHECK("the picture's size: none", ul::steps(3840, 3840) == 0);
    CHECK("a 3D larger than the picture: none", ul::steps(3840, 1920) == 0);
    CHECK("nothing drawn (sizes of 0): none", ul::steps(0, 3840) == 0 && ul::steps(1920, 0) == 0 && ul::steps(0, 0) == 0);
    // below it, log2(share / 0.75) to the nearest quarter level (the fixed shares' own: -0.17, -0.37, -0.58, -1.17)
    CHECK("67%: a quarter", ul::steps(2560, 3840) == 1 && ul::bias(1) == -0.25f);
    CHECK("58%: a quarter", ul::steps(2240, 3840) == 1);
    CHECK("50%: a half", ul::steps(1920, 3840) == 2 && ul::bias(2) == -0.5f);
    CHECK("37.5%, half the game's: a level", ul::steps(1440, 3840) == 4 && ul::bias(4) == -1.0f);
    CHECK("33%: a level and a quarter", ul::steps(1280, 3840) == 5 && ul::bias(5) == -1.25f);
    CHECK("the share, not the size", ul::steps(960, 1920) == ul::steps(1920, 3840) && ul::steps(1280, 2560) == 2);
    for (uint32_t w = 1; w <= 3840; w += 7) {
        const int s = ul::steps(w, 3840);
        CHECK("within the steps", s >= 0 && s <= ul::kMaxSteps);
        CHECK("a smaller 3D never has less bias", s >= ul::steps(w + 7, 3840));
        CHECK("the bias is never positive", ul::bias(s) <= 0.0f && ul::bias(s) >= -2.0f);
    }
    // from the steps there are: left only an eighth of a level past the edge (the edge of 1 and 2 is 1.5 steps: 56.6%)
    CHECK("at its own share a step stays", ul::steps(1920, 3840, 2) == 2 && ul::steps(2560, 3840, 1) == 1);
    CHECK("just over the edge it stays", ul::steps(2150, 3840, 1) == 1 && ul::steps(2150, 3840) == 2);
    CHECK("just under the edge it stays", ul::steps(2240, 3840, 2) == 2 && ul::steps(2240, 3840) == 1);
    CHECK("a size hovering at the edge keeps one step", ul::steps(2200, 3840, ul::steps(2240, 3840, 1)) == 1 && ul::steps(2240, 3840, ul::steps(2200, 3840, 2)) == 2);
    CHECK("well past the edge it moves", ul::steps(1920, 3840, 1) == 2 && ul::steps(2560, 3840, 2) == 1);
    CHECK("a jump moves to the nearest", ul::steps(1280, 3840, 0) == 5 && ul::steps(2880, 3840, 5) == 0);
    CHECK("the game's 75% is none from any step", ul::steps(2880, 3840, 1) == 0 && ul::steps(3840, 3840, 1) == 0);
    CHECK("nothing drawn is none from any step", ul::steps(0, 3840, 3) == 0 && ul::steps(1920, 0, 3) == 0);
    CHECK("steps out of range are held first", ul::steps(1920, 3840, 1000) == 2 && ul::steps(1920, 3840, -5) == 2);
    for (uint32_t w = 1; w <= 3840; w += 7)
        for (int c = 0; c <= ul::kMaxSteps; c++) {
            const int s = ul::steps(w, 3840, c), nearest = ul::steps(w, 3840);
            CHECK("never more than a step from the nearest", s >= 0 && s <= ul::kMaxSteps && s - nearest <= 1 && nearest - s <= 1);
            CHECK("settled: the same again from itself", ul::steps(w, 3840, s) == s);
        }
    CHECK("held to two levels", ul::steps(100, 3840) == ul::kMaxSteps && ul::bias(ul::kMaxSteps) == -2.0f);
    CHECK("steps out of range are held too", ul::bias(-3) == 0.0f && ul::bias(1000) == -2.0f);
    std::puts("upscale LOD bias: ok");
    return 0;
}
