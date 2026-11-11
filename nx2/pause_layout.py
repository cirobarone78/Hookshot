"""(hookshot) A sixth button in the pause menu's Menu page layout, for "Recomp Options" (host/oot_pause_menu.c): PaSystemMenu_00
in UI/Layout2Archive/Common.*.blarc has panes for five buttons (Pa_Button_00..04, PaCommonBtnThin_00 parts) and the page draws
the panes its layout has, so Pa_Button_05 is added to the layout: a copy of Pa_Button_04 below it at the buttons' spacing.

The layout (BFFH, Nintendo.Ui.ResModels.LayoutResData) holds absolute file offsets. Nothing is moved: what grows (the panes'
and the parts' tables, the new pane's and part's records, their strings) is written after the end of the file, its tables
pointed there, the file's size and its string pool's size raised. In the archive (SARC) the edited layout is put after the
last file and its entry pointed at it, so every other file keeps its offset (prompts' runs over Common.blarc stay valid).

What is known of the layout (offsets in the file):
- 0x118 + 32 * k: dictionary k: u64 names table, u64 items table, u64 hashes table, u32 count, u32 8. 0 the panes, 5 the
  parts (layout instances).
- a pane: 0x44 bytes; +0x1c x, +0x20 y (f32), +0x28 parent index, +0x34 the index after its subtree, +0x40 high 16 bits its
  part's index.
- a part: +0x00 its layout's name, +0x40 its pane's index; its overrides' records follow it (offsets into it), one of them a
  string with its pane's index.

python -I nx2/pause_layout.py <Common.blarc decompressed> <out>   (check: the edited archive)
"""
import struct
import sys

PANES = ["RootPane", "N_All_00", "N_InOut_00", "Pa_SystemController_00", "N_Element_00", "P_DecoLine_01", "P_DecoMark_00",
         "P_DecoLine_02", "Pa_Button_00", "Pa_Button_01", "Pa_Button_02", "Pa_Button_03", "Pa_Button_04"]
NEW = "Pa_Button_05"
PANE_SIZE = 0x44


def _str(b, at):
    return b[at:b.index(b"\0", at)].decode("latin1")


def _dict(b, k):
    at = 0x118 + 32 * k
    names, items, hashes = struct.unpack_from("<QQQ", b, at)
    n, = struct.unpack_from("<I", b, at + 24)
    return at, names, items, hashes, n


