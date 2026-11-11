"""The launcher's profiles (nx2/profiles.py): each one has saves of its own, which scripts/oot_saves.py imports from and
exports to an emulator.

python -I -B tests/test_launcher_profiles.py
"""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

RUN_ALL_SKIP = {"windows": "the launcher's profiles, POSIX paths"}

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hookshot_profiles", ROOT / "nx2" / "profiles.py")
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
        # (the launcher's Import and Export: scripts/oot_saves.py with --hookshot the profile's save folder)
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

    def test_the_json_commands_report_the_list_and_errors(self):
        game = self.root / "game"
        (game / "user" / "save").mkdir(parents=True)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(profiles.main(["add", str(game), "Link"]), 0)
        added = json.loads(out.getvalue())
        self.assertEqual([p["name"] for p in added["profiles"]], ["Player", "Link"])
        self.assertEqual(added["selected"], added["profiles"][1]["id"])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(profiles.main(["remove", str(game), profiles.DEFAULT]), 1)
        self.assertIn("cannot be removed", json.loads(out.getvalue())["error"])


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


if __name__ == "__main__":
    unittest.main()
