"""The launcher's drawing, for Tk: the Windows launcher (builder/HookshotBuilder/MainWindow.xaml, as drawn in Paper's
"Hookshot v2") is vector shapes over a dim picture of the game, with a see-through panel. Tk draws none of that, so it is
painted here with numpy into images the canvas lays over each other: the shapes are the drawing's own path data, filled with
antialiasing and written as PNG (which Tk reads with its alpha). Square boxes (the panel's tabs, fields and buttons) are
plain canvas rectangles in hookshot_launcher.py.

Nothing here touches Tk. hookshot_launcher.py puts the images on the canvas and writes the text over them."""
import math
import os
import re
import struct
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "launcher")

# ---- the shapes, as Paper's "Hookshot v2" (and MainWindow.xaml) has them ----
# Play's outline: a torn strip (257 x 98)
STRIP = ("M442.631 118.999C448.417 120.005 452.962 121.032 453.489 121.045 454.487 121.07 475.335 122.287 486.302 122.555 "
         "492.957 122.718 503.52 122.793 511 122.832 511 122.832 511 209.654 511 209.654 507.192 209.846 503.557 210.032 500.7 "
         "210.184 489.689 210.771 468.701 212.289 467.693 212.334 466.816 212.373 448.015 213.053 438.322 213.404 428.277 213.767 "
         "422.536 210.245 407.737 214.229 393.317 218.111 390.477 212.062 381.226 212.077 379.3 211.44 377.766 210.981 374.519 "
         "210.872 371.312 210.795 368.683 210.668 366.926 210.58 366.565 210.561 366.344 210.703 366.319 210.868 366.299 211 "
         "366.404 211.146 366.666 211.24 367.285 211.46 368.092 211.706 369.122 211.973 369.942 212.176 370.856 212.491 371.844 "
         "212.858 361.446 214.11 348.69 216.408 348.008 216.433 347.223 216.461 332.4 217.028 322.124 217.407 322.124 217.407 254 "
         "217.407 254 217.407 254 217.407 254 118.999 254 118.999 254 118.999 442.631 118.999 442.631 118.999Z")
