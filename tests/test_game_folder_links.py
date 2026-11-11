"""What the builder reads back from a game folder it built before stays inside that folder.

A game folder can come from elsewhere (copied, unpacked from an archive). An update or a rebuild into it reads its
.hookshot_romfs_heads list (the damaged textures the extraction found), copies its kept .hookshot_exefs and hard-links
a romfs into its romfs folder. Checked here without a game:
- a heads list line that leaves the romfs (.., an absolute path, a link on the way) is not written to: the list is
  dropped and every file is checked instead;
- a stand-in is copied into a new file of its own, not through a planted <name>.zs.part link;
- a link inside the kept .hookshot_exefs, or inside the romfs the links go into, stops the build;
- so does a link at a name the builder writes in the folder (language.txt, bin, the staged .new files...).

python -I -B tests/test_game_folder_links.py
"""
import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
spec = importlib.util.spec_from_file_location("make_game_under_test", ROOT / "nx2" / "make_game.py")
make_game = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_game)

ZSTD = b"\x28\xb5\x2f\xfd" + b"S" * 12
DAMAGED = b"\0\0\0\0" + b"D" * 12
STAMP = "unpacked by this builder: game.nup 123"


@unittest.skipIf(os.name == "nt", "symbolic links need a privilege on Windows")
class GameFolderLinks(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="hookshot-folder-links-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.out = self.root / "game"
        self.romfs = self.out / "romfs"
        (self.romfs / "Model").mkdir(parents=True)
        (self.romfs / "Model" / "a_Alb.bntx.zs").write_bytes(DAMAGED)
        (self.romfs / "Model" / "b_Alb.bntx.zs").write_bytes(ZSTD)
        self.outside = self.root / "outside"
        self.outside.mkdir()
        (self.outside / "x_Alb.bntx.zs").write_bytes(b"\0\0\0\0outside, not a game file")
        (self.outside / "y_Alb.bntx.zs").write_bytes(ZSTD)
        (self.out / ".hookshot_romfs").write_text(STAMP + "\n", encoding="utf-8")

    def heads(self, *lines):
        (self.out / make_game.HEADS).write_text(STAMP + "\n" + "".join(l + "\n" for l in lines), encoding="utf-8")

    def stand_in(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            make_game.stand_in_damaged_files(str(self.out), str(self.romfs))

    def outside_untouched(self):
        self.assertEqual((self.outside / "x_Alb.bntx.zs").read_bytes(), b"\0\0\0\0outside, not a game file")

    def test_list_lines_outside_the_romfs_are_not_written(self):
        for i, line in enumerate(("../../outside/x_Alb.bntx.zs", str(self.outside / "x_Alb.bntx.zs"),
                                  "Model/../../../outside/x_Alb.bntx.zs")):
            with self.subTest(line=line):
                (self.out / ".hookshot_romfs_checked").unlink(missing_ok=True)
                (self.romfs / "Model" / "a_Alb.bntx.zs").write_bytes(DAMAGED)
                self.heads("Model/a_Alb.bntx.zs", line)
                self.stand_in()
                self.outside_untouched()
                # (the list was dropped and every file checked: the real damaged one still got its stand-in)
                self.assertEqual((self.romfs / "Model" / "a_Alb.bntx.zs").read_bytes(), ZSTD)

    def test_list_through_a_linked_folder_is_not_written(self):
        os.symlink(self.outside, self.romfs / "Linked")
        self.heads("Linked/x_Alb.bntx.zs")
        self.stand_in()
        self.outside_untouched()

    def test_a_planted_part_link_is_not_written_through(self):
        victim = self.root / "victim.txt"
        victim.write_bytes(b"victim")
        os.symlink(victim, self.romfs / "Model" / "a_Alb.bntx.zs.part")
        for listed in (True, False):
            with self.subTest(listed=listed):
                (self.out / ".hookshot_romfs_checked").unlink(missing_ok=True)
                (self.romfs / "Model" / "a_Alb.bntx.zs").write_bytes(DAMAGED)
                if listed:
                    self.heads("Model/a_Alb.bntx.zs")
                else:
                    (self.out / make_game.HEADS).unlink(missing_ok=True)
                self.stand_in()
                self.assertEqual(victim.read_bytes(), b"victim")
                self.assertEqual((self.romfs / "Model" / "a_Alb.bntx.zs").read_bytes(), ZSTD)
                self.assertEqual([p.name for p in (self.romfs / "Model").glob(".standin-*")], [])

    def test_links_in_what_the_builder_made_stop_the_build(self):
        kept = self.out / ".hookshot_exefs"
        kept.mkdir()
        (kept / "main").write_bytes(b"NSO0")
        os.symlink(self.outside / "y_Alb.bntx.zs", kept / "sdk")
        os.symlink(self.outside, self.romfs / "Pack")
        for folder in (kept, self.romfs):
            with self.subTest(folder=folder.name), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit):
                    make_game.refuse_folder_links(str(folder))
        clean = self.root / "clean"
        (clean / "sub").mkdir(parents=True)
        (clean / "sub" / "f").write_bytes(b"f")
        make_game.refuse_folder_links(str(clean))
        make_game.refuse_folder_links(str(self.root / "missing"))
        source = (ROOT / "nx2" / "make_game.py").read_text(encoding="utf-8")
        # (each copy from the kept exefs, and the links into an existing romfs, come after the check)
        self.assertEqual(source.count("shutil.copytree(kept, exefs)"),
                         source.count("refuse_folder_links(kept)\n" + " " * 12 + "shutil.copytree(kept, exefs)") +
                         source.count("refuse_folder_links(kept)\n" + " " * 8 + "shutil.copytree(kept, exefs)"))
        self.assertIn("refuse_folder_links(romfs)", source.split("link_or_copy(a.romfs, romfs)")[0][-300:])

    def test_onedrive_files_in_a_game_folder_are_files(self):
        # (Windows' answers, made up here: a OneDrive file is a reparse point but not a link; a symbolic link is both)
        import stat as st
        from types import SimpleNamespace
        from unittest import mock
        folder = self.root / "onedrive"
        (folder / "sub").mkdir(parents=True)
        (folder / "sub" / "a.zs").write_bytes(ZSTD)
        real = os.lstat

        def tagged(tag):
            def lstat(path, *a, **k):
                if str(path).endswith("a.zs"):
                    return SimpleNamespace(st_mode=st.S_IFREG | 0o644, st_file_attributes=0x400, st_reparse_tag=tag)
                return real(path, *a, **k)
            return lstat
        quiet = contextlib.redirect_stdout(io.StringIO())
        with mock.patch.object(make_game.os, "lstat", tagged(0x9000001A)), quiet:   # (IO_REPARSE_TAG_CLOUD_6)
            make_game.refuse_folder_links(str(folder))
            with self.assertRaises(SystemExit):   # (a dump folder: any reparse point, as before)
                make_game.refuse_dump_links(str(folder))
        for tag in (0xA000000C, 0xA0000003):   # (a symbolic link, a junction)
            with mock.patch.object(make_game.os, "lstat", tagged(tag)), quiet, self.assertRaises(SystemExit):
                make_game.refuse_folder_links(str(folder))

    def test_onedrive_files_keep_the_known_damaged_list(self):
        """(a game folder OneDrive keeps: the extraction's list of damaged textures is still taken, not every file opened)"""
        import stat as st
        from types import SimpleNamespace
        from unittest import mock
        import nup
        real = os.lstat

        def tagged(tag):
            def lstat(path, *a, **k):
                if str(path).endswith("a_Alb.bntx.zs"):
                    return SimpleNamespace(st_mode=st.S_IFREG | 0o644, st_file_attributes=0x400, st_reparse_tag=tag,
                                           st_nlink=1)
                return real(path, *a, **k)
            return lstat
        for tag, fast in ((0x9000001A, True), (0xA000000C, False)):   # (OneDrive's; a symbolic link's)
            with self.subTest(tag=hex(tag)):
                (self.out / ".hookshot_romfs_checked").unlink(missing_ok=True)
                self.heads("Model/a_Alb.bntx.zs")
                calls = []
                with mock.patch.object(nup.os, "lstat", tagged(tag)), \
                        mock.patch.object(nup, "stand_in_damaged", lambda romfs, progress=None, damaged=None:
                                          calls.append(damaged) or []):
                    self.stand_in()
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0] is not None, fast, "the known list was %s" % ("dropped" if fast else "taken"))

    def test_links_at_the_names_the_builder_writes_stop_it(self):
        game = self.root / "built"
        (game / "bin").mkdir(parents=True)
        victim = self.root / "victim.txt"
        victim.write_bytes(b"victim")
        quiet = contextlib.redirect_stdout(io.StringIO())
        with quiet:
            make_game.refuse_written_links(str(game))   # (a folder with none: as it is)
            os.symlink(self.outside, game / "hookshot_programs.bin")   # (a cache the builder does not write: left as it is)
            make_game.refuse_written_links(str(game))
        for rel in ("language.txt", "hookshot_version.txt", "bin", "prompts", make_game.BESIDE[0] + ".new",
                    "bin/" + make_game.BESIDE[0], "bin/" + make_game.BESIDE[1] + ".new", "image.bin.new"):
            with self.subTest(rel=rel):
                link = game / rel
                if rel == "bin":
                    os.rename(game / "bin", self.root / "bin-real")
                os.symlink(victim, link)
                try:
                    with quiet, self.assertRaises(SystemExit):
                        make_game.refuse_written_links(str(game))
                finally:
                    link.unlink()
                    if rel == "bin":
                        os.rename(self.root / "bin-real", game / "bin")
        self.assertEqual(victim.read_bytes(), b"victim")
        # (WSL's links: a tag islink does not see)
        import stat as st
        from types import SimpleNamespace
        from unittest import mock
        (game / "language.txt").write_text("en", encoding="utf-8")
        real = os.lstat

        def wsl(path, *a, **k):
            if str(path).endswith("language.txt"):
                return SimpleNamespace(st_mode=st.S_IFREG | 0o644, st_file_attributes=0x400, st_reparse_tag=0xA000001D)
            return real(path, *a, **k)
        with mock.patch.object(make_game.os, "lstat", wsl), quiet, self.assertRaises(SystemExit):
            make_game.refuse_written_links(str(game))
        (game / "language.txt").unlink()
        source = (ROOT / "nx2" / "make_game.py").read_text(encoding="utf-8")
        # (every name this file joins to the game folder is on the list, so a new one is checked too)
        import re
        joined = set(re.findall(r'os\.path\.join\((?:out|game_dir), "([^"]+)"', source)) | {make_game.HEADS}
        self.assertEqual(sorted(joined - set(make_game.FOLDER_WRITES) - set(make_game.BESIDE)), [])
        main = source[source.index("def main(a=None):"):]
        self.assertLess(main.index("refuse_written_links(out)"), main.index("check_writable(out)"))
        self.assertIn('if os.path.lexists(dst + ".new"):', main)


if __name__ == "__main__":
    unittest.main()
