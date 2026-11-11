"""The Linux launcher's profiles (builder/linux/profiles.py): each one has saves of its own, which scripts/oot_saves.py
imports from and exports to an emulator.

python -I -B tests/test_launcher_profiles.py
"""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

RUN_ALL_SKIP = {"windows": "the Linux launcher's profiles, POSIX paths"}

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("launcher_profiles", ROOT / "builder" / "linux" / "profiles.py")
profiles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profiles)
spec = importlib.util.spec_from_file_location("oot_saves", ROOT / "scripts" / "oot_saves.py")
oot_saves = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oot_saves)


def save(folder, slots=2, marker="a"):
    """a save folder of the game as the console and emulators keep it"""
    folder.mkdir(parents=True)
    (folder / "account.sav").write_text(marker)
    (folder / "option.sav").write_text(marker)
    for n in range(slots):
        slot = folder / ("slot_%02d" % n)
        slot.mkdir()
        (slot / "progress.sav").write_text(marker)
        (slot / "caption.sav").write_text(marker)
    return folder


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hookshot-profiles-")
        self.root = Path(self.tmp.name)
        self.user = str(self.root / "user")

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_default_profile_is_the_user_every_build_had(self):
        self.assertEqual(profiles.load(self.user), [(profiles.DEFAULT, "Player")])
        self.assertEqual(profiles.DEFAULT, "5a3c9e1f0b7d24680000000000000001")   # (host/nn_applet.c's user_uid)

    def test_new_profiles_get_save_folders_of_their_own(self):
        a = profiles.add(self.user, "  Link  ")
        b = profiles.add(self.user, "Zelda")
        self.assertEqual(profiles.load(self.user), [(profiles.DEFAULT, "Player"), (a, "Link"), (b, "Zelda")])
        self.assertEqual(len({profiles.DEFAULT, a, b}), 3)
        for uid in (a, b):
            self.assertRegex(uid, r"^[0-9a-f]{32}$")
        with self.assertRaises(ValueError):
            profiles.add(self.user, "link")
        with self.assertRaises(ValueError):
            profiles.add(self.user, "   ")
        profiles.rename(self.user, profiles.DEFAULT, "Tim")
        self.assertEqual(profiles.load(self.user)[0], (profiles.DEFAULT, "Tim"))
        self.assertEqual(profiles.shown_name(profiles.DEFAULT, "Tim"), "Tim (default)")   # (why it cannot be removed)
        self.assertEqual(profiles.shown_name(a, "Link"), "Link")

    def test_a_removed_profile_keeps_its_saves_and_its_folder_is_not_reused(self):
        uid = profiles.add(self.user, "Link")
        save(Path(self.user) / "save" / uid)
        moved = profiles.remove(self.user, uid)
        self.assertTrue(os.path.isfile(os.path.join(moved, "slot_00", "progress.sav")))
        self.assertFalse(os.path.exists(os.path.join(self.user, "save", uid)))
        self.assertEqual(profiles.load(self.user), [(profiles.DEFAULT, "Player")])
        with self.assertRaises(ValueError):
            profiles.remove(self.user, profiles.DEFAULT)
        self.assertNotEqual(profiles.add(self.user, "Again"), uid)   # (its saves are in save-backups, named by its id)
        other = profiles.add(self.user, "Other")
        save(Path(self.user) / "save" / other)
        profiles.remove(self.user, other)
        save(Path(self.user) / "save" / other)   # (a folder left over: a new profile does not take it either)
        self.assertNotIn(profiles.add(self.user, "Third"), (uid, other))

    def test_a_list_in_another_encoding_keeps_every_profile(self):
        # (a hand edit in Latin-1: the name is shown as best it can be, and adding a profile does not drop the others)
        os.makedirs(self.user)
        uid = "5a3c9e1f0b7d24680000000000000002"
        with open(os.path.join(self.user, profiles.LIST), "wb") as f:
            f.write(("%s Jos\xe9\n" % uid).encode("latin-1"))
        self.assertEqual([u for u, _ in profiles.load(self.user)], [profiles.DEFAULT, uid])
        profiles.add(self.user, "Zelda")
        self.assertEqual([n for _, n in profiles.load(self.user)], ["Player", "Jos\ufffd", "Zelda"])

    def test_a_profiles_saves_go_in_and_out_through_oot_saves(self):
        # (the launchers' Import and Export: scripts/oot_saves.py with --hookshot the profile's save folder)
        uid = profiles.add(self.user, "Link")
        source = save(self.root / "emu" / "nand" / "user" / "save" / "0000000000000000" / "45EB517681BCEAF4B834E0FA511E3212"
                      / "0400486024DEC000", slots=3, marker="new")
        backups = os.path.join(self.user, "save-backups")
        out = io.StringIO()
        with mock.patch.object(oot_saves, "running_games", return_value=[]), contextlib.redirect_stdout(out):
            self.assertEqual(oot_saves.main(["import", "--from", str(self.root / "emu"), "--hookshot",
                                             profiles.save_dir(self.user, uid), "--backup-dir", backups]), 0)
            own = Path(profiles.save_dir(self.user, uid))
            self.assertEqual((own / "slot_02" / "progress.sav").read_text(), "new")   # (a new profile: its folder is made)
            (own / "slot_00" / "progress.sav").write_text("played")
            self.assertEqual(oot_saves.main(["export", "--to", str(self.root / "emu"), "--hookshot", str(own),
                                             "--backup-dir", backups]), 0)
        self.assertEqual((source / "slot_00" / "progress.sav").read_text(), "played")
        (backup,) = os.listdir(backups)   # (the emulator's save before the export)
        self.assertEqual(Path(backups, backup, "slot_00", "progress.sav").read_text(), "new")
        self.assertEqual(profiles.load(self.user)[1], (uid, "Link"))

    def test_open_save_folder_shows_the_profiles_saves_and_makes_no_folder(self):
        uid = profiles.add(self.user, "Link")
        self.assertEqual(profiles.folder_to_show(self.user, uid), self.user)   # (no save folder yet: none is made)
        self.assertFalse(os.path.exists(os.path.join(self.user, "save", uid)))
        save(Path(self.user) / "save" / profiles.DEFAULT)
        self.assertEqual(profiles.folder_to_show(self.user, uid), os.path.join(self.user, "save"))
        save(Path(self.user) / "save" / uid)
        self.assertEqual(profiles.folder_to_show(self.user, uid), os.path.join(self.user, "save", uid))
        self.assertIsNone(profiles.folder_to_show(str(self.root / "none"), uid))

    def test_the_user_folder_is_the_one_the_game_uses(self):
        game = self.root / "game"
        game.mkdir()
        self.assertEqual(profiles.user_dir(str(game), {"XDG_DATA_HOME": "/data", "HOME": "/home/p"}), "/data/hookshot")
        self.assertEqual(profiles.user_dir(str(game), {"XDG_DATA_HOME": "rel", "HOME": "/home/p"}),
                         "/home/p/.local/share/hookshot")
        (game / "user" / "save").mkdir(parents=True)   # (saves the game could not move: hos_main.c keeps using them)
        self.assertEqual(profiles.user_dir(str(game), {"HOME": "/home/p"}), str(game / "user"))


