"""Game-free checks of make_game's damaged_files.txt note: the (damaged, stand-in) pairs a check found are written
beside the game for its startup warning; a second check keeps the note; a clean check removes a previous build's
stale note.

Run with: python -I tests/test_make_game_damaged_files.py
"""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
sys.path.insert(0, str(ROOT / "third_party/a64-kit/tools"))
import nup  # noqa: E402

spec = importlib.util.spec_from_file_location("make_game_damaged_note", ROOT / "nx2" / "make_game.py")
make_game = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_game)


class DamagedFilesNoteTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(prefix="hookshot-damaged-note-")
        self.addCleanup(self.dir.cleanup)
        self.out = Path(self.dir.name) / "game"
        self.romfs = self.out / "romfs"
        (self.romfs / "Tex").mkdir(parents=True)
        (self.out / ".hookshot_romfs").write_text("authored unpack stamp\n", encoding="utf-8")

    def write_romfs(self, damaged=True):
        (self.romfs / "Tex" / "whole.bntx.zs").write_bytes(nup.ZSTD + b"rest")
        bad = self.romfs / "Tex" / "broken.bntx.zs"
        bad.write_bytes(b"\0" * 8 if damaged else nup.ZSTD + b"rest")
        return str(bad)

    def check(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            done = make_game.stand_in_damaged_files(str(self.out), str(self.romfs))
        return done, out.getvalue()

    def test_note_written_and_pairs_returned(self):
        bad = self.write_romfs()
        done, said = self.check()
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0][0], bad)
        self.assertIn("Your game dump is incomplete", said)
        note = self.out / make_game.DAMAGED_FILES
        lines = note.read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines[0].startswith("#"))
        self.assertEqual(len([line for line in lines if line and not line.startswith("#")]), 1)
        self.assertIn("Tex/broken.bntx.zs -> ", lines[-1])
        legacy = self.out / make_game.DAMAGED_FILES_LEGACY
        self.assertEqual(legacy.read_bytes(), note.read_bytes())

    def test_second_check_keeps_the_note(self):
        self.write_romfs()
        first, _ = self.check()
        note = (self.out / make_game.DAMAGED_FILES).read_bytes()
        self.assertEqual(self.check(), ([], ""))
        self.assertEqual((self.out / make_game.DAMAGED_FILES).read_bytes(), note)
        self.assertEqual(len(first), 1)

    def test_clean_check_removes_a_stale_note(self):
        self.write_romfs(damaged=False)
        stale = self.out / make_game.DAMAGED_FILES
        stale.write_text("stale note from a previous build\n", encoding="utf-8")
        stale_legacy = self.out / make_game.DAMAGED_FILES_LEGACY
        stale_legacy.write_text("stale legacy note\n", encoding="utf-8")
        done, said = self.check()
        self.assertEqual(done, [])
        self.assertNotIn("Your game dump is incomplete", said)
        self.assertFalse(stale.exists())
        self.assertFalse(stale_legacy.exists())


if __name__ == "__main__":
    unittest.main()
