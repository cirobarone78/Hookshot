"""The launcher, for Linux: the Windows launcher's one screen (builder/HookshotBuilder/MainWindow.xaml, Launcher.cs and the
build in MainWindow.xaml.cs, as drawn in Paper's "Hookshot v2") on a Tk canvas. The wordmark over a dim picture of the game,
Play, and the version the game folder holds under it. Menu opens a panel from the left with three tabs: Build (the game
files, the folder, Build Game, and the build's options; the build fills its button), Releases (the versions, each brought into
the folder by a press: launch_list.py) and Settings; at its foot Check for updates, which becomes Update Available, and the
bar of an update under way.

launcher_art.py paints the picture, the shapes and the panel's ground (numpy); this file lays them out in the drawing's own
measures (a 960 x 640 window, scaled as the builder's is), draws the panel's square boxes and writes the text over them, and
does what a press asks for. Tk has no buttons that are see-through or torn at the edge, so the canvas is the whole screen and
this file finds what the pointer is on (regions).

What Windows has and this has not: its own title bar (the window manager draws one here), dev builds as folders beside the
game (scripts/build-game.ps1 makes them there), the game files found on the PC by themselves and dropped onto the window, and
AMD FSR 4."""
import base64
import ctypes
import ctypes.util
import json
import math
import os
import signal
import subprocess
import sys
import threading
import time
import traceback

import tkinter as tk
from tkinter import filedialog, messagebox

import game_env
import launcher_art as art
import linux_update
from launch_list import SHOWN, is_pre, is_release, make_lists, newer, same_tag, tab_rows, version_name
from launch_work import KEPT, Work, about, span

GITHUB_PAGE = "https://github.com/NotRexed/Hookshot"
CREDITS_PAGE = "https://github.com/NotRexed/Hookshot#credits"
DISCORD_PAGE = "https://discord.gg/EajnD2AJD9"   # (the server CONTRIBUTING.md names)
WHAT = "Ocarina of Time Remake Recomp"

# ---- the colours, as Paper's "Hookshot v2" has them ----
WHITE, QUIET, FOLD, DIM = "#FFFFFF", "#BCBCBC", "#8E8E8E", "#747474"
TAB_INK, LABEL, FIELD_INK, OFF_INK = "#C5C5C5", "#B8B8B8", "#D6D6D6", "#B0B0B0"
HERE, BUSY, WHY, BUGS = "#ACDF75", "#BBBBBB", "#FF8373", "#E3B955"
TABS, EDGE, PICKED, FIELD, FIELD_EDGE, RULE = "#2B2B2B", "#363636", "#B86C00", "#222222", "#5B5B5B", "#282828"
TRACK, FILLED, STOP, OFFER = "#B4692A", "#D2823F", "#882D23", "#D2823F"
GO_INK = "#37291D"
PANEL = 268   # (the panel's width, its line at the right included)
TABS_ORDER = (("build", "Build"), ("releases", "Releases"), ("settings", "Settings"))


def mix(a, b, k):
    """a moved k of the way to b (#RRGGBB)"""
    pa, pb = (tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in (a, b))
    return "#%02X%02X%02X" % tuple(int(round(x + (y - x) * k)) for x, y in zip(pa, pb))


def lit(color):
    """(under the pointer: white at 10% over it)"""
    return mix(color, WHITE, 0.1)


GO_INK_OFF = mix("#161616", GO_INK, 0.2)   # (Play's word at Paper's opacity of 0.2, over the dim picture)


# ---- what is on GitHub and on this PC ----
def release_list(get=None):
    """GitHub's releases as make_lists takes them, and the latest release's tag; ([], None) when it did not answer.
    (development) HOOKSHOT_LATEST_TAG=v1.2.0-rc.1,v1.1.0,v1.0.0?: the releases instead, newest first. One with a part after
    its numbers is a pre-release, the first without is the latest, one ending in ? has no builder to download; none: no answer"""
    fake = os.environ.get("HOOKSHOT_LATEST_TAG")
    if fake:
        found = [] if fake == "none" else [(t.rstrip("?"), is_pre(t), not t.endswith("?")) for t in
                                           (x.strip() for x in fake.split(",")) if t]
    else:
        get = get or (lambda url: linux_update.fetch_bytes(url, 8))
        try:
            found = [(r["tag_name"], bool(r.get("prerelease")),
                      any(a.get("name") == linux_update.LIST_NAME for a in r.get("assets") or []))
                     for r in json.loads(get(linux_update.RELEASES_API).decode("utf-8"))
                     if not r.get("draft") and is_release(r.get("tag_name") or "")]
        except Exception:
            found = []
    return found, next((tag for tag, pre, _download in found if not pre), None)


def typical_build(make_game):
    """how long a build took on this PC lately, in seconds (make_game.py's build_times.json in its own work folder: the middle
    of the last five), or None when none was kept"""
    work = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "hookshot-builder")
    try:
        took = sorted(float(b["total_seconds"]) for b in make_game.load_times(work)["builds"][-5:]
                      if 0 < float(b["total_seconds"]) < math.inf)
    except Exception:   # (a record from other tools, or none: no time is guessed)
        return None
    return took[len(took) // 2] if took else None


def folder_version(folder):
    """linux_update.game_version, and (None, False) when the folder's hookshot_version.txt cannot be read as text"""
    try:
        return linux_update.game_version(folder)
    except (OSError, ValueError):
        return None, False


def existing_dir(path):
    """the path, or the nearest folder above it that is there (a file dialog's first folder), else the home folder"""
    path = os.path.abspath(os.path.expanduser(path)) if path else ""
    while path and not os.path.isdir(path):
        parent = os.path.dirname(path)
        path = "" if parent == path else parent
    return path or os.path.expanduser("~")


def installed_builders():
    """The releases whose builder is installed here (versions/<tag>, as an update keeps them), and the one running."""
    found = []
    try:
        root = os.path.join(linux_update.data_root(), "versions")
        for name in sorted(os.listdir(root)):
            tag = linux_update.tools_tag(os.path.join(root, name))
            if tag and is_release(tag):
                found.append(tag)
    except OSError:
        pass
    running = linux_update.tools_tag(linux_update.running_root() or "")
    if running and is_release(running):
        found.append(running)
    return found


def memory_gb():
    """this PC's memory, in GB (the build's Memory choices go up to it)"""
    try:
        return int(round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2 ** 30))
    except (ValueError, OSError, AttributeError):
        return 16


# ---- the fonts: Inter for the lines (its SemiBold for the buttons' words), Marcellus for Play (all OFL, beside this file or
# in the checkout) ----
FONT_FILES = ("Inter-Regular.ttf", "Inter-SemiBold.ttf", "Marcellus-Regular.ttf")


def font_files():
    root = os.path.dirname(os.path.dirname(art.HERE))
    found = {}
    for folder in (os.path.join(art.ASSETS, "fonts"), os.path.join(root, "builder", "HookshotBuilder", "Fonts"),
                   os.path.join(root, "builder", "py", "hookshot_builder", "assets", "Fonts")):
        for name in FONT_FILES:   # (not Inter's Bold, which the checkout also has: the buttons are drawn in its SemiBold)
            if os.path.isfile(os.path.join(folder, name)):
                found.setdefault(name, os.path.join(folder, name))
    return list(found.values())


