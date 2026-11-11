"""The builder and game's release checks follow the repository they were packaged from."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hookshot_version", ROOT / "nx2" / "version.py")
version = importlib.util.module_from_spec(spec)
spec.loader.exec_module(version)


class RepositoryTests(unittest.TestCase):
    def test_environment_override_wins(self):
        with mock.patch.dict(os.environ, {"HOOKSHOT_REPOSITORY": "fork-name/Hookshot"}, clear=False):
            self.assertEqual(version.repository(root="/missing"), "fork-name/Hookshot")

    def test_release_metadata_is_read_from_tools_root(self):
        with tempfile.TemporaryDirectory(prefix="hookshot-repository-") as folder:
            Path(folder, "repository.txt").write_text("fork-name/Hookshot\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(version.repository(root=folder), "fork-name/Hookshot")

    def test_invalid_metadata_uses_the_canonical_repository(self):
        with tempfile.TemporaryDirectory(prefix="hookshot-repository-") as folder:
            Path(folder, "repository.txt").write_text("../outside\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"HOOKSHOT_REPOSITORY": "bad value"}, clear=True):
                self.assertEqual(version.repository(root=folder), version.DEFAULT_REPOSITORY)


if __name__ == "__main__":
    unittest.main()
