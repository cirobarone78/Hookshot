"""Game-free check of the Linux launcher's version lists (builder/linux/launch_list.py): the rules of the Windows launcher's
LaunchList.cs, which tests/builder_launcher checks there. Which versions the menu holds, which one is picked, and each row's
mark, from made-up releases: no window, disk or network.

python -I -B tests/test_linux_launcher_lists.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "builder", "linux"))
import launch_list as ll  # noqa: E402

failed = []


def check(what, got, want):
    if got != want:
        failed.append("%s: got %r, want %r" % (what, got, want))


def labels(choices):
    return [c.label for c in choices]


GITHUB = [("v1.2.0-rc.1", True, True), ("v1.1.0", False, True), ("v1.0.0", False, True), ("v0.9.0", False, False),
          ("v0.8.0", False, False)]

# ---- what a tag is ----
for tag, want in (("v1.0.0", True), ("1.0.0", True), ("v2.2.0-rc.1", True), ("v1.0.0-1224-gc0e5538", False),
                  ("v1.0.0-1224-gc0e5538-dirty", False), ("pre-1.1.0 c0e5538", False), ("dev", False), ("", False), (None, False)):
    check("is_release(%r)" % (tag,), ll.is_release(tag), want)
check("a release is ahead of its own pre-release", ll.newer("v1.2.0", "v1.2.0-rc.1"), True)
check("a pre-release is not ahead of its release", ll.newer("v1.2.0-rc.1", "v1.2.0"), False)
check("a later release is ahead", ll.newer("v1.10.0", "v1.9.9"), True)
# (release candidates of one release, as Hookshot tags them: by their number, rc.10 after rc.9; the next one is an update)
check("rc.2 after rc.1", (ll.newer("v2.2.0-rc.2", "v2.2.0-rc.1"), ll.newer("v2.2.0-rc.1", "v2.2.0-rc.2")), (True, False))
check("rc.10 after rc.9", ll.newer("v2.2.0-rc.10", "v2.2.0-rc.9"), True)
check("rc after beta, and more parts after fewer", (ll.newer("v2.2.0-rc.1", "v2.2.0-beta.3"), ll.newer("v2.2.0-rc.1.1", "v2.2.0-rc.1")), (True, True))
check("one release whatever its capitals", (ll.newer("v2.2.0-RC.1", "2.2.0-rc.1"), ll.newer("2.2.0-rc.1", "v2.2.0-RC.1")), (False, False))
_rc = ll.make_lists([("v2.2.0-rc.1", True, True), ("v2.2.0-rc.10", True, True), ("v2.2.0-rc.2", True, True), ("v2.1.0", False, True)],
                    "v2.1.0", "v2.1.0", [], True, None, False)
check("the newest candidate first, whatever order GitHub gave", [c.label for c in _rc["pre"]], ["v2.2.0-rc.10", "v2.2.0-rc.2", "v2.2.0-rc.1"])
check("candidates among the releases, in order", [c.label for c in ll.tab_rows(_rc, True)],
      ["v2.2.0-rc.10", "v2.2.0-rc.2", "v2.2.0-rc.1", "v2.1.0 - Latest"])
_old = ll.make_lists([("v1.2.0", False, True), ("v1.1.0", False, True)], "v1.2.0", "v1.1.0", [], False, None, False)
check("a folder without its game files says why nothing can be brought", _old["releases"][0].tip,
      "This game folder was built before it kept its game files: build it again from the Build tab")
check("...and its own version says nothing of a rebuild", _old["releases"][1].tip, None)
_kept = ll.make_lists([("v1.2.0", False, True), ("v1.1.0", False, True)], "v1.2.0", "v1.1.0", [], True, None, False)
check("the version in a folder that keeps its game files: pressed, it is rebuilt", _kept["releases"][1].tip,
      "Your game. Press it to rebuild it with your settings now")
check("the same tag with and without v", ll.same_tag("V1.0.0", "1.0.0"), True)
check("no tag is no tag", ll.same_tag(None, "1.0.0"), False)

# ---- the folder holds the latest release ----
lists = ll.make_lists(GITHUB, "v1.1.0", "v1.1.0", [], True, None, False)
check("releases, folded", labels(lists["releases"]), ["v1.1.0 - Latest", "v1.0.0"])
check("the fold row", (lists["older"], lists["folded"]), (2, True))
check("the pre-release ahead of the latest", labels(lists["pre"]), ["v1.2.0-rc.1"])
check("no dev build", lists["dev"], [])
check("picked: the one the folder holds", lists["picked"].key, "release:v1.1.0")
check("its row is ticked", (lists["picked"].ticked, lists["picked"].arrow, lists["picked"].dim), (True, False, False))
check("its title under the button", lists["picked"].title, "v1.1.0 - Latest")
older = next(c for c in lists["all"] if c.tag == "v1.0.0")
check("an older release with a builder to download: the arrow", (older.arrow, older.dim, older.tip), (True, False, "Not on this PC yet"))
none = next(c for c in lists["all"] if c.tag == "v0.9.0")
check("one with no builder to download: dim", (none.arrow, none.dim), (False, True))

lists = ll.make_lists(GITHUB, "v1.1.0", "v1.1.0", [], True, None, True)
check("releases, unfolded", labels(lists["releases"]), ["v1.1.0 - Latest", "v1.0.0", "v0.9.0", "v0.8.0"])
check("the fold row, unfolded", (lists["older"], lists["folded"]), (2, False))

# ---- an older folder: the latest is offered, and the folder's own release stays in sight ----
lists = ll.make_lists(GITHUB, "v1.1.0", "v0.8.0", [], True, None, False)
# (the two newest and the folder's own stay; that leaves one, and a row saying "1 older release" would only take its place)
check("one older release is listed itself", labels(lists["releases"]), ["v1.1.0 - Latest", "v1.0.0", "v0.9.0", "v0.8.0"])
check("so there is no fold row", (lists["older"], lists["folded"]), (0, False))
many = GITHUB + [("v0.7.0", False, False), ("v0.6.0", False, False)]
lists = ll.make_lists(many, "v1.1.0", "v0.6.0", [], True, None, False)
check("the folder's own release stays in sight when the others fold", labels(lists["releases"]), ["v1.1.0 - Latest", "v1.0.0", "v0.6.0"])
check("three fold", (lists["older"], lists["folded"]), (3, True))
lists = ll.make_lists(GITHUB, "v1.1.0", "v0.8.0", [], True, None, False)
check("picked: the folder's", lists["picked"].tag, "v0.8.0")

lists = ll.make_lists(GITHUB, "v1.1.0", "v0.8.0", [], True, "release:V1.1.0", False)
check("picked by its key, whatever its capitals", lists["picked"].tag, "v1.1.0")
check("the one picked is not here: the arrow, no tick", (lists["picked"].ticked, lists["picked"].arrow), (False, True))

# ---- a folder that kept no game files cannot be built as another release ----
lists = ll.make_lists(GITHUB, "v1.1.0", "v1.0.0", [], False, None, False)
check("nothing is in reach", [c.tag for c in lists["all"] if c.reach], [])

# ---- a builder installed here brings its release with nothing to download ----
lists = ll.make_lists(GITHUB, "v1.1.0", "v1.1.0", ["v0.9.0"], True, None, True)
check("an installed builder's release is in reach", next(c for c in lists["all"] if c.tag == "v0.9.0").reach, True)

# ---- GitHub did not answer: what is on this PC ----
lists = ll.make_lists([], None, "v1.0.0", ["v0.9.0"], True, None, False)
check("no answer: the folder's and the installed builder's", labels(lists["releases"]), ["v1.0.0", "v0.9.0"])
check("no answer: picked", lists["picked"].tag, "v1.0.0")

# ---- a pre-release of a release that is out: still listed (with pre-releases on), below its release ----
lists = ll.make_lists([("v1.1.0", False, True), ("v1.1.0-rc.2", True, True)], "v1.1.0", "v1.1.0", [], True, None, False)
check("a pre-release of the latest is listed", [c.label for c in lists["pre"]], ["v1.1.0-rc.2"])
check("below its release", [c.label for c in ll.tab_rows(lists, True)], ["v1.1.0 - Latest", "v1.1.0-rc.2"])
# (Hookshot's own list today: the candidates came before their release; with older releases folded, the candidates among the
# releases in sight are listed, the older ones' once they are unfolded)
_today = [("v2.1.0", False, True), ("v2.1.0-rc.3", True, True), ("v2.1.0-rc.2", True, True), ("v2.1.0-rc.1", True, True)] + \
    [("v2.0.%d" % n, False, True) for n in range(14, 7, -1)] + [("v2.0.8-rc.5", True, True), ("v2.0.8-rc.1", True, True)]
lists = ll.make_lists(_today, "v2.1.0", "v2.1.0", [], True, None, False, in_sight=ll.SHOWN)
check("the candidates of the releases in sight", [c.label for c in lists["pre"]], ["v2.1.0-rc.3", "v2.1.0-rc.2", "v2.1.0-rc.1"])
lists = ll.make_lists(_today, "v2.1.0", "v2.1.0", [], True, None, True, in_sight=ll.SHOWN)
check("unfolded, all of them", [c.label for c in lists["pre"]], ["v2.1.0-rc.3", "v2.1.0-rc.2", "v2.1.0-rc.1", "v2.0.8-rc.5", "v2.0.8-rc.1"])
lists = ll.make_lists([("v1.1.0", False, True), ("v1.1.0-rc.2", True, True)], "v1.1.0", "v1.1.0-rc.2", [], True, None, False)
check("the one the folder holds is", labels(lists["pre"]), ["v1.1.0-rc.2"])
check("and it is the one picked", lists["picked"].title, "v1.1.0-rc.2 - Pre-release")

# ---- a folder built by an AppImage that is no release (the Actions tab, a checkout): a list of its own ----
lists = ll.make_lists(GITHUB, "v1.1.0", "v1.0.0-1224-gc0e5538", [], True, None, False)
check("the build the folder holds", labels(lists["dev"]), ["v1.0.0-1224-gc0e5538"])
check("picked: that build", (lists["picked"].key, lists["picked"].title, lists["picked"].ticked),
      ("build:v1.0.0-1224-gc0e5538", "v1.0.0-1224-gc0e5538 - Dev build", True))
check("it is not among the releases", [c.tag for c in lists["releases"]], ["v1.1.0", "v1.0.0"])

# ---- the Releases tab (Paper's "Hookshot v2"): five releases in sight, then "4 older releases" ----
TEN = [("v2.2.0-rc.1", True, True)] + [("v2.%s" % n, False, True) for n in ("1.0", "0.14", "0.13", "0.12", "0.11", "0.10", "0.9", "0.8", "0.7")]
lists = ll.make_lists(TEN, "v2.1.0", "v2.1.0", [], True, None, False, in_sight=ll.SHOWN)
check("five releases, the rest folded", (labels(lists["releases"]), lists["older"]),
      (["v2.1.0 - Latest", "v2.0.14", "v2.0.13", "v2.0.12", "v2.0.11"], 4))
check("pre-releases off: the releases alone", labels(ll.tab_rows(lists, False)), labels(lists["releases"]))
check("pre-releases on: among them by version", labels(ll.tab_rows(lists, True))[:2], ["v2.2.0-rc.1", "v2.1.0 - Latest"])
lists = ll.make_lists([("v2.1.0", False, True), ("v2.1.0-rc.2", True, True)], "v2.1.0", "v2.1.0-rc.2", [], True, None, False)
check("the pre-release the folder holds, even with them off", labels(ll.tab_rows(lists, False)), ["v2.1.0 - Latest", "v2.1.0-rc.2"])

# ---- nothing at all ----
lists = ll.make_lists([], None, None, [], False, None, False)
check("no game, no answer", (lists["all"], lists["picked"]), ([], None))

# ---- Settings' "Lower memory use" (builder/linux/game_env.py): RX_VK_PCACHE_LOAD=0 in the game folder's hookshot_env.txt ----
import game_env as ge  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
check("no line: loaded", (ge.skips_cache(""), ge.skips_cache("RX_VK_NOOPT=1\n")), (False, False))
check("the line, as the game reads it", (ge.skips_cache("RX_VK_PCACHE_LOAD=0\n"), ge.skips_cache("﻿  RX_VK_PCACHE_LOAD=0  \r\n")), (True, True))
check("a note, another value, another name", (ge.skips_cache("# RX_VK_PCACHE_LOAD=0\n"), ge.skips_cache("RX_VK_PCACHE_LOAD=1\n"),
                                               ge.skips_cache("XRX_VK_PCACHE_LOAD=0\n")), (False, False, False))
check("the last line wins; 00 is atoi's 0", (ge.skips_cache("RX_VK_PCACHE_LOAD=0\nRX_VK_PCACHE_LOAD=1\n"),
                                             ge.skips_cache("RX_VK_PCACHE_LOAD=1\nRX_VK_PCACHE_LOAD=00\n")), (False, True))
_mine = "# my switches\r\nRX_VK_NOOPT=1\r\n"
_on = ge.with_skip(_mine, True)
check("on: its line added, CRLF kept", _on, "# my switches\r\nRX_VK_NOOPT=1\r\nRX_VK_PCACHE_LOAD=0\r\n")
check("on twice: one line; off again: as it was", (ge.with_skip(_on, True), ge.with_skip(_on, False)), (_on, _mine))
check("off: every line that sets it goes", ge.with_skip("RX_VK_PCACHE_LOAD=1\nHOS_X=2\nRX_VK_PCACHE_LOAD=0", False), "HOS_X=2\n")
check("a file of its own: made, and empty again", (ge.with_skip("", True), ge.with_skip("RX_VK_PCACHE_LOAD=0\n", False)), ("RX_VK_PCACHE_LOAD=0\n", ""))
check("sizes as Windows writes them", (ge.size_text(2576980378), ge.size_text(458227712)), ("2.4 GB", "437 MB"))
_dir = tempfile.mkdtemp(prefix="hookshot env ü ")
try:
    with open(os.path.join(_dir, ge.CACHE_FILE), "w") as _f:
        _f.write("cache")
    check("no file: off; the cache's size", (ge.folder_skips_cache(_dir), ge.cache_bytes(_dir)), (False, 5))
    ge.set_skip(_dir, True)
    check("on: written", (ge.folder_skips_cache(_dir), open(os.path.join(_dir, ge.FILE_NAME), newline="").read()), (True, "RX_VK_PCACHE_LOAD=0\n"))
    ge.set_skip(_dir, False)
    check("off: the file it made is gone, the cache is still there",
          (os.path.exists(os.path.join(_dir, ge.FILE_NAME)), os.path.exists(os.path.join(_dir, ge.CACHE_FILE))), (False, True))
    check("no cache yet", ge.cache_bytes(os.path.join(_dir, "none")), -1)
finally:
    shutil.rmtree(_dir, ignore_errors=True)

if failed:
    print("\n".join(failed))
    sys.exit(1)
print("the Linux launcher's version lists: ok")