# the wordmark's letters (in their drawing they start at 368, 53.712 and are 416 x 63.791)
WORDMARK_BOX = (368, 53.712, 416, 63.791)
WORDMARK = (
    "M416.399 61.309V110.007L423.2 116.312H396.571L403.277 110.007V88.455H387.759V110.007L394.656 "
    "116.312H368.027L374.733 110.007V61.309L368.027 55.006H394.656L387.759 61.309V81.235H403.277V61.309L396.571 "
    "55.006H423.2L416.399 61.309Z",
    "M449.909 53.379C464.948 53.379 475.197 67.003 475.197 85.71 475.197 104.314 464.948 117.836 449.909 117.836 "
    "434.679 117.836 424.526 104.314 424.526 85.71 424.526 67.003 434.679 53.379 449.909 53.379ZM449.909 "
    "111.024C456.998 111.024 460.924 103.604 460.924 85.505 460.924 67.511 456.998 60.089 449.909 60.089 442.725 "
    "60.089 438.798 67.511 438.798 85.505 438.798 103.604 442.725 111.024 449.909 111.024ZM444.161 85.913L449.909 "
    "76.255 455.561 85.913 449.909 95.165 444.161 85.913Z",
    "M504.724 53.379C519.763 53.379 530.012 67.003 530.012 85.71 530.012 104.314 519.763 117.836 504.724 117.836 "
    "489.495 117.836 479.34 104.314 479.34 85.71 479.34 67.003 489.495 53.379 504.724 53.379ZM504.724 111.024C511.812 "
    "111.024 515.739 103.604 515.739 85.505 515.739 67.511 511.812 60.089 504.724 60.089 497.541 60.089 493.613 "
    "67.511 493.613 85.505 493.613 103.604 497.541 111.024 504.724 111.024ZM498.978 85.913L504.724 76.255 510.376 "
    "85.913 504.724 95.165 498.978 85.913Z",
    "M552.423 61.309V110.007L559.319 116.312H531.349L538.151 110.007V61.309L531.349 55.006H559.319L552.423 "
    "61.309ZM564.875 81.338L577.518 61.309 585.947 55.106H563.917L568.324 60.496 552.327 85.71 566.12 110.924 562.002 "
    "116.312H587.194L580.201 110.007 564.875 81.338Z",
    "M613.057 78.695C620.433 82.76 627.33 87.64 627.33 99.435 627.33 110.517 618.231 117.836 607.79 117.836 602.138 "
    "117.836 598.212 116.312 594.475 113.769L589.591 117.836 589.495 90.792C595.816 105.127 601.085 110.719 607.215 "
    "110.719 611.717 110.719 615.932 107.364 615.932 102.077 615.932 96.385 610.567 93.232 604.245 89.675 597.35 "
    "85.81 590.261 81.235 590.261 70.458 590.261 59.581 597.924 53.481 608.269 53.481 612.483 53.481 616.507 54.599 "
    "619.571 56.836L624.074 53.379V75.441C620.625 64.258 614.783 60.496 609.035 60.496 603.766 60.496 600.797 62.731 "
    "600.797 67.003 600.797 72.188 606.737 75.34 613.057 78.695Z",
    "M678.033 61.309V110.007L684.834 116.312H658.205L664.911 110.007V88.455H649.393V110.007L656.29 "
    "116.312H629.662L636.367 110.007V61.309L629.662 55.006H656.29L649.393 61.309V81.235H664.911V61.309L658.205 "
    "55.006H684.834L678.033 61.309Z",
    "M711.543 53.379C726.581 53.379 736.831 67.003 736.831 85.71 736.831 104.314 726.581 117.836 711.543 117.836 "
    "696.313 117.836 686.16 104.314 686.16 85.71 686.16 67.003 696.313 53.379 711.543 53.379ZM711.543 111.024C718.632 "
    "111.024 722.558 103.604 722.558 85.505 722.558 67.511 718.632 60.089 711.543 60.089 704.359 60.089 700.432 "
    "67.511 700.432 85.505 700.432 103.604 704.359 111.024 711.543 111.024ZM705.796 85.913L711.543 76.255 717.194 "
    "85.913 711.543 95.165 705.796 85.913Z",
    "M776.364 61.309H769.276V110.007L776.077 116.312H748.299L754.909 110.007V61.309H747.916L740.349 "
    "80.015V55.006H784.027V80.015L776.364 61.309Z",
)
# the marks, each drawn in a box of 24 (the menu's lines in one of 20, a build option's arrow in one of 16), a line 1.5 wide
# with round ends. (Paper draws the menu's lines in a box from 2, 2 and the option's arrow from 0.5, 0: moved to 0, 0 here)
MARKS = {
    "menu": (20, "M3.125,5.625 h13.75 M3.125,10 h13.75 M3.125,14.375 h13.75"),
    "close": (24, "M6 18 18 6M6 6l12 12"),
    "tick": (24, "m4.5 12.75 6 6 9-13.5"),
    "download": (24, "M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3"),
    "refresh": (24, "M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 "
                    "9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99"),
    "down": (24, "m19.5 8.25-7.5 7.5-7.5-7.5"),
    "up": (24, "M19.5,15.75 l-7.5,-7.5 l-7.5,7.5"),
    "choose": (16, "M13.313 5.844l-5.313 5.312-5.312-5.312"),
}
# GitHub's mark (drawn at 1/64 around 8, 8: placed by scaling 64 and moving -496) and Discord's (moved -496)
GITHUB = ("M8 7.757C7.866 7.757 7.757 7.866 7.757 8 7.757 8.107 7.827 8.198 7.923 8.231 7.935 8.232 7.94 8.225 7.94 8.218 "
          "7.94 8.213 7.94 8.194 7.94 8.173 7.879 8.184 7.863 8.159 7.858 8.145 7.855 8.138 7.844 8.117 7.833 8.111 7.825 8.106 "
          "7.813 8.095 7.832 8.095 7.852 8.094 7.865 8.112 7.87 8.12 7.892 8.156 7.927 8.146 7.941 8.139 7.943 8.123 7.949 8.113 "
          "7.957 8.107 7.902 8.101 7.846 8.08 7.846 7.987 7.846 7.96 7.855 7.939 7.871 7.922 7.868 7.916 7.86 7.891 7.873 7.858 "
          "7.873 7.858 7.894 7.851 7.94 7.882 7.96 7.877 7.98 7.875 8.001 7.875 8.022 7.875 8.041 7.877 8.061 7.882 8.107 7.851 "
          "8.128 7.858 8.128 7.858 8.141 7.891 8.133 7.916 8.131 7.922 8.146 7.939 8.155 7.96 8.155 7.987 8.155 8.08 8.099 8.101 "
          "8.044 8.107 8.054 8.115 8.061 8.129 8.061 8.152 8.061 8.184 8.06 8.211 8.06 8.218 8.06 8.225 8.065 8.232 8.077 8.231 "
          "8.173 8.198 8.243 8.107 8.243 8 8.243 7.866 8.134 7.757 8 7.757Z")
