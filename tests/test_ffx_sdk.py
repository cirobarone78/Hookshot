"""scripts/ffx_sdk.py: its file table, the SHA-256 checks, the retries and the copy into a game folder, without the network.

Run with: python -I tests/test_ffx_sdk.py
"""
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ffx_sdk_under_test", ROOT / "scripts" / "ffx_sdk.py")
ffx_sdk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ffx_sdk)


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Opener:
    """urlopen over a dict of path -> bytes; records what was asked for. fail: paths that raise OSError once each"""
    def __init__(self, contents, fail=()):
        self.contents, self.asked, self.fail = contents, [], set(fail)

    def __call__(self, url, timeout=None):
        if timeout != ffx_sdk.TIMEOUT:
            raise AssertionError("urlopen without the timeout (%r)" % (timeout,))
        path = url[len(ffx_sdk.BASE) + 1:]
        self.asked.append(path)
        if path in self.fail:
            self.fail.discard(path)
            raise OSError("connection reset")
        return io.BytesIO(self.contents[path])


def fake_table(data):
    """FILES with each file's SHA-256 that of data[path]"""
    return [(p, digest(data[p]), name) for p, _, name in ffx_sdk.FILES]


class TableTests(unittest.TestCase):
    def test_pinned_release(self):
        self.assertRegex(ffx_sdk.COMMIT, r"^[0-9a-f]{40}$")
        self.assertIn(ffx_sdk.COMMIT, ffx_sdk.BASE)

    def test_files(self):
        names = [name for _, _, name in ffx_sdk.FILES]
        self.assertEqual(names, ["amd_fidelityfx_loader_vk.dll", "amd_fidelityfx_upscaler_vk.dll", "LICENSE-AMD-FSR-SDK.md"])
        for path, sha, _ in ffx_sdk.FILES:
            self.assertTrue(path.startswith("Kits/FidelityFX/"), path)
            self.assertRegex(sha, r"^[0-9a-f]{64}$")


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.data = {p: ("file %s" % p).encode() for p, _, _ in ffx_sdk.FILES}

    def test_fetch_and_install(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ffx_sdk, "FILES", fake_table(self.data)):
            opener = Opener(self.data)
            said = []
            ffx_sdk.fetch(os.path.join(tmp, "sdk"), opener=opener, say=said.append)
            self.assertEqual(len(said), 3)
            self.assertTrue(ffx_sdk.complete(os.path.join(tmp, "sdk")))
            ffx_sdk.fetch(os.path.join(tmp, "sdk"), opener=opener, say=said.append)   # (there already: nothing asked)
            self.assertEqual(len(opener.asked), 3)
            game_ffx = ffx_sdk.install(os.path.join(tmp, "sdk"), os.path.join(tmp, "game", "ffx"))
            self.assertTrue(ffx_sdk.complete(game_ffx))

    def test_wrong_file_not_kept(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ffx_sdk, "FILES", fake_table(self.data)):
            bad = dict(self.data)
            first = ffx_sdk.FILES[0][0]
            bad[first] = b"something else"
            with self.assertRaises(ValueError):
                ffx_sdk.fetch(tmp, opener=Opener(bad), say=lambda _: None)
            self.assertFalse(os.path.exists(os.path.join(tmp, ffx_sdk.FILES[0][2])))
            self.assertFalse(os.path.exists(os.path.join(tmp, ffx_sdk.FILES[0][2] + ".part")))
            self.assertFalse(ffx_sdk.complete(tmp))

    def test_retry_after_a_reset(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ffx_sdk, "FILES", fake_table(self.data)):
            second = ffx_sdk.FILES[1][0]
            opener = Opener(self.data, fail=[second])
            ffx_sdk.fetch(tmp, opener=opener, say=lambda _: None)
            self.assertEqual(opener.asked.count(second), 2)
            self.assertTrue(ffx_sdk.complete(tmp))


if __name__ == "__main__":
    unittest.main()
