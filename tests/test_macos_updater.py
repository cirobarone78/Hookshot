"""Check release metadata and streamed integrity validation for the macOS builder updater."""
import hashlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "builder" / "linux"))
import macos_update


class MacOSUpdaterTests(unittest.TestCase):
    def setUp(self):
        self.destination = ROOT / (".macos-updater-%d.zip" % os.getpid())

    def tearDown(self):
        self.destination.unlink(missing_ok=True)

    def test_latest_release_returns_github_asset_integrity_metadata(self):
        data = b"zip contents"
        release = {
            "tag_name": "v1.2.3",
            "draft": False,
            "prerelease": False,
            "assets": [{
                "name": macos_update.ASSET,
                "browser_download_url": "https://github.com/NotRexed/Hookshot/releases/download/v1.2.3/app.zip",
                "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }],
        }
        with patch.object(macos_update, "_get", return_value=json.dumps(release).encode("utf-8")):
            self.assertEqual(macos_update.latest_release(), (
                "v1.2.3",
                release["assets"][0]["browser_download_url"],
                release["assets"][0]["digest"],
                len(data),
            ))

    def test_latest_release_keeps_compatibility_when_digest_is_omitted(self):
        release = {
            "tag_name": "v1.2.3",
            "draft": False,
            "prerelease": False,
            "assets": [{
                "name": macos_update.ASSET,
                "browser_download_url": "https://github.com/NotRexed/Hookshot/releases/download/v1.2.3/app.zip",
            }],
        }
        with patch.object(macos_update, "_get", return_value=json.dumps(release).encode("utf-8")):
            self.assertEqual(macos_update.latest_release()[2:], (None, None))

    def test_latest_release_rejects_malformed_digest(self):
        release = {
            "tag_name": "v1.2.3",
            "draft": False,
            "prerelease": False,
            "assets": [{
                "name": macos_update.ASSET,
                "browser_download_url": "https://github.com/NotRexed/Hookshot/releases/download/v1.2.3/app.zip",
                "digest": "md5:bad",
            }],
        }
        with patch.object(macos_update, "_get", return_value=json.dumps(release).encode("utf-8")):
            with self.assertRaisesRegex(RuntimeError, "unsupported.*checksum"):
                macos_update.latest_release()

    def test_download_checks_digest_and_size_while_streaming(self):
        data = b"builder archive"
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        with patch.object(
                macos_update.urllib.request, "urlopen", return_value=io.BytesIO(data)):
            macos_update._download("https://github.com/download", str(self.destination), digest, len(data))
            self.assertEqual(self.destination.read_bytes(), data)

    def test_download_rejects_wrong_digest_or_truncated_asset(self):
        data = b"builder archive"
        wrong_digest = "sha256:" + "0" * 64
        with patch.object(macos_update.urllib.request, "urlopen", return_value=io.BytesIO(data)):
            with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                macos_update._download("https://github.com/download", str(self.destination), wrong_digest, len(data))
        with patch.object(macos_update.urllib.request, "urlopen", return_value=io.BytesIO(data)):
            with self.assertRaisesRegex(RuntimeError, "incomplete"):
                macos_update._download("https://github.com/download", str(self.destination), None, len(data) + 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