DISCORD = ("M517.491 506.955a13.067 13.067 0 0 0-3.225-1 0.049 0.049 0 0 0-0.052 0.024 9.102 9.102 0 0 0-0.403 0.826 "
           "12.063 12.063 0 0 0-3.622 0 8.349 8.349 0 0 0-0.408-0.826 0.051 0.051 0 0 0-0.052-0.024A13.03 13.03 0 0 0 506.505 "
           "506.955a0.046 0.046 0 0 0-0.022 0.019c-2.054 3.069-2.617 6.063-2.341 9.019a0.054 0.054 0 0 0 0.021 0.037 13.141 "
           "13.141 0 0 0 3.957 2 0.051 0.051 0 0 0 0.056-0.018 9.392 9.392 0 0 0 0.809-1.317 0.05 0.05 0 0 0-0.027-0.069 8.654 "
           "8.654 0 0 1-1.236-0.589 0.051 0.051 0 0 1-0.005-0.084c0.083-0.062 0.166-0.127 0.245-0.192a0.049 0.049 0 0 1 "
           "0.051-0.007c2.593 1.184 5.401 1.184 7.964 0a0.049 0.049 0 0 1 0.052 0.006c0.079 0.065 0.162 0.131 0.247 0.193a0.051 "
           "0.051 0 0 1-0.004 0.084 8.12 8.12 0 0 1-1.238 0.589 0.05 0.05 0 0 0-0.027 0.07 10.545 10.545 0 0 0 0.809 1.316 0.05 "
           "0.05 0 0 0 0.055 0.019 13.097 13.097 0 0 0 3.962-2.001 0.051 0.051 0 0 0 0.021-0.036c0.33-3.418-0.553-6.387-2.343-9.019"
           "a0.04 0.04 0 0 0-0.02-0.02zM509.372 514.193c-0.781 0-1.424-0.717-1.424-1.597s0.631-1.597 1.424-1.597c0.799 0 1.437 "
           "0.723 1.424 1.597 0.001 0.88-0.63 1.597-1.424 1.597z m5.266 0c-0.781 0-1.424-0.717-1.424-1.597s0.631-1.597 "
           "1.424-1.597c0.799 0 1.437 0.723 1.423 1.597 0 0.88-0.624 1.597-1.423 1.597z")

# ---- the colours ----
PAGE = (0x12, 0x12, 0x12)
WHITE = (0xFF, 0xFF, 0xFF)       # the wordmark
PLAY = (0xD2, 0x82, 0x3F)        # Play, Update Available, a bar's filled part
PLAY_OVER = (0xDC, 0x91, 0x50)
BLURPLE = (0x58, 0x65, 0xF2)

_NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_TOKEN = re.compile(r"([MmLlHhVvCcSsQqAaZz])|(%s)" % _NUMBER)