class SupportTests(unittest.TestCase):
    """Profiles only for a game that plays them: a game built before them ignores HOOKSHOT_PROFILE and plays the default
    profile's saves whichever is chosen"""

    def test_only_a_game_marked_by_make_game_plays_profiles(self):
        with tempfile.TemporaryDirectory() as game:
            self.assertFalse(profiles.supported(game))
            version = Path(game) / "hookshot_version.txt"
            version.write_text("version=v2.0.13\nbuilder=/x/AppRun\n", encoding="utf-8")
            self.assertFalse(profiles.supported(game))
            version.write_text("profiles=1\nversion=v2.1.0\n", encoding="utf-8")
            self.assertTrue(profiles.supported(game))

    def test_make_game_marks_every_build(self):
        # (a build from the repository has no release tag, and plays profiles all the same)
        source = (ROOT / "nx2" / "make_game.py").read_text(encoding="utf-8")
        start = source.index('"hookshot_version.txt"), "w"')
        block = source[start:source.index("\n    # ", start)]
        self.assertIn('f.write("profiles=1\\n")', block)
        self.assertLess(block.index('f.write("profiles=1\\n")'), block.index("if tag:"))


def load_builder():
    """builder/linux/hookshot_builder.py with a stand-in for tkinter (no display here)"""
    for name in ("tkinter", "tkinter.filedialog", "tkinter.messagebox", "tkinter.ttk"):
        sys.modules.setdefault(name, types.ModuleType(name))
    tk = sys.modules["tkinter"]
    tk.Tk = getattr(tk, "Tk", type("Tk", (), {}))
    tk.filedialog, tk.messagebox, tk.ttk = (sys.modules["tkinter." + n] for n in ("filedialog", "messagebox", "ttk"))
    spec = importlib.util.spec_from_file_location("hookshot_builder_profiles", ROOT / "builder" / "linux" / "hookshot_builder.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BuilderPlayTests(unittest.TestCase):
    """The builder's Play: the launcher's page, where profiles are made, even with one profile; a game built before them
    starts at once"""

    def test_play_opens_the_launcher_page_for_a_game_that_plays_profiles(self):
        builder = load_builder()
        with tempfile.TemporaryDirectory() as game:
            done = []
            window = types.SimpleNamespace(show_launch=lambda folder: done.append(("launcher", folder)),
                                           play_and_close=lambda folder: done.append(("play", folder)))
            builder.Builder.play_or_choose(window, game)
            Path(game, "hookshot_version.txt").write_text("profiles=1\nversion=v2.1.0\n", encoding="utf-8")
            builder.Builder.play_or_choose(window, game)
            self.assertEqual(done, [("play", game), ("launcher", game)])
            self.assertEqual(window.launch_folder, game)


class LauncherCopyTests(unittest.TestCase):
    """The Linux launcher's Import from an emulator folder with saves of several of its users: it asks whose, and passes that
    user on to scripts/oot_saves.py as --profile (oot_saves refuses to choose)"""

    def test_import_asks_whose_save_and_passes_it_on(self):
        builder = load_builder()
        oot = builder.oot_saves
        with tempfile.TemporaryDirectory() as tmp:
            user = os.path.join(tmp, "hookshot")
            uid = profiles.add(user, "Link")
            emulator = Path(tmp) / "eden"
            users = ["11111111111111111111111111111111", "22222222222222222222222222222222"]
            for n, who in enumerate(users):
                save(emulator / "nand" / "user" / "save" / oot.NO_ACCOUNT / who / oot.TITLE, slots=n + 1, marker=who)
            asked, errors, notes = [], [], []

            def choose(found, other=False):
                if other:   # (the emulators' usual folders: nothing there, so Other folder)
                    asked.append(("usual", found))
                    return "other"
                asked.append([s["id"] for s in found])
                return found[1]
            launcher = types.SimpleNamespace(user=user, current_profile=lambda: (uid, "Link"), profile_error=errors.append,
                                             choose_emulator_save=choose, profile_note=types.SimpleNamespace(set=notes.append))
            launcher.ask_path = lambda kind, title, start=None: str(emulator)
            launcher.run_waiting = lambda work, text: work()
            with mock.patch.object(builder.messagebox, "askyesno", lambda *a, **k: True, create=True), \
                    mock.patch.object(oot, "emulator_saves", return_value=[]), \
                    mock.patch.object(oot, "running_games", return_value=[]):
                builder.Builder.import_profile_save(launcher)
            self.assertEqual(errors, [])
            self.assertEqual(asked, [("usual", []), users])
            saves = Path(profiles.save_dir(user, uid))
            self.assertEqual((saves / "account.sav").read_text(), users[1])
            self.assertEqual(sorted(p.name for p in saves.iterdir() if p.name.startswith("slot_")), ["slot_00", "slot_01"])
            self.assertTrue(notes and notes[-1].startswith("Imported into Link."), notes)

    def test_import_offers_the_emulators_usual_folders_with_their_users_names(self):
        builder = load_builder()
        oot = builder.oot_saves
        with tempfile.TemporaryDirectory() as tmp:
            user = os.path.join(tmp, "data", "hookshot")
            uid = profiles.add(user, "Link")
            eden = Path(tmp) / "data" / "eden"
            who = "533C42419DD767B01211726DADA4670A"
            save(eden / "nand" / "user" / "save" / oot.NO_ACCOUNT / who / oot.TITLE, marker="svenja")
            users(eden / "nand", {who: "Svenja"})
            offered, errors, notes = [], [], []

            def choose(found, other=False):
                offered.append((other, [(s["user"], s["label"]) for s in found]))
                return found[0]
            launcher = types.SimpleNamespace(user=user, current_profile=lambda: (uid, "Link"), profile_error=errors.append,
                                             choose_emulator_save=choose, profile_note=types.SimpleNamespace(set=notes.append))
            folder_asked = []
            launcher.ask_path = lambda *a, **k: folder_asked.append(a)
            launcher.run_waiting = lambda work, text: work()
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(Path(tmp) / "data")}), \
                    mock.patch.object(builder.messagebox, "askyesno", lambda *a, **k: True, create=True), \
                    mock.patch.object(oot, "running_games", return_value=[]):
                builder.Builder.import_profile_save(launcher)
            self.assertEqual(errors, [])
            self.assertEqual(folder_asked, [])
            self.assertEqual(len(offered), 1)
            other, rows = offered[0]
            self.assertTrue(other)
            self.assertEqual([u for u, _ in rows], ["Svenja"])
            self.assertIn("Eden", rows[0][1])
            self.assertEqual((Path(profiles.save_dir(user, uid)) / "account.sav").read_text(), "svenja")

    def test_import_that_fails_says_so_and_an_id_is_never_an_option(self):
        # (a backup that could not be made, a full disk: an OSError past oot_saves' own report is the player's error too,
        # not a traceback on a stderr nobody sees. An id starting with "-" goes to oot_saves joined to its option)
        builder = load_builder()
        with tempfile.TemporaryDirectory() as tmp:
            user = os.path.join(tmp, "hookshot")
            uid = profiles.add(user, "Link")
            errors, notes, argv = [], [], []
            found = {"id": "-backup", "path": os.path.join(tmp, "-backup"), "folder": tmp, "user": None}
            launcher = types.SimpleNamespace(user=user, current_profile=lambda: (uid, "Link"), profile_error=errors.append,
                                             choose_emulator_save=lambda found_, other=False: found,
                                             profile_note=types.SimpleNamespace(set=notes.append),
                                             run_waiting=lambda work, text: work())

            def main(args):
                argv.append(args)
                raise OSError(28, "No space left on device")
            with mock.patch.object(builder.messagebox, "askyesno", lambda *a, **k: True, create=True), \
                    mock.patch.object(builder.oot_saves, "emulator_saves", return_value=[found]), \
                    mock.patch.object(builder.oot_saves, "main", main):
                builder.Builder.import_profile_save(launcher)
            self.assertEqual(len(errors), 1)
            self.assertIn("No space left on device", str(errors[0]))
            self.assertEqual(notes, [])
            self.assertIn("--profile=-backup", argv[0])
            # (and argparse itself takes it so: no SystemExit, which would close the window)
            parsed = []
            with mock.patch.object(builder.oot_saves, "run", parsed.append):
                self.assertEqual(builder.oot_saves.main(["import", "--from=" + tmp, "--profile=-backup"]), 0)
            self.assertEqual(parsed[0].profile, "-backup")

    def test_export_makes_a_new_folder_and_never_touches_an_emulator(self):
        builder = load_builder()
        with tempfile.TemporaryDirectory() as tmp:
            user = os.path.join(tmp, "hookshot")
            uid = profiles.add(user, "Zelda/Link")
            save(Path(profiles.save_dir(user, uid)), marker="mine")
            out = Path(tmp) / "out"
            out.mkdir()
            errors, notes = [], []
            launcher = types.SimpleNamespace(user=user, current_profile=lambda: (uid, "Zelda/Link"), profile_error=errors.append,
                                             profile_note=types.SimpleNamespace(set=notes.append))
            launcher.ask_path = lambda kind, title, start=None: str(out)
            with mock.patch.object(builder.oot_saves, "running_games", return_value=[]), \
                    mock.patch.object(builder.oot_saves, "main", side_effect=AssertionError("no emulator copy")):
                builder.Builder.export_profile_save(launcher)
                builder.Builder.export_profile_save(launcher)
            self.assertEqual(errors, [])
            made = sorted(out.iterdir())
            self.assertEqual(len(made), 2)   # (a second export the same minute: a folder of its own, nothing replaced)
            self.assertTrue(made[0].name.startswith("Hookshot save - Zelda_Link - "), made[0].name)
            self.assertEqual(sorted(p.name for p in made[0].iterdir()), ["account.sav", "option.sav", "slot_00", "slot_01"])
            self.assertEqual((made[0] / "slot_01" / "progress.sav").read_text(), "mine")
            self.assertEqual(oot_saves.saves_in(str(made[0]))[0]["path"], str(made[0]))   # (Import's Other folder takes it)
            self.assertTrue(notes[-1].startswith("Exported Zelda/Link's save to "), notes)
            with mock.patch.object(builder.oot_saves, "running_games", return_value=["Hookshot"]):
                builder.Builder.export_profile_save(launcher)
            self.assertEqual(len(errors), 1)
            empty = profiles.add(user, "Empty")
            with self.assertRaises(ValueError):
                profiles.export(user, empty, "Empty", str(out))


