"""The pause menu's Recomp options button (nx2/oot_pause_menu.py, nx2/pause_layout.py, host/oot_pause_menu.c), on files made
here (no game).

- Its edits of the lifted C: every one found once, each made once in the file that holds it, the host's calls declared there,
  a second run changing nothing; one place missing, no file changed. The page's function keeps its definition line
  (nx2/lifted_c.py HEAD: split_hot takes each function from it) and its own body under the _game name.
- The layout editor: an archive without PaSystemMenu_00, or with a layout that is not the one known, is left as it is.
- With a clang: the edited files and host/oot_pause_menu.c compile.

python -I -B tests/test_oot_pause_menu.py
"""
import contextlib
import io
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import lifted_c  # noqa: E402
import oot_patches  # noqa: E402
import oot_pause_menu as m  # noqa: E402
import pause_layout  # noqa: E402


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def lifted(olds):
    out = '#include "a64.h"\n'
    for old in olds:
        out += old + "    c->x[0] = c->x[0];\nreturn;\n}\n"
    return out


def read(d):
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(Path(d).glob("code_*.c"))}


def sarc(files):
    """a little-endian SARC of (name, bytes), as pause_layout reads one"""
    n = len(files)
    names = b"".join(name.encode() + b"\0" * (4 - len(name) % 4) for name, _ in files)
    data, offs = b"", []
    for _, blob in files:
        offs.append((len(data), len(data) + len(blob)))
        data += blob + b"\0" * (-len(blob) % 8)
    head = 0x14 + 12 + 16 * n + 8 + len(names)
    head += -head % 0x10
    out = bytearray(b"SARC" + struct.pack("<HHIIHH", 0x14, 0xFEFF, 0, head, 0x100, 0))
    out += b"SFAT" + struct.pack("<HHI", 12, n, 0x65)
    at = 0
    for (name, _), (s0, s1) in zip(files, offs):
        out += struct.pack("<IIII", 0, 0x01000000 | at // 4, s0, s1)
        at += len(name) + 1 + (-(len(name) + 1) % 4)
    out += b"SFNT" + struct.pack("<HH", 8, 0) + names
    out += b"\0" * (head - len(out)) + data
    struct.pack_into("<I", out, 8, len(out))
    return bytes(out)


def main():
    olds = [old for old, _ in m.EDITS]
    files = {"code_001.c": lifted(olds[:1]), "code_002.c": lifted(olds[1:]), "code_003.c": lifted([])}
    with tempfile.TemporaryDirectory() as d:
        for name, text in files.items():
            (Path(d) / name).write_text(text, encoding="utf-8", newline="")
        with contextlib.redirect_stdout(io.StringIO()):
            oot_patches.apply_pause_menu(d)
        out = read(d)
        check(out["code_003.c"] == files["code_003.c"], "a file without places was changed")
        joined = "".join(out.values())
        for old, new in m.EDITS:
            check(joined.count(new) == 1, "an edit is not made once: %r" % old)
        check(sum(t.count(m.DECL) for t in out.values()) == 2, "the host's calls are not declared in each edited file")
        heads = [h.group(1) for h in lifted_c.HEAD.finditer(joined)]
        check(heads.count("f_80f99400") == 1 and "void f_80f99400_game(Ctx *__restrict A64_NOESC c) {\n" in joined,
              "the page's function lost its definition line or its own body")
        with contextlib.redirect_stdout(io.StringIO()):
            oot_patches.apply_pause_menu(d)
        check(read(d) == out, "a second run changed the files")
        edited = out
    with tempfile.TemporaryDirectory() as d:
        partial = {"code_001.c": lifted(olds[:1]), "code_002.c": lifted([])}
        for name, text in partial.items():
            (Path(d) / name).write_text(text, encoding="utf-8", newline="")
        said = io.StringIO()
        with contextlib.redirect_stdout(said):
            oot_patches.apply_pause_menu(d)
        check(read(d) == partial, "a lift missing a place was edited")
        check("left out" in said.getvalue(), "a missing place was not said")

    other = sarc([("Other_00.buil", b"BFFH" + b"\0" * 60)])
    check(pause_layout.edit_blarc(other) == (other, 0), "an archive without the page's layout was changed")
    unknown = sarc([("PaSystemMenu_00.buil", b"BFFH" + b"\0" * 0x200)])
    check(pause_layout.edit_blarc(unknown) == (unknown, 0), "a layout that is not the one known was changed")
    check(pause_layout.edit_blarc(b"not an archive") == (b"not an archive", 0), "something that is not an archive was changed")

    host = (ROOT / "host" / "oot_pause_menu.c").read_text(encoding="utf-8")
    buttons = host[host.index("uint64_t hos_pausebtn_buttons("):]
    check("GP(" not in buttons, "the pad's buttons read the game's memory raw (recomp_load* as the rest of the file)")
    gone = host[host.index("void hos_pausebtn_gone("):host.index("uint64_t hos_pausebtn_buttons(")]
    check("our_control = 0" in gone, "the page destroyed does not forget its button's control (read after it is freed)")
    compile_check(edited)
    print("PASS: the pause menu's Recomp options button: its edits all together or none, unknown layouts left alone")


def compile_check(edited):
    emsdk = os.path.join(os.environ.get("EMSDK", r"C:\emsdk"), "upstream", "bin", "clang.exe")
    if not (os.path.isfile(emsdk) or os.name != "nt"):
        print("(no clang: the compile is not checked)")
        return
    import kit  # noqa: F401  (a64-kit's tools on the path)
    import toolchain
    try:
        cc = toolchain.need(toolchain.find("clang"))
    except SystemExit:
        print("(no clang: the compile is not checked)")
        return
    import a64_lift
    import a64_rtgen
    with tempfile.TemporaryDirectory() as d:
        a64_rtgen.write(d)
        Path(d, "a64_fpx.h").write_text(a64_lift.fpx_header(set()), encoding="utf-8", newline="\n")
        inc = ["-I" + str(ROOT / "host"), "-I" + str(ROOT / "third_party" / "a64-kit" / "rt"), "-I" + d]
        for name, text in edited.items():
            p = Path(d) / name
            p.write_text(text, encoding="utf-8", newline="")
            subprocess.run([cc, "-fsyntax-only", "-w", *inc, str(p)], check=True)
        subprocess.run([cc, "-fsyntax-only", "-w", "-Werror=implicit-function-declaration", *inc,
                        str(ROOT / "host" / "oot_pause_menu.c")], check=True)


if __name__ == "__main__":
    main()
