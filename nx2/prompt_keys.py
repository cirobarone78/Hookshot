"""(hookshot) The keyboard face of the button prompts: a key per Windows key code (and the mouse's buttons), from Kenney's Input
Prompts Keyboard & Mouse font (CC0, third_party/kenney_input), the keys whose names are words and the mouse's buttons drawn here.

The font (nx2/prompt_assets.py faces_font) has, beside the faces' icons, the icon of each key at KEY_BASE + its key code (past
every face's code points: PAD_BASE + FACE_CODES x HOS_PROMPT_N). On the keyboard face host/prompts.c points each Switch button's
code point at the icon of the first key bound to it (hookshot_options.ini key_<button>, the Controls page), as the pad faces point
them at their pad input's. A text rewritten after a change while the game runs (host/prompts.c text_code) gets a code of its own
for each Switch button and key it shows, given out as they come from SLOT_BASE: SLOTS codes no font of the game has (the CJK fonts
use most of the private use area), each pointed at its key's icon when given out.
"""
import os

KEY_BASE = 0xF7C0   # (host/prompts.c: PAD_BASE + FACE_CODES x HOS_PROMPT_N)
SLOT_BASE, SLOTS = 0xEEC0, 320   # (host/prompts.c; U+EEC0..U+EFFF: in none of the game's fonts, the External font's BIND_BASE after)
FONT = "kenney_input_keyboard_&_mouse.otf"

# Windows virtual-key codes (learn.microsoft.com/windows/win32/inputdev/virtual-key-codes) -> Kenney's glyph name after "keyboard_"
# ("/name": the whole name). The keys whose names are long words have Kenney's symbol for them, which reads at the icons' size.
KEYS = {
    0x01: "/mouse_left", 0x02: "/mouse_right", 0x04: "/mouse_scroll", 0x05: "/mouse_side_back", 0x06: "/mouse_side_forward",
    0x08: "backspace_icon", 0x09: "tab_icon", 0x0D: "return", 0x10: "shift_icon", 0x11: "ctrl", 0x12: "alt", 0x13: "pause",
    0x14: "capslock_icon", 0x1B: "escape", 0x20: "space_icon", 0x21: "page_up", 0x22: "page_down", 0x23: "end", 0x24: "home",
    0x25: "arrow_left", 0x26: "arrow_up", 0x27: "arrow_right", 0x28: "arrow_down", 0x2C: "printscreen", 0x2D: "insert",
    0x2E: "delete", 0x5B: "win", 0x5C: "win", 0x6A: "asterisk", 0x6B: "numpad_plus", 0x6D: "minus", 0x6E: "period",
    0x6F: "slash_forward", 0x90: "numlock", 0x91: "scroll_lock", 0xA0: "shift_icon", 0xA1: "shift_icon", 0xA2: "ctrl",
    0xA3: "ctrl", 0xA4: "alt", 0xA5: "alt", 0xBA: "semicolon", 0xBB: "equals", 0xBC: "comma", 0xBD: "minus", 0xBE: "period",
    0xBF: "slash_forward", 0xC0: "tilde", 0xDB: "bracket_open", 0xDC: "slash_back", 0xDD: "bracket_close", 0xDE: "apostrophe",
}
KEYS.update({0x30 + i: str(i) for i in range(10)})   # the digits
KEYS.update({0x60 + i: str(i) for i in range(10)})   # (the numpad's digits: Kenney has none of their own)
KEYS.update({0x41 + i: chr(0x61 + i) for i in range(26)})   # the letters
KEYS.update({0x70 + i: f"f{i + 1}" for i in range(12)})
UNKNOWN = "any"   # (a key code Kenney has no key for: its "ANY" key)


def kenney_name(code):
    n = KEYS.get(code, UNKNOWN)
    return n[1:] if n.startswith("/") else "keyboard_" + n


# hookshot's default keys for the Switch's buttons, in HOS_SW_* order (A B X Y LS RS L R ZL ZR Plus Minus Left Up Right Down): the
# first of each button's keys (host/nn_hid.c key_default), the icons the font has before host/prompts.c points them at the controls
DEFAULT = [0x45, 0x10, 0x20, 0x01, 0x11, 0x43, 0x51, 0x52, 0x5A, 0x58, 0x09, 0x4D, 0x31, 0x32, 0x33, 0x34]


# ---- the keys drawn here, not Kenney's: the keys whose names are words (Kenney's words are too small to read at the icons' size) as
# wider keys with the word cut out, in the game's own bold font; the mouse's three buttons as a key with a mouse cut out of it and
# that button left white.
# Every contour is apart from the others or inside one (none cross), so the icons fill the same by either winding rule.
LABELS = {0x05: "M4", 0x06: "M5", 0x11: "Ctrl", 0x12: "Alt", 0x13: "Pause", 0x1B: "Esc", 0x21: "PgUp", 0x22: "PgDn",
          0x23: "End", 0x24: "Home", 0x2C: "PrtSc", 0x2D: "Ins", 0x2E: "Del", 0x90: "NumLk", 0x91: "ScrLk", 0xA2: "Ctrl",
          0xA3: "Ctrl", 0xA4: "Alt", 0xA5: "Alt"}
