"""Game-free check of the Linux launcher's drawing (builder/linux/launcher_art.py): the shapes it takes from the Windows
launcher's MainWindow.xaml are filled as drawn, the PNG it writes reads back, and the picture it ships is there and dim. No
window: Tk is not started.

python -I -B tests/test_linux_launcher_art.py
"""
import os
import sys

RUN_ALL_MODULES = ["numpy"]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "builder", "linux"))
import numpy as np  # noqa: E402

import launcher_art as art  # noqa: E402

failed = []


def check(what, ok, said=""):
    if not ok:
        failed.append("%s%s" % (what, ": " + str(said) if said != "" else ""))


# ---- the shapes are MainWindow.xaml's own: the same path data, so the two launchers cannot drift apart unseen ----
with open(os.path.join(ROOT, "builder", "HookshotBuilder", "MainWindow.xaml"), encoding="utf-8") as f:
    xaml = " ".join(f.read().split())


def in_xaml(data):
    return " ".join(data.split()) in xaml


check("Play's strip is MainWindow.xaml's StripShape", in_xaml(art.STRIP))
for i, letter in enumerate(art.WORDMARK):
    check("the wordmark's letter %d is MainWindow.xaml's" % i, in_xaml(letter))
# (the small marks are Paper's "Hookshot v2" path data, which each launcher writes in its own way: drawn, below)
check("GitHub's mark is MainWindow.xaml's", in_xaml(art.GITHUB))
check("Discord's mark is MainWindow.xaml's", in_xaml(art.DISCORD))

# ---- a path is read as SVG reads it ----
square = art.parse_path("M1 1 H5 V5 H1 Z")
check("a square: one closed figure of 4 corners", [(len(p), closed) for p, closed in square] == [(4, True)], square)
check("relative and absolute lines agree", art.parse_path("M1,1 l4,0 l0,4 l-4,0 z")[0][0] == art.parse_path("M1 1 L5 1 L5 5 L1 5 Z")[0][0])
arc = art.parse_path("M0 5 A5 5 0 0 1 10 5")[0][0]
check("an arc ends where it says", arc[-1] == (10.0, 5.0), arc[-1])
check("a half circle's top is its radius up", abs(min(y for _x, y in arc)) < 0.05, min(y for _x, y in arc))

# ---- a fill covers what the shape covers ----
cover = art.fill(art._placed(square, 1, 1, 0, 0), 8, 8)
check("a square of 4 x 4 covers 16 pixels", abs(float(cover.sum()) - 16) < 1e-3, float(cover.sum()))
check("and nothing outside it", float(cover[0].sum()) == 0 and float(cover[:, 0].sum()) == 0)
half = art.fill(art._placed(square, 1, 1, 0.5, 0.25), 8, 8)
check("moved by a part of a pixel it still covers 16", abs(float(half.sum()) - 16) < 1e-3, float(half.sum()))
check("its edge pixels are part covered", 0.2 < float(half[1, 1]) < 0.6, float(half[1, 1]))
ring = art._placed(art.parse_path("M0 0 H8 V8 H0 Z M2 2 H6 V6 H2 Z"), 1, 1, 0, 0)
check("even-odd leaves the hole", abs(float(art.fill(ring, 8, 8, evenodd=True).sum()) - 48) < 1e-3)
check("nonzero fills a hole turned the same way", abs(float(art.fill(ring, 8, 8).sum()) - 64) < 1e-3)

strip = art.strip(1.0)
check("the strip is 257 x 98", strip.shape == (98, 257, 4), strip.shape)
check("its left edge is cut straight, its right edge torn", strip[49, 0, 3] > 200 and strip[2, 250, 3] < strip[49, 250, 3])
check("it is Paper's orange", tuple(int(v) for v in strip[49, 100, :3]) == art.PLAY)
check("at 0.2 while it cannot be pressed", int(art.strip(1.0, alpha=0.2)[49, 100, 3]) == 51)

