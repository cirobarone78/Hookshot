"""What the Linux launcher says while it builds the game or brings a version into the folder: builder/HookshotBuilder's
LaunchWork.cs and the build's steps in MainWindow.xaml.cs, the same rules. The lines of the programs that do it (the download
of that version's builder, then make_game.py's @@stage, @@progress, @@plan, @@file, @@eta, @@done, @@error) are read into
one number (the bar that fills, Paper's "Hookshot v2") and the line under it, the step under way. Nothing here touches the
window, the disk or a process (tests/test_linux_launcher_work.py)."""
import math
import re
import time

STEPS = (("read", "Read the game files", "Read the kept files"), ("lift", "Translate to PC code", "Translate to PC code"),
         ("compile", "Compile", "Compile"), ("finish", "Put it together", "Swap in the game"),
         ("shaders", "Prepare the shaders", "Prepare the shaders"))
# (how much of the whole each of make_game.py's stages is, and what it is called under the button)
SHARES = {"read": (0.0, 0.05, "Reading the game files"), "lift": (0.05, 0.15, "Translating the game to PC code"),
          "compile": (0.20, 0.70, "Compiling changed files"), "finish": (0.90, 0.02, "Putting the game together"),
          "shaders": (0.92, 0.08, "Preparing the shaders")}
FETCH = 0.12   # (getting that version's builder first, when it has to be downloaded)
KEPT = "Nothing was changed in your game folder."


