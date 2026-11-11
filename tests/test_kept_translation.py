"""A player's update with the same tools skips the lift: the clean-up keeps the lift's small files and the lifted files' object keys.

make_game.py deletes the lifted C (1.5 GB) after a player's build, so every update translated the game again (1-4 minutes) even when
nothing the lift reads had changed. Now keep_translation keeps the rest of the lift and nx2/build.py's list of the lifted files'
object keys (gen/lifted_objects.txt); kept_before says the next build may skip the lift; build.py then links those objects from the
cache by their keys, or stops with KEPT_STALE (before compiling anything) when an object is gone or the flags or headers changed.

python -I -B tests/test_kept_translation.py
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
spec = importlib.util.spec_from_file_location("make_game_under_test", ROOT / "nx2" / "make_game.py")
make_game = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_game)


def lifted_work(d, key="k1"):
    """a work folder as a finished lift and build leave it"""
    work = Path(d)
    gen, image, obj = work / "sa" / "gen", work / "sa" / "image", work / "sa" / "build" / "obj"
    for p in (gen, image, obj, work / "objcache"):
        p.mkdir(parents=True)
    (gen / "code_000.c").write_text("void f(void) {\n}\n", newline="\n")
    (gen / "code_hot_0.c").write_text("void g(void) {\n}\n", newline="\n")
    (gen / "a64_table.c").write_text("int t;\n", newline="\n")
    (gen / "a64_guest.h").write_text("#define X 1\n", newline="\n")
    (image / "image.bin").write_bytes(b"\0" * 16)
    (obj / "code_000.o").write_bytes(b"o")
    make_game.write_lift_key(str(work), key)
    # (build.py writes its list after the lift: the lift is still the one its key names)
    (gen / make_game.KEPT_LIST).write_text("code_000.c %s 17 p\ncode_hot_0.c %s 17 q\n" % ("a" * 40, "b" * 40), newline="\n")
    return work


class KeptTranslationTests(unittest.TestCase):
    def test_kept_after_a_build_and_skips_the_next_lift(self):
        with tempfile.TemporaryDirectory() as d:
            work = lifted_work(d)
            self.assertTrue(make_game.lifted_before(str(work), "k1"))
            kept = make_game.keep_translation(str(work), "k1")
            self.assertIsNotNone(kept)
            gen = work / "sa" / "gen"
            self.assertEqual(sorted(p.name for p in gen.glob("code_*")), [])
            self.assertFalse((work / "sa" / "build").exists())
            self.assertTrue((gen / "a64_table.c").exists() and (gen / "a64_guest.h").exists())
            self.assertTrue((work / "sa" / "image" / "image.bin").exists())
            self.assertFalse(make_game.lifted_before(str(work), "k1"))   # (the C is gone: not a full lift)
            self.assertTrue(make_game.kept_before(str(work), "k1"))
            self.assertFalse(make_game.kept_before(str(work), "k2"))   # (other tools: translated again)
            self.assertFalse(make_game.lifted_cut_short(str(gen)))

    def test_a_second_kept_build_keeps_it_again(self):
        with tempfile.TemporaryDirectory() as d:
            work = lifted_work(d)
            make_game.keep_translation(str(work), "k1")
            (work / "sa" / "build" / "obj").mkdir(parents=True)
            (work / "sa" / "gen" / make_game.KEPT_LIST).write_text("code_000.c %s 17 p\n" % ("a" * 40), newline="\n")   # (build.py wrote it again)
            self.assertTrue(make_game.kept_before(str(work), "k1"))
            self.assertIsNotNone(make_game.keep_translation(str(work), "k1"))
            self.assertTrue(make_game.kept_before(str(work), "k1"))

    def test_not_kept_without_build_pys_list_or_with_another_key(self):
        with tempfile.TemporaryDirectory() as d:
            work = lifted_work(d)
            (work / "sa" / "gen" / make_game.KEPT_LIST).unlink()
            self.assertIsNone(make_game.keep_translation(str(work), "k1"))
        with tempfile.TemporaryDirectory() as d:
            work = lifted_work(d)
            self.assertIsNone(make_game.keep_translation(str(work), "other"))

    def test_lifted_c_back_in_the_folder_is_not_kept(self):
        """another builder's lift in the same folder: the kept mark no longer vouches for it"""
        with tempfile.TemporaryDirectory() as d:
            work = lifted_work(d)
            make_game.keep_translation(str(work), "k1")
            (work / "sa" / "gen" / "code_001.c").write_text("void h(void) {\n}\n", newline="\n")
            self.assertFalse(make_game.kept_before(str(work), "k1"))

    def test_build_py_reads_the_list_and_names_kept_objects_by_it(self):
        sys.path.insert(0, str(ROOT / "nx2"))
        spec = importlib.util.spec_from_file_location("build_under_test", ROOT / "nx2" / "build.py")
        build = importlib.util.module_from_spec(spec)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                spec.loader.exec_module(build)
        except SystemExit:
            self.skipTest("build.py needs its toolchain to import here")
        finally:
            sys.path.remove(str(ROOT / "nx2"))
        self.assertEqual(build.KEPT_STALE, make_game.KEPT_STALE)
        self.assertEqual(build.KEPT_LIST, make_game.KEPT_LIST)
        with tempfile.TemporaryDirectory() as d:
            gen = os.path.join(d, "gen")
            os.makedirs(gen)
            src = os.path.join(gen, "code_000.c")
            with open(src, "w", newline="\n") as f:   # (17 bytes on Windows too)
                f.write("void f(void) {\n}\n")
            fl, deps = ["-O1", "-I" + gen], b"header"
            key = build.object_key(src, fl, deps)
            build.PLANNED.clear()
            build.write_kept(gen, [("cc", src, os.path.join(d, "code_000.o"), fl, deps),
                                   ("cc", os.path.join(gen, "a64_table.c"), os.path.join(d, "t.o"), fl, deps)])
            kept = build.read_kept(os.path.join(gen, build.KEPT_LIST))
            self.assertEqual(kept, {src: (key, 17, build.kept_part(fl, deps))})
            os.remove(src)
            build.KEPT.clear()
            build.KEPT.update(kept)
            try:
                obj = os.path.join(d, "code_000.o")
                build.PLANNED[(src, obj)] = kept[src][0]   # (as main puts it, once the flags and headers are checked)
                self.assertEqual(build.plan_jobs([("cc", src, obj, fl, deps)])[1][(src, obj)], key)   # (the object as before)
                self.assertEqual(build.src_size(src), 17)
                self.assertNotEqual(build.kept_part(["-O2"], deps), kept[src][2])   # (other flags: KEPT_STALE in main)
            finally:
                build.KEPT.clear()
                build.PLANNED.clear()


if __name__ == "__main__":
    unittest.main()