def _arc(x0, y0, rx, ry, turn, large, sweep, x1, y1):
    """An SVG arc from (x0, y0) to (x1, y1) as points (the end point last)."""
    if rx == 0 or ry == 0 or (x0 == x1 and y0 == y1):
        return [(x1, y1)]
    rx, ry, phi = abs(rx), abs(ry), math.radians(turn)
    c, s = math.cos(phi), math.sin(phi)
    dx, dy = (x0 - x1) / 2, (y0 - y1) / 2
    px, py = c * dx + s * dy, -s * dx + c * dy
    lam = px * px / (rx * rx) + py * py / (ry * ry)
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * py * py - ry * ry * px * px
    den = rx * rx * py * py + ry * ry * px * px
    k = math.sqrt(max(0.0, num / den)) * (-1 if bool(large) == bool(sweep) else 1)
    cxp, cyp = k * rx * py / ry, -k * ry * px / rx
    cx, cy = c * cxp - s * cyp + (x0 + x1) / 2, s * cxp + c * cyp + (y0 + y1) / 2
    a0 = math.atan2((py - cyp) / ry, (px - cxp) / rx)
    a1 = math.atan2((-py - cyp) / ry, (-px - cxp) / rx)
    da = a1 - a0
    if sweep and da < 0:
        da += 2 * math.pi
    elif not sweep and da > 0:
        da -= 2 * math.pi
    n = max(4, int(math.ceil(abs(da) / (math.pi / 16))))
    out = []
    for i in range(1, n + 1):
        a = a0 + da * i / n
        out.append((cx + rx * math.cos(a) * c - ry * math.sin(a) * s, cy + rx * math.cos(a) * s + ry * math.sin(a) * c))
    out[-1] = (x1, y1)
    return out


def _cubic(p0, p1, p2, p3, n=20):
    out = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        out.append((u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
                    u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]))
    return out


def parse_path(data):
    """SVG / XAML path data as lines: a list of (points, closed), curves and arcs cut into short lines."""
    tokens = [(m.group(1), m.group(2)) for m in _TOKEN.finditer(data)]
    subs, cur, at, start, i, command, last_ctrl = [], [], (0.0, 0.0), (0.0, 0.0), 0, None, None

    def numbers(count):
        nonlocal i
        got = []
        while len(got) < count:
            if i >= len(tokens) or tokens[i][1] is None:
                raise ValueError("path data ends inside a command")
            got.append(float(tokens[i][1]))
            i += 1
        return got

    def end(closed):
        nonlocal cur
        if len(cur) > 1:
            subs.append((cur, closed))
        cur = []

    while i < len(tokens):
        if tokens[i][0] is not None:
            command = tokens[i][0]
            i += 1
            if command in "Zz":
                end(True)
                at = start
                cur = [at]
                last_ctrl = None
                continue
        elif command is None:
            raise ValueError("path data starts with a number")
        rel = command.islower()
        op = command.upper()
        if op == "M":
            x, y = numbers(2)
            end(False)
            at = (at[0] + x, at[1] + y) if rel else (x, y)
            start, cur, last_ctrl = at, [at], None
            command = "l" if rel else "L"   # (the pairs after a move are lines)
            continue
        if op == "L":
            x, y = numbers(2)
            at = (at[0] + x, at[1] + y) if rel else (x, y)
            cur.append(at)
        elif op == "H":
            (x,) = numbers(1)
            at = (at[0] + x, at[1]) if rel else (x, at[1])
            cur.append(at)
        elif op == "V":
            (y,) = numbers(1)
            at = (at[0], at[1] + y) if rel else (at[0], y)
            cur.append(at)
        elif op in "CS":
            if op == "C":
                x1, y1, x2, y2, x, y = numbers(6)
                if rel:
                    x1, y1 = at[0] + x1, at[1] + y1
            else:
                x2, y2, x, y = numbers(4)
                x1, y1 = (2 * at[0] - last_ctrl[0], 2 * at[1] - last_ctrl[1]) if last_ctrl else at
            if rel:
                x2, y2, x, y = at[0] + x2, at[1] + y2, at[0] + x, at[1] + y
            cur.extend(_cubic(at, (x1, y1), (x2, y2), (x, y)))
            at, last_ctrl = (x, y), (x2, y2)
            continue
        elif op == "Q":
            x1, y1, x, y = numbers(4)
            if rel:
                x1, y1, x, y = at[0] + x1, at[1] + y1, at[0] + x, at[1] + y
            c1 = (at[0] + 2 / 3 * (x1 - at[0]), at[1] + 2 / 3 * (y1 - at[1]))
            c2 = (x + 2 / 3 * (x1 - x), y + 2 / 3 * (y1 - y))
            cur.extend(_cubic(at, c1, c2, (x, y)))
            at = (x, y)
        elif op == "A":
            rx, ry, turn, large, sweep, x, y = numbers(7)
            if rel:
                x, y = at[0] + x, at[1] + y
            cur.extend(_arc(at[0], at[1], rx, ry, turn, large, sweep, x, y))
            at = (x, y)
        else:
            raise ValueError("path command %s is not drawn here" % command)
        last_ctrl = None
    end(False)
    return subs