def edit_layout(b):
    """PaSystemMenu_00's bytes with Pa_Button_05; None when the layout is not the one known"""
    b = bytearray(b)
    if b[:4] != b"BFFH" or b"Nintendo.Ui.ResModels.LayoutResData" not in b[:0x60]:
        return None
    pd_at, p_names, p_items, p_hashes, pn = _dict(b, 0)
    if pn != len(PANES) or [_str(b, struct.unpack_from("<Q", b, p_names + 8 * i)[0]) for i in range(pn)] != PANES:
        return None
    qd_at, q_names, q_items, q_hashes, qn = _dict(b, 5)
    parts = [_str(b, struct.unpack_from("<Q", b, q_names + 8 * i)[0]) for i in range(qn)]
    if parts[-1] != "Pa_Button_04":
        return None
    pane = lambda i: struct.unpack_from("<Q", b, p_items + 8 * i)[0]
    rec4, rec3 = pane(12), pane(11)
    part4 = struct.unpack_from("<Q", b, q_items + 8 * (qn - 1))[0]
    # (the part's record runs to the next thing after it: the next part's, or the end of the parts' records)
    later = sorted(v for v in (struct.unpack_from("<Q", b, q_items + 8 * i)[0] for i in range(qn)) if v > part4)
    part_end = later[0] if later else part4 + 0xa0
    if struct.unpack_from("<I", b, part4 + 0x40)[0] != 12:
        return None

    tail = bytearray()
    base = (len(b) + 15) & ~15

    def put(data, align=8):
        nonlocal tail
        while (base + len(tail)) % align:
            tail.append(0)
        at = base + len(tail)
        tail += data
        return at

    s_name = put(NEW.encode() + b"\0", 1)
    s_index = put(b"13\0", 1)
    # the pane: Pa_Button_04's, below it at the spacing of 03 and 04, its subtree to 14, its part the seventh
    rec = bytearray(b[rec4:rec4 + PANE_SIZE])
    y3, y4 = struct.unpack_from("<f", b, rec3 + 0x20)[0], struct.unpack_from("<f", b, rec4 + 0x20)[0]
    struct.pack_into("<f", rec, 0x20, y4 + (y4 - y3))
    struct.pack_into("<I", rec, 0x34, len(PANES) + 1)
    struct.pack_into("<I", rec, 0x40, (qn << 16) | 0xffff)
    r_pane = put(bytes(rec), 4)
    # the part: Pa_Button_04's, its offsets into itself moved with it, its pane 13, its index string "13"
    part = bytearray(b[part4:part_end])
    r_part = put(b"", 8)
    delta = r_part - part4
    for o in range(0, len(part) - 7, 8):
        v, = struct.unpack_from("<Q", part, o)
        if part4 <= v < part_end:
            struct.pack_into("<Q", part, o, v + delta)
        elif 0 < v < len(b) - 3 and b[v:v + 3] == b"12\0":   # (its pane's index, as a string)
            struct.pack_into("<Q", part, o, s_index)
    struct.pack_into("<I", part, 0x40, len(PANES))
    put(bytes(part), 8)

    def grown(table, n, extra):
        return put(b[table:table + 8 * n] + struct.pack("<Q", extra), 8)
    np_names, np_items, np_hashes = grown(p_names, pn, s_name), grown(p_items, pn, r_pane), grown(p_hashes, pn, 0)
    nq_names, nq_items, nq_hashes = grown(q_names, qn, s_name), grown(q_items, qn, r_part), grown(q_hashes, qn, 0)
    struct.pack_into("<QQQI", b, pd_at, np_names, np_items, np_hashes, pn + 1)
    struct.pack_into("<QQQI", b, qd_at, nq_names, nq_items, nq_hashes, qn + 1)
    for i in range(3):   # (RootPane, N_All_00, N_InOut_00: the new pane is in their subtrees)
        at = pane(i) + 0x34
        if struct.unpack_from("<I", b, at)[0] == len(PANES):
            struct.pack_into("<I", b, at, len(PANES) + 1)
    out = bytes(b) + b"\0" * (base - len(b)) + bytes(tail)
    out = bytearray(out)
    struct.pack_into("<I", out, 8, len(out))   # (the file's size)
    sp = out.find(b"BFSI", 0xa8 + 4)   # (the string pool's chunk: offset, size)
    if sp > 0 and out[sp + 0x14:sp + 0x1e] == b"StringPool":
        off, = struct.unpack_from("<I", out, sp + 4)
        struct.pack_into("<I", out, sp + 8, len(out) - off)
    return bytes(out)


def sarc_entries(a):
    """(name, node offset, data start, data end) of a little-endian SARC's files"""
    data, = struct.unpack_from("<I", a, 0xC)
    n, = struct.unpack_from("<H", a, 0x14 + 6)
    names = 0x14 + 12 + 16 * n + 8
    out = []
    for i in range(n):
        node = 0x14 + 12 + 16 * i
        attr, s0, s1 = struct.unpack_from("<III", a, node + 4)
        nm = names + (attr & 0xFFFFFF) * 4
        out.append((a[nm:a.index(b"\0", nm)].decode(), node, data + s0, data + s1))
    return out


def edit_blarc(blarc):
    """Common.blarc with every PaSystemMenu_00 layout given Pa_Button_05 (put after the archive's last file); (archive, bytes
    added), (blarc, 0) when there is none to edit"""
    if blarc[:4] != b"SARC":
        return blarc, 0
    a = bytearray(blarc)
    data, = struct.unpack_from("<I", a, 0xC)
    done = 0
    for name, node, s0, s1 in sarc_entries(bytes(a)):
        if not name.endswith("PaSystemMenu_00.buil"):
            continue
        new = edit_layout(a[s0:s1])
        if not new:
            continue
        while len(a) % 0x100:
            a.append(0)
        at = len(a)
        a += new
        struct.pack_into("<II", a, node + 8, at - data, len(a) - data)
        done += 1
    if not done:
        return blarc, 0
    struct.pack_into("<I", a, 0x8, len(a))   # (the archive's size)
    return bytes(a), len(a) - len(blarc)


if __name__ == "__main__":
    src = open(sys.argv[1], "rb").read()
    out, added = edit_blarc(src)
    print("pause layout: %d bytes added" % added)
    if len(sys.argv) > 2:
        open(sys.argv[2], "wb").write(out)
