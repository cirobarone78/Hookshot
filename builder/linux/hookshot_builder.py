"""Hookshot Builder for Linux: what builder/HookshotBuilder (WPF) is on Windows, in Tk. It runs nx2/make_game.py and
follows its @@ lines (make_game.py's docstring), then offers to start the game. The AppImage starts it (builder/linux/AppRun),
with the compiler, sysroot and libraries it brings in the environment.

    hookshot_builder.py                     the window. Its button is Build, Update, Play, or Update builder
    hookshot_builder.py --play              the game built last time, if there is one (else the window)
    hookshot_builder.py --launch <folder>   that folder's launcher: Play with a profile (profiles.py), and Update when a newer
                                            release is out
    hookshot_builder.py --update <folder>   download the new release (only parts that changed) and build the folder again
"""
import contextlib
import io
import math
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("HOOKSHOT_TOOLS") or os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "nx2"))
sys.path.insert(0, os.path.join(ROOT, "third_party", "a64-kit", "tools"))
sys.path.append(os.path.join(ROOT, "scripts"))   # (last: nothing there takes the place of a module the builder means)
import linux_update  # noqa: E402  (the release check and the part download)
import profiles  # noqa: E402  (the launcher's profiles)
import oot_saves  # noqa: E402  (a profile's saves in and out: the copy docs/saves.md describes)
import make_game  # noqa: E402  (LANGUAGES, BUILD_ID)
import toolchain  # noqa: E402  (default_jobs: RX_JOBS)

CONFIG = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "hookshot", "builder.ini")
STAGES = {"read": "Reading your game files", "lift": "Translating the game to PC code", "compile": "Compiling",
          "finish": "Putting the game folder together", "shaders": "Preparing shaders"}
DLSS_LICENSE = (
    "NVIDIA DLSS is NVIDIA's, not Hookshot's. With it ticked, the build downloads NVIDIA's DLSS SDK (release v310.9.16) from "
    "github.com/NVIDIA/DLSS, under NVIDIA's own license, the NVIDIA RTX SDKs license:\n\n"
    "https://github.com/NVIDIA/DLSS/blob/9981c6350dc58c0ce21f024fd65e31e851c31689/LICENSE.txt\n\n"
    "Its files stay on this PC (in the builder's ngx-sdk folder, and libnvidia-ngx-dlss.so in the game folder's ngx folder). "
    "Hookshot never includes or shares them: never share a game folder built with them.\n\n"
    "Do you accept NVIDIA's license?"
)


def ngx_sdk_dir():
    """Where NVIDIA's DLSS SDK goes when the player ticks NVIDIA DLSS: beside the builder's versions, kept across updates."""
    return os.path.join(linux_update.data_root(), "ngx-sdk")


def folder_has_dlss(folder):
    """Whether a game folder was built with NVIDIA DLSS (its runtime in ngx/, and NVIDIA's license in ngx-sdk)."""
    if not folder:
        return False
    ngx_dir = os.path.join(os.path.expanduser(folder), "ngx")
    try:
        has_runtime = any(name.startswith("libnvidia-ngx-dlss.so") for name in os.listdir(ngx_dir))
    except OSError:
        return False
    return has_runtime and os.path.isfile(os.path.join(ngx_sdk_dir(), "LICENSE.txt"))


def dlss_args(dlss):
    return ["--fetch-ngx-sdk", "--accept-nvidia-license"] if dlss else []


def make_game_env(dlss, environ=None):
    """The environment make_game.py runs in. HOOKSHOT_NGX_SDK is set only when DLSS is chosen (one set in the shell is not
    passed on when unticked, as on Windows), and HOOKSHOT_VK_PREBUILT is dropped so build.py compiles hookshot_vk.so with NGX."""
    env = dict(os.environ if environ is None else environ)
    if dlss:
        env["HOOKSHOT_NGX_SDK"] = ngx_sdk_dir()
        env.pop("HOOKSHOT_VK_PREBUILT", None)
    else:
        env.pop("HOOKSHOT_NGX_SDK", None)
    return env


def left_text(seconds):
    """The countdown make_game.py and build.py work out from this PC's earlier builds."""
    if seconds < 45:
        return "less than a minute left"
    if seconds < 90:
        return "about a minute left"
    minutes = int(round(seconds / 60))
    return "about %d h %d min left" % (minutes // 60, minutes % 60) if minutes >= 60 else "about %d minutes left" % minutes


TRACK_NAMES = {"release": "Release", "rc": "Release candidate", "nightly": "Nightly"}


def load_config():
    cfg = {}
    try:
        for line in open(CONFIG, encoding="utf-8"):
            k, eq, v = line.rstrip("\n").partition("=")
            if eq:
                cfg[k] = v
    except OSError:
        pass
    return cfg


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w", encoding="utf-8") as f:
        f.writelines("%s=%s\n" % kv for kv in cfg.items())


def game_ready(folder):
    return linux_update.game_exe(folder) is not None


def chosen_profile(folder, cfg=None):
    """the profile Play starts the game with: the one chosen last, while it is still on the list"""
    uid = (load_config() if cfg is None else cfg).get("profile", "")
    return uid if any(uid == p[0] for p in profiles.load(profiles.user_dir(folder))) else profiles.DEFAULT


def play(folder):
    """the game, on its own (it outlives this window), from its folder. The launcher already asked about updates."""
    exe = linux_update.game_exe(folder)
    if not exe:
        return
    env = make_game.game_env()   # (as make_game's shader preparation and hookshot-launch: the game's own SDL, the system's libraries)
    env["HOOKSHOT_NO_UPDATE_CHECK"] = "1"
    env["HOOKSHOT_PROFILE"] = chosen_profile(folder)
    exe = os.path.abspath(exe)
    options = dict(cwd=folder, env=env, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with open(os.path.join(HERE, "play-diagnostics.sh"), encoding="utf-8") as script:
            command = ["/bin/sh", "-c", script.read(), "hookshot-play", exe]
        subprocess.Popen(command, **options)
    except OSError:
        subprocess.Popen([exe], **options)


def desktop_exec(path):
    """One Exec argument. A % in the path is a field code, so "100% Games" is rejected and the menu entry does not run.
    Inside the quotes the Desktop Entry spec wants the characters double quote, backtick, dollar and backslash each
    preceded by a backslash, and every backslash written twice because the file's string escaping is applied first
    (so a literal backslash is four, and a dollar is two backslashes and the dollar)."""
    escaped = path.replace("\\", "\\\\\\\\")
    for char in ('"', "`", "$"):
        escaped = escaped.replace(char, "\\\\" + char)
    return '"%s"' % escaped.replace("%", "%%")


def chooser_command(kind, title, start, environ=os.environ, which=shutil.which):
    """The desktop's own file chooser, for kind "folder" or "nup" (the game's .nup): kdialog on KDE, zenity elsewhere
    (the other when that one is missing), at the desktop's size and in its light or dark look, which Tk's own dialog has
    neither of. None: neither is here, and Tk's dialog is used. Each prints the path chosen; exit 1 is Cancel."""
    kde = "KDE" in environ.get("XDG_CURRENT_DESKTOP", "").upper().split(":")
    for tool in ("kdialog", "zenity") if kde else ("zenity", "kdialog"):
        path = which(tool)
        if not path:
            continue
        if tool == "kdialog":
            if kind == "folder":
                return [path, "--title", title, "--getexistingdirectory", start]
            return [path, "--title", title, "--getopenfilename", start, "Switch 2 game package (*.nup)"]
        args = [path, "--file-selection", "--title=" + title, "--filename=" + os.path.join(start, "")]
        if kind == "folder":
            return args + ["--directory"]
        return args + ["--file-filter=Switch 2 game package | *.nup", "--file-filter=All files | *"]
    return None


APP_ID = "io.github.NotRexed.Hookshot"   # (the game's window names itself so: host/posix/display_sdl.c's HOS_APP_ID)


def add_to_menu(folder):
    """an entry in the applications menu that starts the game"""
    if any(ch in folder for ch in "\r\n\0"):   # (a line break would start another key of the entry)
        raise ValueError("the game folder's name has a line break")
    icon = os.path.join(folder, "hookshot.png")
    src = os.path.join(ROOT, "assets", "hookshot.png")
    if os.path.exists(src):
        shutil.copyfile(src, icon)
    apps = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "applications")
    os.makedirs(apps, exist_ok=True)
    with open(os.path.join(apps, "hookshot.desktop"), "w", encoding="utf-8") as f:
        f.write("[Desktop Entry]\nType=Application\nName=Hookshot\nComment=The Legend of Zelda: Ocarina of Time, built from your copy\n"
                "Exec=%s\nPath=%s\nIcon=%s\nCategories=Game;\nTerminal=false\nStartupWMClass=%s\n"
                % (desktop_exec(os.path.join(folder, "hookshot")), folder, icon, APP_ID))


def free_gb(path):
    path = os.path.expanduser(path or "")   # (the field takes ~/Games/Hookshot, as build() and apply_mode() read it)
    while path and not os.path.exists(path):
        path = os.path.dirname(path)
    try:
        return shutil.disk_usage(path or "/").free / 2 ** 30
    except OSError:
        return None


def slow_disk_warning(folder):
    """The game folder on a hard drive: the build works, but much more slowly than on an SSD. None for an SSD or a drive whose
    kind cannot be told (a network share)"""
    if make_game.spinning_disk(os.path.expanduser(folder)) is not True:
        return None
    return ("%s is on a hard drive. An SSD builds the game much faster: build there if you can.\n\n"
            "Build here anyway?" % os.path.expanduser(folder))


def xft_dpi():
    """the DPI KDE and GNOME hand X apps when the desktop is scaled. Tk on X11 and XWayland never reads it."""
    env = {k: v for k, v in os.environ.items() if k != "LD_LIBRARY_PATH"}
    try:
        out = subprocess.run(["xrdb", "-query"], env=env, capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    found = re.search(r"^Xft\.dpi:\s*([0-9.]+)", out, re.M)
    return float(found.group(1)) if found else None


def ui_scale(screen_height, dpi=None, environ=os.environ):
    """how much bigger than 96 DPI to draw the window. HOOKSHOT_UI_SCALE, then GDK_SCALE or QT_SCALE_FACTOR above 1
    (Wayland sessions export GDK_SCALE=1 whatever the screen), then Xft.dpi; with none of them (gamescope, a bare X
    session) a 1440p or 4K screen is still scaled by its height."""
    for name, least in (("HOOKSHOT_UI_SCALE", 0), ("GDK_SCALE", 1), ("QT_SCALE_FACTOR", 1)):
        try:
            value = float(environ.get(name, ""))
        except ValueError:
            continue
        if value > least:
            return min(max(value, 0.5), 4.0)
    if dpi:
        return min(max(dpi / 96, 0.5), 4.0)
    return min(screen_height / 1080, 4.0) if screen_height >= 1440 else 1.0


# ---- the look: the Windows builder's (builder/HookshotBuilder/App.xaml, "Slate"): its colours, Inter, its sizes in 96 DPI
# pixels, its rounded buttons, fields and cards. Tk draws no rounded corners or alpha, so they are painted into images here,
# antialiased and laid over the colour they sit on, and ttk's clam theme draws everything else ----
PAGE, RAISED, RAISED_HOVER, LINE_STRONG = "#14161a", "#1c1f24", "#23272d", "#3d434c"
LINE = "#2c3037"   # (a line on Raised: the popup lists' separator)
INK, INK_SOFT, INK_FAINT = "#edeff2", "#a2a9b3", "#6e7681"
BRAND, BRAND_HOVER, BRAND_INK = "#3d63e6", "#4b70f0", "#dfe6ff"
GO, GO_HOVER, GO_INK, BAD = "#5fb08a", "#70c09a", "#06150e", "#e2776b"
UI_FONTS = ("Inter", "Inter Variable", "Segoe UI", "Cantarell", "Noto Sans", "DejaVu Sans", "Liberation Sans")
MONO_FONTS = ("Cascadia Mono", "JetBrains Mono", "DejaVu Sans Mono", "Noto Sans Mono", "Liberation Mono")


def mix(color, under, alpha):
    """color at alpha over under: the WPF window's #AARRGGBB glass brushes, flattened onto what is behind them"""
    if alpha >= 1:
        return color
    a, b = int(color[1:], 16), int(under[1:], 16)
    return "#%02x%02x%02x" % tuple(round(((a >> s) & 255) * alpha + ((b >> s) & 255) * (1 - alpha)) for s in (16, 8, 0))


WHITE = "#ffffff"
GLASS = mix(WHITE, PAGE, 0x0D / 255)          # cards, fields
GLASS_LINE = mix(WHITE, PAGE, 0x17 / 255)     # their edges, and a hovered quiet button
QUIET = mix(WHITE, PAGE, 0x08 / 255)          # Cancel, Change, Open folder
QUIET_LINE = mix(WHITE, PAGE, 0x1F / 255)
QUIET_HOVER_LINE = mix(WHITE, PAGE, 0x2A / 255)
TICK_LINE = mix(WHITE, PAGE, 0x40 / 255)
TRACK = mix(WHITE, PAGE, 0x12 / 255)          # a bar's empty part
LOG = mix("#000000", GLASS, 0x33 / 255)       # the build's lines


def box(x, y, w, h, r):
    """a distance function: from a point to the box at x, y of w x h with corners of radius r (negative inside)"""
    cx, cy, hx, hy = x + w / 2, y + h / 2, w / 2 - r, h / 2 - r

    def dist(px, py):
        qx, qy = abs(px - cx) - hx, abs(py - cy) - hy
        return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - r
    return dist, (x, y, x + w, y + h)


def ring(cx, cy, r, width):
    def dist(px, py):
        return abs(math.hypot(px - cx, py - cy) - (r - width / 2)) - width / 2
    return dist, (cx - r, cy - r, cx + r, cy + r)


def stroke(points, width):
    """a line through points, width wide (a tick, a chevron)"""
    pairs = list(zip(points, points[1:]))

    def dist(px, py):
        best = 1e9
        for (ax, ay), (bx, by) in pairs:
            dx, dy = bx - ax, by - ay
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
            best = min(best, math.hypot(px - ax - t * dx, py - ay - t * dy))
        return best - width / 2
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return dist, (min(xs) - width, min(ys) - width, max(xs) + width, max(ys) + width)


def triangle(points):
    """a filled convex triangle (Play's), its points clockwise"""
    edges = []
    for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1]):
        length = math.hypot(bx - ax, by - ay)
        edges.append((ax, ay, (by - ay) / length, -(bx - ax) / length))

    def dist(px, py):
        return max((px - ax) * nx + (py - ay) * ny for ax, ay, nx, ny in edges)
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return dist, (min(xs), min(ys), max(xs), max(ys))