def short_left(seconds):
    """time_left, in the room of the panel's line: "18 min left" """
    if seconds < 45:
        return "less than a minute left"
    minutes = max(1, int(round(seconds / 60)))
    return "%d h %d min left" % (minutes // 60, minutes % 60) if minutes >= 60 else "%d min left" % minutes


def about(seconds):
    """how long a build usually takes, to five minutes (a guess, not a promise): "about 30 minutes"; None: not known"""
    if not seconds:
        return "around half an hour or more"
    minutes = max(5, int(round(seconds / 300.0)) * 5)
    if minutes >= 60:
        return "about %d h" % (minutes // 60) + (" %d min" % (minutes % 60) if minutes % 60 else "")
    return "about %d minutes" % minutes


def span(seconds):
    """how long something took, in words: "41 minutes", "1 h 5 min" """
    minutes = int(round(seconds / 60))
    if minutes < 1:
        return "less than a minute"
    if minutes == 1:
        return "a minute"
    return "%d h %d min" % (minutes // 60, minutes % 60) if minutes >= 60 else "%d minutes" % minutes


class Work(object):
    """A build, or a version brought into the folder: the lines of the programs that do it (make_game.py's @@stage,
    @@progress, @@plan, @@file, @@eta, @@done, @@error) read into one number, the line under it and the steps.
    Nothing here touches the window, the disk or a process. What is not understood moves nothing and is kept in the
    details; the number never goes back."""

    def __init__(self, title, update=False, fetch=False, shaders=True, back="launcher", not_prepared=None):
        self.title, self.update, self.fetch, self.back = title, update, fetch, back
        self.fraction, self.stage, self.changed, self.compiled, self.eta = 0.0, None, -1, 0, -1.0
        self.says = "Getting its builder" if fetch else "Starting"   # (the line under the bar before a step is under way)
        self.done, self.error, self.cancelled, self.times, self.shaders_later = None, None, False, None, False
        self.started, self.compile_started, self.log = time.time(), None, []
        # (the shaders' step: its share of the bar is small, but on some GPUs it takes as long as the compile. Its own number and
        # a time from how fast it goes are said under the bar, so a bar near its end is not taken for a stuck one)
        self.shader_done, self.shader_started = 0.0, None
        self.not_prepared = not_prepared   # (make_game.py's line when the shaders' step is left to the game's first start)
        # (the menu's steps: [id, name, state, the small words at its right]; state: "wait", "now", "done", "stopped")
        self.steps = ([["download", "Get its builder", "now", ""]] if fetch else []) + \
            [[key, kept if update else first, "wait", ""] for key, first, kept in STEPS if key != "shaders" or shaders]

    def step(self, key):
        return next((s for s in self.steps if s[0] == key), None)

    def whole(self, f):
        """(make_game.py's share of the whole: all of it when nothing is downloaded first)"""
        return FETCH + (1 - FETCH) * f if self.fetch else f

    def reach(self, f):
        self.fraction = max(self.fraction, min(max(f, 0.0), 1.0))

    def note(self, text):
        """what the download of that version's builder says ("Downloading part 2 of 7 (310 MB)...")"""
        text = text.strip().rstrip(".")
        part = re.search(r"[Pp]art (\d+) of (\d+)", text)
        if part and int(part.group(2)) > 0:
            self.reach(FETCH * (min(int(part.group(1)), int(part.group(2))) - 1) / int(part.group(2)))
        if text:
            self.says = "Getting its builder: " + text[0].lower() + text[1:]
            if self.step("download"):
                self.step("download")[3] = ""
        self.log.append(text)

    def fetched(self):
        self.reach(FETCH)
        if self.step("download"):
            self.step("download")[2] = "done"
        self.says = "Starting"

    def line(self, line):
        self.log.append(line)
        if len(self.log) > 6000:
            del self.log[:2000]
        if line.startswith("@@error "):
            self.error = line[8:].strip()
        elif line.startswith("@@done "):
            self.done = line[7:].strip()
            for s in self.steps:   # (a version whose tools name no last step is done all the same)
                if s[2] == "now" and s[0] != "shaders":
                    s[2] = "done"
        elif line.startswith("@@stage "):
            key = line[8:].strip().split(" ")[0]
            for s in self.steps:
                if s[2] == "now":
                    s[2] = "done"
            self.stage = key
            if self.step(key):
                self.step(key)[2] = "now"
            if key in SHARES:
                self.says = SHARES[key][2]
                self.reach(self.whole(SHARES[key][0]))
            else:
                self.says = "Working"   # (a stage this launcher has no words for)
            self.compile_started = time.time() if key == "compile" else None
            self.eta = -1.0
            if key == "shaders":
                self.shader_done, self.shader_started = 0.0, time.time()
        elif line.startswith("@@progress "):
            try:
                f = float(line[11:])
            except ValueError:
                return
            if math.isnan(f):   # (not a number: moves nothing; inf is the end, clamped below)
                return
            if self.stage in SHARES:
                self.reach(self.whole(SHARES[self.stage][0] + SHARES[self.stage][1] * min(max(f, 0.0), 1.0)))
            if self.stage == "shaders":
                self.shader_done = max(self.shader_done, min(max(f, 0.0), 1.0))
        elif line.startswith("@@plan "):
            p = line.split(" ")
            if len(p) == 3 and p[1].isdigit():
                self.changed, self.compiled = int(p[1]), 0
                self.count()
        elif line.startswith("@@file "):
            p = line.split(" ")
            if len(p) == 4 and p[3] in ("new", "again"):
                self.compiled += 1
                self.count()
        elif line.startswith("@@eta "):
            try:
                eta = float(line[6:])
            except ValueError:
                return
            if math.isfinite(eta):   # (inf or nan would make the time left raise: not a time, so it is not taken)
                self.eta = max(eta, 0.0)
        elif line.startswith("@@times "):
            p = line.split(" ")
            if len(p) == 4:
                try:
                    self.times = (float(p[1]), float(p[2]), float(p[3]))
                except ValueError:
                    pass
        elif self.not_prepared and line.startswith(self.not_prepared):
            self.shaders_later = True

    def count(self):
        """(the count at the Compile row's right, as drawn: "31 of 58")"""
        row = self.step("compile")
        if row and self.changed >= 0:
            row[3] = "Already built" if self.changed == 0 else "%d of %d" % (self.compiled, self.changed)

    def end(self, ok):
        for s in self.steps:
            if s[2] == "now":
                s[2] = "done" if ok else "stopped"
        if ok:
            self.reach(1.0)

    def bar(self):
        """in the bar that fills (Paper: "Build Menu - Building", "Releases Menu - Updating"): "Building... 42%" """
        verb = self.title.split(" ")[0] if self.title.split(" ")[0] in ("Building", "Updating", "Switching", "Rebuilding") else "Working"
        return "%s... %d%%" % (verb, int(self.fraction * 100))

    def step_line(self, now=None):
        """the one line under the bar: the step under way, "Read the game files...", "Compile 31 of 58 · 18 min left",
        "Prepare the shaders... 25% · 30 min left" """
        if self.stage is None:
            return self.says + ("" if self.says.endswith("...") else "...")
        row = self.step(self.stage)
        if self.stage == "compile":
            files = " %d of %d" % (self.compiled, self.changed) if self.changed > 0 else ""
            return "Compile%s · %s" % (files, short_left(self.eta) if self.eta >= 0 else "estimating...")
        if self.stage == "shaders":
            line = "%s... %d%%" % (row[1] if row else self.says, int(self.shader_done * 100))
            gone = ((time.time() if now is None else now) - self.shader_started) if self.shader_started else 0
            if 0.02 <= self.shader_done < 1 and gone >= 20:
                line += " · " + short_left(gone / self.shader_done * (1 - self.shader_done))
            return line
        return (row[1] if row else self.says) + "..."

    def rebuild_line(self):
        """the first line under an update's bar: a version is never downloaded ready to play, its tools build the game
        again from the player's own files, and that is said plainly ("Rebuilding your game as v2.2.0")"""
        if self.title.startswith("Rebuilding "):   # (the version in the folder, built again: Settings' Rebuild, or its own row)
            return "Rebuilding your game with your settings now"
        name = self.title.partition(" to ")[2]
        return "Rebuilding your game as %s" % name if name else "Rebuilding your game"

    def under_bar(self, typical, now=None):
        """the two lines under an update's bar: that it is a rebuild, then the step and the time left. Until the compile
        gives its own time, the time is what a build took on this PC before (typical, in seconds; None when none was kept)
        less the time gone"""
        step = self.step_line(now)
        # (the build's usual time has no shaders in it: their step has its own, step_line)
        if not (self.stage == "compile" and self.eta >= 0) and self.stage != "shaders" and typical:
            left = typical - ((time.time() if now is None else now) - self.started)
            if left >= 90:
                waiting = " · estimating..."
                step = "%s · %s" % (step[:-len(waiting)] if step.endswith(waiting) else step.rstrip("."), short_left(left))
        return self.rebuild_line() + "\n" + step

    def stopped_title(self):
        """what the stopped state says under Retry: "The build stopped", "The update to v2.2.0 stopped" """
        if not self.update:
            return "The build stopped"
        verb, _space, rest = self.title.partition(" ")
        if verb == "Rebuilding":
            return "The rebuild of %s stopped" % rest
        return "The %s %s stopped" % ("update" if verb == "Updating" else "switch", rest)