LABELS.update({0x60 + i: f"Num{i}" for i in range(10)})
MICE = {0x01: "left", 0x02: "right", 0x04: "middle"}
LABEL_FONT = "Font2/Scalable/ClarimoUDPE-DemiBold.Nin_Ounce_NVN2.bfotf.zs"   # (the game's own: read from the romfs at the build)
MOST = 2.2   # (how much wider than the game's icon a word key may be)
K = 0.5523   # (a quarter circle's control points, as a fraction of its radius)


def _area(record):
    from fontTools.pens.areaPen import AreaPen
    p = AreaPen()
    record.replay(p)
    return p.value


def _contour(pen, sign, draw):
    """draw(pen) one closed contour, turned to go counter-clockwise (y up) for sign 1, clockwise for -1"""
    from fontTools.pens.recordingPen import RecordingPen
    from fontTools.pens.reverseContourPen import ReverseContourPen
    rec = RecordingPen()
    draw(rec)
    rec.replay(pen if (_area(rec) > 0) == (sign > 0) else ReverseContourPen(pen))


def _rrect(x0, y0, x1, y1, r):
    r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
    k = K * r

    def draw(pen):
        pen.moveTo((x0 + r, y0))
        pen.lineTo((x1 - r, y0))
        pen.curveTo((x1 - r + k, y0), (x1, y0 + r - k), (x1, y0 + r))
        pen.lineTo((x1, y1 - r))
        pen.curveTo((x1, y1 - r + k), (x1 - r + k, y1), (x1 - r, y1))
        pen.lineTo((x0 + r, y1))
        pen.curveTo((x0 + r - k, y1), (x0, y1 - r + k), (x0, y1 - r))
        pen.lineTo((x0, y0 + r))
        pen.curveTo((x0, y0 + r - k), (x0 + r - k, y0), (x0 + r, y0))
        pen.closePath()
    return draw


def _button(a, b, y0, top, y1, ry, left):
    """a mouse button's area: x a..b, from y0 up to top, then a quarter ellipse up to (the inner side, y1) on the outer side (left:
    at a), ry high and b - a wide"""
    rx = b - a

    def draw(pen):
        pen.moveTo((a, y0))
        pen.lineTo((b, y0))
        if left:
            pen.lineTo((b, y1))
            pen.curveTo((b - K * rx, y1), (a, top + K * ry), (a, top))
        else:
            pen.lineTo((b, top))
            pen.curveTo((b, top + K * ry), (a + K * rx, y1), (a, y1))
        pen.closePath()
    return draw


def _box(box):
    gx0, gy0, gx1, gy1 = box
    return max(gx1 - gx0, gy1 - gy0), (gx0 + gx1) / 2, (gy0 + gy1) / 2


def word_key(pen, label, box, lset, lcmap):
    """a key as high as the game's icon (box: that glyph's bounds) and as wide as the word needs, the word cut out of it, in the
    label font (lset, lcmap: its glyph set and cmap): how much wider than the icon it is"""
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.pens.transformPen import TransformPen
    side, cx, cy = _box(box)
    names = [lcmap[ord(c)] for c in label]
    adv = sum(lset[n].width for n in names)
    bp = BoundsPen(lset)
    lset[lcmap[ord("H")]].draw(bp)
    caph = bp.bounds[3]
    s = side * 0.48 / caph   # (the capitals about half the key's height)
    pad = side * 0.20
    w = max(side, adv * s + 2 * pad)
    if w > side * MOST:
        s *= (side * MOST - 2 * pad) / (adv * s)
        w = side * MOST
    x0, y0 = cx - side / 2, cy - side / 2
    _contour(pen, -1 if _letters_ccw(lset, lcmap) else 1, _rrect(x0, y0, x0 + w, y0 + side, side * 0.2))   # (the letters' outer contours go the other way)
    x, ty = x0 + (w - adv * s) / 2, cy - caph * s / 2
    for n in names:
        lset[n].draw(TransformPen(pen, (s, 0, 0, s, x, ty)))
        x += lset[n].width * s
    return w - side


def _letters_ccw(lset, lcmap):
    from fontTools.pens.recordingPen import RecordingPen
    rec = RecordingPen()
    lset[lcmap[ord("I")]].draw(rec)
    return _area(rec) > 0


def mouse(pen, which, box, sign=1):
    """a key (as the others) with a mouse cut out of it, the button `which` (left, right; middle: the wheel) left white in the
    mouse. sign: the white contours' direction"""
    side, cx, cy = _box(box)
    x0, y0 = cx - side / 2, cy - side / 2
    _contour(pen, sign, _rrect(x0, y0, x0 + side, y0 + side, side * 0.2))   # the key
    mw, mh = side * 0.52, side * 0.76
    mx0, my0, mx1, my1 = cx - mw / 2, cy - mh / 2, cx + mw / 2, cy + mh / 2
    _contour(pen, -sign, _rrect(mx0, my0, mx1, my1, mw / 2))   # the mouse, cut out
    g = side * 0.06   # (the dark line round the white button, and between the buttons)
    ix0, ix1, iy1, ri = mx0 + g, mx1 - g, my1 - g, mw / 2 - g
    by = cy + side * 0.02   # (the buttons' lower edge)
    top = iy1 - ri
    if which in ("left", "right"):
        left = which == "left"
        a, b = (ix0, cx - g / 2) if left else (cx + g / 2, ix1)
        _contour(pen, sign, _button(a, b, by, top, iy1, ri, left))
    else:   # the wheel
        ww = side * 0.13
        _contour(pen, sign, _rrect(cx - ww / 2, by, cx + ww / 2, iy1 - side * 0.02, ww / 2))