letters = art.wordmark(1.0)
check("the wordmark is 416 wide", letters.shape[1] == 416, letters.shape)
check("its first letter's stem is solid", float(letters[30, 14]) > 0.95, float(letters[30, 14]))
check("the O's middle is open around its diamond", float(letters[14, 82]) < 0.05, float(letters[14, 82]))
check("and the diamond in it is solid", float(letters[32, 82]) > 0.95, float(letters[32, 82]))

for name in art.MARKS:
    drawn = art.mark(name, 1.0)
    check("the %s mark is drawn in its box" % name, drawn.shape[0] == art.MARKS[name][0] and int(drawn[..., 3].max()) > 200)
    check("the %s mark stays inside its box" % name, int(drawn[0, :, 3].max()) < 60 and int(drawn[:, -1, 3].max()) < 60)
check("GitHub's mark fills its 32", int(art.github(1.0)[..., 3].max()) == 255 and art.github(1.0).shape == (32, 32, 4))
disc = art.discord(1.0)
check("Discord's mark: white on its blue", tuple(int(v) for v in disc[4, 16, :3]) == art.BLURPLE and int(disc[13, 12, 0]) > 200)
panel = art.bar(268, 10, 1.0)
check("the panel is black at 96%, its edge line is not see-through", panel.shape[1] == 268 and int(panel[5, 10, 3]) == 0xF5
      and int(panel[5, 267, 3]) == 255 and int(panel[5, 267, 0]) == 0x30)

# ---- PNG: what is written reads back ----
rng = np.random.default_rng(7)
for channels in (3, 4):
    for sub in (False, True):
        pixels = rng.integers(0, 256, size=(9, 13, channels), dtype=np.uint8)
        path = os.path.join(os.environ.get("TMPDIR") or os.environ.get("TEMP") or "/tmp", "hookshot_launcher_art_%d_%d.png" % (channels, sub))
        with open(path, "wb") as f:
            f.write(art.png(pixels, sub=sub))
        try:
            check("a PNG of %d channels%s reads back" % (channels, " (differences)" if sub else ""), (art.read_png(path) == pixels).all())
        finally:
            os.remove(path)

# ---- a PNG cut short, or not a picture at all: a ValueError, which picture() takes as no picture (the window's page colour),
# not an exception that leaves the window unpainted ----
whole = art.png(rng.integers(0, 256, size=(9, 13, 3), dtype=np.uint8))
for name, data in (("cut inside a chunk's length", whole[:35]), ("cut inside its pixels", whole[:-20]), ("no chunks", whole[:8]),
                   ("not a PNG", b"GIF89a")):
    path = os.path.join(os.environ.get("TMPDIR") or os.environ.get("TEMP") or "/tmp", "hookshot_launcher_art_cut.png")
    with open(path, "wb") as f:
        f.write(data)
    try:
        art.read_png(path)
        check("a PNG %s is refused" % name, False)
    except ValueError:
        pass
    except Exception as error:   # (zlib.error is what a cut stream of pixels raises: picture() takes that too)
        check("a PNG %s: a ValueError or zlib.error" % name, isinstance(error, art.zlib.error), repr(error))
    finally:
        os.remove(path)

# ---- the window's ground: the page's colour (no picture of the game ships) and the wordmark ----
check("no picture of the game ships with the launcher", not os.path.exists(os.path.join(art.ASSETS, "picture.png")))
for w, h in ((960, 640), (1600, 640), (700, 900)):
    ground = art.background(w, h, 1.0)
    check("the window's ground at %d x %d" % (w, h), ground.shape == (h, w, 3) and ground.dtype == np.uint8, ground.shape)
ground = art.background(960, 640, 1.0)
white = ground[art.WORDMARK_TOP + 30, (960 - 416) // 2 + 14]
check("the wordmark is white on it, 59 from the top", min(int(v) for v in white) > 245, tuple(int(v) for v in white))
check("and the page's colour around it", tuple(int(v) for v in ground[art.WORDMARK_TOP - 3, 10]) == art.PAGE, tuple(int(v) for v in ground[art.WORDMARK_TOP - 3, 10]))

if failed:
    print("\n".join(failed))
    sys.exit(1)
print("the Linux launcher's drawing: ok")