class ChooserTests(unittest.TestCase):
    """The file choosers are the desktop's own (its size, its dark mode): kdialog on KDE, zenity elsewhere, Tk's without"""

    def test_the_desktops_chooser(self):
        builder = load_builder()
        both = lambda tool: "/usr/bin/" + tool
        kde = builder.chooser_command("folder", "Where", "/home/x", {"XDG_CURRENT_DESKTOP": "KDE"}, both)
        self.assertEqual(kde, ["/usr/bin/kdialog", "--title", "Where", "--getexistingdirectory", "/home/x"])
        gnome = builder.chooser_command("folder", "Where", "/home/x", {"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}, both)
        self.assertEqual(gnome, ["/usr/bin/zenity", "--file-selection", "--title=Where", "--filename=/home/x/", "--directory"])
        nup = builder.chooser_command("nup", "Your game", "/g", {"XDG_CURRENT_DESKTOP": "KDE"}, both)
        self.assertEqual(nup[-1], "Switch 2 game package (*.nup)")
        only_zenity = lambda tool: "/usr/bin/zenity" if tool == "zenity" else None
        self.assertEqual(builder.chooser_command("nup", "G", "/g", {"XDG_CURRENT_DESKTOP": "KDE"}, only_zenity)[-2:],
                         ["--file-filter=Switch 2 game package | *.nup", "--file-filter=All files | *"])
        self.assertIsNone(builder.chooser_command("folder", "G", "/g", {}, lambda tool: None))


def users(nand, names):
    """an Eden user list (nand/system/save/8000000000000010/su/avators/profiles.dat) naming the save folders' users"""
    import struct
    data = bytearray(0x650)
    for n, (folder, name) in enumerate(names.items()):
        at = 0x10 + n * 0xC8
        struct.pack_into("<QQ", data, at, int(folder[16:], 16), int(folder[:16], 16))
        data[at + 40:at + 40 + len(name.encode())] = name.encode()
    path = nand.joinpath("system", "save", "8000000000000010", "su", "avators", "profiles.dat")
    path.parent.mkdir(parents=True)
    path.write_bytes(bytes(data))


if __name__ == "__main__":
    unittest.main()