# ---- the sticks: the game's stick icons (L or R, with the ways they mean) as the keys that move (WASD: hookshot's defaults,
# host/nn_hid.c key_default) and the mouse that turns the camera. In a text after a change while the game runs, each one's code
# is rewritten to the face's: STICK_KEYS + its place on the keyboard face, STICK_GAME + its place (the game's own icon) on the
# rest (host/prompts.c stick_code[]; U+F8C0..U+F8DF, in none of the game's fonts)
STICKS = [   # (code point, stick, the ways shown: up down left right), in host/prompts.c stick_code order
    (0xE050, "move", "d"), (0xE052, "move", "u"), (0xE054, "move", "lr"), (0xE058, "move", "r"), (0xE05A, "move", "l"),
    (0xE05C, "move", "ud"), (0xE05E, "move", "uldr"),
    (0xE051, "cam", "d"), (0xE053, "cam", "u"), (0xE055, "cam", "lr"), (0xE059, "cam", "r"), (0xE05B, "cam", "l"),
    (0xE05D, "cam", "ud"), (0xE05F, "cam", "uldr"), (0xE068, "cam", "uldr")]
STICK_KEYS, STICK_GAME = 0xF8C0, 0xF8D0
MOVE = {"u": 0x57, "d": 0x53, "l": 0x41, "r": 0x44}


def keyboard_glyphs(add, gset, cmap, chars, hmtx, label_otf, kset, draw):
    """the keyboard face's glyphs into the game's font (add(name, charstring, width): faces_font's; kset: Kenney's font's glyphs;
    draw(target, Kenney name, scale): that glyph in the box of the game's glyph target, its charstring and width; label_otf: the
    game's bold font, for the keys whose names are words): {code point: glyph name} for every key at
    KEY_BASE + its code and the sticks at STICK_KEYS.., and each key's advance by its code (256 of them: 0 none)"""
    import io
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.pens.recordingPen import RecordingPen
    from fontTools.pens.t2CharStringPen import T2CharStringPen
    from fontTools.ttLib import TTFont
    lfont = TTFont(io.BytesIO(label_otf)) if label_otf else None
    lset, lcmap = (lfont.getGlyphSet(), lfont.getBestCmap()) if lfont else (None, None)
    target = cmap[0xE040]   # (each key in the box of the game's A)
    bp = BoundsPen(gset)
    gset[target].draw(bp)
    box, cs, width0 = bp.bounds, chars[target], hmtx[target][0]

    def drawn(name, rec, over):
        pen = T2CharStringPen(width0 + round(over), gset)
        rec.replay(pen)
        return add(name, pen.getCharString(private=cs.private, globalSubrs=cs.globalSubrs), width0 + round(over))

    placed, widths = {}, [0] * 256
    for code in range(1, 256):
        name = f"key_{code:02x}"
        if code in MICE:
            rec = RecordingPen()
            mouse(rec, MICE[code], box)
            placed[KEY_BASE + code] = drawn(name, rec, 0)
        elif lfont and code in LABELS:
            rec = RecordingPen()
            placed[KEY_BASE + code] = drawn(name, rec, word_key(rec, LABELS[code], box, lset, lcmap))
        elif kenney_name(code) in kset and code in KEYS:
            placed[KEY_BASE + code] = add(name, *draw(target, kenney_name(code)))
        else:
            continue
        widths[code] = hmtx[placed[KEY_BASE + code]][0]
    made = {}
    for i, (code, stick, ways) in enumerate(STICKS):
        placed[STICK_GAME + i] = cmap[code]
        if stick == "cam":   # (the mouse moving, those ways; the arrows round it take room: a little larger than a key)
            kn = "mouse_move" if len(ways) == 4 else "mouse_horizontal" if ways[0] in "lr" else "mouse_vertical"
            if kn not in made:
                c, w = draw(target, kn, 1.2)
                made[kn] = add(f"stick_{kn}", c, w)
            placed[STICK_KEYS + i] = made[kn]
        elif len(ways) == 1:
            placed[STICK_KEYS + i] = placed[KEY_BASE + MOVE[ways]]
        elif lfont:
            label = "".join(chr(MOVE[w]) for w in ways)
            if label not in made:
                rec = RecordingPen()
                made[label] = drawn(f"stick_{label.lower()}", rec, word_key(rec, label, box, lset, lcmap))
            placed[STICK_KEYS + i] = made[label]
        else:
            placed[STICK_KEYS + i] = cmap[code]
    return placed, widths
