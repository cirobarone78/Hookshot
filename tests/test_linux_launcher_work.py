"""Game-free check of what the Linux launcher says while it builds or updates (builder/linux/launch_work.py): the rules of the
Windows launcher's LaunchWork.cs and of its menu's steps. Made-up lines of make_game.py go in; the number under the button,
the bar's words, the line under it and the steps' states come out. No window, disk or process.

python -I -B tests/test_linux_launcher_work.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "builder", "linux"))
import launch_work as lw  # noqa: E402

failed = []


def check(what, got, want):
    if got != want:
        failed.append("%s: got %r, want %r" % (what, got, want))


def states(work):
    return [(key, state, small) for key, _name, state, small in work.steps]


# ---- a build from game files ----
w = lw.Work("Building your game", back="files")
check("a build's steps", [name for _k, name, _s, _t in w.steps],
      ["Read the game files", "Translate to PC code", "Compile", "Put it together", "Prepare the shaders"])
check("before anything is said", (w.bar(), w.step_line(), w.fraction), ("Building... 0%", "Starting...", 0.0))
for line in ("build: up to 6 compilers at once", "@@stage read Reading your game files", "@@stage lift Translating", "@@progress 0.5"):
    w.line(line)
check("half way through the translation", round(w.fraction, 3), 0.125)
check("read is done, the translation is now", states(w)[:2], [("read", "done", ""), ("lift", "now", "")])
check("the line under the bar: the step under way", w.step_line(), "Translate to PC code...")
for line in ("@@stage compile Compiling", "@@plan 58 259", "@@file a.c 0 new", "@@file b.c 1 again", "@@file c.c 2 kept", "@@eta 1080",
             "@@progress 0.5"):
    w.line(line)
check("the compile's count is of the files that changed", w.step("compile")[2:], ["now", "2 of 58"])
check("half way through the compile", (round(w.fraction, 3), w.bar()), (0.55, "Building... 55%"))
check("the line under it", w.step_line(), "Compile 2 of 58 · 18 min left")
w.line("@@progress 0.2")
check("the number never goes back", round(w.fraction, 3), 0.55)
w.line("@@stage polish Something a later version says")
check("a stage with no words here moves nothing", (round(w.fraction, 3), w.says), (0.55, "Working"))
check("and the compile is done all the same", w.step("compile")[2], "done")
for line in ("@@stage finish Putting the game folder together", "@@stage shaders Preparing shaders", "@@progress 0.5", "@@times 2136 1585 0",
             "@@done /home/player/Games/Hookshot"):
    w.line(line)
check("where the game is", (w.done, w.times), ("/home/player/Games/Hookshot", (2136.0, 1585.0, 0.0)))
w.end(True)
check("done", (w.fraction, [s for _k, s, _t in states(w)]), (1.0, ["done"] * 5))
check("every line is kept for the details", len(w.log), 18)

# ---- the shaders' step left to the game's first start ----
w = lw.Work("Building your game", shaders=False, not_prepared="the shaders were not prepared")
check("no shaders step", [k for k, _s, _t in states(w)], ["read", "lift", "compile", "finish"])
w.line("the shaders were not prepared now: the game prepares them at its first start")
check("and it says so", w.shaders_later, True)

# ---- a compile with nothing to do ----
w = lw.Work("Updating to v2.1.0", update=True)
check("an update's steps", [name for _k, name, _s, _t in w.steps][::3], ["Read the kept files", "Swap in the game"])
w.line("@@stage compile Compiling")
w.line("@@plan 0 259")
check("everything already built", w.step("compile")[3], "Already built")
check("an update's bar", w.bar(), "Updating... 20%")
check("a switch's bar", lw.Work("Switching to v2.0.14", update=True).bar(), "Switching... 0%")

# ---- it stops ----
w = lw.Work("Building your game")
for line in ("@@stage read x", "@@stage lift x", "@@stage compile x", "clang: error: unable to execute command: Killed",
             "@@error The compiler stopped on code_006.c"):
    w.line(line)
w.end(False)
check("why it stopped", w.error, "The compiler stopped on code_006.c")
check("the step it stopped in", states(w)[2][:2], ("compile", "stopped"))
check("what the stopped state says", w.stopped_title(), "The build stopped")
check("an update's", lw.Work("Updating to v2.1.0", update=True).stopped_title(), "The update to v2.1.0 stopped")
check("a switch back's", lw.Work("Switching to v2.0.14", update=True).stopped_title(), "The switch to v2.0.14 stopped")
check("a rebuild's", lw.Work("Rebuilding v2.1.0", update=True).stopped_title(), "The rebuild of v2.1.0 stopped")

# ---- a version whose builder is downloaded first ----
w = lw.Work("Updating to v2.1.0", update=True, fetch=True)
check("its first step", (w.steps[0][:3], w.step_line()), (["download", "Get its builder", "now"], "Getting its builder..."))
w.note("Downloading part 3 of 6 (310 MB)...")
check("part 3 of 6: a third of the download's share", (round(w.fraction, 3), w.says), (0.04, "Getting its builder: downloading part 3 of 6 (310 MB)"))
w.fetched()
check("the builder is here", (round(w.fraction, 3), w.steps[0][2]), (0.12, "done"))
w.line("@@stage compile x")
w.line("@@progress 1")
check("the build's share comes after the download's", round(w.fraction, 3), round(0.12 + 0.88 * 0.9, 3))

# ---- under an update's bar: that it is a rebuild, then the step and the time left ----
w = lw.Work("Updating to v2.2.0", update=True)
w.started = 1000.0
w.line("@@stage lift x")
check("before the compile: what a build took here, less the time gone", w.under_bar(1800, now=1600.0),
      "Rebuilding your game as v2.2.0\nTranslate to PC code · 20 min left")
check("no build kept: no time guessed", w.under_bar(None, now=1600.0), "Rebuilding your game as v2.2.0\nTranslate to PC code...")
check("past the usual time: no time guessed", w.under_bar(1800, now=2750.0), "Rebuilding your game as v2.2.0\nTranslate to PC code...")
w.line("@@stage compile x")
check("the compile before its own time", w.under_bar(1800, now=1600.0), "Rebuilding your game as v2.2.0\nCompile · 20 min left")
w.line("@@eta 190")
check("the compile's own time wins", w.under_bar(1800, now=1600.0), "Rebuilding your game as v2.2.0\nCompile · 3 min left")
check("a switch back", lw.Work("Switching to v2.0.14", update=True).rebuild_line(), "Rebuilding your game as v2.0.14")
check("a rebuild: the version in the folder, with the settings now", lw.Work("Rebuilding v2.1.0", update=True).rebuild_line(),
      "Rebuilding your game with your settings now")
check("a rebuild's bar", lw.Work("Rebuilding v2.1.0", update=True).bar(), "Rebuilding... 0%")
for seconds, want in ((None, "around half an hour or more"), (1810, "about 30 minutes"), (100, "about 5 minutes"), (3900, "about 1 h 5 min"),
                      (3600, "about 1 h")):
    check("about(%r)" % seconds, lw.about(seconds), want)

# ---- the shaders' step: its own number and time under the bar (its share of the bar is small, the step can be long) ----
w = lw.Work("Updating to v2.2.0", update=True)
w.line("@@stage shaders Preparing shaders")
w.shader_started = 1000.0
check("the shaders' step before a number", w.step_line(now=1005.0), "Prepare the shaders... 0%")
w.line("@@progress 0.25")
check("a quarter done in 10 minutes: 30 left", w.step_line(now=1600.0), "Prepare the shaders... 25% · 30 min left")
check("too soon to tell: no time", w.step_line(now=1010.0), "Prepare the shaders... 25%")
check("the build's usual time is not the shaders'", w.under_bar(1800, now=1600.0), "Rebuilding your game as v2.2.0\nPrepare the shaders... 25% · 30 min left")
w.line("@@progress 0.1")
check("its number never goes back", w.step_line(now=1600.0), "Prepare the shaders... 25% · 30 min left")
w.line("@@progress nan")
check("not a number moves nothing", w.step_line(now=1600.0), "Prepare the shaders... 25% · 30 min left")

# ---- how long ----
for seconds, want in ((20, "less than a minute left"), (60, "1 min left"), (1080, "18 min left"), (3900, "1 h 5 min left")):
    check("short_left(%d)" % seconds, lw.short_left(seconds), want)
for seconds, want in ((20, "less than a minute"), (70, "a minute"), (2460, "41 minutes"), (3900, "1 h 5 min")):
    check("span(%d)" % seconds, lw.span(seconds), want)

# ---- a time that is no time: the line under the bar is still written (inf made it raise, once a second) ----
w = lw.Work("Building your game")
w.line("@@stage compile x")
for line in ("@@eta inf", "@@eta nan", "@@eta -inf", "@@eta soon"):
    w.line(line)
check("no time taken from them", (w.eta, w.step_line()), (-1.0, "Compile · estimating..."))
w.line("@@eta -5")
check("a time already past: less than a minute", w.step_line(), "Compile · less than a minute left")
w.line("@@eta inf")
try:
    check("@@eta inf after a time: that time stays", w.step_line(), "Compile · less than a minute left")
except OverflowError as error:
    check("@@eta inf: the line under the bar", repr(error), "written")
w.line("@@progress inf")
check("a share past the whole stops at the stage's end", round(w.fraction, 3), 0.9)

# ---- the download of a version's builder, as the launcher says it: once a part ----
w = lw.Work("Updating to v2.1.0", update=True, fetch=True)
w.note("Keeping usr (unchanged), part 1 of 4")
w.note("Downloading python (310 MB), part 3 of 4")
check("part 3 of 4", (round(w.fraction, 3), w.step_line()),
      (0.06, "Getting its builder: downloading python (310 MB), part 3 of 4..."))


# ---- the launcher's screen, its work run without a window (builder/linux/hookshot_launcher.py) ----
def launcher_module():
    """hookshot_launcher, or None when this Python has no Tk. Its drawing (numpy) is not used here: a stand-in when numpy
    is missing"""
    import types
    try:
        import tkinter  # noqa: F401
    except ImportError:
        return None
    try:
        import launcher_art  # noqa: F401
    except ImportError:
        sys.modules["launcher_art"] = types.ModuleType("launcher_art")
    import hookshot_launcher
    return hookshot_launcher


hl = launcher_module()
if hl is None:
    print("(no Tk in this Python: the launcher's screen is not checked)")
else:
    import contextlib
    import io
    import json
    import shutil
    import tempfile

    class Lines(object):
        def __init__(self):
            self.said = []

        def put(self, what):
            self.said.append(what)

    class App(object):
        def __init__(self):
            self.lines, self.proc, self.jobs = Lines(), None, []

        def after(self, ms, then):
            self.jobs.append((ms, then))
            return "after#%d" % len(self.jobs)

        def after_cancel(self, job):
            pass

    class Tools(object):
        """(hookshot_builder, as the launcher uses it)"""
        ready = False
        made = []

        def game_ready(self, folder):
            if isinstance(self.ready, Exception):
                raise self.ready
            return self.ready

        def add_to_menu(self, folder):
            self.made.append(folder)

    def screen():
        """a Launcher whose drawing and folder reading are left out: what it does is noted instead"""
        s = hl.Launcher.__new__(hl.Launcher)
        s.app, s.hb, s.did = App(), Tools(), []
        s.work, s.proc, s.state, s.folder, s.built, s.bringing, s.tick_job = None, None, "idle", "/games/Hookshot", "v2.1.0", None, None
        s.details, s.log_box, s.typical, s.menu_open, s.exited_at = False, None, None, True, None
        s.canvas = type("Canvas", (), {"winfo_exists": lambda self: True, "itemconfigure": lambda self, *a, **k: None})()
        s.fit = lambda font, text, width: text
        s.u = lambda n: n
        s.draw = lambda: s.did.append("draw")
        s.fill = lambda: s.did.append("fill")
        s.show_details = lambda on: None
        s.run_update = lambda: s.did.append("run_update")
        s.enter = lambda folder, note=None: (setattr(s, "state", "idle"), s.did.append(("enter", folder, note)))
        return s

    # Cancel while that version's builder is downloaded: what the download brings or says after is not used
    s = screen()
    work = s.work = hl.Work("Updating to v2.2.0", update=True, fetch=True)
    s.state = "working"
    s.cancel()
    check("cancelled while downloading: as it was", (s.state, work.cancelled), ("idle", True))
    for late in (("note", work, "Downloading usr (1 MB), part 2 of 4"), ("fetched", work), ("failed", work, "GitHub answered 500")):
        s.message(late)
    check("and nothing after it is acted on (a build was started once the download ended)", ("run_update" in s.did, s.state, work.error),
          (False, "idle", None))

    # a build that stopped: its end said a second time changes nothing
    s = screen()
    work = s.work = hl.Work("Building your game")
    s.state = "working"
    s.message(("line", work, "@@error The compiler stopped on code_006.c"))
    s.message(("exit", work, 1))
    check("stopped, with why", (s.state, work.error), ("stopped", "The compiler stopped on code_006.c"))
    work.done, s.hb.ready = "/games/Hookshot", True   # (so that, taken again, this end would read as a build that ended well)
    s.message(("exit", work, 0))
    check("its end said again: still stopped", s.state, "stopped")
    s.message(("exit", hl.Work("Building your game"), 0))
    check("another build's end: not this one's", s.state, "stopped")

    # what goes wrong while its end is read: the screen says so instead of waiting for good (and the builder's loop goes on)
    s = screen()
    work = s.work = hl.Work("Building your game")
    s.state = "working"
    s.message(("line", work, "@@done /games/Hookshot"))
    s.hb.ready = RuntimeError("the disk went away")
    with contextlib.redirect_stderr(io.StringIO()):
        s.message(("exit", work, 0))
    check("an exception in its end: stopped, with it", (s.state, work.error), ("stopped", "The launcher stopped: the disk went away"))

    # a build that ended well
    s = screen()
    work = s.work = hl.Work("Building your game")
    s.state, s.hb.ready = "working", True
    s.message(("line", work, "@@done /games/Hookshot"))
    s.message(("exit", work, 0))
    check("built: the launcher of the folder", [d for d in s.did if isinstance(d, tuple)][0][:2], ("enter", "/games/Hookshot"))

    # make_game.py gone and its output never ended (a program it started holds it): over all the same, 10 seconds on
    class Gone(object):
        returncode = 0
        pid = 0

        def poll(self):
            return 0
    s = screen()
    work = s.work = hl.Work("Building your game")
    s.state, s.proc = "working", Gone()
    s.tick()
    check("gone a moment: still waited on", s.state, "working")
    s.exited_at -= 11
    s.tick()
    check("gone 11 seconds: over", (s.state, work.error), ("stopped", "The build tools stopped without saying why"))

    # GitHub's releases: an answer that is not a list (rate limited) is no answer, not an exception
    os.environ.pop("HOOKSHOT_LATEST_TAG", None)
    limited = json.dumps({"message": "API rate limit exceeded"}).encode()
    check("rate limited", hl.release_list(lambda url: limited), ([], None))
    check("no network", hl.release_list(lambda url: (_ for _ in ()).throw(OSError("unreachable"))), ([], None))
    listed = json.dumps([{"tag_name": "v1.2.0-rc.1", "prerelease": True, "assets": [{"name": hl.linux_update.LIST_NAME}]},
                         {"tag_name": "v1.1.0", "assets": None}, {"tag_name": "v1.0.0", "draft": True},
                         {"tag_name": "nightly"}]).encode()
    check("GitHub's answer", hl.release_list(lambda url: listed), ([("v1.2.0-rc.1", True, True), ("v1.1.0", False, False)], "v1.1.0"))
    os.environ["HOOKSHOT_LATEST_TAG"] = "v1.2.0-rc.1, v1.1.0,v1.0.0?"
    check("(development) made-up releases", hl.release_list(lambda url: limited),
          ([("v1.2.0-rc.1", True, True), ("v1.1.0", False, True), ("v1.0.0", False, False)], "v1.1.0"))
    del os.environ["HOOKSHOT_LATEST_TAG"]

    # how long a build took here: a record that is no time is left out
    class Times(object):
        def __init__(self, builds):
            self.builds = builds

        def load_times(self, work):
            return {"builds": self.builds}
    check("the middle of the last five", hl.typical_build(Times([{"total_seconds": s} for s in (9, 100, 300, 200, 0, 400)])), 300.0)
    check("inf and nan left out", hl.typical_build(Times([{"total_seconds": s} for s in (float("inf"), float("nan"), 600)])), 600.0)
    check("none kept", hl.typical_build(Times([])), None)

    # the folder: one whose version file is not text, and a file dialog's first folder
    here = tempfile.mkdtemp(prefix="hookshot launcher ü ")
    try:
        with open(os.path.join(here, "hookshot_version.txt"), "wb") as f:
            f.write(b"version=\xff\xfe\n")
        check("a version file that is not text: no version, no exception", hl.folder_version(here), (None, False))
        check("the first folder: the nearest one that is there", hl.existing_dir(os.path.join(here, "gone", "deeper")), here)
        check("none chosen: home", hl.existing_dir(""), os.path.expanduser("~"))
    finally:
        shutil.rmtree(here, ignore_errors=True)

if failed:
    print("\n".join(failed))
    sys.exit(1)
print("the Linux launcher's build and update words: ok")
