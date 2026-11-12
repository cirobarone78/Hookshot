"""First person's hook follows the free camera's at the head of the view's loop in f_804e48c0, wherever that head is and
whichever of the two hooks is already in: a fresh lift takes both, a lift the shipped free-camera patch touched takes
first person's beside it, and a second run over either takes nothing (no hook and no declaration twice).

python -I -B tests/test_first_person_anchor.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import oot_patches  # noqa: E402

HOOK = oot_patches.VIEW_HOOK
FP_HOOK = oot_patches.VIEW_FP_HOOK
DECL = oot_patches.VIEW_DECL
FP_DECL = oot_patches.VIEW_FP_DECL


def lifted(head, hooks=""):
    """f_804e48c0 as the lifter writes it around the loop's head, with the hooks a past patch left after the head"""
    return ('#include "a64.h"\n' + oot_patches.VIEW_HEAD + "    c->x[20]=c->x[0];\n" + head + hooks +
            "    c->x[8]=recomp_load64(c,c->x[20] + 8);\n"
            "if ((uint32_t)c->x[8] != 0) { { A64_POLL(c); goto L_804e5068; } }\n"
            "return;\n}\n")


def shipped(source):
    """what the shipped patch_view made of it: the free camera's hook and declaration alone"""
    return source.replace('#include "a64.h"\n', '#include "a64.h"\n' + DECL, 1)


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def main():
    for head in oot_patches.VIEW_ANCHORS:
        # a fresh lift: both hooks, in order at the head, both declarations
        out = oot_patches.patch_view(lifted(head))
        check(out is not None, "a fresh lift was left alone: %r" % head)
        check(out.count(HOOK) == 1 and out.count(FP_HOOK) == 1, "the hooks are not in once each: %r" % head)
        check(head + HOOK + FP_HOOK in out, "first person's hook does not follow the free camera's: %r" % head)
        check(DECL in out and FP_DECL in out, "a declaration is missing: %r" % head)
        check("A64_POLL(c); goto L_804e5068;" in out, "the back-edge's poll was lost")
        # the shipped patch's lift: first person's hook beside the free camera's, nothing of the shipped one again
        out = oot_patches.patch_view(shipped(lifted(head, HOOK)))
        check(out is not None, "a shipped lift was left alone: %r" % head)
        check(out.count(HOOK) == 1 and out.count(FP_HOOK) == 1, "the hooks are not in once each: %r" % head)
        check(HOOK + FP_HOOK in out, "first person's hook does not follow the free camera's: %r" % head)
        check(out.count(DECL) == 1 and FP_DECL in out, "a declaration is wrong: %r" % head)
        # both in already: a second run changes nothing
        both = oot_patches.patch_view(lifted(head))
        check(oot_patches.patch_view(both) == both, "a second run changed the patched lift: %r" % head)
        both = oot_patches.patch_view(shipped(lifted(head, HOOK)))
        check(oot_patches.patch_view(both) == both, "a second run changed the upgraded lift: %r" % head)
    check(oot_patches.patch_view(lifted("L_804e5070:;\n")) is None, "a function without the label was patched")
    print("PASS: first person's hook follows the free camera's once, over a fresh, a shipped and an upgraded lift")


if __name__ == "__main__":
    main()
