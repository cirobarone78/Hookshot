"""Post-extraction validation progress, with authored files and no package or native decoder."""
import builtins
from contextlib import redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


nup = load("scan_progress_nup", HERE / "nup.py")
make_game = load("scan_progress_builder", HERE / "make_game.py")
ZSTD = b"\x28\xb5\x2f\xfd"
BEGIN = "Checking unpacked game files..."
END = "Checked %d unpacked .zs headers."


class ScanProgress(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)
        self.romfs = self.out / "romfs"
        self.romfs.mkdir()
        self.good = self.out / ".hookshot_romfs"
        self.checked = self.out / ".hookshot_romfs_checked"
        self.good.write_text("authored unpack 1\n", encoding="utf-8")

    def write(self, name, data=ZSTD):
        path = self.romfs / name
        path.write_bytes(data)
        return path

    def run_scan(self, output=None):
        output = output if output is not None else io.StringIO()
        with patch.dict(sys.modules, {"nup": nup}), redirect_stdout(output):
            make_game.stand_in_damaged_files(str(self.out), str(self.romfs))
        return output.getvalue()

    def test_progress_before_completion_batches_and_throttles(self):
        # 769 four-byte files cross three real 256-check batches, with no sleeps or game bytes.
        for i in range(769):
            self.write("%04d.zs" % i)
        self.write("unrelated.txt", b"not checked")
        class Output(io.StringIO):
            flushed = ""

            def flush(self):
                self.flushed = self.getvalue()

        output, reads, before_read = Output(), [], {}
        real_open, real_walk = builtins.open, os.walk

        class Reader:
            def __init__(self, stream, path):
                self.stream, self.path = stream, path

            def __enter__(self):
                self.stream.__enter__()
                return self

            def __exit__(self, *args):
                return self.stream.__exit__(*args)

            def read(self, size):
                reads.append((self.path, size))
                return self.stream.read(size)

        def opened(path, mode="r", *args, **kwargs):
            stream = real_open(path, mode, *args, **kwargs)
            if str(path).endswith(".zs") and mode == "rb":
                before_read[len(reads) + 1] = output.flushed
                return Reader(stream, str(path))
            return stream

        with patch.object(nup, "open", opened, create=True), \
                patch.object(nup.os, "walk", wraps=real_walk) as walk, \
                patch.object(make_game.time, "monotonic", side_effect=[0, 2, 2.5, 4.1, 4.2]) as clock:
            self.run_scan(output)
        self.assertIn(BEGIN, before_read[1])
        self.assertIn("256 .zs headers checked", before_read[257])
        self.assertNotIn("512 .zs headers checked", output.getvalue())
        self.assertIn("768 .zs headers checked", before_read[769])
        self.assertNotIn(END % 769, before_read[769])
        self.assertIn(END % 769, output.flushed)
        self.assertNotIn("@@progress", output.getvalue())
        self.assertEqual(len(reads), 769)
        self.assertEqual(len({path for path, _ in reads}), 769)
        self.assertEqual({size for _, size in reads}, {4})
        walk.assert_called_once_with(str(self.romfs))
        self.assertEqual(clock.call_count, 5)  # start, three batches and the final partial batch
        self.assertEqual(self.checked.read_bytes(), self.good.read_bytes())

    def test_empty_scan_reports_zero(self):
        output = self.run_scan()
        self.assertIn(BEGIN, output)
        self.assertIn(END % 0, output)
        self.assertEqual(self.checked.read_bytes(), self.good.read_bytes())

    def test_changed_unpack_reports_again(self):
        self.write("valid.zs")
        output = self.run_scan()
        self.good.write_text("authored unpack 2\n", encoding="utf-8")
        output += self.run_scan()
        self.assertEqual(output.count(BEGIN), 2)
        self.assertEqual(output.count(END % 1), 2)
        self.assertEqual(self.checked.read_bytes(), self.good.read_bytes())

    def test_missing_stamp_is_silent(self):
        self.good.unlink()
        with patch.object(nup, "stand_in_damaged", side_effect=AssertionError("must not scan")), \
                patch.object(make_game.time, "monotonic", side_effect=AssertionError("must not time")):
            self.assertEqual(self.run_scan(), "")
        self.assertFalse(self.checked.exists())

    def test_matching_stamp_is_silent(self):
        self.checked.write_bytes(self.good.read_bytes())
        with patch.object(nup, "stand_in_damaged", side_effect=AssertionError("must not scan")), \
                patch.object(make_game.time, "monotonic", side_effect=AssertionError("must not time")):
            self.assertEqual(self.run_scan(), "")

    def test_default_scanner_result_unchanged(self):
        good = self.write("good.zs")
        bad = self.write("bad.zs", bytes(4))
        self.write("skippable.zs", b"\x5f\x2a\x4d\x18")
        self.write("ignored.txt", bytes(4))
        self.assertEqual(nup.damaged_game_files(str(self.romfs)), [str(bad)])
        self.assertEqual(good.read_bytes(), ZSTD)

    def test_damage_replacement_and_marker_unchanged(self):
        bad = self.write("Authored_A_Nrm.bntx.zs", bytes(8))
        good = self.write("Authored_B_Nrm.bntx.zs", ZSTD + b"authored")
        self.run_scan()
        self.assertEqual(bad.read_bytes(), good.read_bytes())
        self.assertFalse(Path(str(bad) + ".part").exists())
        self.assertEqual(self.checked.read_bytes(), self.good.read_bytes())

    def test_read_error_propagates_without_completion_or_marker(self):
        self.write("A.zs")
        bad = self.write("B.zs")
        output, error, real_open = io.StringIO(), OSError("authored read failure"), builtins.open

        def opened(path, *args, **kwargs):
            if str(path) == str(bad):
                raise error
            return real_open(path, *args, **kwargs)

        with patch.object(nup, "open", opened, create=True), self.assertRaises(OSError) as raised:
            self.run_scan(output)
        self.assertIs(raised.exception, error)
        self.assertNotIn("Checked ", output.getvalue())
        self.assertFalse(self.checked.exists())

    def test_copy_error_propagates_without_completion_or_marker(self):
        self.write("Authored_A_Nrm.bntx.zs", bytes(8))
        self.write("Authored_B_Nrm.bntx.zs", ZSTD)
        output, error = io.StringIO(), OSError("authored copy failure")
        with patch.object(nup.shutil, "copyfile", side_effect=error), self.assertRaises(OSError) as raised:
            self.run_scan(output)
        self.assertIs(raised.exception, error)
        self.assertNotIn("Checked ", output.getvalue())
        self.assertFalse(self.checked.exists())

    def test_marker_error_propagates_without_completion(self):
        self.write("valid.zs")
        output, error, real_open = io.StringIO(), OSError("authored marker failure"), builtins.open

        def opened(path, mode="r", *args, **kwargs):
            if str(path) == str(self.checked) and mode == "w":
                raise error
            return real_open(path, mode, *args, **kwargs)

        with patch.object(make_game, "open", opened, create=True), self.assertRaises(OSError) as raised:
            self.run_scan(output)
        self.assertIs(raised.exception, error)
        self.assertNotIn("Checked ", output.getvalue())
        self.assertFalse(self.checked.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
