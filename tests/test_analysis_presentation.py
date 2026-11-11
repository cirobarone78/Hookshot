"""Authored startup logs distinguish requested windows from offscreen fallback."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('analysis', ROOT / 'scripts/analysis_api.py')
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


class PresentationTests(unittest.TestCase):
    def test_missing_optional_dlss_adapter_fails_before_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(analysis, 'ROOT', root):
                with self.assertRaisesRegex(ValueError, 'optional DLSS adapter is not installed'):
                    analysis.HookshotAPI.launch(root / 'game', root / 'save', dlss5=True)
            self.assertEqual(list(root.iterdir()), [])

    def test_initial_swapchain_is_not_relabelled_by_later_recreation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = root / 'session.json'
            session.write_text('{}')
            api = analysis.HookshotAPI(session)
            for mode in ('fifo', 'mailbox', 'immediate'):
                (root / 'game.log').write_text(
                    f'vk: swapchain 1280x720, 4 images, {mode}\n'
                    'vk: replay ready (window; fixture)\n'
                    'vk: swapchain 1920x1080, 3 images, fifo\n')
                self.assertEqual(api.presentation_startup()['initial_swapchain'],
                                 dict(width=1280, height=720, images=4, present_mode=mode))
            (root / 'game.log').write_text('vk: replay ready (offscreen; fixture)\n')
            self.assertIsNone(api.presentation_startup()['initial_swapchain'])

    def test_status_uses_observed_mode_even_after_startup_leaves_log_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = root / 'session.json'
            session.write_text(json.dumps({'headless': False, 'audio_enabled': False}))
            api = analysis.HookshotAPI(session)
            api.alive = lambda: False
            for marker, mode, headless in (
                ('vk: replay ready (window; fixture)\n', 'window', False),
                ('vk: replay ready (offscreen; fixture)\n', 'offscreen', True),
                ('display: requested minimized startup\n', 'unknown', None),
            ):
                with self.subTest(mode=mode):
                    (root / 'game.log').write_text(marker + 'x' * (2 * 1024 * 1024))
                    status = api.status()
                    self.assertEqual(status['presentation_mode'], mode)
                    self.assertIs(status['headless'], headless)
                    self.assertFalse(status['headless_requested'])


if __name__ == '__main__':
    unittest.main()