def _placed(subs, sx, sy, tx, ty):
    return [(np.asarray(points, dtype=np.float64) * (sx, sy) + (tx, ty), closed) for points, closed in subs]


def fill(subs, w, h, evenodd=False, ss=4):
    """How much of each pixel the shape covers (h x w, 0..1): each row cut into ss lines, each line's spans exact across."""
    w, h = int(w), int(h)
    xa, ya, xb, yb, turn = [], [], [], [], []
    for points, _closed in subs:
        p, q = points, np.roll(points, -1, axis=0)   # (a fill closes every figure)
        down = q[:, 1] > p[:, 1]
        level = q[:, 1] == p[:, 1]
        top = np.where(down[:, None], p, q)[~level]
        bottom = np.where(down[:, None], q, p)[~level]
        xa.append(top[:, 0]); ya.append(top[:, 1]); xb.append(bottom[:, 0]); yb.append(bottom[:, 1])
        turn.append(np.where(down, 1, -1)[~level])
    edge = np.zeros((h, w + 2))
    step = np.zeros((h, w + 2))
    if not xa:
        return np.zeros((h, w), dtype=np.float32)
    xa, ya, xb, yb, turn = (np.concatenate(v) for v in (xa, ya, xb, yb, turn))
    slope = (xb - xa) / (yb - ya)
    first = max(0, int(math.floor(ya.min() * ss)))
    last = min(h * ss, int(math.ceil(yb.max() * ss)))
    for line in range(first, last):
        y = (line + 0.5) / ss
        on = (ya <= y) & (y < yb)
        if not on.any():
            continue
        xs = xa[on] + (y - ya[on]) * slope[on]
        order = np.argsort(xs, kind="stable")
        xs = xs[order]
        if evenodd:
            n = len(xs) // 2 * 2
            a, b = xs[0:n:2], xs[1:n:2]
        else:
            wind = np.cumsum(turn[on][order])
            before = np.concatenate(([0], wind[:-1]))
            a, b = xs[(before == 0) & (wind != 0)], xs[(before != 0) & (wind == 0)]
            n = min(len(a), len(b))
            a, b = a[:n], b[:n]
        a, b = np.clip(a, 0, w), np.clip(b, 0, w)
        ia, ib = np.floor(a).astype(int), np.floor(b).astype(int)
        row = line // ss
        # (a span from a to b: the pixel a is in holds what is right of a, every pixel after it is whole, until b takes
        # the same away)
        np.add.at(edge[row], ia, ia + 1 - a)
        np.add.at(step[row], ia + 1, 1.0)
        np.add.at(edge[row], ib, -(ib + 1 - b))
        np.add.at(step[row], ib + 1, -1.0)
    cover = (edge + np.cumsum(step, axis=1))[:, :w] / ss
    return np.clip(cover, 0, 1).astype(np.float32)


def stroke(subs, w, h, width):
    """A line of that width along the figures, its ends and corners round (h x w, 0..1)."""
    w, h = int(w), int(h)
    ys, xs = np.mgrid[0:h, 0:w]
    px, py = xs + 0.5, ys + 0.5
    best = np.full((h, w), 1e9)
    for points, closed in subs:
        pairs = list(zip(points[:-1], points[1:])) + ([(points[-1], points[0])] if closed else [])
        for (ax, ay), (bx, by) in pairs:
            dx, dy = bx - ax, by - ay
            length = dx * dx + dy * dy
            t = np.clip(((px - ax) * dx + (py - ay) * dy) / length, 0, 1) if length > 0 else 0
            best = np.minimum(best, np.hypot(px - ax - t * dx, py - ay - t * dy))
    return np.clip(width / 2 + 0.5 - best, 0, 1).astype(np.float32)