def own_font():
    """A font of the player's own for the button's word: the first .otf or .ttf in ~/.local/share/hookshot/fonts (Windows:
    HookshotBuilder\\fonts). Never shipped with the builder. (its file, its family's name), or None"""
    folder = os.path.join(os.path.dirname(linux_update.data_root()), "fonts")
    try:
        names = sorted(n for n in os.listdir(folder) if n.lower().endswith((".ttf", ".otf")))
    except OSError:
        return None
    if not names:
        return None
    path = os.path.join(folder, names[0])
    env = {k: v for k, v in os.environ.items() if k != "LD_LIBRARY_PATH"}
    try:
        family = subprocess.run(["fc-scan", "--format", "%{family[0]}", path], env=env, capture_output=True, text=True,
                                timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        family = ""
    return (path, family) if family else None


def add_fonts(paths):
    """Fonts from files, for this program alone (fontconfig, which Tk's Xft reads): True when it took them."""
    try:
        fc = ctypes.CDLL(ctypes.util.find_library("fontconfig") or "libfontconfig.so.1")
        fc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        fc.FcConfigAppFontAddFile.restype = ctypes.c_int
        return all([fc.FcConfigAppFontAddFile(None, os.fsencode(p)) for p in paths])
    except (OSError, AttributeError):
        return False


class Launcher(object):
    """The one screen. app: hookshot_builder's Builder (its queue brings what the threads here find back to the Tk thread;
    its settings, the same builder.ini, are the build's options)."""

    def __init__(self, app, folder):
        self.app, self.folder, self.scale = app, folder or "", app.scale
        self.hb = sys.modules[type(app).__module__]   # (hookshot_builder, which opened this: its helpers, not a second copy)
        # (development) HOOKSHOT_UI_PREVIEW=menu,tab=releases,older,building|stopped|updating|update-stopped: the panel open on
        # that tab from the start, its older releases unfolded, a build or an update made up and drawn half way or stopped
        preview = [p.strip() for p in os.environ.get("HOOKSHOT_UI_PREVIEW", "").split(",")]
        self.older_open = "older" in preview
        self.share_said = None   # (what Save my pipeline list did, under it in Settings)
        self.releases, self.latest, self.checked, self.checking, self.check_says = [], None, False, False, None
        self.photos, self.regions, self.hot, self.down, self.size, self.scroll = {}, [], None, None, (0, 0), 0
        self.redraw_job = self.tip_job = self.tip_window = self.tick_job = self.said_job = None
        self.exited_at = None   # (when the build's program was seen gone while its output had not ended: tick)
        self.work, self.proc, self.state, self.details, self.log_box, self.log_shown = None, None, "idle", False, None, 0
        self.ready_note, self.copied, self.bringing, self.rows_fit = None, None, None, 0
        self.typical, self.foot_note = None, None   # (how long a build took here lately: typical_build; the note drawn under an update's bar)
        self.fonts()
        u = self.u
        app.minsize(u(960), u(640))
        app.geometry("%dx%d" % (u(960), u(640)))
        self.canvas = c = tk.Canvas(app, background="#121212", highlightthickness=0, borderwidth=0)
        c.pack(fill="both", expand=True)
        c.bind("<Configure>", self.on_size)
        c.bind("<Motion>", self.on_move)
        c.bind("<Leave>", lambda e: self.point(None))
        c.bind("<Button-1>", self.on_press)
        c.bind("<ButtonRelease-1>", self.on_release)
        c.bind("<MouseWheel>", lambda e: self.on_wheel(e, -1 if e.delta > 0 else 1))
        c.bind("<Button-4>", lambda e: self.on_wheel(e, -1))
        c.bind("<Button-5>", lambda e: self.on_wheel(e, 1))
        c.bind("<Destroy>", self.on_destroy)
        self.keys = [(key, app.bind(key, action)) for key, action in
                     (("<Return>", lambda e: self.play()), ("<Escape>", lambda e: self.show_menu(False)))]
        self.check_trace = app.check_text.trace_add("write", lambda *a: self.menu_open and self.tab == "build" and self.draw())
        self.enter(self.folder)
        # (no game yet: the panel open on Build. Else it opens on Releases the first time)
        game = self.hb.game_ready(self.folder)
        self.menu_open = not game or "menu" in preview or "versions" in preview
        self.tab = next((p[4:] for p in preview if p.startswith("tab=")), "releases" if game else "build")
        if self.source_ready() and not app.check_text.get():
            app.check_version()
        self.check(say=False)
        for made_up in ("building", "stopped", "updating", "update-stopped"):
            if made_up in preview:
                self.make_up(made_up)

    def u(self, n):
        return int(round(n * self.scale))

    # ---- fonts and images ----
    def fonts(self):
        app = self.app
        own = own_font()
        took = add_fonts(font_files() + ([own[0]] if own else []))
        families = {name.lower(): name for name in app.tk.splitlist(app.tk.call("font", "families"))}
        line = next((families[n] for n in ("inter", "segoe ui", "cantarell", "noto sans", "dejavu sans") if n in families), None)
        # (Paper's Segoe UI Semibold: Inter SemiBold when fontconfig names it a family of its own, else the line's family in bold)
        strong = families.get("inter semibold")
        word = next((families[n] for n in ([own[1].lower()] if own and took else []) + ["marcellus"] if n in families), None)
        mono = next((families[n] for n in ("cascadia mono", "jetbrains mono", "dejavu sans mono", "noto sans mono", "liberation mono")
                     if n in families), None)
        named = set(app.tk.splitlist(app.tk.call("font", "names")))
        for name, size, family, weight in (("LsLine", 16, line, "normal"), ("LsLabel", 12, line, "normal"), ("LsWhy", 13, line, "normal"),
                                           ("LsStrong", 16, strong or line, "normal" if strong else "bold"),
                                           ("LsUnder", 14, strong or line, "normal" if strong else "bold"),
                                           ("LsGo", 44, word or line, "normal"), ("LsGoSmall", 30, word or line, "normal"),
                                           ("LsLog", 11, mono, "normal")):
            options = ["-size", -self.u(size), "-weight", weight] + (["-family", family] if family else [])
            app.tk.call("font", "configure" if name in named else "create", name, *options)

    def measure(self, font, text):
        return int(self.app.tk.call("font", "measure", font, text))

    def fit(self, font, text, width):
        """text, cut short with … when it is wider than width"""
        if self.measure(font, text) <= width:
            return text
        low, high = 1, len(text) - 1   # (the most of it that fits with the …, found by halves: a long path is many measures)
        while low < high:
            mid = (low + high + 1) // 2
            if self.measure(font, text[:mid] + "…") <= width:
                low = mid
            else:
                high = mid - 1
        return text[:low].rstrip() + "…"

    def photo(self, key, make):
        """An image painted once and kept (Tk drops an image nothing holds)."""
        if key not in self.photos:
            self.photos[key] = tk.PhotoImage(master=self.app, data=base64.b64encode(art.png(make())))
        return self.photos[key]

    def pill(self, w, h, color=(0, 0, 0), alpha=1.0):
        return self.photo(("pill", w, h, color, alpha), lambda: art.pill(w, h, self.scale, color, alpha))

    def mark(self, name, color):
        rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
        return self.photo(("mark", name, rgb), lambda: art.mark(name, self.scale, rgb))

    # ---- the folder and its versions ----
    def enter(self, folder, note=None):
        """The screen becomes the launcher of that folder: at the start, and when a build here has made the game"""
        self.folder, self.state, self.ready_note = folder or "", "idle", note
        self.built, self.rebuilds = folder_version(self.folder)
        self.show_details(False)
        self.fill()

    def fill(self):
        self.typical = typical_build(self.hb.make_game)   # (read again with the lists: after a build it has one more)
        self.lists = make_lists(self.releases, self.latest, self.built, installed_builders(), self.rebuilds, None,
                                self.older_open, in_sight=SHOWN)
        self.draw()

    def newer_out(self):
        """the latest release is ahead of the one this folder holds"""
        return bool(self.latest and self.built and is_release(self.built) and newer(self.latest, self.built))

    def pre_on(self):
        """(Settings, Enable pre-releases: the update track is a release candidate's, or nightly)"""
        return self.app.track_id() != "release"

    def check(self, say):
        """GitHub's releases asked for: when the launcher opens, and by Check for updates, which then says what came of it"""
        if self.checking:
            return
        self.checking = True
        if hasattr(self, "tab") and self.menu_open:
            self.draw()

        def run():
            found = [], None
            try:
                found = release_list()
            finally:   # (an answer always comes back: else Check for updates would say Checking… for good)
                self.app.lines.put(("launcher", ("releases", found, say)))
        threading.Thread(target=run, daemon=True).start()

    def message(self, what):
        """(from the builder's queue, on the Tk thread. Its loop stops at an exception, and every later message with it: so
        none leaves here, and work that cannot go on is stopped with the reason)"""
        try:
            self.take(what)
        except Exception as error:
            traceback.print_exc()
            work = self.work
            if what[0] in ("exit", "failed") and work is not None and what[1] is work and self.state == "working":
                self.state = "stopped"
                work.error = work.error or "The launcher stopped: %s" % (str(error) or type(error).__name__)
                try:
                    self.draw()
                except Exception:
                    traceback.print_exc()

    def take(self, what):
        kind = what[0]
        if kind == "releases":
            (found, latest), say = what[1], what[2]
            if found or not self.releases:   # (no answer: the releases of the check before stay)
                self.releases, self.latest = found, latest
            self.checked, self.checking = True, False
            if say and not self.newer_out():
                self.check_says = "Could not check" if not found else "Up to date"
                if self.said_job is not None:
                    self.app.after_cancel(self.said_job)
                self.said_job = self.app.after(2400, self.check_said)
            self.fill()
        elif what[1] is not self.work:
            return   # (from a build that was cancelled, or the one before)
        elif self.work.cancelled and kind != "exit":
            return   # (cancelled: what its download still says or brings is not used, its program's end is waited for)
        elif kind == "line":
            self.work_line(what[2])
        elif kind == "exit":
            self.work_ended(what[2])
        elif kind == "note":
            self.work.note(what[2])
            self.show_work()
        elif kind == "fetched":   # (that version's builder is these tools: the folder is built here)
            self.work.fetched()
            self.run_update()
        elif kind == "failed":
            self.work.error = what[2]
            self.work_ended(1)

    def check_said(self):
        self.check_says, self.said_job = None, None
        if self.canvas.winfo_exists():
            self.draw()

    # ---- a build from game files (the Build tab) ----
    def source_ready(self):
        app = self.app
        if app.kind.get() == "nup":
            return os.path.isfile(app.nup.get())
        return os.path.isdir(app.romfs.get()) and os.path.isdir(app.exefs.get())

    def source_words(self):
        """the game files chosen, as their box says them: (words, they are there)"""
        app = self.app
        if app.kind.get() == "nup" and os.path.isfile(app.nup.get()):
            return os.path.basename(app.nup.get()), True
        if app.kind.get() != "nup" and os.path.isdir(app.romfs.get()) and os.path.isdir(app.exefs.get()):
            return "romfs and exefs folders", True
        return "Browse files", False

    def source_check(self):
        """what the check of the game files said, and whether it is the supported version (None: no answer yet)"""
        said = self.app.check_text.get()
        if not said or said.startswith("Checking"):
            return said, None
        return said, said.startswith("This is the version")

    def choose_source(self):
        """the ways to choose the game files, in a list under the pointer"""
        menu = tk.Menu(self.canvas, tearoff=0, font="LsLabel", borderwidth=0, activeborderwidth=0)
        menu.add_command(label="Browse for a .nup file…", command=self.choose_nup)
        menu.add_command(label="Use romfs and exefs folders…", command=self.choose_folders)
        self.popup(menu)

    def popup(self, menu):
        """a list under the pointer (its grab let go after, as Tk's own menus do)"""
        self.hide_tip()
        try:
            menu.tk_popup(self.canvas.winfo_pointerx(), self.canvas.winfo_pointery())
        finally:
            menu.grab_release()

    def choose_nup(self):
        app = self.app
        path = filedialog.askopenfilename(parent=app, title="Your game's .nup", initialdir=existing_dir(os.path.dirname(app.nup.get())),
                                          filetypes=[("Switch 2 game package", "*.nup"), ("All files", "*")])
        if path:
            app.kind.set("nup")
            app.nup.set(path)
            self.source_chosen()

    def choose_folders(self):
        app = self.app
        romfs = filedialog.askdirectory(parent=app, title="Choose the romfs folder", initialdir=existing_dir(app.romfs.get()))
        if not romfs:
            return
        beside = os.path.join(os.path.dirname(romfs), "exefs")
        exefs = beside if os.path.isdir(beside) else filedialog.askdirectory(parent=app, title="Choose the exefs folder", initialdir=os.path.dirname(romfs))
        if exefs:
            app.kind.set("folders")
            app.romfs.set(romfs)
            app.exefs.set(exefs)
            self.source_chosen()

    def source_chosen(self):
        self.back_to_idle()
        self.app.check_text.set("Checking that it is the supported version…")
        self.app.check_version()
        self.draw()

    def choose_out(self):
        app = self.app
        folder = filedialog.askdirectory(parent=app, title="Choose where the game goes", initialdir=existing_dir(app.out.get().strip()))
        if folder:
            app.out.set(folder)
            self.back_to_idle()
            self.draw()

    def back_to_idle(self):
        """(a build that stopped is left once anything it was made from changes)"""
        if self.state == "stopped" and self.work is not None and not self.work.update:
            self.state = "idle"
            self.show_details(False)

    def build_env(self, dlss):
        """make_game.py's environment: NVIDIA's SDK when DLSS is on, and the build's Memory choice"""
        env = self.hb.make_game_env(dlss) if dlss or "HOOKSHOT_NGX_SDK" in os.environ else dict(os.environ)
        memory = self.app.cfg.get("memory", "")
        if memory.isdigit() and int(memory) > 0:
            env["HOOKSHOT_MEM_LIMIT_GB"] = memory
        return env

    def build_jobs(self):
        """the build's Workers choice, else HOOKSHOT_JOBS (None: make_game.py chooses)"""
        workers = self.app.cfg.get("workers", "")
        if workers.isdigit() and int(workers) > 0:
            return int(workers)
        jobs = self.hb.make_game.requested_jobs(os.environ.get("HOOKSHOT_JOBS"))
        if jobs is None and os.environ.get("RX_JOBS"):   # (the older setting, still honoured)
            jobs = self.hb.toolchain.default_jobs()
        return jobs

    def start_build(self):
        """Build Game pressed: make_game.py from the game files chosen, into the folder chosen (hookshot_builder's build, here)"""
        app, hb = self.app, self.hb
        out = app.out.get().strip()
        if not self.source_ready() or not out or self.state == "working":
            return
        out = os.path.abspath(os.path.expanduser(out))   # (make_game.py runs in the tools' folder: a relative one would land there)
        src = ["--nup", app.nup.get()] if app.kind.get() == "nup" else ["--romfs", app.romfs.get(), "--exefs", app.exefs.get()]
        try:
            jobs = self.build_jobs()
        except ValueError as error:
            return messagebox.showerror("Hookshot", str(error), parent=app)
        try:
            slow = hb.slow_disk_warning(out)   # (a warning, not a stop: a hard drive still builds, only much slower)
        except Exception:   # (the drive's kind could not be told)
            slow = None
        if slow is not None and not messagebox.askokcancel("Hookshot", slow, parent=app):
            return
        code = next((c for c, n in hb.make_game.LANGUAGES if n == app.language.get()), "en-US")
        dlss = bool(app.dlss.get())
        app.cfg.update(kind=app.kind.get(), nup=app.nup.get(), romfs=app.romfs.get(), exefs=app.exefs.get(), out=out, language=code,
                       prepare="1" if app.prepare.get() else "0", dlss="1" if dlss else "0")
        self.save()
        args = src + ["--out", out, "--language", code] + ([] if jobs is None else ["--jobs", str(jobs)]) + \
            ([] if app.prepare.get() else ["--no-prepare-shaders"]) + (hb.dlss_args(True) if dlss else [])
        self.tab = "build"
        self.begin_work(Work("Building your game", shaders=bool(app.prepare.get()), back="files",
                             not_prepared=hb.make_game.NOT_PREPARED))
        self.run(args, self.build_env(dlss))

    # ---- a version brought into the folder (the Releases tab, Update Available; Paper: "Releases Menu - Updating") ----
    def bring(self, choice):
        """a release's row pressed: the folder updated to it, or switched back to an older one (asked first)"""
        if self.state == "working" or not choice.reach:
            return
        if self.asked(choice.tag):
            self.start_update(choice.tag)

    def update_latest(self):
        """Update Available: the latest release brought into the folder"""
        if self.state != "working" and self.newer_out() and self.asked(self.latest):
            self.start_update(self.latest)

    def asked(self, tag):
        """asked every time: a version is not downloaded ready to play, its tools build the game again from the player's files"""
        name = version_name(tag)
        rebuild = ("Your game is rebuilt from your game files with %s's tools. That takes %s on this PC, and Play waits until "
                   "it is done. Your saves and settings stay." % (name, about(self.typical)))
        ahead = not self.built or not is_release(self.built) or newer(tag, self.built)
        return messagebox.askyesno("Hookshot", ("Update to %s?\n\n%s" if ahead else "Switch back to %s?\n\n%s") % (name, rebuild),
                                   parent=self.app)

    def rebuild(self):
        """The version in the folder built again from the game files it keeps, with the settings now (asked first): Settings'
        Rebuild, or its own row in Releases. DLSS takes effect at a build, not when it is switched"""
        if self.state == "working" or not self.has_game():
            return
        name = version_name(self.built) if self.built and is_release(self.built) else "your game"
        ask = ("Rebuild %s?\n\nYour game is built again from your game files with your settings now (DLSS %s). That takes %s on "
               "this PC, and Play waits until it is done. Your saves and settings stay." %
               (name, "on" if self.app.dlss.get() else "off", about(self.typical)))
        if messagebox.askyesno("Hookshot", ask, parent=self.app):
            self.start_update(self.built if self.built and is_release(self.built) else None, rebuild=True)

    def rebuild_note(self):
        """Settings' note when DLSS is on and the game in the folder was built without it, else None. (Turning it off is not
        one: NVIDIA's library stays in the folder, and the game's Upscaler menu chooses whether it is used)"""
        if self.has_game() and self.app.dlss.get() and not self.hb.folder_has_dlss(self.folder):
            return "Built without DLSS"
        return None

    def has_game(self):
        return bool(self.folder) and os.path.isfile(os.path.join(self.folder, "bin", "hookshot"))

    def start_update(self, tag=None, fetched=False, rebuild=False):
        """The folder updated or switched to a release: its builder installed first when these tools are not it (the new
        builder then starts on this folder, hookshot_builder's begin_update), else the folder built again here"""
        app = self.app
        target = tag or linux_update.update_target(app.latest, app.tools, app.switching())
        ahead = not self.built or not is_release(self.built) or not target or not is_release(target) or newer(target, self.built)
        name = version_name(target) if target and is_release(target) else target or "the newest version"
        # (no version named, as the game's own update offer starts it, --update <folder>: the track's target may be older than
        # the folder's, a newer release candidate's or nightly's (#2352). Asked first, as a row of an older release is)
        if tag is None and not ahead and not self.asked(target):
            return
        fetch = not fetched and not (app.tools and target == app.tools)
        title = ("Rebuilding " if rebuild else "Updating to " if ahead else "Switching to ") + name
        work = Work(title, update=True, fetch=fetch, shaders=bool(app.prepare.get()), not_prepared=self.hb.make_game.NOT_PREPARED)
        self.bringing = target
        self.begin_work(work)
        if not fetch:
            return self.run_update()
        # (read here: only the Tk thread may touch the builder's Tk variables)
        named = target if target and (tag or app.switching() or linux_update.track_of(target) != "release") else None
        folder = self.folder

        def run():
            try:
                root = linux_update.running_root()
                if root is None:
                    raise RuntimeError("These tools are a source checkout, so they cannot download a release. Start the AppImage to update")
                manifest = linux_update.startup_manifest(root, tag=named)
                if work.cancelled:
                    return
                if manifest.tag == linux_update.tools_tag(root):
                    return app.lines.put(("launcher", ("fetched", work)))
                # (as Windows does: GitHub's latest list lags right after a publish, and installing it would put the
                # release before the one asked for over these tools)
                if tag and manifest.tag != tag:
                    raise RuntimeError("GitHub offered %s, not %s: its download links can lag right after a release. "
                                       "Try again in a few minutes" % (manifest.tag, tag))
                parts, done = len(manifest.parts), [0]

                def note(message):
                    # (said once a part: Cancel stops the download there, and install leaves nothing of it behind)
                    if work.cancelled:
                        raise RuntimeError("Cancelled")
                    done[0] += 1
                    app.lines.put(("launcher", ("note", work, "%s, part %d of %d" % (message, done[0], parts) if parts else message)))
                apprun = linux_update.install(manifest, root, linux_update.read_manifest(root), note=note)
                if work.cancelled:
                    return
                env = {k: v for k, v in os.environ.items() if k not in ("APPDIR", "APPIMAGE", "ARGV0", "OWD", "LD_LIBRARY_PATH")}
                os.execve(apprun, [apprun, "--update", folder, "--tag", manifest.tag, "--fetched"], env)
            except Exception as error:
                app.lines.put(("launcher", ("failed", work, str(error) or type(error).__name__)))
        threading.Thread(target=run, daemon=True).start()

    def run_update(self):
        app, hb = self.app, self.hb
        # (a folder built with NVIDIA DLSS, its license accepted then, is built with it again; a rebuild is for the settings now)
        rebuilding = self.work is not None and self.work.title.startswith("Rebuilding ")
        dlss = bool(app.dlss.get()) if rebuilding else hb.folder_has_dlss(self.folder)
        try:
            jobs = self.build_jobs()
        except ValueError:
            jobs = None
        self.run(["--update", self.folder] + ([] if jobs is None else ["--jobs", str(jobs)]) +
                 ([] if app.prepare.get() else ["--no-prepare-shaders"]) + hb.dlss_args(dlss), self.build_env(dlss))

    # ---- the work itself: make_game.py as a hidden program, and what it says ----
    def begin_work(self, work):
        self.work, self.state, self.ready_note, self.copied, self.exited_at = work, "working", None, None, None
        self.show_details(False)
        self.menu_open = True   # (the panel holds the bar that fills: the build's in Build, an update's at its foot)
        self.draw()
        if self.tick_job is not None:   # (one tick at a time: a build started again within the second of the last one's)
            self.app.after_cancel(self.tick_job)
        self.tick()

    def run(self, args, env):
        """(development) HOOKSHOT_MAKE_GAME=<script>: that instead of nx2/make_game.py, to try the screen with no game"""
        work = self.work
        make = os.environ.get("HOOKSHOT_MAKE_GAME") or os.path.join(self.hb.ROOT, "nx2", "make_game.py")
        try:
            proc = subprocess.Popen([sys.executable, "-I", make] + args, cwd=self.hb.ROOT, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, bufsize=1, encoding="utf-8", errors="replace",
                                    start_new_session=True)
        except OSError as error:
            work.error = "The build tools could not be started: %s" % error
            return self.work_ended(1)
        self.proc = self.app.proc = proc   # (the builder's own close asks before it stops a build)

        def read():
            try:
                for line in proc.stdout:
                    self.app.lines.put(("launcher", ("line", work, line.rstrip("\n"))))
            finally:   # (its end always said: else the screen would wait on it for good)
                self.app.lines.put(("launcher", ("exit", work, proc.wait())))
        threading.Thread(target=read, daemon=True).start()

    def work_line(self, line):
        work = self.work
        before = (int(work.fraction * 100), work.step_line())
        work.line(line)
        if self.details and self.log_box is not None:
            self.fill_log()
        if (int(work.fraction * 100), work.step_line()) != before:
            self.show_work()

    def show_work(self):
        if self.canvas.winfo_exists() and self.state == "working":
            self.draw()

    def tick(self):
        """(the line under the bar, once a second: the compile's time left)"""
        self.tick_job = None
        if self.state != "working" or not self.canvas.winfo_exists():
            return
        self.canvas.itemconfigure("step", text=self.fit("LsLabel", self.work.step_line(), self.u(235)))
        # (the time left under an update's bar, while the panel shows it)
        if self.work.update and self.menu_open and self.work.under_bar(self.typical) != self.foot_note:
            self.draw()
        # (make_game.py gone, and its output not ended 10 seconds on: a program it started holds it open. It is over all the same)
        proc = self.proc
        if proc is not None and proc.poll() is not None:
            self.exited_at = self.exited_at or time.time()
            if time.time() - self.exited_at > 10:
                return self.work_ended(proc.returncode)
        self.tick_job = self.app.after(1000, self.tick)

    def cancel(self):
        work = self.work
        if self.state != "working" or work is None:
            return
        work.cancelled = True
        proc = self.proc
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except OSError:
                pass
            self.app.after(8000, lambda: self.kill(proc))   # (one that has not stopped 8 seconds on is made to)
        else:   # (that version's builder still being downloaded: it stops at its next part, and what it brings is not used)
            self.work_ended(1)

    @staticmethod
    def kill(proc):
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass

    def work_ended(self, code):
        work, hb = self.work, self.hb
        if work is None or self.state != "working":
            return   # (said twice: the end of its program seen by tick, then its output's end)
        self.proc = self.app.proc = None
        folder = work.done or (self.folder if work.update else None)
        ok = code == 0 and bool(folder) and hb.game_ready(folder) and not work.cancelled
        work.end(ok)
        if ok:
            try:
                hb.add_to_menu(folder)
            except (OSError, ValueError):   # (no menu entry; the game is built)
                pass
            took = span(time.time() - work.started)
            note = "Your game is %s · %s in %s" % (("updated", "updated", took) if work.update else ("ready", "built", took))
            if work.shaders_later:
                note += " · its shaders are prepared at its first start"
            self.bringing = None
            return self.enter(folder, note)
        if work.cancelled:   # (cancelled: as it was before, with nothing said)
            self.state, self.bringing = "idle", None
            self.show_details(False)
            return self.fill()
        if not work.error:
            work.error = "The build tools stopped without saying why"
        self.state = "stopped"
        self.draw()

    def dismiss(self):
        """(an update that stopped, left as it is: Check for updates and Update Available come back, as on Windows)"""
        if self.state != "stopped":
            return
        self.state = "idle"
        self.show_details(False)
        self.draw()

    def retry(self):
        work = self.work
        self.state = "idle"
        self.show_details(False)
        if work.update:
            self.start_update(self.bringing)
        else:
            self.start_build()

    def copy_details(self):
        """what stopped, for a bug report: the versions, the reason and the last of what the hidden programs said"""
        work = self.work
        said = "\n".join(work.log)
        report = "Hookshot launcher (Linux): %s\nBuilder %s, the folder holds %s\n%s\n\n%s" % (
            work.stopped_title(), self.app.tools or "from source", self.built or "no release", work.error, said[-6000:])
        try:
            self.app.clipboard_clear()
            self.app.clipboard_append(report)
            self.copied = "Copied"
        except tk.TclError:
            self.copied = "Could not copy"
        self.draw()

    def make_up(self, what):
        """(development) a build or an update made up, nothing run: drawn half way, or stopped"""
        if what in ("building", "stopped"):
            work = Work("Building your game", shaders=True, back="files", not_prepared=self.hb.make_game.NOT_PREPARED)
            lines = ["@@stage read x", "@@stage lift x", "@@stage compile x", "@@plan 58 259"] + \
                ["@@file f%d.c %d new" % (i, i) for i in range(31)] + ["@@eta 1080", "@@progress 0.072"]
            self.tab = "build"
        else:
            work = Work("Updating to v2.2.0", update=True, shaders=True, not_prepared=self.hb.make_game.NOT_PREPARED)
            lines = ["@@stage read x", "@@stage lift x", "@@stage compile x", "@@progress 0.33"]
            self.bringing = "v2.2.0"
        for line in lines:
            work.line(line)
        if what == "stopped":
            work.line("@@error The compiler stopped on src_4.c")
        elif what == "update-stopped":
            work.line("@@error GitHub did not answer, so v2.2.0 could not be downloaded")
        self.work, self.ready_note, self.menu_open = work, None, True
        self.state = "stopped" if what in ("stopped", "update-stopped") else "working"
        if self.state == "stopped":
            work.end(False)
        self.draw()

    # ---- what the hidden programs said, over the picture ----
    def show_details(self, on):
        self.details = on
        if not on and self.log_box is not None:
            self.log_box.destroy()
            self.log_box = None
        if on and self.canvas.winfo_exists():
            self.draw()

    def fill_log(self):
        box, log = self.log_box, self.work.log if self.work else []
        if box is None:
            return
        box.configure(state="normal")   # (read-only to the player: only this writes in it)
        if self.log_shown > len(log):
            box.delete("1.0", "end")
            self.log_shown = 0
        if self.log_shown < len(log):
            box.insert("end", "".join(line + "\n" for line in log[self.log_shown:]))
            self.log_shown = len(log)
            box.see("end")
        box.configure(state="disabled")

    def draw_log(self):
        """(right of the panel, between the wordmark's line and Play)"""
        c, u = self.canvas, self.u
        w, h = self.size
        if self.log_box is None:
            self.log_box = tk.Text(c, font="LsLog", background="#0A0A0A", foreground=QUIET, insertbackground=QUIET, wrap="none",
                                   borderwidth=0, highlightthickness=1, highlightbackground="#303030", highlightcolor="#303030",
                                   padx=u(10), pady=u(10), cursor="xterm", state="disabled")
            self.log_shown = 0
        x = u(PANEL) + u(16)
        c.create_window(x, u(170), window=self.log_box, anchor="nw", width=max(u(120), w - x - u(16)),
                        height=max(u(60), h - u(170) - u(180)), tags="ui")
        self.fill_log()

    # ---- the screen ----
    def on_size(self, event):
        if (event.width, event.height) == self.size:
            return
        first = self.size == (0, 0)
        self.size = (event.width, event.height)
        if self.redraw_job is not None:
            self.app.after_cancel(self.redraw_job)
        if first:
            self.repaint()
        else:   # (a window being dragged larger: the picture once it rests, the rest as it goes)
            self.draw()
            self.redraw_job = self.app.after(90, self.repaint)

    def repaint(self):
        """the picture and the wordmark, the size the window is now"""
        self.redraw_job = None
        w, h = self.size
        if w < 2 or h < 2:
            return
        self.photos.pop("ground", None)
        self.canvas.delete("ground")
        try:
            ground = self.photo("ground", lambda: art.background(w, h, self.scale))
        except (MemoryError, ValueError, tk.TclError):   # (no picture: the canvas's own dark ground, the rest drawn all the same)
            traceback.print_exc()
        else:
            self.canvas.create_image(0, 0, image=ground, anchor="nw", tags="ground")
            self.canvas.tag_lower("ground")
        self.draw()

    def region(self, x0, y0, x1, y1, press=None, over=None, tip=None):
        """A place the pointer acts on (the last one made is on top). over(on): drawn as under the pointer, or not."""
        self.regions.append({"box": (x0, y0, x1, y1), "press": press, "over": over, "tip": tip})

    def box(self, x0, y0, x1, y1, fill, edge=None):
        """a square box of the panel (its line inside it, as CSS's border-box)"""
        line = max(1, self.u(1))
        if edge is None:
            return self.canvas.create_rectangle(x0, y0, x1, y1, fill=fill, width=0, tags="ui")
        return self.canvas.create_rectangle(x0 + line / 2, y0 + line / 2, x1 - line / 2, y1 - line / 2, fill=fill, outline=edge,
                                            width=line, tags="ui")

    def button(self, x0, y0, x1, y1, text, fill, ink=WHITE, press=None, edge=None, font="LsStrong", tip=None):
        """a square button of the panel (Build Game, Check for updates, Update Available, Build stopped)"""
        c = self.canvas
        item = self.box(x0, y0, x1, y1, fill, edge)
        c.create_text((x0 + x1) // 2, (y0 + y1) // 2, text=self.fit(font, text, x1 - x0 - self.u(16)), font=font, fill=ink, tags="ui")
        if press:
            self.region(x0, y0, x1, y1, press=press, tip=tip, over=lambda on: c.itemconfigure(item, fill=lit(fill) if on else fill))

    def bar_fill(self, x0, y0, x1, y1, fraction, text):
        """the bar that fills (Paper: "Building... 25%", "Updating... 43%")"""
        self.box(x0, y0, x1, y1, TRACK)
        filled = int(round((x1 - x0) * min(max(fraction, 0.0), 1.0)))
        if filled > 0:
            self.box(x0, y0, x0 + filled, y1, FILLED)
        self.canvas.create_text((x0 + x1) // 2, (y0 + y1) // 2, text=text, font="LsStrong", fill=WHITE, tags="ui")

    def link(self, x, y, text, press, font="LsLabel", ink=LABEL, anchor="center"):
        """a word that does something (Show details, Copy error log, Cancel). Returns its width"""
        c = self.canvas
        item = c.create_text(x, y, text=text, font=font, fill=ink, anchor=anchor, tags="ui")
        x0, y0, x1, y1 = c.bbox(item)
        self.region(x0 - self.u(4), y0 - self.u(4), x1 + self.u(4), y1 + self.u(4), press=press,
                    over=lambda on: c.itemconfigure(item, fill=WHITE if on else ink))
        return x1 - x0

    def links(self, cx, y, words):
        """words side by side, 8 apart, centred on cx"""
        widths = [self.measure("LsLabel", text) for text, _press in words]
        x = cx - (sum(widths) + self.u(8) * (len(words) - 1)) // 2
        for (text, press), width in zip(words, widths):
            self.link(x, y, text, press, anchor="w")
            x += width + self.u(8)

    def wrapped(self, x, y, text, font, ink, width, anchor="nw", justify="left", lines=None):
        """text in lines no wider than width, and no more than lines of them (cut short with …: a long error stays clear of
        what is under it; Copy error log has all of it). Returns its bottom (anchor n...) or top (anchor s...)"""
        c = self.canvas
        item = c.create_text(x, y, text=text, font=font, fill=ink, anchor=anchor, width=width, justify=justify, tags="ui")
        if lines is not None:
            line = int(self.app.tk.call("font", "metrics", font, "-linespace"))
            room = line * max(1, lines) + line // 2   # (half a line over: the box Tk gives may be a pixel taller)

            def fits(n):
                c.itemconfigure(item, text=text[:n].rstrip() + "…")
                y0, y1 = c.bbox(item)[1::2]
                return y1 - y0 <= room
            y0, y1 = c.bbox(item)[1::2]
            if y1 - y0 > room:
                low, high = 0, len(text) - 1
                while low < high:
                    mid = (low + high + 1) // 2
                    if fits(mid):
                        low = mid
                    else:
                        high = mid - 1
                fits(low)
        box = c.bbox(item)
        return box[1] if anchor.startswith("s") else box[3]

    def soft_word(self, cx, cy, text, press, tip=None):
        """a word on the picture with a soft pill under the pointer (the version under Play, Credits)"""
        c, u = self.canvas, self.u
        width = self.measure("LsLine", text) + u(24)
        x0, y0 = cx - width // 2, cy - u(18)
        shine = c.create_image(x0, y0, image=self.pill(width / self.scale, 36, (255, 255, 255), 0.1), anchor="nw", state="hidden",
                               tags="ui")
        c.create_text(cx, cy, text=text, font="LsLine", fill=WHITE, tags="ui")
        if press:
            self.region(x0, y0, x0 + width, y0 + u(36), press=press, tip=tip,
                        over=lambda on: c.itemconfigure(shine, state="normal" if on else "hidden"))

    def draw(self):
        c, u = self.canvas, self.u
        w, h = self.size
        if w < 2 or h < 2 or not hasattr(self, "tab"):
            return
        self.hide_tip()
        c.delete("ui")
        self.regions, self.hot = [], None
        c.create_text(w // 2, u(137) + u(10), text=WHAT, font="LsLine", fill=WHITE, tags="ui")
        self.draw_play()
        # Credits, GitHub and Discord, at the bottom right
        self.soft_word(w - u(150), h - u(42), "Credits", lambda: self.open_page(CREDITS_PAGE), "Who made Hookshot")
        for i, (name, make, page, tip) in enumerate((("github", art.github, GITHUB_PAGE, "Hookshot on GitHub"),
                                                     ("discord", art.discord, DISCORD_PAGE, "Discord"))):
            x, y = w - u(98) + i * u(42), h - u(58)
            full = self.photo((name, 1.0), lambda make=make: make(self.scale))
            soft = self.photo((name, 0.8), lambda make=make: make(self.scale, 0.8))
            item = c.create_image(x, y, image=full, anchor="nw", tags="ui")
            self.region(x, y, x + u(32), y + u(32), press=lambda page=page: self.open_page(page), tip=tip,
                        over=lambda on, item=item, full=full, soft=soft: c.itemconfigure(item, image=soft if on else full))
        if self.menu_open:
            if self.details:
                self.draw_log()
            self.draw_panel()
        else:   # (the menu's button, at the top left; its dot says a newer release is in there)
            self.menu_button(u(16), u(72), dot=self.newer_out() and self.state != "working")
        px, py = c.winfo_pointerx() - c.winfo_rootx(), c.winfo_pointery() - c.winfo_rooty()
        self.point((px, py) if 0 <= px < w and 0 <= py < h else None)

    def draw_play(self):
        """Play (Paper: a torn strip, #D2823F; at 0.2 while something is being built or brought), Build in its place while there
        is no game yet (it opens the build), Update beside it while a newer release is out, and the version the folder holds
        under it (pressed: the folder)"""
        c, u = self.canvas, self.u
        w, h = self.size
        gx, gy, gw, gh = (w - u(257)) // 2, h - u(74) - u(98), u(257), u(98)
        game = self.hb.game_ready(self.folder)
        can = self.state != "working"
        normal = self.photo(("strip", "normal"), lambda: art.strip(self.scale))
        over = self.photo(("strip", "over"), lambda: art.strip(self.scale, art.PLAY_OVER))
        off = self.photo(("strip", "off"), lambda: art.strip(self.scale, alpha=0.2))
        strip = c.create_image(gx, gy, image=normal if can else off, anchor="nw", tags="ui")
        # (the word's capitals' middle on the strip's)
        ascent = int(self.app.tk.call("font", "metrics", "LsGo", "-ascent"))
        descent = int(self.app.tk.call("font", "metrics", "LsGo", "-descent"))
        c.create_text(gx + gw // 2, gy + gh // 2 + round(0.35 * u(44) - (ascent - descent) / 2), text="Play" if game else "Build",
                      font="LsGo", fill=GO_INK if can else GO_INK_OFF, tags="ui")
        if can:
            self.region(gx, gy, gx + gw, gy + gh, press=self.play if game else self.open_build,
                        over=lambda on: c.itemconfigure(strip, image=over if on else normal))
        # (Update, at Play's right so the menu's panel never covers it: the panel's dark with the accent's words; it brings the
        # latest release, asked first, as Update Available does. Play then plays the version in the folder)
        if game and can and self.newer_out() and any(same_tag(ch.tag, self.latest) and ch.reach for ch in self.lists["all"]):
            ux, uy = gx + gw + u(12), gy + (gh - u(72)) // 2
            dark = self.photo(("update", "normal"), lambda: art.strip(self.scale, (0x2B, 0x2B, 0x2B), width=150, height=72))
            lit_ = self.photo(("update", "over"), lambda: art.strip(self.scale, (0x36, 0x36, 0x36), width=150, height=72))
            item = c.create_image(ux, uy, image=dark, anchor="nw", tags="ui")
            c.create_text(ux + u(75), uy + u(30), text="Update", font="LsGoSmall", fill=OFFER, tags="ui")
            c.create_text(ux + u(75), uy + u(54), text="to " + version_name(self.latest), font="LsLabel", fill=OFFER, tags="ui")
            self.region(ux, uy, ux + u(150), uy + u(72), press=self.update_latest, over=lambda on: c.itemconfigure(item, image=lit_ if on else dark),
                        tip="Update to %s: your game is rebuilt from your game files (%s). Your saves and settings stay."
                        % (version_name(self.latest), about(self.typical)))
        picked = self.lists["picked"]
        if not game:
            under = "No game yet"
        elif picked is not None and picked.here:
            under = picked.label if picked.kind != "dev" else picked.build
        else:
            under = version_name(self.built) if self.built and is_release(self.built) else self.built or "Your game"
        self.soft_word(w // 2, h - u(42), self.fit("LsLine", under, u(400)), (lambda: self.open_page(self.folder)) if game else None,
                       "Open the game folder")

    def menu_button(self, x, y, dot=False):
        """Menu (Paper: black, square, 8 by 20 around its lines and word; a dot after it: a newer release is out)"""
        c, u = self.canvas, self.u
        width = u(20) + u(20) + u(8) + self.measure("LsLine", "Menu") + (u(16) if dot else 0) + u(20)
        item = self.box(x, y, x + width, y + u(36), "#000000")
        c.create_image(x + u(20), y + u(8), image=self.mark("menu", WHITE), anchor="nw", tags="ui")
        tx = x + u(48)
        c.create_text(tx, y + u(18), text="Menu", font="LsLine", fill=WHITE, anchor="w", tags="ui")
        if dot:
            c.create_image(tx + self.measure("LsLine", "Menu") + u(8), y + u(14), image=self.photo("dot", lambda: art.dot(self.scale)),
                           anchor="nw", tags="ui")
        self.region(x, y, x + width, y + u(36), press=lambda: self.show_menu(True),
                    over=lambda on: c.itemconfigure(item, fill="#1A1A1A" if on else "#000000"))

    # ---- the panel (Paper: "Build Menu", "Releases Menu", "Settings Menu") ----
    def draw_panel(self):
        c, u = self.canvas, self.u
        h = self.size[1]
        # (one panel as tall as the screen, cut by the window: one made for every height a window is dragged through would all be kept)
        tall = max(h, self.app.winfo_screenheight())
        if ("bar", tall) not in self.photos:
            for key in [k for k in self.photos if k[0] == "bar"]:
                del self.photos[key]
        c.create_image(0, 0, image=self.photo(("bar", tall), lambda: art.bar(PANEL, tall, self.scale)), anchor="nw", tags="ui")
        self.region(0, 0, u(PANEL), h, press=lambda: None)   # (a press in the panel itself, between its rows: it stays)
        # Close menu: a row the panel's width, 40 high from 42
        y = u(42)
        shine = self.box(0, y, u(PANEL - 1), y + u(40), "#1A1A1A")
        c.itemconfigure(shine, state="hidden")
        c.create_image(u(20), y + u(8), image=self.mark("close", WHITE), anchor="nw", tags="ui")
        c.create_text(u(52), y + u(20), text="Close menu", font="LsLine", fill=WHITE, anchor="w", tags="ui")
        self.region(0, y, u(PANEL - 1), y + u(40), press=lambda: self.show_menu(False),
                    over=lambda on: c.itemconfigure(shine, state="normal" if on else "hidden"))
        self.draw_tabs(u(90))
        top = self.draw_foot()
        bottom = top - u(8)
        {"build": self.draw_build, "releases": self.draw_releases, "settings": self.draw_settings}[self.tab](u(140), bottom)

    def draw_tabs(self, y):
        """Build, Releases, Settings: three equal cells in a box 235 wide, the one shown in the accent"""
        c, u = self.canvas, self.u
        x0, x1 = u(16), u(251)
        self.box(x0, y, x1, y + u(38), TABS, EDGE)
        inner0, inner1 = x0 + u(5), x1 - u(5)
        cell = (inner1 - inner0) / 3.0
        for i, (key, name) in enumerate(TABS_ORDER):
            a, b = int(round(inner0 + i * cell)), int(round(inner0 + (i + 1) * cell))
            if key == self.tab:
                self.box(a, y + u(5), b, y + u(33), PICKED)
            text = c.create_text((a + b) // 2, y + u(19), text=name, font="LsLine", fill=WHITE if key == self.tab else TAB_INK, tags="ui")
            self.region(a, y + u(5), b, y + u(33), press=lambda key=key: self.show_tab(key),
                        over=None if key == self.tab else (lambda on, text=text: c.itemconfigure(text, fill=WHITE if on else TAB_INK)))

    def draw_foot(self):
        """At the panel's foot: Check for updates; Update Available when the latest release is ahead of the folder's; the bar
        of an update under way with Cancel; why it stopped. Returns the top of its line"""
        c, u = self.canvas, self.u
        h = self.size[1]
        x0, x1, cx = u(16), u(251), u(133)
        bottom = h - u(12)
        work = self.work
        update = work is not None and work.update
        if update and self.state == "working":
            self.link(cx, bottom - u(9), "Cancel", self.cancel, font="LsUnder", ink=BUSY)
            # (under the bar: that it is a rebuild, then the step and the time left; tick draws it again when it changes)
            self.foot_note = work.under_bar(self.typical)
            y = self.wrapped(cx, bottom - u(18) - u(8), self.foot_note, "LsLabel", LABEL, u(235), anchor="s", justify="center",
                             lines=3)
            top = y - u(8) - u(38)
            self.bar_fill(x0, top, x1, top + u(38), work.fraction, work.bar())
        elif update and self.state == "stopped":
            self.links(cx, bottom - u(8), [("Show details" if not self.details else "Hide details", lambda: self.show_details(not self.details)),
                                           (self.copied or "Copy error log", self.copy_details), ("Dismiss", self.dismiss)])
            y = bottom - u(16) - u(8) - u(38)
            word = "Rebuild stopped" if work.title.startswith("Rebuilding ") else "Update stopped"
            self.button(x0, y, x1, y + u(38), word, STOP, press=self.retry, tip="Try again")
            top = self.wrapped(x0, y - u(8), work.error.rstrip(".") + ". " + KEPT, "LsWhy", WHY, u(235), anchor="sw", lines=5)
        elif self.newer_out() and self.state != "working":
            # (that installing it rebuilds the game, and how long that takes here: not in Paper, said before it is pressed)
            y = self.wrapped(cx, bottom, "Rebuilds your game from your game files · %s" % about(self.typical), "LsLabel", LABEL,
                             u(235), anchor="s", justify="center")
            c.create_text(cx, y - u(8) - u(9), text="%s Latest" % version_name(self.latest), font="LsUnder", fill=WHITE, tags="ui")
            top = y - u(8) - u(18) - u(8) - u(38)
            self.button(x0, top, x1, top + u(38), "Update Available", OFFER, "#000000", self.update_latest, EDGE,
                        tip="Update your game to %s: it is rebuilt from your game files. Your saves and settings stay." % version_name(self.latest))
        else:
            top = bottom - u(38)
            says = "Checking…" if self.checking else self.check_says or "Check for updates"
            self.button(x0, top, x1, bottom, says, TABS, press=None if self.checking or self.check_says else lambda: self.check(say=True),
                        edge=EDGE)
        line = top - u(16) - max(1, u(1))
        self.box(0, line, u(PANEL - 1), line + max(1, u(1)), RULE)
        return line

    # ---- the Build tab ----
    def field(self, y, label, words, ink, press, tip=None):
        """a label and its box under it (Paper: "Game File", "Install to"). Returns the box's bottom"""
        c, u = self.canvas, self.u
        x0, x1 = u(16), u(251)
        c.create_text(x0, y + u(8), text=label, font="LsLabel", fill=WHITE, anchor="w", tags="ui")
        top = y + u(24)
        item = self.box(x0, top, x1, top + u(34), FIELD, FIELD_EDGE)
        c.create_text((x0 + x1) // 2, top + u(17), text=self.fit("LsLabel", words, x1 - x0 - u(24)), font="LsLabel", fill=ink, tags="ui")
        if press:
            self.region(x0, top, x1, top + u(34), press=press, tip=tip,
                        over=lambda on: c.itemconfigure(item, outline="#8A8A8A" if on else FIELD_EDGE))
        return top + u(34)

    def draw_build(self, y, bottom):
        app, hb, c, u = self.app, self.hb, self.canvas, self.u
        x0, x1, cx = u(16), u(251), u(133)
        work = self.work
        building = work is not None and not work.update and self.state in ("working", "stopped")
        busy = self.state == "working"
        words, there = self.source_words()
        said, good = self.source_check()
        y = self.field(y, "Game File", words, WHY if there and good is False else FIELD_INK, None if busy else self.choose_source,
                       app.nup.get() if there and app.kind.get() == "nup" else None)
        if there and good is False:   # (why the file chosen cannot be built from: one line, whole under the pointer)
            said_top = y + u(4)
            y = self.wrapped(x0, said_top, said, "LsLabel", WHY, u(235), lines=1)
            self.region(x0, said_top, x1, y, tip=said)
        out = app.out.get().strip()
        y = self.field(y + u(8), "Install to", out or "Choose a folder", FIELD_INK if out else LABEL,
                       None if busy else self.choose_out, os.path.expanduser(out) if out else None)
        top = y + u(24)
        if building and self.state == "working":
            self.bar_fill(x0, top, x1, top + u(38), work.fraction, work.bar())
            c.create_text(cx, top + u(38) + u(16), text=self.fit("LsLabel", work.step_line(), u(235)), font="LsLabel", fill=LABEL,
                          tags=("ui", "step"))
            self.links(cx, bottom - u(17), [("Show details" if not self.details else "Hide details", lambda: self.show_details(not self.details)),
                                            ("Cancel", self.cancel)])
            return
        if building:   # (it stopped: Paper's "Build Menu - Building Error")
            self.button(x0, top, x1, top + u(38), "Build stopped", STOP, press=self.retry, tip="Try again")
            line = int(self.app.tk.call("font", "metrics", "LsWhy", "-linespace"))
            room = bottom - u(17) - u(16) - (top + u(38) + u(8))   # (down to the links under it)
            self.wrapped(x0, top + u(38) + u(8), work.error.rstrip(".") + ". " + KEPT, "LsWhy", WHY, u(235),
                         lines=max(1, room // max(1, line)))
            self.links(cx, bottom - u(17), [("Show details" if not self.details else "Hide details", lambda: self.show_details(not self.details)),
                                            (self.copied or "Copy error log", self.copy_details)])
            return
        ready = there and bool(out) and not busy
        self.button(x0, top, x1, top + u(38), "Build Game", PICKED if ready else mix("#000000", PICKED, 0.4), WHITE if ready else "#9A9A9A",
                    self.start_build if ready else None, EDGE)
        y = top + u(38)
        line, ink = self.build_line(there, out, said, good)
        # (the build options are drawn from the panel's foot up: the line takes the lines there is room for above them, never
        # one over them. A long reason under the game file and this line together ran into "Build options" on a 640 window)
        height = int(self.app.tk.call("font", "metrics", "LsLabel", "-linespace"))
        room = self.options_top(bottom) - u(4) - u(16) - (y + u(8))
        if line and room >= height:
            y = self.wrapped(cx, y + u(8), line, "LsLabel", ink, u(235), anchor="n", justify="center", lines=min(3, room // height))
        self.box(0, y + u(16), u(PANEL - 1), y + u(16) + max(1, u(1)), RULE)
        self.draw_options(bottom)

    def build_line(self, there, out, said, good):
        """the line under Build Game: the build just done, the check under way, or the time and the room it takes"""
        if self.ready_note:
            return self.ready_note, LABEL
        if not there:
            return "", LABEL
        if good is None and said:
            return said, LABEL
        if not out:
            return "", LABEL
        free = self.hb.free_gb(out)
        if free is None:
            return "About 45 minutes, once · needs 45 GB", LABEL
        return "About 45 minutes, once · needs 45 GB, %d GB free there" % free, WHY if free < 45 else LABEL

    OPTIONS = 3   # (Language, Workers, Memory)

    def options_top(self, bottom):
        """where the build options start, their "Build options" label's top: rows of 32 and 8 between, up from the foot"""
        u = self.u
        return bottom - u(32) * self.OPTIONS - u(8) * (self.OPTIONS - 1) - u(16) - u(8)

    def draw_options(self, bottom):
        """Build options (Paper: Language, Workers, Memory), rows of 32 from the body's foot up"""
        app, hb, c, u = self.app, self.hb, self.canvas, self.u
        cpus = os.cpu_count() or 4
        workers = app.cfg.get("workers", "")
        memory = app.cfg.get("memory", "")
        rows = (("Language", app.language.get(), [n for _c, n in hb.make_game.LANGUAGES], self.set_language,
                 "The language the game's text and voices are in"),
                ("Workers", workers if workers.isdigit() else "Auto", ["Auto"] + [str(n) for n in range(1, cpus + 1)],
                 lambda v: self.set_option("workers", v),
                 "How many compilers run at once. Auto: as many as the memory free allows. More need more memory and may not be faster."),
                ("Memory", memory + " GB" if memory.isdigit() else "Auto",
                 ["Auto"] + ["%d GB" % gb for gb in range(4, memory_gb() + 4, 4)], lambda v: self.set_option("memory", v.split(" ")[0]),
                 "How much memory the compilers may take together. Auto leaves free memory to your other programs."))
        y = bottom - u(32) * len(rows) - u(8) * (len(rows) - 1)
        c.create_text(u(16), y - u(8) - u(8), text="Build options", font="LsLabel", fill=LABEL, anchor="w", tags="ui")
        for label, value, names, then, tip in rows:
            c.create_text(u(16), y + u(16), text=label, font="LsLabel", fill=WHITE, anchor="w", tags="ui")
            text = c.create_text(u(202), y + u(16), text=self.fit("LsLabel", value, u(120)), font="LsLabel", fill=FIELD_INK, anchor="e",
                                 tags="ui")
            sign = c.create_image(u(223), y + u(8), image=self.mark("choose", FIELD_INK), anchor="nw", tags="ui")

            def over(on, text=text, sign=sign):
                c.itemconfigure(text, fill=WHITE if on else FIELD_INK)
                c.itemconfigure(sign, image=self.mark("choose", WHITE if on else FIELD_INK))
            busy = self.state == "working"
            self.region(u(16), y, u(251), y + u(32), press=None if busy else (lambda names=names, then=then: self.pick_from(names, then)),
                        over=None if busy else over, tip=tip)
            y += u(32) + u(8)

    def set_language(self, name):
        self.app.language.set(name)
        self.app.cfg["language"] = next((c for c, n in self.hb.make_game.LANGUAGES if n == name), "en-US")
        self.save()

    def set_option(self, key, value):
        self.app.cfg[key] = "" if value == "Auto" else value
        self.save()

    def save(self):
        """builder.ini written. One that cannot be (a full disk, a folder not the player's): the choices hold until the
        launcher closes, and nothing stops for it"""
        try:
            self.hb.save_config(self.app.cfg)
        except OSError as error:
            print("Hookshot: the settings could not be saved: %s" % error, file=sys.stderr)

    def pick_from(self, names, then):
        """a list under the pointer, to pick one of (the language, the workers, the memory)"""
        menu = tk.Menu(self.canvas, tearoff=0, font="LsLabel", borderwidth=0, activeborderwidth=0)

        def picked(name):
            then(name)
            if self.canvas.winfo_exists():
                self.draw()
        for name in names:
            menu.add_command(label=name, command=lambda name=name: picked(name))
        self.popup(menu)

    # ---- the Releases tab ----
    def draw_releases(self, y, bottom):
        """(Paper: "Releases Menu") the versions, rows of 40 four apart: the one the folder holds in green with its tick, the ones
        a press brings with the download mark, the one being brought with the refresh mark, and the fold row"""
        u = self.u
        rows = tab_rows(self.lists, self.pre_on())
        # (as Windows says it when GitHub did not answer: the list holds what is on this PC alone)
        note = "GitHub did not answer: only the versions on this PC are listed." if self.checked and not self.releases else None
        if not rows:
            if note and not self.checking:
                self.wrapped(u(16), y + u(10), note, "LsLabel", FOLD, u(235), lines=3)
            else:
                self.row(y, "Looking for releases…", FOLD)
            return
        fold = self.lists["older"] > 0
        self.rows_fit = max(1, (bottom - y + u(4)) // u(44) - (1 if fold else 0) - (1 if note else 0))
        self.scroll = min(self.scroll, max(0, len(rows) - self.rows_fit))
        busy = self.state == "working"
        for choice in rows[self.scroll:self.scroll + self.rows_fit]:
            if busy and self.bringing and same_tag(choice.tag, self.bringing):   # (being brought, or rebuilt: the turning mark)
                ink, mark, press, tip = BUSY, "refresh", None, None
            elif choice.here:
                # (built again with the settings now, asked first: a folder without its game files cannot be)
                can = choice.rebuilds and not busy and self.has_game()
                ink, mark, press, tip = HERE, "tick", self.rebuild if can else None, choice.tip if can else "In your game folder"
            elif choice.reach:
                ink, mark = QUIET, "download"
                press = None if busy else (lambda choice=choice: self.bring(choice))
                ahead = not self.built or not is_release(self.built) or newer(choice.tag, self.built)
                tip = ("Update to %s" if ahead else "Switch back to %s") % version_name(choice.tag) + \
                    ": your game is rebuilt from your game files. Your saves and settings stay."
            else:
                ink, mark, press, tip = DIM, None, None, choice.tip
            y = self.row(y, choice.label, ink, press, mark, tip) + u(4)
        if fold:
            folded = self.lists["folded"]
            y = self.row(y, "%d older releases" % self.lists["older"] if folded else "Fewer releases", FOLD, self.fold,
                         "down" if folded else "up") + u(4)
        if note:
            self.wrapped(u(16), y + u(4), note, "LsLabel", FOLD, u(235), lines=2)

    def row(self, y, text, ink, press=None, mark=None, tip=None):
        """a row of the Releases tab, 40 high across the panel: its words from 16, a mark of 24 at its right"""
        c, u = self.canvas, self.u
        x, right = u(16), u(251)
        label = c.create_text(x, y + u(20), text=self.fit("LsLine", text, right - x - (u(32) if mark else 0)), font="LsLine", fill=ink,
                              anchor="w", tags="ui")
        sign = c.create_image(right - u(24), y + u(8), image=self.mark(mark, ink), anchor="nw", tags="ui") if mark else None
        if press:
            def over(on):
                c.itemconfigure(label, fill=WHITE if on else ink)
                if sign is not None:
                    c.itemconfigure(sign, image=self.mark(mark, WHITE if on else ink))
            self.region(0, y, u(PANEL - 1), y + u(40), press=press, over=over, tip=tip)
        elif tip:
            self.region(0, y, u(PANEL - 1), y + u(40), tip=tip)
        return y + u(40)

    # ---- the Settings tab ----
    def draw_settings(self, y, bottom):
        """(Paper: "Settings Menu") on or off, each with an OFF | ON switch at its right"""
        app, u = self.app, self.u
        y = self.switch(y, "Prepare Shaders", bool(app.prepare.get()), self.prepare_pressed,
                        "Prepares the game's shaders at the end of the build, a few minutes (longer on some GPUs). Off, the game "
                        "prepares them at its first start, behind a black window.")
        y = self.switch(y + u(12), "Enable DLSS", bool(app.dlss.get()), self.dlss_pressed,
                        "NVIDIA DLSS, for NVIDIA RTX graphics cards. The build downloads NVIDIA's SDK under NVIDIA's license. "
                        "NVIDIA's files stay on this PC: never share a game folder built with them.")
        # (DLSS takes effect at a build: when the game was built without it, this says so, with Rebuild beside it)
        # (one line, as the panel has room for: the whole under the pointer)
        note = self.rebuild_note()
        if note:
            self.link(u(251), y + u(8) + u(8), "Rebuild", None if self.state == "working" else self.rebuild, anchor="e")
            top = y + u(8)
            y = self.wrapped(u(16), top, note, "LsLabel", BUGS, u(170), lines=1)
            self.region(u(16), top, u(190), y, tip="%s. Rebuild builds your game again from its game files with your settings now, "
                                                   "%s on this PC. Your saves stay." % (note, about(self.typical)))
        # (#2206's RX_VK_PCACHE_LOAD=0, a line of the game folder's hookshot_env.txt, so it holds however the game is started:
        # game_env.py. Only with a game folder; the game's own setting, not the build's: it takes effect at its next start)
        if self.folder and os.path.isdir(self.folder):
            y = self.switch(y + u(12), "Lower memory use", game_env.folder_skips_cache(self.folder), self.low_mem_pressed,
                            "The game neither loads nor saves its pipeline cache file (mkw_vk_pipelines.bin), which the graphics "
                            "driver holds in memory for the whole session: up to about 3 GB less memory. On a fresh driver cache "
                            "the game may stutter more the first time it draws something. The file stays: switched off again, "
                            "the game uses it as before. Applies from the game's next start, however it is started (a line in "
                            "the game folder's hookshot_env.txt).")
            size = game_env.cache_bytes(self.folder)
            note = ("Skips the %s pipeline cache file: less memory, may stutter more the first time." % game_env.size_text(size) if size > 0 else
                    "Skips the pipeline cache file the game makes as it plays: less memory, may stutter more the first time.")
            y = self.wrapped(u(16), y + u(4), note, "LsLabel", OFF_INK, u(205), lines=3)
            # (#2447's Save my pipeline list: the game folder's list and the "Submit your pipelines" issue's report, zipped into
            # Downloads, hookshot_builder.share_pipeline_list. What it did, under it)
            y += u(12)
            self.canvas.create_text(u(16), y + u(16), text="Pipeline list", font="LsLabel", fill=WHITE, anchor="w", tags="ui")
            self.link(u(251), y + u(16), "Save", self.share_pressed, anchor="e")
            said = self.share_said or "Helps remove stutter: a zip to attach to the Submit your pipelines issue."
            top = y + u(36)
            y = self.wrapped(u(16), top, said, "LsLabel", OFF_INK, u(205), lines=3)
            self.region(u(16), top, u(221), y, tip=said)   # (whole under the pointer: the note is cut at three lines)
        y = self.switch(y + u(12), "Enable pre-releases", self.pre_on(), self.pre_pressed,
                        "Release candidates in Releases, and Check for updates offers them.")
        # (Paper's 189 in Segoe UI; Inter is wider, and 205 breaks its lines where Paper's do)
        self.runs(u(16), y + u(4), u(205), [("These versions contain the latest experimental features and changes, ", OFF_INK),
                                             ("bugs may occur.", BUGS)])

    def switch(self, y, label, on, press, tip):
        """a setting's row: its name, and at its right OFF | ON with the one it is in the accent (32 high). Returns its bottom"""
        c, u = self.canvas, self.u
        x1 = u(251)
        c.create_text(u(16), y + u(16), text=label, font="LsLabel", fill=WHITE, anchor="w", tags="ui")
        cells = [(word, self.measure("LsLabel", word) + u(8)) for word in ("OFF", "ON")]
        width = u(1) + u(4) + cells[0][1] + u(4) + cells[1][1] + u(4) + u(1)
        x0 = x1 - width
        frame = self.box(x0, y, x1, y + u(32), FIELD, FIELD_EDGE)
        x = x0 + u(5)
        for word, cell in cells:
            chosen = (word == "ON") == on
            if chosen:
                self.box(x, y + u(6), x + cell, y + u(26), PICKED)
            c.create_text(x + cell // 2, y + u(16), text=word, font="LsLabel", fill=WHITE if chosen else OFF_INK, tags="ui")
            x += cell + u(4)
        self.region(u(16), y, x1, y + u(32), press=lambda: (press(), self.draw()), tip=tip,
                    over=lambda on_: c.itemconfigure(frame, outline="#8A8A8A" if on_ else FIELD_EDGE))
        return y + u(32)

    def runs(self, x, y, width, parts):
        """words of more than one colour in lines no wider than width (Paper: the note under Enable pre-releases)"""
        c, u = self.canvas, self.u
        space = self.measure("LsLabel", " ")
        at, line_h = x, u(16)
        for text, ink in parts:
            for word in text.split(" "):
                if not word:
                    continue
                size = self.measure("LsLabel", word)
                if at > x and at + size > x + width:
                    at, y = x, y + line_h
                c.create_text(at, y, text=word, font="LsLabel", fill=ink, anchor="nw", tags="ui")
                at += size + space

    def save_options(self):
        app = self.app
        app.cfg.update(prepare="1" if app.prepare.get() else "0", dlss="1" if app.dlss.get() else "0")
        self.save()

    def prepare_pressed(self):
        self.app.prepare.set(not self.app.prepare.get())
        self.save_options()

    def dlss_pressed(self):
        """NVIDIA DLSS: off unless picked. Picking it shows NVIDIA's license; the build downloads NVIDIA's SDK under it"""
        app = self.app
        if not app.dlss.get() and not messagebox.askyesno("NVIDIA DLSS", self.hb.DLSS_LICENSE, parent=app):
            return
        app.dlss.set(not app.dlss.get())
        app.dlss_toggled = True
        self.save_options()

    def low_mem_pressed(self):
        """Lower memory use: its line in the game folder's hookshot_env.txt, on or off (game_env.py)"""
        try:
            game_env.set_skip(self.folder, not game_env.folder_skips_cache(self.folder))
        except OSError as error:
            messagebox.showwarning("Hookshot", "The setting could not be saved in the game folder: %s" % error, parent=self.app)

    def share_pressed(self):
        """Save my pipeline list (hookshot_builder.share_pipeline_list): the zip in Downloads, the report copied, the issue opened"""
        self.share_said = "Saving..."
        self.draw()
        self.app.update_idletasks()
        self.share_said = self.hb.share_pipeline_list(self.folder, copy=self.app.copy_text)
        self.draw()

    def pre_pressed(self):
        """Enable pre-releases: the update track, Release or Release candidate (a nightly one kept is turned off to Release)"""
        app = self.app
        app.track.set(self.hb.TRACK_NAMES["release" if self.pre_on() else "rc"])
        try:
            app.on_track_changed()   # (saved, and the builder's own check of the newest asked again)
        except OSError as error:
            print("Hookshot: the settings could not be saved: %s" % error, file=sys.stderr)
        self.fill()

    # ---- the pointer ----
    def at(self, x, y):
        for i in range(len(self.regions) - 1, -1, -1):
            x0, y0, x1, y1 = self.regions[i]["box"]
            if x0 <= x < x1 and y0 <= y < y1:
                return i
        return None

    def point(self, where):
        hit = self.at(*where) if where else None
        if hit == self.hot:
            return
        self.hide_tip()
        if self.hot is not None and self.hot < len(self.regions) and self.regions[self.hot]["over"]:
            self.regions[self.hot]["over"](False)
        self.hot = hit
        region = self.regions[hit] if hit is not None else None
        if region and region["over"]:
            region["over"](True)
        self.canvas.configure(cursor="hand2" if region and region["press"] and region["over"] else "")
        if region and region["tip"]:
            self.tip_job = self.app.after(700, lambda: self.show_tip(region["tip"]))

    def on_move(self, event):
        self.point((event.x, event.y))

    def on_press(self, event):
        self.hide_tip()
        hit = self.at(event.x, event.y)
        self.down = (hit, self.regions[hit]["box"]) if hit is not None else None

    def on_release(self, event):
        down, self.down = self.down, None
        hit = self.at(event.x, event.y)
        if hit is None:
            if down is None:
                self.show_menu(False)   # (a press in the window that no button took: the menu closes)
            return
        # (the same place pressed and let go: a build's line can draw the screen again in between, so it is told by where it is)
        if down == (hit, self.regions[hit]["box"]) and self.regions[hit]["press"]:
            self.regions[hit]["press"]()

    def on_wheel(self, event, way):
        """(the Releases tab, when it holds more rows than the panel has room for)"""
        if not self.menu_open or self.tab != "releases" or event.x >= self.u(PANEL):
            return
        rows = len(tab_rows(self.lists, self.pre_on()))
        scroll = min(max(0, rows - self.rows_fit), max(0, self.scroll + way))
        if scroll != self.scroll:
            self.scroll = scroll
            self.draw()

    def show_tip(self, text):
        self.tip_job = None
        c = self.canvas
        if not c.winfo_exists():
            return
        self.tip_window = top = tk.Toplevel(c)
        top.wm_overrideredirect(True)
        tk.Label(top, text=text, font="LsLabel", background="#1E1E1E", foreground="#E6E6E6", padx=self.u(8), pady=self.u(4),
                 borderwidth=0, wraplength=self.u(380), justify="left").pack()
        top.wm_geometry("+%d+%d" % (c.winfo_pointerx() + self.u(12), c.winfo_pointery() + self.u(18)))

    def hide_tip(self):
        job, top, self.tip_job, self.tip_window = self.tip_job, self.tip_window, None, None
        try:   # (also as the window closes, when Tk may have taken them already)
            if job is not None:
                self.app.after_cancel(job)
            if top is not None:
                top.destroy()
        except tk.TclError:
            pass

    def on_destroy(self, event):
        """(the window closes, or the builder's own pages take it)"""
        if event.widget is not self.canvas:
            return
        self.hide_tip()
        for job in (self.redraw_job, self.tick_job, self.said_job):   # (none of them may draw on a canvas that is gone)
            if job is not None:
                try:
                    self.app.after_cancel(job)
                except tk.TclError:
                    pass
        self.redraw_job = self.tick_job = self.said_job = None
        for key, bound in self.keys:
            try:
                self.app.unbind(key, bound)
            except tk.TclError:
                pass
        try:
            self.app.check_text.trace_remove("write", self.check_trace)
        except tk.TclError:
            pass
        if getattr(self.app, "launcher", None) is self:
            self.app.launcher = None

    # ---- what a press does ----
    def show_menu(self, on):
        if on == self.menu_open:
            return
        self.menu_open, self.scroll = on, 0
        if not on:
            self.show_details(False)
        self.draw()

    def show_tab(self, key):
        """a tab pressed: shown; pressed while it is shown, a build or an update that stopped is left"""
        if key == self.tab and self.state == "stopped":
            self.state = "idle"
            self.show_details(False)
        self.tab, self.scroll = key, 0
        if key == "build" and self.source_ready() and not self.app.check_text.get():
            self.app.check_version()
        self.draw()

    def fold(self):
        self.older_open = not self.older_open
        self.fill()

    def open_page(self, what):
        """a folder in the file manager, a page in the browser (the system's own, not with this AppImage's libraries)"""
        env = {k: v for k, v in os.environ.items() if k not in ("LD_LIBRARY_PATH", "PYTHONHOME", "PYTHONPATH")}
        try:
            subprocess.Popen(["xdg-open", what], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass   # (nothing to open it with)

    def open_build(self):
        """Build, with no game yet: the build's choices, in the menu's Build tab"""
        self.tab, self.menu_open = "build", True
        self.draw()

    def play(self):
        """Play: the game the folder holds (nothing while there is none, or while it is being built or brought); Return with no
        game yet opens the build, as the button does"""
        if self.state != "working" and not self.hb.game_ready(self.folder):
            return self.open_build()
        if self.state != "working" and self.hb.game_ready(self.folder):
            try:
                self.app.play_and_close(self.folder)
            except OSError as error:   # (the game could not be started: the launcher stays, and says why)
                messagebox.showerror("Hookshot", "The game could not be started: %s" % error, parent=self.app)
