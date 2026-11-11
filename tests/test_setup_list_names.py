"""The Python builder reads the setup list by builder/setup/setup.c's rules, refusing a bad list before any folder is removed

python -I -B tests/test_setup_list_names.py
"""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "builder" / "py"))
from hookshot_builder import setup_parts  # noqa: E402

SHA = "0123456789abcdef" * 4


OURS = "https://github.com/NotRexed/Hookshot/releases/download/builder-parts/y.zip"


def read(tag="v2", sha=SHA, dest="HookshotBuilder/tools", size="100", url=OURS):
    text = "tag %s\npart %s %s %s - llvm-mingw %s\nrun a.exe\n" % (tag, sha, size, dest, url)
    with mock.patch.object(setup_parts.Http, "get", lambda self, url, **kw: text.encode()):
        return setup_parts.read_manifest(lambda s: None)


class SetupListNamesTests(unittest.TestCase):
    def test_a_list_with_a_name_outside_the_install_folder_or_a_bad_checksum_or_size_is_refused(self):
        self.assertEqual(read()[0], "v2")
        for bad in ({"tag": ".."}, {"tag": "C:\\Users"}, {"tag": "/tmp"}, {"dest": "a/../.."}, {"sha": SHA.upper()},
                    {"size": "1e3"}):
            with self.subTest(**bad), self.assertRaises(setup_parts.SetupError):
                read(**bad)

    def test_a_part_comes_only_from_this_projects_releases_or_llvm_mingws(self):
        with mock.patch.dict(os.environ, {"HOOKSHOT_SETUP_LIST": ""}):
            for good in (OURS, "https://github.com/mstorsjo/llvm-mingw/releases/download/20261104/llvm-mingw.zip"):
                with self.subTest(good=good):
                    self.assertEqual(read(url=good)[0], "v2")
            for bad in ("https://x/y.zip", "https://github.com/someone/Hookshot/releases/download/v2/y.zip",
                        "https://github.com/NotRexed/Hookshot/releases/download/../../../someone/x/y.zip",
                        "https://github.com/NotRexed/Hookshot/releases/download/v2/%2e%2e/y.zip",
                        "https://github.com/NotRexed/Hookshot/releases/download/v2/y.zip?x=@evil",
                        "https://github.com/NotRexed/Hookshot/releases/download/", "http://github.com/NotRexed/Hookshot/"
                        "releases/download/v2/y.zip"):
                with self.subTest(bad=bad), self.assertRaises(setup_parts.SetupError):
                    read(url=bad)
        # (a list for testing a release elsewhere: its parts may be on any https link, as before)
        with mock.patch.dict(os.environ, {"HOOKSHOT_SETUP_LIST": "https://example.org/list.txt"}):
            self.assertEqual(read(url="https://x/y.zip")[0], "v2")

    def test_setup_c_takes_the_same_links(self):
        import re
        import shutil
        import subprocess
        cc = shutil.which("gcc") or shutil.which("cc")
        if not cc:
            self.skipTest("no C compiler")
        src = (Path(__file__).resolve().parents[1] / "builder" / "setup" / "setup.c").read_text(encoding="utf-8")
        m = re.search(r"static int part_url_ok\(const char \*u\) \{.*?\n\}\n", src, re.S)
        self.assertTrue(m, "setup.c has no part_url_ok")
        urls = [OURS, "https://github.com/mstorsjo/llvm-mingw/releases/download/a/b.zip", "https://x/y.zip",
                "https://github.com/NotRexed/Hookshot/releases/download/../../../someone/x/y.zip",
                "https://github.com/NotRexed/Hookshot/releases/download/v2/%2e%2e/y.zip",
                "https://github.com/NotRexed/Hookshot/releases/download/"]
        want = "110000"
        with tempfile.TemporaryDirectory() as tmp:
            c = Path(tmp, "f.c")
            c.write_text("#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n#include <strings.h>\n"
                         "#define _strnicmp strncasecmp\n" + m.group(0) +
                         "int main(int argc, char **argv) { for (int i = 1; i < argc; i++) putchar('0' + part_url_ok(argv[i])); "
                         "return 0; }\n", encoding="utf-8")
            exe = Path(tmp, "f.exe" if os.name == "nt" else "f")
            subprocess.run([cc, "-std=gnu11", "-Wall", str(c), "-o", str(exe)], check=True)
            env = {k: v for k, v in os.environ.items() if k != "HOOKSHOT_SETUP_LIST"}
            got = subprocess.run([str(exe)] + urls, capture_output=True, text=True, env=env, check=True).stdout
        self.assertEqual(got, want)

    def test_a_part_is_reused_only_for_its_exact_checksum(self):
        with tempfile.TemporaryDirectory() as base, mock.patch.dict(os.environ, {"HOOKSHOT_SETUP_BASE": base}):
            v = Path(base, "versions")
            (v / "v1" / "tools" / "llvm-mingw").mkdir(parents=True)
            (v / "current.txt").write_text("v1")
            p = setup_parts.Part(SHA, 100, "tools", "-", "llvm-mingw", "https://x/y.zip")
            for listed, want in (("f" + SHA, False), (SHA, True)):
                (v / "v1" / "parts.txt").write_text(listed + "\n")
                self.assertEqual(setup_parts.reuse_part("v2", p, str(v / "v2.part")), want)


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=1))