"""The packages the shipped Python installs from PyPI are checked against requirements-lock.txt's SHA-256s.

scripts/linux/deps.sh (the AppImage's Python) and scripts/release_parts.py package --python-packages (the Windows
builder's Python part) install the pinned wheels with pip --require-hashes from requirements-lock.txt, which
scripts/python_lock.py writes from requirements.txt's pins. Checked here without the network: the lock has every pin at
its version with a hash, both installers use it, and a pin the lock lacks stops the Windows packaging.

python -I -B tests/test_python_lock.py
"""
import importlib.util
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PythonLock(unittest.TestCase):
    def setUp(self):
        self.lock = load("python_lock", "scripts/python_lock.py")

    def test_lock_has_every_pin_with_a_hash(self):
        self.assertEqual(self.lock.check(), [])
        pins = self.lock.pins()
        self.assertGreaterEqual(len(pins), 10)
        names = {self.lock.norm(n) for n, _ in pins}
        self.assertIn("archspec", names)   # (nx2/prompt_requirements.txt's, through requirements.txt's -r)

    def test_check_finds_a_stale_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            req, lock = Path(tmp) / "r.txt", Path(tmp) / "l.txt"
            req.write_text("lz4==4.4.5\nnumpy==2.5.4\npillow==13.0.0\n", encoding="utf-8")
            lock.write_text("lz4==4.4.5 \\\n    --hash=sha256:%s\nnumpy==2.5.3 --hash=sha256:%s\n" % ("a" * 64, "b" * 64),
                            encoding="utf-8")
            bad = self.lock.check(str(req), str(lock))
            self.assertEqual(len(bad), 2, bad)
            lock.write_text("lz4==4.4.5 --hash=sha256:short\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                self.lock.read_lock(str(lock))

    def test_deps_sh_installs_with_hashes(self):
        text = (ROOT / "scripts/linux/deps.sh").read_text(encoding="utf-8")
        installs = re.findall(r"pip install((?:[^\n]*\\\n)*[^\n]*)", text)
        self.assertTrue(installs)
        for args in installs:
            self.assertIn("--require-hashes", args)
            self.assertIn("-r requirements-lock.txt", args)
        # (a new lock installs again, in CI too)
        self.assertRegex(text, r"PY_MARK=.*requirements-lock\.txt")
        workflow = (ROOT / ".github/workflows/linux-appimage.yml").read_text(encoding="utf-8")
        self.assertRegex(workflow, r"linux-deps-built-\$\{\{ hashFiles\([^)]*'requirements-lock\.txt'")

    def test_windows_packaging_takes_only_locked_pins(self):
        parts = load("release_parts", "scripts/release_parts.py")
        text = parts.locked(["archspec==0.2.7"])
        self.assertRegex(text, r"^archspec==0\.2\.7( --hash=sha256:[0-9a-f]{64})+\n$")
        with self.assertRaises(SystemExit):
            parts.locked(["archspec==0.2.6"])
        with self.assertRaises(SystemExit):
            parts.locked(["notapackage==1.0"])
        source = (ROOT / "scripts/release_parts.py").read_text(encoding="utf-8")
        for call in re.findall(r'"pip", "install".*?check=True\)', source, re.S):
            self.assertIn('"--require-hashes"', call)


if __name__ == "__main__":
    unittest.main()
