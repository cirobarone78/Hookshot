"""Which versions the Linux launcher's menu holds: builder/HookshotBuilder/LaunchList.cs, the same rules (as drawn in Paper's
"v2 - Version List by channel"): what a version is comes first, whether it is on this PC is the mark at its right. Nothing
here touches the window, the disk or the network (tests/test_linux_launcher_lists.py).

One difference from Windows: there a dev build is a folder of its own beside the launch folder (scripts/build-game.ps1 makes
them). Here the "Dev builds" list holds the launch folder's own build when that is no release: one built by an AppImage from
the Actions tab or from a checkout, which names itself as git describe does (v1.0.0-1224-gc0e5538)."""
import re


def is_release(tag):
    """v1.0.0, 1.0.0, v2.2.0-rc.1: a release's tag, not a build's name from a checkout or the Actions tab"""
    return bool(tag) and re.fullmatch(r"v?\d+\.\d+\.\d+(-(?!\d+-g[0-9a-f]+)[0-9A-Za-z][0-9A-Za-z.-]*)?", tag) is not None


def is_pre(tag):
    """(a tag GitHub has not told us about: the part after the numbers says it is a pre-release, as Semantic Versioning has it)"""
    return "-" in tag


def _bare(tag):
    return tag.lstrip("vV").lower()


def same_tag(a, b):
    return a is not None and b is not None and _bare(a) == _bare(b)


def release_order(tag):
    try:
        return tuple(int(n) for n in _bare(tag).split("-")[0].split("."))
    except ValueError:
        return (0, 0)


def version_name(tag):
    """as the launcher writes a release: v1.0.0"""
    return "v" + tag.lstrip("vV")


def order(tag):
    """Releases in order, as Semantic Versioning orders them (sorted by this): by their numbers; then a release after its
    pre-releases; then the pre-releases by their parts, a number by its value (rc.10 after rc.9) and before a word, a word
    by its letters, and more parts after fewer"""
    bare = _bare(tag)
    pre = bare.split("-", 1)[1] if "-" in bare else None
    if pre is None:
        return release_order(tag), 1, ()
    return release_order(tag), 0, tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split("."))


def newer(a, b):
    """a is ahead of b: a later release, the release itself after its own pre-releases, or a later pre-release of it (rc.2
    after rc.1: an update, not a switch back)"""
    return order(a) > order(b)


class Choice(object):
    """One version in the menu: a release or a pre-release (played in the launch folder, which holds one at a time and is
    updated to another first), or the build the folder holds when that is no release."""

    def __init__(self, kind, label, title, tag=None, build=None, here=False, reach=False, rebuilds=True):
        # label, in the menu: "v2.1.0 - Latest", "v2.2.0-rc.1". title, under the button: "v2.2.0-rc.1 - Pre-release"
        self.kind, self.label, self.title, self.tag, self.build = kind, label, title, tag, build
        self.here = here      # (on this PC: what the launch folder holds)
        self.reach = reach    # (not here, and the button brings it: its builder is installed, or its release has one)
        self.rebuilds = rebuilds   # (the folder keeps its game files: it can be built as another release at all)
        self.picked = False

    @property
    def key(self):
        return "release:" + self.tag if self.tag is not None else "build:" + self.build

    # (the row: no mark means it is here, the arrow that the button brings it, dim that nothing can)
    @property
    def ticked(self):
        return self.picked and self.here

    @property
    def arrow(self):
        return not self.here and self.reach

    @property
    def dim(self):
        return not self.here and not self.reach and not self.picked

    @property
    def tip(self):
        if self.here:
            return "Your game. Press it to rebuild it with your settings now" if self.rebuilds else None
        if self.reach:
            return "Not on this PC yet"
        if not self.rebuilds:
            return "This game folder was built before it kept its game files: build it again from the Build tab"
        return "Not on this PC, and its release has no builder to download"


NEWEST = 2   # (the two newest releases stay in sight; the rest fold into one row when that hides two or more)
SHOWN = 5    # (the Releases tab of Paper's "Hookshot v2": five releases, then "4 older releases")


def make_lists(github, latest, built, builders, rebuilds, pick, open_older, in_sight=NEWEST):
    """github: GitHub's releases as (tag, pre-release, has a builder to download); latest: its latest release's tag; built:
    what the launch folder holds; builders: the releases whose builder is installed here; rebuilds: the folder keeps its game
    files (it can be built as another release); pick: the key of the version picked; open_older: the older releases are
    unfolded; in_sight: how many releases stay in sight. older: how many releases the fold row stands for (0: no fold row);
    folded: they are out of the list now."""
    known = {}
    for tag, pre, download in github:
        known[_bare(tag)] = (tag, pre, download)
    # (on this PC and no longer, or not yet, among GitHub's: the folder's own release, an installed builder's)
    for tag in list(builders) + ([built] if built else []):
        if is_release(tag):
            known.setdefault(_bare(tag), (tag, is_pre(tag), False))
    everything = []
    for tag, pre, download in sorted(known.values(), key=lambda r: order(r[0]), reverse=True):
        here, name, newest = same_tag(tag, built), version_name(tag), same_tag(tag, latest)
        everything.append(Choice("pre" if pre else "release", name + " - Latest" if newest else name,
                                 name + " - Latest" if newest else name + " - Pre-release" if pre else name, tag=tag, here=here,
                                 reach=not here and rebuilds and (download or any(same_tag(b, tag) for b in builders)),
                                 rebuilds=rebuilds))
    if built and not is_release(built):
        everything.append(Choice("dev", built, built + " - Dev build", build=built, here=True))

    def first(test):
        return next((c for c in everything if test(c)), None)
    # (a key holds a tag or a build's name: neither minds capitals)
    picked = (first(lambda c: pick is not None and c.key.lower() == pick.lower()) or first(lambda c: same_tag(c.tag, built))
              or first(lambda c: c.here) or first(lambda c: c.kind == "release") or (everything[0] if everything else None))
    if picked is not None:
        picked.picked = True
    releases = [c for c in everything if c.kind == "release"]
    stay = [c for i, c in enumerate(releases) if i < in_sight or c.here or c.picked]
    older = len(releases) - len(stay)
    if older < 2:   # (a row that says "1 older release" takes the place of the release itself)
        stay, older = releases, 0
    # (the pre-releases among the releases in sight, in version order: every one newer than the oldest release in sight, and
    # all of them once the older releases are unfolded. Hookshot's release candidates come before their release (v2.1.0-rc.3,
    # then v2.1.0), so one that is out is still listed, below its release. The one the folder holds, or the one picked,
    # always is)
    floor = None
    if not open_older and older:
        plain = [c for c in stay if not c.here and not c.picked]
        floor = (plain or stay)[-1].tag
    pre = [c for c in everything if c.kind == "pre" and (c.here or c.picked or floor is None or newer(c.tag, floor))]
    return {"all": everything, "releases": releases if open_older else stay, "older": older, "folded": older > 0 and not open_older,
            "pre": pre, "dev": [c for c in everything if c.kind == "dev"], "picked": picked}


def tab_rows(lists, with_pre):
    """The Releases tab's rows: the releases in sight, and the pre-releases among them in version order while the player
    has them on (Settings, Enable pre-releases). The one the folder holds is always there"""
    pre = [c for c in lists["pre"] if with_pre or c.here]
    return sorted(lists["releases"] + pre, key=lambda c: order(c.tag), reverse=True)
