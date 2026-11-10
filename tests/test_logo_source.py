"""Game-free: the logo's VectorCraft project is kept in the repository and out of the releases.

The Linux AppImage copies assets/, which holds the icon's editable source beside the PNG: the source must not be
shipped. GitHub's source archives are not the release files; git archive leaves it out through .gitattributes.

python -I -B tests/test_logo_source.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / "assets" / "hookshot.vectorcraft"
    if not source.is_file():
        raise SystemExit("assets/hookshot.vectorcraft is missing: the icon's project file belongs in the repository")
    if "assets/*.vectorcraft export-ignore" not in (ROOT / ".gitattributes").read_text(encoding="utf-8"):
        raise SystemExit(".gitattributes does not leave the logo's project file out of git archive")

    appimage = (ROOT / "scripts" / "linux" / "appimage.sh").read_text(encoding="utf-8")
    copies_assets = re.search(r"^\s*cp\b[^\n]*\bassets\b", appimage, re.MULTILINE)
    removes_source = re.search(r"^\s*rm\b[^\n]*assets/\*\.vectorcraft", appimage, re.MULTILINE)
    if copies_assets and not removes_source:
        raise SystemExit("the Linux AppImage copies assets/ but would ship assets/hookshot.vectorcraft")
    print("PASS: the logo's VectorCraft project stays out of the release files")


if __name__ == "__main__":
    main()
