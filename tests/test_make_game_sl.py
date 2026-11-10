"""nx2/make_game.py and NVIDIA DLSS Frame Generation: Streamline's runtime placed beside hookshot.exe (bin\\ with the
launcher, else the folder), taken out again when the folder is built without it, and --fetch-sl-sdk, which needs NVIDIA's
licenses accepted. No network, no game.

Run with: python -I tests/test_make_game_sl.py
"""
import importlib.util
import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("make_game_sl_under_test", ROOT / "nx2" / "make_game.py")
make_game = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_game)


class SlRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hookshot-make-game-sl-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sdk = self.root / "sdk"
        self.game = self.root / "game" / "bin"
        self.game.mkdir(parents=True)
        self.sl = make_game.sl_script()

    def sdk_files(self, runtime=True):
        (self.sdk / "include").mkdir(parents=True, exist_ok=True)
        (self.sdk / "include" / "sl.h").write_bytes(b"header")
        if runtime:
            for f in self.sl.runtime(str(self.sdk)):
                Path(f).parent.mkdir(parents=True, exist_ok=True)
                Path(f).write_bytes(os.path.basename(f).encode())

    def place(self, sdk=None, linux=False):
        env = {"HOOKSHOT_SL_SDK": str(self.sdk) if sdk is None else sdk}
        with mock.patch.object(make_game, "LINUX", linux), mock.patch.dict(os.environ, env), \
                mock.patch("sys.stdout", io.StringIO()):
            return make_game.place_sl_runtime(str(self.game))

    def test_runtime_goes_beside_the_exe(self):
        self.sdk_files()
        placed = self.place()
        self.assertEqual(sorted(Path(p).name for p in placed), sorted(self.sl.runtime_names()))
        self.assertEqual((self.game / "sl.interposer.dll").read_bytes(), b"sl.interposer.dll")
        self.assertEqual(sorted(p.name for p in self.game.iterdir()), sorted(self.sl.runtime_names()))
        self.assertEqual([p.name for p in self.game.parent.iterdir()], ["bin"])   # (nothing else in the game folder)

    def test_rebuilding_without_it_removes_the_runtime(self):
        self.sdk_files()
        self.place()
        (self.game / "hookshot.exe").write_bytes(b"exe")
        self.assertEqual(self.place(sdk=""), [])
        self.assertEqual([p.name for p in self.game.iterdir()], ["hookshot.exe"])

    def test_nothing_without_the_sdk_or_its_runtime(self):
        self.assertEqual(self.place(sdk=""), [])
        self.sdk_files(runtime=False)
        self.assertEqual(self.place(), [])
        self.assertEqual(list(self.game.iterdir()), [])

    def test_nothing_for_the_linux_game(self):
        self.sdk_files()
        self.assertEqual(self.place(linux=True), [])
        self.assertEqual(list(self.game.iterdir()), [])


class FetchGateTests(unittest.TestCase):
    def fetch(self, accept, sdk="sdk", linux=False):
        calls = []
        sl = SimpleNamespace(NOTICE="notice", fetch=lambda *a, **k: calls.append(a))
        with mock.patch.object(make_game, "sl_script", return_value=sl), mock.patch.object(make_game, "LINUX", linux), \
                mock.patch.dict(os.environ, {"HOOKSHOT_SL_SDK": sdk}), mock.patch("sys.stdout", io.StringIO()) as out:
            try:
                make_game.fetch_sl_sdk(SimpleNamespace(accept_nvidia_license=accept))
            except SystemExit as e:
                return calls, e.code, out.getvalue()
        return calls, 0, out.getvalue()

    def test_needs_the_licenses_accepted(self):
        calls, code, out = self.fetch(False)
        self.assertEqual((calls, code), ([], 1))
        self.assertIn("@@error", out)
        self.assertIn("licenses", out)

    def test_needs_the_sdk_folder_and_the_windows_game(self):
        self.assertEqual(self.fetch(True, sdk="")[:2], ([], 1))
        self.assertEqual(self.fetch(True, linux=True)[:2], ([], 1))

    def test_fetches_after_the_notice(self):
        calls, code, out = self.fetch(True)
        self.assertEqual((calls, code), ([("sdk",)], 0))
        self.assertTrue(out.startswith("notice"))

    def test_flags_are_off_by_default(self):
        with mock.patch("sys.argv", ["make_game.py", "--out", "x", "--nup", "y"]):
            a = make_game.parse_args()
        self.assertFalse(a.fetch_sl_sdk)
        self.assertFalse(a.accept_nvidia_license)


if __name__ == "__main__":
    unittest.main()