def paint(w, h, under, layers):
    """Photo image data, w x h over the colour under: each layer (colour, (distance function, bounds)) laid on in turn,
    antialiased by its distance. A colour may be a function of y (the Windows step's gradient)."""
    rows = []
    for j in range(h):
        y = j + 0.5
        row = []
        for i in range(w):
            x = i + 0.5
            color = under
            for paint_color, (dist, (x0, y0, x1, y1)) in layers:
                if x < x0 - 1 or x > x1 + 1 or y < y0 - 1 or y > y1 + 1:
                    continue
                cover = 0.5 - dist(x, y)
                if cover > 0:
                    color = mix(paint_color(y) if callable(paint_color) else paint_color, color, min(cover, 1.0))
            row.append(color)
        rows.append("{%s}" % " ".join(row))
    return " ".join(rows)


def framed(w, h, r, fill, line, width):
    """the layers of a rounded box: its edge, and its fill inside it"""
    layers = [(line, box(0, 0, w, h, r))] if line and width else []
    return layers + [(fill, box(width, width, w - 2 * width, h - 2 * width, max(r - width, 0)) if line and width else
                      box(0, 0, w, h, r))]


def read_only(text):
    """text, a tk.Text, read-only as Windows' IsReadOnly box: it selects and copies (Ctrl+A, Ctrl+C) but typing, paste, cut
    and delete leave it as it is. Returns the function that adds to its end. Its insert and delete are refused in Tcl, so Tk's
    own bindings stay. (Not -state disabled: Tk 8.5 and early 8.6 give a disabled Text no focus from a click off Windows, so
    Ctrl+C would not reach it.)"""
    w = str(text)
    text.tk.call("rename", w, w + "_rw")
    text.tk.call("proc", w, "op args", "if {$op in {insert delete replace}} return\n"
                                       "uplevel 1 [list {%s_rw} $op {*}$args]" % w)
    # (Tk deletes the widget's own command when the window goes: the proc goes with it)
    text.tk.call("trace", "add", "command", w + "_rw", "delete", "apply {{w args} {rename $w {}}} {%s}" % w)
    # (Ctrl+A is line start in Tk's X11 bindings: here it selects all, as in the Windows box)
    text.bind("<Control-a>", lambda e: (text.tag_add("sel", "1.0", "end"), "break")[1])
    return lambda s: text.tk.call(w + "_rw", "insert", "end", s)


def _arg(name):
    args = sys.argv[1:]
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return None