def rounded(w, h, r):
    """A box with round corners (a pill when r is half its height)."""
    w, h = int(w), int(h)
    r = min(r, w / 2, h / 2)
    ys, xs = np.mgrid[0:h, 0:w]
    qx = np.abs(xs + 0.5 - w / 2) - (w / 2 - r)
    qy = np.abs(ys + 0.5 - h / 2) - (h / 2 - r)
    dist = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r
    return np.clip(0.5 - dist, 0, 1).astype(np.float32)


def tinted(mask, color, alpha=1.0):
    """An image of one colour: RGBA bytes (h x w x 4), its alpha the mask's."""
    h, w = mask.shape
    out = np.empty((h, w, 4), dtype=np.uint8)
    out[..., 0], out[..., 1], out[..., 2] = color
    out[..., 3] = np.clip(mask * alpha * 255 + 0.5, 0, 255).astype(np.uint8)
    return out


def over(under, mask, color, alpha=1.0, at=(0, 0)):
    """color laid over under (h x w x 3, float) through mask, at (x, y); what falls outside is cut."""
    x, y = int(at[0]), int(at[1])
    h, w = mask.shape
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, under.shape[1]), min(y + h, under.shape[0])
    if x1 <= x0 or y1 <= y0:
        return
    m = (mask[y0 - y:y1 - y, x0 - x:x1 - x] * alpha)[..., None]
    part = under[y0:y1, x0:x1]
    part += (np.asarray(color, dtype=np.float32) - part) * m


