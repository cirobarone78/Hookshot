"""The update tracks (release, release candidate, nightly): which track a version is on and the version order, the same in
the game's update check (host/hos_update.c, compiled here from its own text), the setup (builder/setup/setup.c) and the
Linux updater (builder/linux/linux_update.py). Updater.cs has the same rules and is checked by the Windows CI build."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "builder" / "linux"))
import linux_update  # noqa: E402

CC = "gcc"

# (version, track)
TRACKS = [
    ("v2.0.7", "release"), ("v2.1.0", "release"),
    ("v2.1.0-rc.1", "rc"), ("v2.1.0-rc.12", "rc"),
    ("v2.1.0-rc.1-3-g1a2b3c4", "nightly"), ("v2.1.0-rc.1-0-g1a2b3c4", "nightly"), ("v2.0.14-12-gabcdef01", "nightly"),
    ("v2.0.5-3-g1a2b3c4-dirty", "nightly"),
]
# newer, older (semver: a release candidate before its release, rc.N by number)
ORDER = [
    ("v2.1.0-rc.2", "v2.1.0-rc.1"), ("v2.1.0-rc.10", "v2.1.0-rc.9"), ("v2.1.0", "v2.1.0-rc.2"), ("v2.1.0-rc.1", "v2.0.14"),
    ("v2.0.10", "v2.0.9"), ("v3.0.0-rc.1", "v2.9.9"),
]

# (the rolling releases, nightly and rc, and the parts releases are not versions: every track's list leaves them out)
LIST = """[{"tag_name":"nightly","draft":false},{"tag_name":"rc","draft":false,"prerelease":true},
{"tag_name":"v2.1.0-rc.2","draft":false},{"tag_name":"linux-parts"},
{"tag_name":"v2.1.0-rc.10","draft":false},{"tag_name":"v2.0.14","draft":false},{"tag_name":"v2.1.0-rc.9"}]"""

FIXTURE = r"""
#include <stdio.h>
/* PORTABLE */
/* SETUP */
int main(int argc, char **argv) {
    if (argc == 3 && argv[1][0] == 'n') return printf("%d %d\n", nightly_version(argv[2]), nightly_tag(argv[2])), 0;
    if (argc == 4 && argv[1][0] == 'o') return printf("%d\n", newer_version(argv[2], argv[3])), 0;
    if (argc == 3 && argv[1][0] == 'l') {
        char tag[128] = "";
        FILE *f = fopen(argv[2], "rb");
        static char body[1 << 16];
        body[fread(body, 1, sizeof body - 1, f)] = 0;
        fclose(f);
        return printf("%s\n", newest_tag(body, tag, sizeof tag) ? tag : "-"), 0;
    }
    if (argc == 4 && argv[1][0] == 'e') {   /* e <NAME=VALUE> <names, comma-separated>: set by hookshot_env.txt? */
        static char names[256];
        snprintf(names, sizeof names - 1, "%s", argv[3]);
        for (char *c = names; *c; c++) if (*c == ',') *c = 0;
        return printf("%d\n", set_by_env_file(argv[2], names)), 0;
    }
    if (argc == 5 && argv[1][0] == 'b')   /* b <exe> <args or -> <w|l> */
        return printf("%d\n", builder_ok(argv[2], strcmp(argv[3], "-") ? argv[3] : NULL, argv[4][0] == 'w')), 0;
    return 2;
}
"""

# builder= / builder_args= as the builders write them (nx2/make_game.py from HOOKSHOT_BUILDER_EXE / _ARGS): the game
# starts the builder they name, so other shapes are taken as no builder (the download page)
PY_ARGS = r'-I "C:\Users\Ana Paula\Hookshot Builder\app\hookshot_builder_start.py"'
BUILDERS_OK = [
    (r"C:\Users\ana\Downloads\HookshotBuilder\HookshotBuilder.exe", "-", "w"),   # (Runner.cs: Environment.ProcessPath)
    (r"D:/Games/HookshotBuilder.exe", "", "w"),
    (r"C:\Users\Ana Paula\Hookshot Builder\python\pythonw.exe", PY_ARGS, "w"),   # (core.py: list2cmdline)
    (r"C:\HB\python\python.exe", r"-I C:\HB\app\hookshot_builder_start.py", "w"),
    ("/home/ana/Applications/Hookshot-x86_64.AppImage", "-", "l"),   # (builder/linux/AppRun: $APPIMAGE)
    ("/home/ana/Hookshot/squashfs-root/AppRun", "-", "l"),            # (unpacked: $HERE/AppRun)
]
BUILDERS_BAD = [
    (r"C:\Users\ana\Downloads\evil.bat", "-", "w"),
    (r"C:\Users\ana\Downloads\HookshotBuilder.exe.lnk", "-", "w"),
    (r"C:\Users\ana\Downloads\notHookshotBuilder.exe", "-", "w"),
    (r"HookshotBuilder.exe", "-", "w"),                                     # (relative: the working folder's)
    (r"..\HookshotBuilder.exe", "-", "w"),
    (r"\\server\share\HookshotBuilder.exe", "-", "w"),                  # (a network path)
    (r"C:\a\..\b\HookshotBuilder.exe", "-", "w"),
    (r"C:\a\HookshotBuilder.exe", "--update x", "w"),                     # (the exe takes no builder_args)
    (r"C:\HB\python\pythonw.exe", "-", "w"),                             # (python with no start script)
    (r"C:\HB\python\pythonw.exe", r'-I "C:\HB\app\hookshot_builder_start.py', "w"),   # (unbalanced quote)
    (r"C:\HB\python\pythonw.exe", r'-I "C:\HB\app\x.py" --update "C:\Windows" --tag "a"', "w"),
    (r"C:\HB\python\pythonw.exe", r"-I C:\HB\app\hookshot_builder_start.py --fetched x", "w"),
    (r"C:\HB\python\pythonw.exe", r"-c import os", "w"),
    (r"C:\HB\python\pythonw.exe", r"-I app\hookshot_builder_start.py", "w"),   # (relative script)
    (r"C:\HB\python\pythonw.exe", r"-I C:\HB\app\evil_hookshot_builder_start.py", "w"),
    ("/usr/bin/sh", "-", "l"),
    ("/tmp/x/hookshot", "-", "l"),
    ("AppRun", "-", "l"),                                                   # (relative)
    ("./Hookshot.AppImage", "-", "l"),
    ("/home/ana/../tmp/Hookshot.AppImage", "-", "l"),
    ("/home/ana/.AppImage", "-", "l"),
    ("/home/ana/Hookshot.AppImage", "-I x", "l"),
]


def portable(source):
    start = source.index("#if defined(_WIN32) || defined(__linux__)")
    end = source.index("#endif", source.index("static int newest_tag("))
    return source[start:end].replace("#if defined(_WIN32) || defined(__linux__)", "", 1)


def setup_part(source):
    start = source.index("static int nightly_tag(")
    return source[start:source.index("\n}\n", start) + 3]


class Tracks(unittest.TestCase):
    exe = None

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="hookshot-tracks-")
        folder = Path(cls.tmp.name)
        code = FIXTURE.replace("/* PORTABLE */", "#include <ctype.h>\n#include <stdlib.h>\n#include <string.h>\n" +
                               portable((ROOT / "host/hos_update.c").read_text(encoding="utf-8")))
        code = code.replace("/* SETUP */", setup_part((ROOT / "builder/setup/setup.c").read_text(encoding="utf-8")))
        (folder / "t.c").write_text(code, encoding="utf-8")
        cls.exe = str(folder / "t")
        subprocess.run([CC, "-std=c11", "-Wall", "-Wextra", "-Werror", str(folder / "t.c"), "-o", cls.exe], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def c(self, *args):
        return subprocess.run([self.exe, *args], capture_output=True, text=True, check=True).stdout.split()

    def test_the_builder_is_started_without_what_the_env_file_set(self):
        # (hookshot_env.txt's names, as host/hos_main.c hos_env_file_names lists them: the builder an update starts
        # inherits the game's environment, and reads some of the same names for its build)
        names = "RX_MARCH,HOS_T,RX_VK_ONLY"
        for entry, want in (("RX_MARCH=native", "1"), ("HOS_T=", "1"), ("RX_VK_ONLY=1", "1"), ("PATH=/usr/bin", "0"),
                            ("RX_MARCHX=1", "0"), ("RX_MARC=1", "0"), ("HOS_TX=1", "0"), ("HOME=/home/ana", "0")):
            self.assertEqual(self.c("e", entry, names), [want], entry)
        self.assertEqual(self.c("e", "RX_MARCH=native", ""), ["0"])
        source = (ROOT / "host/hos_update.c").read_text(encoding="utf-8")
        linux = source[source.index("#elif defined(__linux__)"):]
        self.assertIn("if (!set_by_env_file(environ[i], names)) env[kept++] = environ[i];", linux)
        self.assertIn("execve(builder, args, env);", linux)
        self.assertNotIn("execl(builder", linux)
        windows = source[source.index("void hos_update_check(void) {"):source.index("#elif defined(__linux__)")]
        self.assertLess(windows.index("_putenv(gone);"), windows.index("ShellExecuteW(NULL, L\"open\", wbuilder"))

    def test_the_track_of_a_version(self):
        for version, track in TRACKS + [("nightly", "release"), ("rc", "release"), ("dev", "release")]:
            self.assertEqual(linux_update.track_of(version), track, version)
            nightly = "1" if track == "nightly" else "0"
            self.assertEqual(self.c("n", version), [nightly, nightly], version)

    def test_semver_order(self):
        for newer, older in ORDER:
            self.assertGreater(linux_update.release_key(newer), linux_update.release_key(older), (newer, older))
            self.assertEqual(self.c("o", newer, older), ["1"], (newer, older))
            self.assertEqual(self.c("o", older, newer), ["0"], (older, newer))
            self.assertEqual(self.c("o", newer, newer), ["0"])

    def test_the_newest_release_candidate_or_release(self):
        path = Path(self.tmp.name) / "list.json"
        path.write_text(LIST, encoding="utf-8")
        self.assertEqual(self.c("l", str(path)), ["v2.1.0-rc.10"])
        self.assertIsNone(linux_update.release_key("rc"))
        self.assertEqual(linux_update.newest_release(["rc", "nightly"]), None)
        get = lambda url: LIST.encode() if url == linux_update.RELEASES_API else b"{}"   # noqa: E731
        self.assertEqual(linux_update.latest_tag(get, "rc"), "v2.1.0-rc.10")
        # (its version's release ships: the release is the newest)
        released = LIST.replace("v2.0.14", "v2.1.0")
        path.write_text(released, encoding="utf-8")
        self.assertEqual(self.c("l", str(path)), ["v2.1.0"])
        self.assertEqual(linux_update.latest_tag(lambda url: released.encode(), "rc"), "v2.1.0")

    def test_each_track_asks_its_own_release(self):
        asked = []

        def get(url):
            asked.append(url)
            if url == linux_update.RELEASES_API:
                raise OSError("rate limited")
            if url == linux_update.LATEST_API:
                return b'{"tag_name": "v2.0.14"}'
            if url.endswith("/releases/download/nightly/hookshot-linux.txt"):
                return ("tag v2.1.0-rc.1-3-g1a2b3c4\npart %s 10 usr/share/hookshot https://github.com/NotRexed/Hookshot/releases/download/linux-parts/a.zip\nfile x\n"
                        % ("a" * 64)).encode()
            raise OSError(url)
        self.assertEqual(linux_update.latest_tag(get), "v2.0.14")
        self.assertEqual(asked, [linux_update.LATEST_API])   # (a release: as before, the latest release only)
        self.assertEqual(linux_update.latest_tag(get, "rc"), "v2.0.14")   # (no API answer: the latest release)
        self.assertEqual(linux_update.latest_tag(get, "nightly"), "v2.1.0-rc.1-3-g1a2b3c4")
        self.assertEqual(linux_update.list_url("v2.1.0-rc.1-3-g1a2b3c4"),
                         "https://github.com/NotRexed/Hookshot/releases/download/nightly/hookshot-linux.txt")
        self.assertEqual(linux_update.list_url("v2.1.0-rc.2"),
                         "https://github.com/NotRexed/Hookshot/releases/download/v2.1.0-rc.2/hookshot-linux.txt")
        self.assertEqual(linux_update.list_url(None), linux_update.LATEST_LIST)

    def test_what_each_track_updates_to(self):
        target = linux_update.update_target
        # a release candidate is never taken back to an older release, and is offered the next one and its release
        self.assertEqual(target("v2.0.14", "v2.1.0-rc.1"), "v2.1.0-rc.1")
        self.assertEqual(target("v2.1.0-rc.2", "v2.1.0-rc.1"), "v2.1.0-rc.2")
        self.assertEqual(target("v2.1.0", "v2.1.0-rc.2"), "v2.1.0")
        # a nightly takes the nightly's build whenever it is another one
        self.assertEqual(target("v2.1.0-rc.1-5-gbbbbbbb", "v2.1.0-rc.1-3-gaaaaaaa"), "v2.1.0-rc.1-5-gbbbbbbb")
        # a switch of track takes its newest, an older version too
        self.assertEqual(target("v2.0.14", "v2.1.0-rc.1", switch=True), "v2.0.14")
        self.assertEqual(target("v2.0.14", "v2.1.0-rc.1-3-gaaaaaaa", switch=True), "v2.0.14")
        self.assertEqual(linux_update.choose_mode(None, "v2.1.0-rc.1", "v2.0.14", False, False), "build")
        self.assertEqual(linux_update.choose_mode(None, "v2.1.0-rc.1", "v2.0.14", False, False, True), "update-builder")
        self.assertEqual(linux_update.choose_mode("v2.1.0-rc.1", "v2.1.0-rc.1", "v2.1.0-rc.2", False, True), "update-game")

    def test_the_builder_the_game_starts_has_a_builders_shape(self):
        for exe, args, os_ in BUILDERS_OK:
            self.assertEqual(self.c("b", exe, args, os_), ["1"], (exe, args))
        for exe, args, os_ in BUILDERS_BAD:
            self.assertEqual(self.c("b", exe, args, os_), ["0"], (exe, args))
        # (what the builders write passes: the Python builder's own arguments, from its own code)
        self.assertEqual(subprocess.list2cmdline(["-I", r"C:\Users\Ana Paula\Hookshot Builder\app\hookshot_builder_start.py"]),
                         PY_ARGS)
        source = (ROOT / "host/hos_update.c").read_text(encoding="utf-8")
        self.assertIn("builder_ok(builder, bargs, 1)", source)   # (Windows)
        self.assertIn("builder_ok(builder, NULL, 0)", source)    # (Linux)

    def test_every_builder_entry_takes_one_tag_rule(self):
        import re
        sys.path.insert(0, str(ROOT / "builder" / "py"))
        from hookshot_builder import setup_parts, updater
        cs = (ROOT / "builder/HookshotBuilder/Updater.cs").read_text(encoding="utf-8")
        # (anchored with \z: .NET's $ also matches before a last line break, so "v2\n" passed there; the C# fixture,
        # tests/updater_asset_digest_test.cs tag-rule, runs the rule itself)
        found = re.search(r'TagName = new\(@"\^(.*?)\\z"\)', cs)
        self.assertIsNotNone(found, "Updater.cs TagName must end in \\z")
        cs_rule = found.group(1)
        cs_ok = lambda t: re.fullmatch(cs_rule, t) is not None and t not in (".", "..")   # noqa: E731
        good = ["v2.1.0", "v2.1.0-rc.1", "v2.1.0-rc.1-3-g1a2b3c4", "nightly", "v2.0.5-3-g1a2b3c4-dirty"]
        bad = ["", ".", "..", "../v2", "v2/../..", "v2 --fetched", "v2\\x", "C:", "v2\n", "a" * 129, "%2e%2e", "v2?x", "v2#x"]
        for t in good:
            self.assertTrue(linux_update.tag_ok(t) and setup_parts.list_name_ok(t) and cs_ok(t), t)
        for t in bad:
            self.assertFalse(linux_update.tag_ok(t), t)
            self.assertFalse(setup_parts.list_name_ok(t) and len(t) <= 128, t)
            self.assertFalse(cs_ok(t), t)
        # (Updater.cs: --tag at the start of an update, and the tags it reads from GitHub)
        self.assertIn("if (tag != null && !TagOk(tag))", cs)
        self.assertNotIn("return line[4..].Trim();", cs)
        self.assertEqual(cs.count("return ListTag(line);"), 2)
        self.assertIn('GetProperty("tag_name").GetString() is { } latest && TagOk(latest)', cs)
        # (the Python builder refuses a bad --tag before anything is downloaded)
        said = []

        class Ui:
            def begin_update(self, folder, tag):
                pass

            def download_failed(self, text):
                said.append(text)
        with mock.patch.object(updater.Tools, "find", side_effect=AssertionError("went on")):
            updater.update_folder(Ui(), "/x", "../../x", False)
        self.assertEqual(len(said), 1)
        builder = (ROOT / "builder/linux/hookshot_builder.py").read_text(encoding="utf-8")
        self.assertIn("if tag is not None and not linux_update.tag_ok(tag):", builder)

    def test_the_game_offers_a_release_candidate_only_a_newer_one(self):
        source = (ROOT / "host/hos_update.c").read_text(encoding="utf-8")
        guard = "if (strchr(have, '-') && !nightly_version(have) && !newer_version(tag, have)) return;"
        self.assertEqual(source.count(guard), 2)   # (Windows and Linux)
        self.assertEqual(source.count("if (!latest_tag(have, tag, sizeof tag)) {"), 2)


if __name__ == "__main__":
    if "--cc" in sys.argv:
        i = sys.argv.index("--cc")
        CC = sys.argv[i + 1]
        del sys.argv[i:i + 2]
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    unittest.main()