class Builder(tk.Tk):
    def __init__(self, launch=None, update=None, fetched=False, tag=None):
        super().__init__()
        self.title("Hookshot Builder")
        self.apply_scale()
        self.apply_theme()
        self.minsize(self.px(760), self.px(520))
        self.cfg = load_config()
        self.proc = None
        self.lines = queue.Queue()
        self.started = 0.0
        self.launch_folder = launch
        self.update_folder = update
        self.fetched = fetched
        self.update_tag = tag
        self.mode = "build"
        self.latest = None
        self.source_picked = False
        self.dlss_toggled = False
        self.tools = linux_update.tools_tag(linux_update.running_root() or ROOT)
        # (the update track: the one chosen in the Track menu, saved; by default these tools' own)
        own = linux_update.track_of(self.tools)
        self.track = tk.StringVar(value=TRACK_NAMES[self.cfg.get("track") if self.cfg.get("track") in linux_update.TRACKS else own])
        self.status = tk.StringVar()
        self.kind = tk.StringVar(value=self.cfg.get("kind", "nup"))
        self.nup = tk.StringVar(value=self.cfg.get("nup", ""))
        self.romfs = tk.StringVar(value=self.cfg.get("romfs", ""))
        self.exefs = tk.StringVar(value=self.cfg.get("exefs", ""))
        self.out = tk.StringVar(value=self.cfg.get("out", os.path.expanduser("~/Games/Hookshot")))
        names = [n for _, n in make_game.LANGUAGES]
        code = self.cfg.get("language", "en-US")
        self.language = tk.StringVar(value=dict(make_game.LANGUAGES).get(code, names[0]))
        self.prepare = tk.BooleanVar(value=self.cfg.get("prepare", "1") != "0")   # (make_game.py's last step: off, at the first start)
        self.dlss = tk.BooleanVar(value=self.cfg.get("dlss", "0") == "1")
        self.check_text = tk.StringVar()
        self.space_text = tk.StringVar()
        self.stage_text = tk.StringVar()
        self.time_text = tk.StringVar()
        self.page = None
        self.build_button = None
        self.busy = False   # (a desktop file chooser is open: run_chooser)
        if update is not None:
            self.after(200, self.begin_update)
        elif launch:
            self.show_launch(launch)
        else:
            self.show_form()
            self.after(200, self.lookup_latest)
        self.after(100, self.pump)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def apply_scale(self):
        """Fonts sized in points follow tk scaling; a named font sized in pixels (Tk 8.6 on X11: -12) does not, so it is
        multiplied."""
        self.scale = ui_scale(self.winfo_screenheight(), xft_dpi())
        if self.scale == 1.0:
            return
        self.tk.call("tk", "scaling", self.scale * 96 / 72)
        for name in self.tk.splitlist(self.tk.call("font", "names")):
            size = int(self.tk.call("font", "configure", name, "-size"))
            if size < 0:
                self.tk.call("font", "configure", name, "-size", -max(1, round(-size * self.scale)))

    def px(self, n):
        return int(round(n * self.scale))

    # ---- the look (the colours and images above, as ttk styles) ----
    def apply_theme(self):
        px = self.px
        self.images = {}
        self.configure(background=PAGE)
        families = {name.lower(): name for name in self.tk.splitlist(self.tk.call("font", "families"))}
        ui = next((families[n.lower()] for n in UI_FONTS if n.lower() in families), None)
        mono = next((families[n.lower()] for n in MONO_FONTS if n.lower() in families), None)
        named = set(self.tk.splitlist(self.tk.call("font", "names")))

        def font(name, size, weight="normal", family=ui):
            options = ["-size", -px(size), "-weight", weight] + (["-family", family] if family else [])
            self.tk.call("font", "configure" if name in named else "create", name, *options)
        for name, size, weight in (("HsUi", 14, "normal"), ("HsStrong", 14, "bold"), ("HsNote", 13, "normal"),
                                   ("HsNoteStrong", 13, "bold"), ("HsSmall", 12, "normal"), ("HsLabel", 12, "bold"),
                                   ("HsBrand", 15, "bold"), ("HsTitle", 24, "bold"), ("HsDisplay", 34, "bold"),
                                   ("HsPlay", 16, "bold"), ("TkDefaultFont", 13, "normal"), ("TkTextFont", 13, "normal"),
                                   ("TkMenuFont", 13, "normal"), ("TkHeadingFont", 13, "bold"), ("TkCaptionFont", 14, "bold")):
            font(name, size, weight)
        font("HsMono", 12, family=mono)
        font("HsLog", 11, family=mono)
        if mono:
            font("TkFixedFont", 12, family=mono)

        # (the classic widgets and dialogs: the file chooser, the DLSS license's question, the language list)
        for pattern, value in (("*Background", PAGE), ("*Foreground", INK), ("*selectBackground", BRAND),
                               ("*selectForeground", WHITE), ("*insertBackground", INK), ("*highlightBackground", PAGE),
                               ("*highlightColor", BRAND), ("*activeBackground", RAISED_HOVER), ("*activeForeground", INK),
                               ("*troughColor", TRACK), ("*Dialog.msg.font", "HsUi"),
                               ("*Dialog.msg.wrapLength", px(460)), ("*Dialog.dtl.font", "HsNote"),
                               ("*TCombobox*Listbox.background", RAISED), ("*TCombobox*Listbox.foreground", INK),
                               ("*TCombobox*Listbox.selectBackground", RAISED_HOVER),
                               ("*TCombobox*Listbox.selectForeground", BRAND_INK), ("*TCombobox*Listbox.font", "HsNote"),
                               ("*TCombobox*Listbox.borderWidth", 0), ("*TCombobox*Listbox.highlightThickness", 0),
                               ("*TCombobox*Listbox.relief", "flat")):
            self.option_add(pattern, value)

        s = self.style = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", background=PAGE, foreground=INK, font="HsUi", bordercolor=QUIET_LINE, lightcolor=PAGE,
                    darkcolor=PAGE, troughcolor=TRACK, focuscolor=BRAND, selectbackground=BRAND, selectforeground=WHITE,
                    fieldbackground=GLASS, insertcolor=INK, arrowcolor=INK_SOFT, borderwidth=0)
        s.map(".", foreground=[("disabled", INK_FAINT)], background=[("disabled", PAGE)])
        for name, options in (("TFrame", {}), ("Card.TFrame", {"background": GLASS}),
                              ("TLabel", {}), ("Title.TLabel", {"font": "HsTitle"}), ("Display.TLabel", {"font": "HsDisplay"}),
                              ("Sub.TLabel", {"foreground": INK_SOFT}), ("Note.TLabel", {"foreground": INK_SOFT, "font": "HsNote"}),
                              ("Small.TLabel", {"foreground": INK_SOFT, "font": "HsSmall"}),
                              ("Faint.TLabel", {"foreground": INK_FAINT, "font": "HsSmall"}),
                              ("Section.TLabel", {"foreground": INK_SOFT, "font": "HsLabel"}),
                              ("Status.TLabel", {"foreground": BRAND_INK, "font": "HsNote"}),
                              ("Stage.TLabel", {"background": GLASS, "font": "HsStrong"}),
                              ("Bad.Stage.TLabel", {"foreground": BAD}), ("Go.Stage.TLabel", {"foreground": GO}),
                              ("Card.Note.TLabel", {"background": GLASS})):
            s.configure(name, **options)

        # buttons: Quiet (also every plain ttk button, the dialogs' among them), Primary (blue: the step's action), Go (green: Play)
        def button(style, fill, hover, line, hover_line, focus_line, foreground, font, padding, radius=8, disabled=None, under=PAGE):
            r, w = px(radius), px(1)
            n = 2 * r + 6
            image = {k: self.photo("%s-%s" % (style, k), n, n, under, framed(n, n, r, f, l, w))
                     for k, f, l in (("normal", fill, line), ("hover", hover, hover_line), ("focus", fill, focus_line),
                                     ("disabled", disabled or fill, disabled or line))}
            s.element_create(style + ".box", "image", image["normal"], ("disabled", image["disabled"]),
                             ("pressed", image["hover"]), ("active", image["hover"]), ("focus", image["focus"]),
                             border=r + 2, padding=0, sticky="nsew")
            s.layout(style + ".TButton", [(style + ".box", {"sticky": "nsew", "children": [
                ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})]})])
            s.configure(style + ".TButton", foreground=foreground, font=font, padding=padding, anchor="center", background=fill)
            s.map(style + ".TButton", foreground=[("disabled", INK_FAINT)], background=[("disabled", disabled or fill)])
        button("Quiet", QUIET, GLASS_LINE, QUIET_LINE, QUIET_HOVER_LINE, BRAND_HOVER, INK, "HsStrong", (px(18), px(6)))
        button("Primary", BRAND, BRAND_HOVER, mix(WHITE, BRAND, 0x33 / 255), mix(WHITE, BRAND_HOVER, 0x33 / 255),
               mix(WHITE, BRAND, 0xAA / 255), WHITE, "HsStrong", (px(22), px(6)), disabled=mix(WHITE, PAGE, 0x14 / 255))
        button("Go", GO, GO_HOVER, mix(WHITE, GO, 0x40 / 255), mix(WHITE, GO_HOVER, 0x40 / 255), mix(WHITE, GO, 0xAA / 255),
               GO_INK, "HsPlay", (px(30), px(10)), radius=10)
        s.layout("TButton", s.layout("Quiet.TButton"))
        s.configure("TButton", **{k: s.lookup("Quiet.TButton", k) for k in ("foreground", "font", "padding", "anchor", "background")})
        s.map("TButton", foreground=[("disabled", INK_FAINT)])
        # (a text link: Open the game folder)
        s.layout("Link.TButton", [("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})])
        s.configure("Link.TButton", foreground=INK_FAINT, font="HsNoteStrong", padding=0, background=PAGE)
        s.map("Link.TButton", foreground=[("active", INK)], background=[("active", PAGE)])

        # ticks and the game files' choice (the Windows Tick and DumpRow)
        b, t = px(18), px(8)
        for name, under, layers in (
                ("tick", PAGE, framed(b, b, px(5), PAGE, TICK_LINE, px(1.5))),
                ("tick-on", PAGE, framed(b, b, px(5), BRAND, BRAND, px(1.5)) +
                 [(WHITE, stroke([(px(2.5), px(8.5)), (px(6.5), px(12.5)), (px(14.5), px(3.5))], px(2)))]),
                ("radio", GLASS, [(INK_FAINT, ring(b / 2, b / 2, b / 2, px(2)))]),
                ("radio-on", GLASS, [(BRAND, ring(b / 2, b / 2, b / 2, px(2))), (BRAND, ring(b / 2, b / 2, px(4), px(4)))])):
            self.photo(name, b + px(14 if name.startswith("radio") else 8), b, under, layers)
        s.element_create("Hs.tick", "image", self.images["tick"], ("selected", self.images["tick-on"]), sticky="w")
        s.element_create("Hs.radio", "image", self.images["radio"], ("selected", self.images["radio-on"]), sticky="w")
        s.layout("TCheckbutton", [("Checkbutton.padding", {"sticky": "nsew", "children": [
            ("Hs.tick", {"side": "left", "sticky": ""}), ("Checkbutton.label", {"side": "left", "sticky": "nsew"})]})])
        s.configure("TCheckbutton", foreground=INK, font="HsNote", padding=(0, px(2)))
        s.map("TCheckbutton", background=[("active", PAGE)], foreground=[("active", WHITE)])
        s.layout("Row.TRadiobutton", [("Radiobutton.padding", {"sticky": "nsew", "children": [
            ("Hs.radio", {"side": "left", "sticky": ""}), ("Radiobutton.label", {"side": "left", "sticky": "nsew"})]})])
        s.configure("Row.TRadiobutton", background=GLASS, foreground=INK, font="HsUi", padding=(px(16), px(13)))
        s.map("Row.TRadiobutton", background=[("active", GLASS)], foreground=[("active", WHITE)])

        # fields: the paths (monospaced, as on Windows) and the language
        r, w, n = px(8), px(1), px(8) * 2 + 6
        field = self.photo("field", n, n, PAGE, framed(n, n, r, GLASS, GLASS_LINE, w))
        field_hover = self.photo("field-hover", n, n, PAGE, framed(n, n, r, GLASS, QUIET_HOVER_LINE, w))
        field_focus = self.photo("field-focus", n, n, PAGE, framed(n, n, r, GLASS, BRAND, w))
        s.element_create("Hs.field", "image", field, ("focus", field_focus), ("hover", field_hover), border=r + 2, padding=0,
                         sticky="nsew")
        s.layout("TEntry", [("Hs.field", {"sticky": "nsew", "children": [
            ("Entry.padding", {"sticky": "nsew", "children": [("Entry.textarea", {"sticky": "nsew"})]})]})])
        s.configure("TEntry", foreground=INK_SOFT, padding=(px(12), px(8)), fieldbackground=GLASS, insertwidth=max(1, px(1)))
        chevron = self.photo("chevron", px(8 + 14), px(8), GLASS,
                             [(INK_SOFT, stroke([(px(1), px(2)), (px(5), px(6)), (px(9), px(2))], px(1.4)))])
        s.element_create("Hs.chevron", "image", chevron, sticky="")
        s.layout("TCombobox", [("Hs.field", {"sticky": "nsew", "children": [
            ("Hs.chevron", {"side": "right", "sticky": ""}),
            ("Combobox.padding", {"sticky": "nsew", "children": [("Combobox.textarea", {"sticky": "nsew"})]})]})])
        s.configure("TCombobox", foreground=INK, padding=(px(12), px(7), px(4), px(7)), arrowsize=px(12))
        s.map("TCombobox", fieldbackground=[("readonly", GLASS)], foreground=[("readonly", INK)],
              selectbackground=[("readonly", GLASS)], selectforeground=[("readonly", INK)])
        s.configure("ComboboxPopdownFrame", background=RAISED, bordercolor=LINE_STRONG, relief="solid", borderwidth=1)
        # a choice that opens a list (the launcher's profile; the Windows builder's ComboBox Choice): the field, its chevron
        s.element_create("Hs.choice", "image", field, ("pressed", field_focus), ("active", field_hover), ("focus", field_focus),
                         border=r + 2, padding=0, sticky="nsew")
        s.layout("Choice.TButton", [("Hs.choice", {"sticky": "nsew", "children": [
            ("Hs.chevron", {"side": "right", "sticky": ""}),
            ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})]})])
        s.configure("Choice.TButton", foreground=INK, font="HsUi", padding=(px(12), px(7), px(4), px(7)), anchor="w")
        s.map("Choice.TButton", foreground=[("disabled", INK_FAINT)])
        # its list, and the Manage menu's (the Windows builder's: Raised in LineStrong, radius 8, padding 4; rows 10/7,
        # RaisedHover under the mouse, BrandInk for the one chosen)
        r, n = px(8), px(8) * 2 + 6
        self.photo("popup", n, n, PAGE, framed(n, n, r, RAISED, LINE_STRONG, px(1)))
        s.element_create("Hs.popup", "image", self.images["popup"], border=r + 2, padding=0, sticky="nsew")
        s.layout("Popup.TFrame", [("Hs.popup", {"sticky": "nsew", "children": [("Frame.padding", {"sticky": "nsew"})]})])
        s.configure("Popup.TFrame", background=RAISED)
        button("Item", RAISED, RAISED_HOVER, RAISED, RAISED_HOVER, RAISED_HOVER, INK, "HsNote", (px(10), px(7)), radius=6,
               under=RAISED)
        s.configure("Item.TButton", anchor="w")
        s.configure("Chosen.Item.TButton", foreground=BRAND_INK)

        # cards (the found list's, the build's steps on Windows)
        r, n = px(10), px(10) * 2 + 6
        self.photo("card", n, n, PAGE, framed(n, n, r, GLASS, GLASS_LINE, px(1)))
        s.element_create("Hs.card", "image", self.images["card"], border=r + 2, padding=0, sticky="nsew")
        s.layout("Card.TFrame", [("Hs.card", {"sticky": "nsew", "children": [("Frame.padding", {"sticky": "nsew"})]})])

        # bars: the free space (green, red when short) and a step's progress (blue), 6 px and round
        h = max(4, px(6))
        # (the parts' names end in trough and pbar: the progress bar finds the part it sizes by that name)
        for name, under, color in (("HsTrack.trough", PAGE, TRACK), ("HsGo.pbar", PAGE, GO), ("HsBad.pbar", PAGE, BAD),
                                   ("HsCardTrack.trough", GLASS, mix(WHITE, GLASS, 0x12 / 255)), ("HsCard.pbar", GLASS, BRAND)):
            self.photo(name, h + 4, h, under, [(color, box(0, 0, h + 4, h, h / 2))])
            s.element_create(name, "image", self.images[name], border=(h // 2 + 1, 0), padding=0, sticky="nsew")
        for style, track in (("Go", "HsTrack"), ("Bad", "HsTrack"), ("Card", "HsCardTrack")):
            s.layout(style + ".Horizontal.TProgressbar", [(track + ".trough", {"sticky": "nsew", "children": [
                ("Hs%s.pbar" % style, {"side": "left", "sticky": "ns"})]})])
            s.configure(style + ".Horizontal.TProgressbar", thickness=h, background=GLASS)

        # the log's scroll bar: a thumb on the log, no arrows
        s.layout("Log.Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nsew"})]})])
        s.configure("Log.Vertical.TScrollbar", troughcolor=LOG, background=RAISED_HOVER, bordercolor=LOG, lightcolor=RAISED_HOVER,
                    darkcolor=RAISED_HOVER, gripcount=0, arrowsize=px(10))
        s.map("Log.Vertical.TScrollbar", background=[("active", LINE_STRONG)], lightcolor=[("active", LINE_STRONG)],
              darkcolor=[("active", LINE_STRONG)])

        # Play's triangle, and the hookshot of the window's head
        self.photo("play", px(11) + px(10), px(14), GO,
                   [(GO_INK, triangle([(px(0.5), px(0.5)), (px(11), px(7)), (px(0.5), px(13.5))]))])
        self.load_logo(px(28))

    def photo(self, name, w, h, under, layers):
        image = tk.PhotoImage(master=self, width=int(w), height=int(h))
        image.put(paint(int(w), int(h), under, layers))
        self.images[name] = image
        return image

    def load_logo(self, size):
        """assets/hookshot.png (the Windows head's and the game's icon), size pixels wide over the page: averaged down with its
        alpha on Tk 9, every nth pixel on an older Tk"""
        self.images["logo"] = None
        path = os.path.join(ROOT, "assets", "hookshot.png")
        try:
            full = tk.PhotoImage(master=self, file=path)
        except (tk.TclError, OSError):
            return
        w, h = full.width(), full.height()
        try:
            rows = [self.tk.splitlist(row) for row in
                    self.tk.splitlist(self.tk.call(full, "data", "-format", "default -colorformat rgba"))]
        except tk.TclError:
            self.images["logo"] = full.subsample(max(1, w // size))
            return
        tw, th = size, max(1, round(h * size / w))
        page = [int(PAGE[i:i + 2], 16) for i in (1, 3, 5)]
        out = []
        for j in range(th):
            y0, y1 = j * h // th, max(j * h // th + 1, (j + 1) * h // th)
            line = []
            for i in range(tw):
                x0, x1 = i * w // tw, max(i * w // tw + 1, (i + 1) * w // tw)
                acc, n = [0.0, 0.0, 0.0, 0.0], 0
                for y in range(y0, y1):
                    for x in range(x0, x1):
                        v = int(rows[y][x][1:], 16)
                        a = (v & 255) / 255
                        acc[0] += (v >> 24 & 255) * a
                        acc[1] += (v >> 16 & 255) * a
                        acc[2] += (v >> 8 & 255) * a
                        acc[3] += a
                        n += 1
                alpha = acc[3] / n
                line.append("#%02x%02x%02x" % tuple(min(255, round(acc[k] / n + page[k] * (1 - alpha))) for k in range(3)))
            out.append("{%s}" % " ".join(line))
        logo = tk.PhotoImage(master=self, width=tw, height=th)
        logo.put(" ".join(out))
        self.images["logo"] = logo

    def header(self, parent, step=None, chip=None):
        """the window's head, as Windows draws it: the hookshot and Hookshot at the left, and in the middle the steps (Game files >
        Build > Play) or, for the launcher, the game's version"""
        px = self.px
        canvas = tk.Canvas(parent, height=px(64), background=PAGE, highlightthickness=0, borderwidth=0)
        canvas.pack(fill="x")
        x = px(28)
        if self.images.get("logo") is not None:
            canvas.create_image(x, px(32), image=self.images["logo"], anchor="w")
            x += self.images["logo"].width() + px(10)
        canvas.create_text(x, px(32), text="Hookshot", font="HsBrand", fill=INK, anchor="w")
        x += int(self.tk.call("font", "measure", "HsBrand", "Hookshot"))
        if chip:
            canvas.create_text(x + px(12), px(32), text=chip, font="HsSmall", fill=INK_SOFT, anchor="w")
        self.header_canvas = canvas
        if step is not None:
            self.set_step(step)
            canvas.bind("<Configure>", lambda event: self.center_steps(event.width))
        return canvas

    def set_step(self, step):
        canvas = getattr(self, "header_canvas", None)
        if canvas is None or not canvas.winfo_exists():
            return
        canvas.delete("steps")
        pill, labels = self.step_pill(step)
        canvas.create_image(0, self.px(12), image=pill, anchor="nw", tags=("steps", "pill"))
        for lx, text, font, color in labels:
            canvas.create_text(lx, self.px(32), text=text, font=font, fill=color, anchor="w", tags="steps")
        self.center_steps(canvas.winfo_width())

    def center_steps(self, width):
        canvas = self.header_canvas
        pill = canvas.bbox("pill")
        if pill and width > 1:
            canvas.move("steps", (width - (pill[2] - pill[0])) // 2 - pill[0], 0)

    def step_pill(self, on):
        """Windows' SetStep: the steps in a pill, the one now in blue, the ones done with a green tick. One image (the shapes),
        and the labels with their x, for the canvas to write over it"""
        px = self.px
        names = ("Game files", "Build", "Play")
        container = mix(WHITE, PAGE, 0x0B / 255)
        layers, labels = [], []
        x = px(4)
        for i, name in enumerate(names):
            if i:
                layers.append((mix(INK_SOFT, container, 0.45), stroke([(x + px(5), px(16)), (x + px(9), px(20)), (x + px(5), px(24))], px(1.6))))
                x += px(14)
            font = "HsNoteStrong" if i == on else "HsNote"
            width = int(self.tk.call("font", "measure", font, name))
            done = i < on
            pill_w = (px(4) + px(22) + px(8) if done else px(14)) + width + px(14)
            if i == on:
                layers.append((lambda y: mix("#3557d6", "#4b70f0", min(1, max(0, (y - px(5)) / px(30)))),
                               box(x, px(5), pill_w, px(30), px(15))))
            if done:
                cx, cy = x + px(4) + px(11), px(20)
                layers.append((mix(GO, container, 0x26 / 255), box(cx - px(11), cy - px(11), px(22), px(22), px(11))))
                layers.append((GO, stroke([(cx - px(5), cy), (cx - px(1.5), cy + px(3.5)), (cx + px(5), cy - px(3.5))], px(1.8))))
            text_x = x + (px(4) + px(22) + px(8) if done else px(14))
            labels.append((text_x, name, font, WHITE if i == on else INK_SOFT if done else INK_FAINT))
            x += pill_w
        width = x + px(4)
        image = self.photo("steps-%d" % on, width, px(40), PAGE,
                           framed(width, px(40), px(20), container, GLASS_LINE, px(1)) + layers)
        return image, labels

    def section(self, parent, text, row, column=0, columnspan=1, top=24):
        """the Windows builder's section labels: FOUND ON THIS PC, INSTALL THE GAME TO"""
        label = ttk.Label(parent, text=text.upper(), style="Section.TLabel")
        label.grid(row=row, column=column, columnspan=columnspan, sticky="w", pady=(self.px(top), self.px(10)))
        return label

    # ---- the form ----
    def show_form(self):
        self.title("Hookshot Builder")
        if self.page:
            self.page.destroy()
        px = self.px
        page = self.page = ttk.Frame(self)
        page.pack(fill="both", expand=True)
        self.header(page, step=0)
        f = ttk.Frame(page, padding=(px(48), px(6), px(48), px(28)))
        f.pack(fill="both", expand=True)
        f.columnconfigure(0, weight=1, minsize=px(580))   # (every page px(800) wide: the window keeps its width, as on Windows)
        f.columnconfigure(1, minsize=px(20))
        f.columnconfigure(2, minsize=px(200))
        ttk.Label(f, text="Build your game", style="Title.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(f, text="Pick your game files and where the game goes. Hookshot does the rest, once.", style="Sub.TLabel",
                  wraplength=px(800)).grid(row=1, column=0, columnspan=3, sticky="w", pady=(px(6), 0))
        if game_ready(self.cfg.get("out")):
            ttk.Button(f, text="Play the game built in %s" % self.cfg["out"], command=lambda: self.play_or_choose(self.cfg["out"])).grid(
                row=2, column=0, columnspan=3, sticky="w", pady=(px(16), 0))
        self.section(f, "Game files", 3, columnspan=3)
        kinds = ttk.Frame(f, style="Card.TFrame", padding=px(5))
        kinds.grid(row=4, column=0, columnspan=3, sticky="we")
        kinds.columnconfigure(0, weight=1)
        ttk.Radiobutton(kinds, text=".nup file", value="nup", variable=self.kind, command=self.show_form,
                        style="Row.TRadiobutton", cursor="hand2").grid(row=0, column=0, sticky="we")
        tk.Frame(kinds, height=max(1, px(1)), background=GLASS_LINE).grid(row=1, column=0, sticky="we", padx=px(12))
        ttk.Radiobutton(kinds, text="romfs and exefs folders", value="folders", variable=self.kind, command=self.show_form,
                        style="Row.TRadiobutton", cursor="hand2").grid(row=2, column=0, sticky="we")
        paths = ttk.Frame(f)
        paths.grid(row=5, column=0, columnspan=3, sticky="we", pady=(px(10), 0))
        paths.columnconfigure(1, weight=1)
        if self.kind.get() == "nup":
            self.path_row(paths, 0, ".nup file", self.nup, lambda: self.pick_file(self.nup))
        else:
            self.path_row(paths, 0, "romfs", self.romfs, lambda: self.pick_dir(self.romfs))
            self.path_row(paths, 1, "exefs", self.exefs, lambda: self.pick_dir(self.exefs))
        ttk.Label(f, textvariable=self.check_text, style="Small.TLabel", wraplength=px(800)).grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(px(6), 0))

        self.section(f, "Install the game to", 7, top=18)
        self.section(f, "Game language", 7, column=2, top=18)
        out = ttk.Frame(f)
        out.grid(row=8, column=0, sticky="we")
        out.columnconfigure(1, weight=1)
        self.path_row(out, 0, None, self.out, lambda: self.pick_dir(self.out), button="Change")
        ttk.Combobox(f, textvariable=self.language, values=[n for _, n in make_game.LANGUAGES], state="readonly",
                     font="HsNote", cursor="hand2").grid(row=8, column=2, sticky="we")
        # (the update track: Release, Release candidate or Nightly; the builder updates from it, saved once chosen)

        options = ttk.Frame(f)
        options.grid(row=9, column=0, sticky="we", pady=(px(22), 0))
        # (the update track: Release, Release candidate or Nightly. The builder updates from it; saved once chosen)
        tracks = ttk.Frame(f)
        tracks.grid(row=9, column=2, sticky="nwe", pady=(px(22), 0))
        tracks.columnconfigure(0, weight=1)
        self.section(tracks, "Update track", 0, top=0)
        track = ttk.Combobox(tracks, textvariable=self.track, values=list(TRACK_NAMES.values()), state="readonly", font="HsNote",
                             cursor="hand2")
        track.grid(row=1, column=0, sticky="we")
        track.bind("<<ComboboxSelected>>", self.on_track_changed)
        ttk.Checkbutton(options, text="Prepare shaders now", variable=self.prepare, cursor="hand2").pack(anchor="w")
        ttk.Label(options, text="A few minutes at the end of the build. Unticked, the game prepares them at its first start, "
                  "behind a black window.", style="Small.TLabel", wraplength=px(540)).pack(anchor="w", padx=(px(26), 0), pady=(px(2), 0))
        ttk.Checkbutton(options, text="NVIDIA DLSS (downloads NVIDIA's SDK under NVIDIA's license)", variable=self.dlss,
                        command=self.on_dlss_changed, cursor="hand2").pack(anchor="w", pady=(px(12), 0))
        ttk.Label(options, text="For NVIDIA RTX graphics cards. NVIDIA's files stay on this PC: never share a game folder built with them.",
                  style="Small.TLabel", wraplength=px(540)).pack(anchor="w", padx=(px(26), 0), pady=(px(2), 0))

        f.rowconfigure(10, weight=1, minsize=px(18))
        ttk.Label(f, textvariable=self.status, style="Status.TLabel", wraplength=px(800)).grid(
            row=11, column=0, columnspan=3, sticky="w", pady=(0, px(12)))
        foot = ttk.Frame(f)
        foot.grid(row=12, column=0, columnspan=3, sticky="we")
        foot.columnconfigure(1, weight=1)
        self.space_bar = ttk.Progressbar(foot, maximum=1.0, length=px(160), style="Go.Horizontal.TProgressbar")
        self.space_bar.grid(row=0, column=0)
        ttk.Label(foot, textvariable=self.space_text, style="Small.TLabel").grid(row=0, column=1, sticky="w", padx=(px(10), 0))
        self.about_label = ttk.Label(foot, text="About 45 min", style="Faint.TLabel")
        self.about_label.grid(row=0, column=2, padx=(px(14), px(14)))
        self.build_button = ttk.Button(foot, text="Build the game", command=self.build, style="Primary.TButton", cursor="hand2")
        self.build_button.grid(row=0, column=3)
        self.out.trace_add("write", lambda *a: self.update_space())
        self.update_space()
        self.apply_mode()

    def path_row(self, f, row, label, var, browse, button="Browse…"):
        if label:
            ttk.Label(f, text=label, style="Small.TLabel").grid(row=row, column=0, sticky="w", padx=(0, self.px(12)))
        ttk.Entry(f, textvariable=var, font="HsMono").grid(row=row, column=1, sticky="we", pady=self.px(3))
        ttk.Button(f, text=button, command=browse, cursor="hand2").grid(row=row, column=2, padx=(self.px(10), 0), pady=self.px(3))

    def ask_path(self, kind, title, start=None):
        """a folder (kind "folder") or the game's .nup ("nup"), from the desktop's own chooser (chooser_command), or Tk's
        when there is none or it could not open. "" when cancelled"""
        start = start if start and os.path.isdir(start) else os.path.expanduser("~")
        command = chooser_command(kind, title, start)
        if command:
            answer = self.run_chooser(command)
            if answer is not None:
                return answer
        if kind == "folder":
            return filedialog.askdirectory(parent=self, title=title, initialdir=start)
        return filedialog.askopenfilename(parent=self, title=title, initialdir=start,
                                          filetypes=[("Switch 2 game package", "*.nup"), ("All files", "*")])

    def run_chooser(self, command):
        """runs the desktop's chooser (run_waiting). The path; "" when cancelled; None when the chooser could not run"""
        def run():
            try:
                done = subprocess.run(command, env=make_game.game_env(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                      text=True, encoding="utf-8", errors="surrogateescape")
                return done.stdout.rstrip("\n") if done.returncode == 0 else "" if done.returncode == 1 else None
            except OSError:
                return None
        return self.run_waiting(run, "Choose in the window that opened…")

    def run_waiting(self, work, text):
        """work() on a thread of its own while this window waits under a veil saying text, which takes its clicks (and
        Enter: self.busy), so it keeps drawing meanwhile. What work returns; what it raises is raised here"""
        result = []

        def run():
            try:
                result.append((True, work()))
            except BaseException as error:   # (raised again below: a work that never answered would leave the veil up)
                result.append((False, error))
        veil = tk.Frame(self, background=PAGE, cursor="watch")
        veil.place(x=0, y=0, relwidth=1, relheight=1)
        ttk.Label(veil, text=text, style="Sub.TLabel").place(relx=0.5, rely=0.5, anchor="center")
        self.busy = True
        threading.Thread(target=run, daemon=True).start()
        finished = tk.BooleanVar(self, False)

        def check():
            if result:
                finished.set(True)
            else:
                self.after(100, check)
        check()
        self.wait_variable(finished)
        veil.destroy()
        self.busy = False
        ok, value = result[0]
        if not ok:
            raise value
        return value

    def pick_file(self, var):
        p = self.ask_path("nup", "Your game's .nup", os.path.dirname(var.get()))
        if p:
            var.set(p)
            self.source_picked = True
            self.apply_mode()
            self.check_version()

    def pick_dir(self, var):
        p = self.ask_path("folder", "Choose a folder", var.get())
        if p:
            var.set(p)
            if var is self.exefs:
                self.source_picked = True
                self.apply_mode()
                self.check_version()

    def update_space(self):
        gb = free_gb(self.out.get())
        self.space_text.set("Needs 45 GB · %.0f GB free there" % gb if gb is not None else "Needs 45 GB")
        bar = getattr(self, "space_bar", None)   # (as on Windows: the 45 GB's share of what is free, green when it fits)
        try:
            if bar is not None and bar.winfo_exists():
                bar.configure(value=min(1.0, 45 / max(gb, 0.1)) if gb is not None else 0,
                              style="Go.Horizontal.TProgressbar" if gb is None or gb >= 45 else "Bad.Horizontal.TProgressbar")
        except tk.TclError:
            pass
        self.apply_mode()

    def on_dlss_changed(self):
        if self.dlss.get() and not messagebox.askyesno("NVIDIA DLSS", DLSS_LICENSE):
            self.dlss.set(False)
        else:
            self.dlss_toggled = True
        self.cfg["dlss"] = "1" if self.dlss.get() else "0"
        save_config(self.cfg)
        self.apply_mode()

    def check_version(self):
        args = ["--nup", self.nup.get()] if self.kind.get() == "nup" else ["--exefs", self.exefs.get()]
        self.check_text.set("Checking the game version...")

        def run():
            r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "nx2", "make_game.py"), "--check"] + args,
                               capture_output=True, text=True, cwd=ROOT)
            said = []
            for l in r.stdout.splitlines():
                t = make_game.reported(l)
                if t is not None:
                    said.append(t)
            tail = [l for l in (r.stderr or "").splitlines() if l.strip()]
            text = said[-1] if said else (tail[-1] if tail else "The version could not be read.")
            self.lines.put(("check", text))
        threading.Thread(target=run, daemon=True).start()

    def lookup_latest(self):
        def run():
            forced = os.environ.get("HOOKSHOT_LATEST_TAG")
            tag = None if forced == "none" else (forced or linux_update.latest_tag(track=track))
            self.lines.put(("latest", tag or ""))
        track = self.track_id()
        threading.Thread(target=run, daemon=True).start()

    def apply_mode(self):
        if self.launch_folder and self.build_button is None:
            self.apply_launch()
            return
        folder = self.out.get().strip()
        expanded = os.path.expanduser(folder) if folder else ""
        game, kept = linux_update.game_version(expanded) if expanded else (None, False)
        self.mode = linux_update.choose_mode(game, self.tools, self.latest, self.source_picked, kept, self.switching())
        dlss_changed = bool(kept and game and not self.source_picked and getattr(self, "dlss_toggled", False) and
                            hasattr(self, "dlss") and bool(self.dlss.get()) != folder_has_dlss(expanded))
        if self.mode == "up-to-date" and dlss_changed:
            self.mode = "update-game"
        button = self.build_button
        if button is None:
            return
        try:
            if not button.winfo_exists():
                return
        except tk.TclError:
            return
        button.configure(text={"update-game": "Update", "up-to-date": "Play", "update-builder": "Update builder",
                                "build": "Build the game"}[self.mode])
        about = getattr(self, "about_label", None)   # (Windows: the time only for a build)
        try:
            if about is not None and about.winfo_exists():
                about.configure(text="About 45 min" if self.mode == "build" else "")
        except tk.TclError:
            pass
        target = linux_update.update_target(self.latest, self.tools, self.switching())
        if self.mode == "update-game" and dlss_changed and game == target:
            self.status.set("Update builds your game again %s NVIDIA DLSS."
                            % ("with" if self.dlss.get() else "without"))
        elif self.mode == "update-game":
            self.status.set("Hookshot %s is available. Your game is %s. Update downloads only what changed, then compiles what changed."
                            % (target, game))
        elif self.mode == "up-to-date" and self.latest is None:
            self.status.set("Your game is %s, as this builder. GitHub did not answer, so newer versions could not be checked." % game)
        elif self.mode == "up-to-date":
            self.status.set("%s is the latest version." % game)
        elif self.mode == "update-builder":
            self.status.set("Hookshot Builder %s is available (this one is %s). Update it first, then build." % (target, self.tools or "this one"))
        else:
            self.status.set("")

    def apply_launch(self):
        if not self.launch_folder or not hasattr(self, "launch_status"):
            return
        game, kept = linux_update.game_version(self.launch_folder)
        target = linux_update.update_target(self.latest, self.tools, self.switching())
        show = False
        if target and game and game != target and kept:
            self.launch_status.set("Update available: %s" % target)
            show = True
        elif target and game and game != target:
            self.launch_status.set("%s is out. Build this folder again with Hookshot Builder to get it." % target)
        elif game and self.latest is None:
            self.launch_status.set("Up to date with this builder (GitHub did not answer)")
        elif game:
            self.launch_status.set("Up to date")
        else:
            self.launch_status.set("Could not check for updates (GitHub did not answer)" if self.latest is None else "Hookshot")
        if hasattr(self, "launch_update"):
            self.launch_update.pack(side="right", padx=self.px(4)) if show else self.launch_update.pack_forget()

    def show_launch(self, folder):
        if self.page:
            self.page.destroy()
        self.title("Hookshot")
        px = self.px
        page = self.page = ttk.Frame(self)
        page.pack(fill="both", expand=True)
        game, _kept = linux_update.game_version(folder)
        self.header(page, chip=game)
        # (the Windows launcher's page: the game's name in the middle, Update beside Play when there is one, the folder below)
        f = ttk.Frame(page, padding=(px(48), px(24), px(48), px(56)))
        f.pack(fill="both", expand=True)
        ttk.Frame(f, width=px(800), height=0).pack()
        ttk.Label(f, text="THE LEGEND OF ZELDA", style="Section.TLabel").pack()
        ttk.Label(f, text="Ocarina of Time", style="Display.TLabel").pack(pady=(px(4), 0))
        ttk.Label(f, text=folder, style="Sub.TLabel", wraplength=px(600), justify="center").pack(pady=(px(8), 0))
        self.launch_status = tk.StringVar(value="Checking for updates...")
        ttk.Label(f, textvariable=self.launch_status, style="Note.TLabel", wraplength=px(600), justify="center").pack(pady=(px(16), 0))
        if profiles.supported(folder):   # (a game built before profiles plays the default profile's saves whichever is chosen)
            self.show_profile_row(f, folder)
        buttons = ttk.Frame(f)
        buttons.pack(pady=(px(28), 0))
        self.launch_update = ttk.Button(buttons, text="Update", style="Primary.TButton", cursor="hand2",
                                        command=lambda: self.begin_update(folder))
        play_button = ttk.Button(buttons, text="Play", style="Go.TButton", image=self.images["play"], compound="left",
                                 cursor="hand2", command=lambda: self.play_and_close(folder))
        play_button.pack(side="right", padx=px(4))
        play_button.focus_set()   # (Enter plays, with the profile above)
        def enter(event):
            # (a button with the focus is pressed: Enter on Update or Manage is not Play. Play has it at first)
            if self.page is not page or self.busy:
                return
            if isinstance(event.widget, ttk.Button) and event.widget is not play_button:
                event.widget.invoke()
            else:
                self.play_and_close(folder)
        self.bind("<Return>", enter)
        ttk.Button(f, text="Open the game folder", style="Link.TButton", cursor="hand2",
                   command=lambda: subprocess.Popen(["xdg-open", folder])).pack(pady=(px(22), 0))
        self.lookup_latest()

    # ---- the launcher's profiles (profiles.py) ----
    def show_profile_row(self, f, folder):
        """the profile Play starts the game with, right above Play, with New profile beside it. What changes the chosen profile
        is wanted rarely: it is in the Manage menu, out of Play's way, with Remove last and apart"""
        px = self.px
        self.user = profiles.user_dir(folder)
        ttk.Label(f, text="PROFILE", style="Section.TLabel").pack(pady=(px(24), px(8)))
        row = ttk.Frame(f)
        row.pack()
        self.profile_box = ttk.Button(row, style="Choice.TButton", width=24, cursor="hand2",
                                      command=lambda: self.popup(self.profile_box, [
                                          (profiles.shown_name(u, n), lambda i=i: self.pick_profile(i), i == self.profile_index)
                                          for i, (u, n) in enumerate(self.profile_list)]))
        self.profile_box.pack(side="left")
        manage = ttk.Button(row, text="Manage", cursor="hand2", command=lambda: self.popup(manage, self.manage_rows()))
        manage.pack(side="left", padx=(px(8), 0))
        ttk.Button(row, text="New profile…", cursor="hand2", command=self.new_profile).pack(side="left", padx=(px(8), 0))
        self.profile_note = tk.StringVar()   # (what the last action did; empty until then)
        ttk.Label(f, textvariable=self.profile_note, style="Small.TLabel", wraplength=px(600), justify="center").pack(pady=(px(8), 0))
        self.show_profiles(chosen_profile(folder, self.cfg))

    def manage_rows(self):
        """the Manage menu, naming the profile its actions change"""
        uid, name = self.current_profile()
        rows = [("Rename %s…" % name, self.rename_profile), ("Import a save into %s…" % name, self.import_profile_save),
                ("Export %s's save…" % name, self.export_profile_save), ("Open %s's save folder" % name, self.open_profile_folder),
                None]
        if uid == profiles.DEFAULT:
            return rows + [("The default profile cannot be removed", None)]
        return rows + [("Remove %s…" % name, self.remove_profile)]

    def popup(self, anchor, rows):
        """A list under anchor in the theme's look (the Windows builder's ComboBox list): rows are (text, command, chosen),
        a command of None for a row that cannot be chosen, or None for a line between rows. It closes on a choice, on a click
        anywhere else, on Escape, and when the window moves."""
        px = self.px
        box = tk.Toplevel(self, background=RAISED)
        box.withdraw()
        box.overrideredirect(True)
        box.transient(self)
        card = ttk.Frame(box, style="Popup.TFrame", padding=px(4))   # (inside its line: a frame's padding is its own, not the style's)
        card.pack(fill="both", expand=True)

        def close(event=None):
            if box.winfo_exists():
                box.grab_release()
                box.destroy()
            self.unbind("<Configure>", moved)

        def choose(command):
            close()
            command()
        for row in rows:
            if row is None:
                tk.Frame(card, height=max(1, px(1)), background=LINE).pack(fill="x", padx=px(6), pady=px(4))
                continue
            text, command, *chosen = row
            item = ttk.Button(card, text=text, style="Chosen.Item.TButton" if chosen and chosen[0] else "Item.TButton",
                              cursor="hand2" if command else "", takefocus=False,
                              command=(lambda c=command: choose(c)) if command else None)
            if not command:
                item.state(["disabled"])
            item.pack(fill="x")
        box.update_idletasks()
        width = max(anchor.winfo_width(), box.winfo_reqwidth())
        box.geometry("%dx%d+%d+%d" % (width, box.winfo_reqheight(), anchor.winfo_rootx(),
                                      anchor.winfo_rooty() + anchor.winfo_height() + px(4)))
        box.deiconify()
        box.lift()

        def outside(event):
            x, y = event.x_root - box.winfo_rootx(), event.y_root - box.winfo_rooty()
            if not (0 <= x < box.winfo_width() and 0 <= y < box.winfo_height()):
                close()
        box.bind("<ButtonPress>", outside)
        box.bind("<Escape>", close)
        moved = self.bind("<Configure>", lambda event: close() if event.widget is self else None, add="+")
        box.wait_visibility()
        box.grab_set()
        box.focus_set()

    def show_profiles(self, uid):
        self.profile_list = profiles.load(self.user)
        ids = [p[0] for p in self.profile_list]
        self.pick_profile(ids.index(uid) if uid in ids else 0)

    def pick_profile(self, index):
        self.profile_index = index if 0 <= index < len(self.profile_list) else 0
        uid, name = self.current_profile()
        self.profile_box.configure(text=profiles.shown_name(uid, name))
        self.cfg["profile"] = uid
        save_config(self.cfg)

    def current_profile(self):
        return self.profile_list[self.profile_index]

    def ask_name(self, title, prompt, initial="", action="OK"):
        """a profile's name, in the theme's look; None when cancelled"""
        px = self.px
        box = tk.Toplevel(self, background=PAGE)
        box.title(title)
        box.transient(self)
        box.resizable(False, False)
        f = ttk.Frame(box, padding=px(24))
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=title, style="Title.TLabel").pack(anchor="w")
        ttk.Label(f, text=prompt, style="Sub.TLabel", wraplength=px(420)).pack(anchor="w", pady=(px(6), px(14)))
        text = tk.StringVar(box, initial)
        entry = ttk.Entry(f, textvariable=text, width=36, font="HsUi")
        entry.pack(fill="x")
        entry.select_range(0, "end")
        answer = []

        def done(ok):
            if ok:
                answer.append(text.get())
            box.destroy()
        buttons = ttk.Frame(f)
        buttons.pack(fill="x", pady=(px(20), 0))
        ttk.Button(buttons, text=action, style="Primary.TButton", cursor="hand2", command=lambda: done(True)).pack(
            side="right", padx=(px(8), 0))
        ttk.Button(buttons, text="Cancel", cursor="hand2", command=lambda: done(False)).pack(side="right")
        box.bind("<Return>", lambda event: done(True))
        box.bind("<Escape>", lambda event: done(False))
        box.protocol("WM_DELETE_WINDOW", lambda: done(False))
        self.center(box)
        entry.focus_set()
        box.grab_set()
        self.wait_window(box)
        return answer[0] if answer else None

    def center(self, box):
        """a dialog over the middle of the window"""
        box.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - box.winfo_reqwidth()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - box.winfo_reqheight()) // 3
        box.geometry("+%d+%d" % (max(0, x), max(0, y)))
        box.wait_visibility()

    def profile_error(self, error):
        messagebox.showerror("Hookshot", str(error), parent=self)

    def new_profile(self):
        name = self.ask_name("New profile", "Its saves start empty: the game starts it at an empty file select.",
                             action="Create")
        if name is None:
            return
        try:
            uid = profiles.add(self.user, name)
        except (OSError, ValueError) as error:
            return self.profile_error(error)
        self.show_profiles(uid)
        self.profile_note.set("%s has no saves yet: the game starts at an empty file select. Manage, Import a save brings one in."
                              % profiles.clean_name(name))

    def rename_profile(self):
        uid, old = self.current_profile()
        name = self.ask_name("Rename profile", "The new name for %s." % old, old, action="Rename")
        if name is None:
            return
        try:
            profiles.rename(self.user, uid, name)
        except (OSError, ValueError) as error:
            return self.profile_error(error)
        self.show_profiles(uid)

    def remove_profile(self):
        uid, name = self.current_profile()
        if uid == profiles.DEFAULT:
            return self.profile_error("%s is the default profile and cannot be removed: the game plays it when it is started "
                                      "without the launcher." % name)
        if "Hookshot" in oot_saves.running_games():   # (the game still running on these saves writes them out again)
            return self.profile_error("Close Hookshot first: the game, still running, can write the saves again.")
        if not messagebox.askyesno("Hookshot", "Remove the profile %s?\n\nIts saves are not deleted: they are moved to %s."
                                   % (name, os.path.join(self.user, "save-backups")), parent=self):
            return
        try:
            moved = profiles.remove(self.user, uid)
        except (OSError, ValueError) as error:
            return self.profile_error(error)
        self.show_profiles(profiles.DEFAULT)
        self.profile_note.set("Removed %s.%s" % (name, " Its saves are in %s" % moved if moved else ""))

    def open_profile_folder(self):
        path = profiles.folder_to_show(self.user, self.current_profile()[0])
        if not path:
            return self.profile_error("There are no saves yet: the game makes %s at its first start." % self.user)
        subprocess.Popen(["xdg-open", path])

    def choose_emulator_save(self, found, other=False):
        """which save to import: found is oot_saves.emulator_saves's list (other: True, the emulators' usual folders, with
        Other folder for any folder) or saves_in's (one folder's users). The saves are a card of rows, as the form's choice
        of game files. Returns the save chosen, "other", or None"""
        px = self.px
        box = tk.Toplevel(self, background=PAGE)
        box.title("Import a save")
        box.transient(self)
        box.resizable(False, False)
        f = ttk.Frame(box, padding=px(24))
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Import a save", style="Title.TLabel").pack(anchor="w")
        if other and found:
            text = "Saves found in the emulators' usual folders. Choose the one to import, or Other folder for one elsewhere."
        elif other:
            text = ("No emulator save was found in the usual folders (%s). Choose its folder with Other folder: an emulator's "
                    "data folder, its portable user folder, or the save folder itself."
                    % ", ".join(sorted(set(os.path.join(d, "") for p in oot_saves.EMULATORS for d in oot_saves.folders(p)))))
        else:
            text = "This folder has saves of %d users of the emulator. Choose the one to import." % len(found)
        ttk.Label(f, text=text, style="Sub.TLabel", wraplength=px(640)).pack(anchor="w", pady=(px(6), px(14)))
        pick = tk.IntVar(box, 0)
        chosen = []

        def done(answer):
            if answer == "ok" and found:
                chosen.append(found[pick.get()])
            elif answer == "other":
                chosen.append("other")
            box.destroy()
        if found:
            card = ttk.Frame(f, style="Card.TFrame", padding=px(5))
            card.pack(fill="x")
            card.columnconfigure(0, weight=1)
            for i, save in enumerate(found):
                if i:
                    tk.Frame(card, height=max(1, px(1)), background=GLASS_LINE).grid(row=2 * i - 1, column=0, sticky="we",
                                                                                     padx=px(12))
                row = ttk.Radiobutton(card, text=save["label"], value=i, variable=pick, style="Row.TRadiobutton", cursor="hand2")
                row.grid(row=2 * i, column=0, sticky="we")
                row.bind("<Double-Button-1>", lambda event: done("ok"))
        buttons = ttk.Frame(f)
        buttons.pack(fill="x", pady=(px(20), 0))
        if found:
            ttk.Button(buttons, text="Import", style="Primary.TButton", cursor="hand2", command=lambda: done("ok")).pack(
                side="right", padx=(px(8), 0))
        ttk.Button(buttons, text="Cancel", cursor="hand2", command=lambda: done(None)).pack(side="right")
        if other:
            ttk.Button(buttons, text="Other folder…", cursor="hand2", command=lambda: done("other")).pack(side="left")
        box.bind("<Return>", lambda event: done("ok" if found else "other"))
        box.bind("<Escape>", lambda event: done(None))
        box.protocol("WM_DELETE_WINDOW", lambda: done(None))
        self.center(box)
        box.focus_set()
        box.grab_set()
        self.wait_window(box)
        return chosen[0] if chosen else None

    def import_profile_save(self):
        """an emulator's save (or a save's folder) into the profile. The emulators' usual folders are looked through first,
        each save shown with the emulator's name for its user; Other folder chooses any folder. The copy is
        scripts/oot_saves.py's, with the profile's save folder as Hookshot's side: it copies only the save's files, refuses
        while a game runs and backs up the profile's saves first, to save-backups here. Nothing of the emulator's changes"""
        uid, name = self.current_profile()
        saves = profiles.save_dir(self.user, uid)
        backups = os.path.join(self.user, "save-backups")
        try:
            found = oot_saves.emulator_saves()
        except (oot_saves.Fail, OSError):
            found = []
        save = self.choose_emulator_save(found, other=True)
        if save == "other":
            chosen = self.ask_path("folder", "The save to import: its folder, or an emulator's data or save folder")
            if not chosen:
                return
            # (an emulator keeps a save for each of its users: with several, the player says whose, passed on as --profile)
            try:
                listed = oot_saves.saves_in(chosen)
            except oot_saves.Fail as error:
                return self.profile_error(error)
            save = listed[0] if len(listed) == 1 else self.choose_emulator_save(listed)
        if not save:
            return
        whose = "%s's save" % save["user"] if save.get("user") else "the save"
        if not messagebox.askyesno("Hookshot", "Import %s in %s into the profile %s?\n\nThe profile's saves now, if it has "
                                   "any, are copied to %s first." % (whose, save["path"], name, backups), parent=self):
            return
        def copy():
            # (each value joined to its option: an id or a folder that starts with "-" is not taken for an option. The output
            # is this process's while the copy runs: nothing else here prints meanwhile, the window waits under its veil)
            out, err = io.StringIO(), io.StringIO()
            try:
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = oot_saves.main(["import", "--from=" + save["folder"], "--profile=" + save["id"], "--hookshot=" + saves,
                                           "--backup-dir=" + backups])
            except OSError as error:   # (oot_saves reports a copy that failed; a backup that could not be made is this)
                return 1, out.getvalue(), "The copy failed: %s" % error
            except SystemExit:   # (its arguments refused: argparse's reason is the last line, after the usage)
                return 1, out.getvalue(), (err.getvalue().strip().splitlines() or [""])[-1]
            return code, out.getvalue(), err.getvalue()
        code, out, err = self.run_waiting(copy, "Copying the save…")
        if code:
            return self.profile_error(err.strip().removeprefix("error: ") or "The copy failed.")
        done = (out.strip().splitlines() or [""])[-1].removeprefix("Done.").strip()   # (where the backup went)
        self.profile_note.set("Imported into %s.%s" % (name, " " + done if done else ""))

    def export_profile_save(self):
        """the profile's save, copied into a new folder of its own in the folder the player chooses: never into an emulator,
        and nothing there is replaced. That folder is a save Import (Other folder) takes, here or on another PC"""
        uid, name = self.current_profile()
        if "Hookshot" in oot_saves.running_games():   # (a save the game is writing could be copied half old, half new)
            return self.profile_error("Close Hookshot first: the game, still running, can be writing the save.")
        chosen = self.ask_path("folder", "Where %s's save goes (a new folder is made in it)" % name)
        if not chosen:
            return
        try:
            path = profiles.export(self.user, uid, name, chosen)
        except (OSError, ValueError) as error:
            return self.profile_error(error)
        self.profile_note.set("Exported %s's save to %s" % (name, path))

    def track_id(self):
        return next((k for k, v in TRACK_NAMES.items() if v == self.track.get()), "release")

    def switching(self):
        """(a Track other than these tools' own: its newest is installed, even an older version)"""
        return self.track_id() != linux_update.track_of(self.tools)

    def on_track_changed(self, _event=None):
        self.cfg["track"] = self.track_id()
        save_config(self.cfg)
        self.latest = None
        self.apply_mode()
        self.lookup_latest()

    def older_ok(self, target, have):
        """(going to an older version, from another track: asked first)"""
        old, new = linux_update.release_key(have), linux_update.release_key(target)
        if not (self.switching() and old and new and new < old):
            return True
        return messagebox.askyesno("Hookshot", "%s is older than %s, the version you have now. Install %s?" % (target, have, target))

    def begin_update(self, folder=None):
        if folder is not None:
            self.update_folder = folder
        self.show_progress("Updating your game" if self.update_folder else "Updating Hookshot Builder")
        folder = self.update_folder
        # (a game older than this builder is built again with it: nothing to download, and GitHub need not answer. So is one
        # from a builder that is not an older release, e.g. from the Actions tab: issue 902)
        target = self.update_tag or linux_update.update_target(self.latest, self.tools, self.switching())
        fetched = self.fetched or bool(folder and self.tools and target == self.tools)

        def run():
            try:
                if not fetched:
                    root = linux_update.running_root()
                    if root is None:
                        raise RuntimeError("These tools are a source checkout, so they cannot download a release. Start the AppImage to update.")
                    # (another track's build, or a Track switch: that version's own list)
                    named = target if target and (self.switching() or linux_update.track_of(target) != "release") else None
                    manifest = linux_update.startup_manifest(root, tag=named)
                    if manifest.tag != linux_update.tools_tag(root):
                        # (as Windows does: GitHub's latest list lags right after a publish, and installing it would put
                        # the release before the one asked for over these tools)
                        if self.update_tag and manifest.tag != self.update_tag:
                            raise RuntimeError("GitHub offered %s, not %s: its download links can lag right after a release. "
                                               "Try Update again in a few minutes." % (manifest.tag, self.update_tag))
                        source =linux_update.read_manifest(root)
                        apprun = linux_update.install(manifest, root, source, note=lambda message: self.lines.put(("note", message)))
                        for name in ("APPDIR", "APPIMAGE", "ARGV0", "OWD", "LD_LIBRARY_PATH"):
                            os.environ.pop(name, None)
                        args = [apprun]
                        if folder:
                            args += ["--update", folder, "--tag", manifest.tag, "--fetched"]
                        os.execv(apprun, args)
                self.lines.put(("do-build", folder or ""))
            except Exception as error:
                self.lines.put(("update-error", str(error)))

        threading.Thread(target=run, daemon=True).start()

    def start_make_update(self, folder):
        if not folder:
            self.show_form()
            self.status.set("This builder is the latest version.")
            self.lookup_latest()
            return
        dlss = bool(self.dlss.get()) if getattr(self, "dlss_toggled", False) else folder_has_dlss(folder)
        cmd = [sys.executable, "-I", os.path.join(ROOT, "nx2", "make_game.py"), "--update", folder] + \
            ([] if self.prepare.get() else ["--no-prepare-shaders"]) + dlss_args(dlss)   # (as the last build chose)
        self.heading.configure(text="Updating your game")
        self.stage_text.set("Compiling what changed")
        self.started = time.time()
        self.proc = subprocess.Popen(cmd, cwd=ROOT, env=make_game_env(dlss), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, bufsize=1, encoding="utf-8", errors="replace", start_new_session=True)
        threading.Thread(target=self.read, args=(self.proc,), daemon=True).start()
        self.tick()

    # ---- the build ----
    def build(self):
        mode = getattr(self, "mode", "build")
        if mode == "up-to-date":
            folder = os.path.expanduser(self.out.get().strip())
            if game_ready(folder):
                self.play_or_choose(folder)
            return
        if mode in ("update-game", "update-builder"):
            game, _kept = linux_update.game_version(os.path.expanduser(self.out.get().strip()))
            if not self.older_ok(linux_update.update_target(self.latest, self.tools, self.switching()),
                                 game if mode == "update-game" and game else self.tools):
                return
        if mode == "update-game":
            self.fetched = False
            self.begin_update(os.path.expanduser(self.out.get().strip()))
            return
        if mode == "update-builder":
            self.fetched = False
            self.update_folder = ""
            self.begin_update("")
            return
        out = os.path.expanduser(self.out.get().strip())
        if self.kind.get() == "nup":
            if not os.path.isfile(self.nup.get()):
                return messagebox.showerror("Hookshot", "Choose your game's .nup file.")
            src = ["--nup", self.nup.get()]
        else:
            if not (os.path.isdir(self.romfs.get()) and os.path.isdir(self.exefs.get())):
                return messagebox.showerror("Hookshot", "Choose your game's romfs and exefs folders.")
            src = ["--romfs", self.romfs.get(), "--exefs", self.exefs.get()]
        if not out:
            return messagebox.showerror("Hookshot", "Choose where to save the game.")
        try:
            jobs = make_game.requested_jobs(os.environ.get("HOOKSHOT_JOBS"))
            if jobs is None and os.environ.get("RX_JOBS"):   # (the older setting, still honoured)
                jobs = toolchain.default_jobs()
        except ValueError as error:
            return messagebox.showerror("Hookshot", str(error))
        code = next((c for c, n in make_game.LANGUAGES if n == self.language.get()), "en-US")
        dlss = bool(self.dlss.get()) if hasattr(self, "dlss") else False
        self.cfg.update(kind=self.kind.get(), nup=self.nup.get(), romfs=self.romfs.get(), exefs=self.exefs.get(), out=out, language=code,
                        prepare="1" if self.prepare.get() else "0", **({"dlss": "1" if dlss else "0"} if hasattr(self, "dlss") else {}))
        save_config(self.cfg)
        # (issue 531) Without HOOKSHOT_JOBS or RX_JOBS, make_game chooses as on Windows, from the memory free now; this window chose
        # fewer, 80% of the total memory at 3.5 GB each, and the CPU sat at 29%
        cmd = [sys.executable, "-I", os.path.join(ROOT, "nx2", "make_game.py")] + src + ["--out", out, "--language", code] + \
            ([] if jobs is None else ["--jobs", str(jobs)]) + ([] if self.prepare.get() else ["--no-prepare-shaders"]) + \
            (dlss_args(True) if dlss else [])
        slow = slow_disk_warning(out)   # (a warning, not a stop: a hard drive still builds, only much slower)
        if slow is not None and not messagebox.askokcancel("Hookshot", slow):
            return
        self.show_progress()
        self.started = time.time()
        env_kw = {"env": make_game_env(dlss)} if (dlss or "HOOKSHOT_NGX_SDK" in os.environ) else {}
        self.proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, bufsize=1, encoding="utf-8", errors="replace", start_new_session=True, **env_kw)
        threading.Thread(target=self.read, args=(self.proc,), daemon=True).start()

    def read(self, proc):
        for line in proc.stdout:
            self.lines.put(("line", line.rstrip("\n")))
        self.lines.put(("exit", proc.wait()))

    def show_progress(self, title="Building your game"):
        if self.page:
            self.page.destroy()
        self.changed, self.compiled_files = -1, 0
        self.eta = None
        self.compile_started = None
        self.times = None
        self.shaders_later = False
        px = self.px
        page = self.page = ttk.Frame(self)
        page.pack(fill="both", expand=True)
        self.header(page, step=1)
        f = ttk.Frame(page, padding=(px(48), px(6), px(48), px(28)))
        f.pack(fill="both", expand=True)
        f.columnconfigure(0, weight=1, minsize=px(800))
        f.rowconfigure(3, weight=1)
        self.heading = ttk.Label(f, text=title, style="Title.TLabel")
        self.heading.grid(row=0, column=0, sticky="w")
        ttk.Label(f, text="This takes a while, and your PC stays usable.", style="Sub.TLabel").grid(
            row=1, column=0, sticky="w", pady=(px(6), 0))
        # (the step, its bar and the clock in a card, as Windows' steps; the lines make_game.py prints below it)
        card = ttk.Frame(f, style="Card.TFrame", padding=(px(20), px(16)))
        card.grid(row=2, column=0, sticky="we", pady=(px(22), px(14)))
        card.columnconfigure(0, weight=1)
        self.stage_label = ttk.Label(card, textvariable=self.stage_text, style="Stage.TLabel", wraplength=px(760))
        self.stage_label.grid(row=0, column=0, sticky="w")
        self.bar = ttk.Progressbar(card, maximum=1.0, mode="determinate", style="Card.Horizontal.TProgressbar")
        self.bar.grid(row=1, column=0, sticky="we", pady=(px(12), px(10)))
        ttk.Label(card, textvariable=self.time_text, style="Card.Note.TLabel").grid(row=2, column=0, sticky="w")
        lines = tk.Frame(f, background=LOG, highlightthickness=max(1, px(1)), highlightbackground=GLASS_LINE,
                         highlightcolor=GLASS_LINE)
        lines.grid(row=3, column=0, sticky="nsew")
        lines.columnconfigure(0, weight=1)
        lines.rowconfigure(0, weight=1)
        self.log = tk.Text(lines, height=12, wrap="none", font="HsLog", background=LOG, foreground=INK_SOFT,
                           borderwidth=0, highlightthickness=0, padx=px(10), pady=px(8), insertbackground=INK,
                           selectbackground=BRAND, selectforeground=WHITE)
        self.add_log = read_only(self.log)
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(lines, orient="vertical", command=self.log.yview, style="Log.Vertical.TScrollbar")
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)
        self.buttons = ttk.Frame(f)
        self.buttons.grid(row=4, column=0, sticky="e", pady=(px(14), 0))
        ttk.Button(self.buttons, text="Cancel", command=self.cancel, cursor="hand2").pack(side="right")
        self.stage_text.set("Starting")
        self.tick()

    def tick(self):
        if self.proc and self.proc.poll() is None:
            s = int(time.time() - self.started)
            text = "Elapsed %d:%02d:%02d" % (s // 3600, s // 60 % 60, s % 60)
            if self.compile_started:
                c = int(time.time() - self.compile_started)
                text += " · compiling %d:%02d" % (c // 60, c % 60)
            if self.eta is not None:
                text += " · " + left_text(self.eta)
            self.time_text.set(text)
            self.after(1000, self.tick)

    def pump(self):
        try:
            while True:
                kind, v = self.lines.get_nowait()
                if kind == "check":
                    self.check_text.set(v)
                elif kind == "latest":
                    self.latest = v or None
                    self.apply_mode()
                elif kind == "note":
                    if hasattr(self, "stage_text"):
                        self.stage_text.set(v)
                elif kind == "do-build":
                    self.start_make_update(v)
                elif kind == "update-error":
                    if hasattr(self, "stage_text"):
                        self.stage_text.set(v + " Your game folder is unchanged.")
                    if hasattr(self, "buttons"):
                        for widget in self.buttons.winfo_children():
                            widget.destroy()
                        ttk.Button(self.buttons, text="Back", command=self.show_form, cursor="hand2").pack(side="right", padx=self.px(4))
                    if hasattr(self, "stage_label"):
                        self.stage_label.configure(style="Bad.Stage.TLabel")
                elif kind == "line":
                    self.on_line(v)
                elif kind == "exit":
                    self.on_exit(v)
        except queue.Empty:
            pass
        self.after(100, self.pump)

    def on_line(self, line):
        if line.startswith("@@stage "):
            stage = line.split(" ", 2)[1]
            self.stage_text.set(STAGES.get(stage, line.split(" ", 2)[-1]))
            self.bar.configure(mode="determinate", value=0)
            # (the compile's clock and countdown are the compile's: a later step, the minutes-long shaders one, without them)
            self.compile_started = time.time() if stage == "compile" else None
            self.eta = None
        elif line.startswith("@@progress "):
            try:
                self.bar.configure(value=float(line.split()[1]))
            except ValueError:
                pass
        elif line.startswith("@@plan "):
            parts = line.split(" ")
            if len(parts) == 3:
                try:
                    self.changed, total = int(parts[1]), int(parts[2])
                except ValueError:
                    pass
                else:
                    self.stage_text.set("Compiling: everything is already built" if not self.changed else
                                        "Compiling %d changed files of %d" % (self.changed, total) if self.changed < total else
                                        "Compiling %d files" % total)
            return
        elif line.startswith("@@file "):
            parts = line.split(" ")
            if len(parts) == 4 and parts[3] in ("new", "again"):
                self.compiled_files += 1
                if self.changed > 0:
                    self.stage_text.set("Compiling %d of %d changed files" % (self.compiled_files, self.changed))
            return
        elif line.startswith("@@eta "):
            try:
                self.eta = float(line.split()[1])
            except (ValueError, IndexError):
                pass
            return
        elif line.startswith("@@times "):
            parts = line.split(" ")
            if len(parts) == 4:
                try:
                    self.times = (float(parts[1]), float(parts[2]), float(parts[3]))
                except ValueError:
                    pass
            return
        elif line.startswith("@@done "):
            self.built = line[7:]
        elif line.startswith("@@error "):
            self.error = line[8:]
        elif line.startswith(make_game.NOT_PREPARED):
            self.shaders_later = True
        if hasattr(self, "log"):
            self.add_log(line + "\n")
            self.log.see("end")

    def on_exit(self, code):
        self.proc = None
        for w in self.buttons.winfo_children():
            w.destroy()
        folder = getattr(self, "built", None)
        if code == 0 and folder and game_ready(folder):
            s = int(time.time() - self.started)
            text = "Your game is ready, built in %d:%02d" % (s // 3600, s // 60 % 60)
            if self.times:
                total, compiled, previous = self.times
                text += ", compiled in %d:%02d" % (int(compiled) // 60, int(compiled) % 60)
                if previous > 0:
                    text += " · last time %d:%02d" % (int(previous) // 3600, int(previous) // 60 % 60)
            if self.shaders_later:
                text += " · the shaders are prepared at its first start"
            self.stage_text.set(text)
            self.bar.configure(value=1.0)
            try:
                add_to_menu(folder)
            except (OSError, ValueError):   # (no menu entry; the game is built)
                pass
            ttk.Button(self.buttons, text="Play", style="Go.TButton", image=self.images["play"], compound="left", cursor="hand2",
                       command=lambda: self.play_or_choose(folder)).pack(side="right", padx=self.px(4))
            ttk.Button(self.buttons, text="Open folder", cursor="hand2",
                       command=lambda: subprocess.Popen(["xdg-open", folder])).pack(side="right", padx=self.px(4))
            self.heading.configure(text="Your game is ready")
            self.stage_label.configure(style="Go.Stage.TLabel")
            self.set_step(2)
        else:
            self.stage_text.set("The build stopped: %s" % getattr(self, "error", "see the lines above"))
            ttk.Button(self.buttons, text="Back", command=self.show_form, cursor="hand2").pack(side="right", padx=self.px(4))
            self.heading.configure(text="The build stopped")
            self.stage_label.configure(style="Bad.Stage.TLabel")

    def cancel(self):
        if self.proc and self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGTERM)
            self.error = "Build cancelled. You can start again from the same folder."

    def play_or_choose(self, folder):
        """Play from the builder's pages: the launcher's page first, where the profile Play starts is shown and profiles are
        made and changed (the builder's own pages have none of that). A game built before profiles: at once"""
        if profiles.supported(folder):
            self.launch_folder, self.build_button = folder, None
            self.show_launch(folder)
        else:
            self.play_and_close(folder)

    def play_and_close(self, folder):
        play(folder)
        self.destroy()

    def close(self):
        if self.proc and self.proc.poll() is None:
            if not messagebox.askyesno("Hookshot", "Stop the build and close?"):
                return
            os.killpg(self.proc.pid, signal.SIGTERM)
        self.destroy()


def main():
    if "--play" in sys.argv[1:]:
        folder = _arg("--play") or load_config().get("out")
        if game_ready(folder):
            play(folder)
            return
    launch = _arg("--launch")
    update = _arg("--update")
    if update is not None:
        Builder(update=update, fetched="--fetched" in sys.argv[1:], tag=_arg("--tag")).mainloop()
    elif launch:
        Builder(launch=launch).mainloop()
    else:
        Builder().mainloop()


if __name__ == "__main__":
    main()