# ---- PNG: written for Tk to read, and the launcher's own picture read back ----
def _chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def png(pixels, level=1, sub=False):
    """PNG bytes of h x w x 3 or h x w x 4 bytes. sub: each row as its difference from the pixel before (the picture: smaller)."""
    pixels = np.ascontiguousarray(pixels, dtype=np.uint8)
    h, w, n = pixels.shape
    rows = np.empty((h, 1 + w * n), dtype=np.uint8)
    if sub:
        rows[:, 0] = 1
        flat = pixels.reshape(h, w * n)
        rows[:, 1:1 + n] = flat[:, :n]
        rows[:, 1 + n:] = flat[:, n:] - flat[:, :-n]
    else:
        rows[:, 0] = 0
        rows[:, 1:] = pixels.reshape(h, w * n)
    head = struct.pack(">IIBBBBB", w, h, 8, 2 if n == 3 else 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", head) + _chunk(b"IDAT", zlib.compress(rows.tobytes(), level)) + _chunk(b"IEND", b"")


def read_png(path):
    """The pixels (h x w x channels, bytes) of an 8-bit RGB or RGBA PNG whose rows are stored plain, as differences from the
    pixel before, or from the row above: what png() writes, not every PNG there is."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("%s is not a PNG" % path)
    at, packed, w, h, n = 8, [], 0, 0, 0
    try:
        while at < len(data):
            (length,), kind = struct.unpack(">I", data[at:at + 4]), data[at + 4:at + 8]
            body = data[at + 8:at + 8 + length]
            at += 12 + length
            if kind == b"IHDR":
                w, h, depth, color, _c, _f, lace = struct.unpack(">IIBBBBB", body)
                if depth != 8 or color not in (2, 6) or lace:
                    raise ValueError("%s: only 8-bit RGB or RGBA, not interlaced" % path)
                n = 3 if color == 2 else 4
            elif kind == b"IDAT":
                packed.append(body)
            elif kind == b"IEND":
                break
    except struct.error:   # (a file cut short: what is left of a chunk is not one)
        raise ValueError("%s is cut short" % path)
    if not (w and h and n and packed):
        raise ValueError("%s has no picture in it" % path)
    rows = np.frombuffer(zlib.decompress(b"".join(packed)), dtype=np.uint8).reshape(h, 1 + w * n)
    kinds, flat = rows[:, 0], rows[:, 1:].copy()
    if (kinds > 2).any():
        raise ValueError("%s: its rows use a filter this reader does not undo" % path)
    for row in np.nonzero(kinds == 1)[0]:
        flat[row] = np.cumsum(flat[row].reshape(w, n), axis=0, dtype=np.uint8).reshape(-1)
    for row in np.nonzero(kinds == 2)[0]:
        if row:
            flat[row] += flat[row - 1]
    return flat.reshape(h, w, n)


# ---- what the launcher is made of ----
WORDMARK_TOP = 59   # (the drawing's: the letters' box from the window's top, centred across it)


def wordmark(scale):
    """The letters 416 wide: how much of each pixel they cover (h x w, 0..1)."""
    x, y, bw, bh = WORDMARK_BOX
    k = 416 * scale / bw
    w, h = int(math.ceil(bw * k)), int(math.ceil(bh * k))
    letters = np.zeros((h, w), dtype=np.float32)
    for data in WORDMARK:
        letters = np.maximum(letters, fill(_placed(parse_path(data), k, k, -x * k, -y * k), w, h, evenodd=True))
    return letters


def background(w, h, scale):
    """The window behind everything: the page's colour and the white wordmark, w x h pixels (bytes, h x w x 3). (No picture of
    the game ships with the launcher, which is the game's art: original art takes its place here)"""
    base = np.empty((h, w, 3), dtype=np.float32)
    base[:] = PAGE
    over(base, wordmark(scale), WHITE, at=(int(round((w - 416 * scale) / 2)), int(round(WORDMARK_TOP * scale))))
    return np.clip(base + 0.5, 0, 255).astype(np.uint8)


def strip(scale, color=PLAY, alpha=1.0, width=257, height=98):
    """Play's torn strip, 257 x 98 (RGBA; Update beside it, 150 x 72: the same shape stretched, as the Windows launcher's
    Path with Stretch="Fill"). alpha: the whole of it, as Paper's opacity (0.2 while it cannot be pressed)."""
    subs = parse_path(STRIP)
    w, h = int(round(width * scale)), int(round(height * scale))
    mask = fill(_placed(subs, w / 257.0, h / (217.407 - 118.999), -254 * w / 257.0, -118.999 * h / (217.407 - 118.999)), w, h)
    return tinted(mask, color, alpha)


def pill(w, h, scale, color=(0, 0, 0), alpha=1.0, radius=None):
    """A round-ended button's ground, w x h in the drawing's units."""
    w, h = int(round(w * scale)), int(round(h * scale))
    return tinted(rounded(w, h, (radius * scale) if radius is not None else h / 2), color, alpha)


def mark(name, scale, color=(255, 255, 255)):
    box, data = MARKS[name]
    n = int(round(box * scale))
    return tinted(stroke(_placed(parse_path(data), scale, scale, 0, 0), n, n, 1.5 * scale), color)


def dot(scale, color=PLAY):
    n = int(round(8 * scale))
    return tinted(rounded(n, n, n / 2), color)


def github(scale, alpha=1.0):
    n = int(round(32 * scale))
    return tinted(fill(_placed(parse_path(GITHUB), 64 * scale, 64 * scale, -496 * scale, -496 * scale), n, n), (255, 255, 255), alpha)


def discord(scale, alpha=1.0):
    n = int(round(32 * scale))
    disc = rounded(n, n, n / 2) * 1.0
    glyph = fill(_placed(parse_path(DISCORD), scale, scale, -496 * scale, -496 * scale), n, n, evenodd=True)
    base = np.zeros((n, n, 3), dtype=np.float32)
    base[:] = BLURPLE
    over(base, glyph, (255, 255, 255))
    out = np.empty((n, n, 4), dtype=np.uint8)
    out[..., :3] = np.clip(base + 0.5, 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(disc * alpha * 255 + 0.5, 0, 255).astype(np.uint8)
    return out


def bar(w, h, scale):
    """The menu: a panel from the left, black at 96% (#000000F5), with a line #303030 down its right edge (RGBA, w units wide
    with the line, h pixels high)."""
    w = int(round(w * scale))
    out = np.zeros((int(h), w, 4), dtype=np.uint8)
    out[..., 3] = 0xF5
    line = max(1, int(round(scale)))
    out[:, w - line:, :3] = 0x30
    out[:, w - line:, 3] = 255
    return out
