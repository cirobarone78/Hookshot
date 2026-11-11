"""scripts/linux/deps.sh: every download goes through its CURL array (https only) and its SHA-256-checked fetch, the
license texts the AppImage ships included (they were four bare curl calls, neither https-only nor checked). Runs the
script's own fetch over its license lines with a stand-in curl that serves a fixed text, so nothing is downloaded: a
text other than the pinned one stops the script.

    python -I -B tests/test_deps_downloads.py
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RUN_ALL_SKIP = {"windows": "scripts/linux/deps.sh is bash: checked on Linux"}

ROOT = Path(__file__).resolve().parents[1]
DEPS = ROOT / "scripts/linux/deps.sh"


def code_lines(text):
    """the script's lines without comments (a # that starts a line or follows a space)"""
    return [re.sub(r"(^|\s)#.*$", "", line) for line in text.splitlines()]


class DepsDownloads(unittest.TestCase):
    def test_no_curl_but_the_checked_one(self):
        lines = code_lines(DEPS.read_text(encoding="utf-8"))
        bare = [(i + 1, l.strip()) for i, l in enumerate(lines) if re.search(r"(^|[\s;|&(])curl\s", l)
                and not l.strip().startswith("CURL=(curl ")]
        self.assertEqual(bare, [], "curl outside CURL=(...): use fetch (with a SHA-256) or \"${CURL[@]}\"")
        self.assertIn("--proto '=https'", next(l for l in lines if l.strip().startswith("CURL=(curl ")))

    def test_license_fetches_are_hashed(self):
        text = DEPS.read_text(encoding="utf-8")
        start = text.index("# ---- the licenses of what the AppImage carries")
        block = text[start:text.index("\nfi\n", start)]
        fetches = re.findall(r'^\s*fetch "([^"]+)" "([^"]+)" "\$(\w+_SHA256)"$', block, re.M)
        self.assertEqual(len(fetches), 4, block)
        self.assertEqual(block.count("fetch "), 4)
        for _, _, name in fetches:
            self.assertRegex(text, r"(?m)^%s=[0-9a-f]{64}$" % name)

    @unittest.skipUnless(sys.platform.startswith("linux"), "bash")
    def test_a_changed_license_text_stops_the_script(self):
        text = DEPS.read_text(encoding="utf-8")
        helpers = text[text.index("CURL=(curl "):text.index("done_for() {")]
        start = text.index("# ---- the licenses of what the AppImage carries")
        block = text[start:text.index("\nfi\n", start)]
        fetches = "\n".join(re.findall(r'^\s*(fetch "[^"]+" "[^"]+" "\$\w+_SHA256")$', block, re.M))
        versions = "\n".join(re.findall(r"^(?:LLVM_VER|FFMPEG_VER|DAV1D_VER|\w+_(?:LICENSE|LGPL|COPYING)_SHA256)=\S+$", text, re.M))
        with tempfile.TemporaryDirectory(prefix="hookshot-deps-") as tmp:
            t = Path(tmp)
            (t / "bin").mkdir()
            (t / "dl").mkdir()
            # (a stand-in curl: writes "served" to -o's file and records the arguments)
            (t / "bin/curl").write_text('#!/bin/sh\necho "$@" >> "$LOG"\nwhile [ $# -gt 0 ]; do [ "$1" = -o ] && '
                                        'printf served > "$2"; shift; done\n', encoding="utf-8")
            os.chmod(t / "bin/curl", 0o755)
            env = dict(os.environ, PATH="%s:%s" % (t / "bin", os.environ["PATH"]), DL=str(t / "dl"), LOG=str(t / "log"))
            run = subprocess.run(["bash", "-eu", "-c", "%s\n%s\n%s\n" % (versions, helpers, fetches)], env=env,
                                 capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("SHA-256 differs", run.stdout + run.stderr)
            self.assertEqual(os.listdir(t / "dl"), [])   # (the wrong text is not kept)
            self.assertIn("--proto =https", (t / "log").read_text())


if __name__ == "__main__":
    unittest.main()
