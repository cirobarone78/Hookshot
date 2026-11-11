"""The game folder's launcher page draws its hero from the player's own folder, never from art the repository ships
(CONTRIBUTING.md, "The rule with no exceptions"), and the window drives it the way the mockup lays it out.

python -I -B tests/test_builder_launch_hero.py
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "builder" / "py" / "hookshot_builder" / "launch_page.py").read_text(encoding="utf-8")
WINDOW = (ROOT / "builder" / "py" / "hookshot_builder" / "window.py").read_text(encoding="utf-8")
TK = (ROOT / "builder" / "linux" / "hookshot_builder.py").read_text(encoding="utf-8")


def body_of(source, start_marker, end_marker):
    start = source.index(start_marker)
    return source[start:source.index(end_marker, start + len(start_marker))]


class LaunchHeroTests(unittest.TestCase):
    def test_hero_is_read_from_the_game_folder_only(self):
        body = body_of(PAGE, "def hero_file", "\n\n")
        self.assertIn("os.path.join(folder, HERO_FILE)", body)
        self.assertNotIn("ASSETS", body)
        self.assertIn('HERO_FILE = "hookshot_hero.png"', PAGE)

    def test_the_builder_ships_no_hero_art(self):
        """The launcher's own assets are the hookshot item and the fonts; no hero picture, no screenshot of the game."""
        assets = ROOT / "builder" / "py" / "hookshot_builder" / "assets"
        names = [p.name.lower() for p in assets.rglob("*") if p.is_file()]
        self.assertFalse([n for n in names if n.startswith("hero") or n.endswith((".jpg", ".jpeg"))])

    def test_the_window_drives_the_new_page(self):
        body = body_of(WINDOW, "def _launch_page", "\n    def ")
        self.assertIn("launch_page.LaunchPage", body)
        self.assertIn("self.launch_page.set_hero(folder)", WINDOW)   # (show_launcher: the folder's own picture, if any)
        self.assertIn("self.launch_page.set_ready(", WINDOW)
        self.assertIn("Hookshot: Update available:", WINDOW)          # (the footer strip's sentence)
        self.assertIn("Version %s → %s", WINDOW)                      # (the mockup's version chain)

    def test_the_windows_builder_pages_share_the_launcher_chrome(self):
        """The overhaul: the launcher's frame (green rail + dark footer strip) wraps every page of the Qt builder, and the
        pages put their action rows on the strip instead of floating. (The Linux builder reaches the same look through its own
        Slate theme, above: same greens, same page colour.)"""
        self.assertIn("self.chrome_strip = QFrame(self.main)", WINDOW)
        self.assertIn("self.chrome_rail = launch_page.Rail(self.hook)", WINDOW)
        self.assertIn("chrome_on = page is not self.launch_page", WINDOW)
        self.assertIn("self.chrome_rail.setVisible(chrome_on)", WINDOW)

    def test_the_preview_fakes_a_built_folder_not_a_game(self):
        """HOOKSHOT_UI_PREVIEW=launch invents the names a built folder keeps; nothing is read from a dump (no game in CI)."""
        body = body_of(WINDOW, "def preview_game_folder", "\n    # ================= 1: game files")
        for made_up in ("hookshot_version.txt", '"bin"', ".hookshot_exefs", "romfs"):
            self.assertIn(made_up, body)
        for game_data in (".nup", ".nca", ".xci", "work/", "image.bin"):
            self.assertNotIn(game_data, body)

    def test_the_linux_tk_launcher_draws_the_same_page(self):
        """builder/linux (the AppImage's Tk builder) shows the same design from the same rule: the hero comes from the player's
        folder, the footer says it in the mockup's words, and no hero picture of the game sits anywhere under builder/."""
        start = TK.index("def hero_image")
        body = TK[start:TK.index("\n\n", start)]
        self.assertIn("os.path.join(folder, HERO_FILE)", body)
        self.assertIn('HERO_FILE = "hookshot_hero.png"', TK)
        show = TK[TK.index("def show_launch"):TK.index("\n    def begin_update")]
        for piece in ("hero_image(folder)", "Build & Update", "Ocarina of Time:", "Hookshot Launcher"):
            self.assertIn(piece, show)
        apply_ = TK[TK.index("def apply_launch"):TK.index("\n    def show_launch")]
        self.assertIn("Hookshot: Version %s (Built & Installed, Ready to play)", apply_)
        self.assertIn("Version %s -> %s", apply_)
        shipped = [p for p in (ROOT / "builder").rglob("*") if p.is_file() and p.name.lower().startswith("hero")]
        self.assertEqual(shipped, [])


if __name__ == "__main__":
    unittest.main()
