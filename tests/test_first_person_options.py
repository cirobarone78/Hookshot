"""First person's eye is placed by two sliders of the Controls tab, and they apply while he walks.

Reads the sources: the option ids and the comment's count in vk_api.h, the rows and their scales in vk_menu.cpp (a row
is kept in hookshot_options.ini as its name, so their keys are the rows' names), the renderer's option answers the host
gives them, and host/hos_first_person.c reading both rows at every view — live, as the Camera speed row is at each
present — with HOS_FP_UP and HOS_FP_FORWARD still winning for a run.
python -I -B tests/test_first_person_options.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def block(text, start):
    """the statement that starts at `start`, braces balanced"""
    opening = text.index("{", start)
    depth = 0
    for at in range(opening, len(text)):
        depth += text[at] == "{"
        depth -= text[at] == "}"
        if depth == 0:
            return text[start:at + 1]
    raise SystemExit("unterminated block at %d" % start)


def main():
    api = (ROOT / "gpu" / "vk" / "vk_api.h").read_text(encoding="utf-8")
    menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
    header = (ROOT / "gpu" / "vk" / "vk_menu.h").read_text(encoding="utf-8")
    replay = (ROOT / "gpu" / "vk" / "vk_replay.cpp").read_text(encoding="utf-8")
    fp = (ROOT / "host" / "hos_first_person.c").read_text(encoding="utf-8")
    readme = (ROOT / "readme.md").read_text(encoding="utf-8")

    # the ids, free on main: FOV has 51, and 49 and 50 are reserved for Walk mode and Walk speed (#2345)
    ids = {}   # (every HOS_OPT_* enum, names that follow a first one counted up from it)
    for first, start, rest in re.findall(r"enum \{ (HOS_OPT_\w+) = (\d+)(?:, ([^}]*))? \}", api):
        names = [first] + [n.strip() for n in (rest or "").split(",") if n.strip()]
        ids.update({n: int(start) + i for i, n in enumerate(names)})
    if (ids.get("HOS_OPT_FP_HEIGHT"), ids.get("HOS_OPT_FP_OFFSET")) != (52, 53):
        raise SystemExit("first person's rows are not options 52 and 53: %s" % ids)
    table = block(replay, replay.index("t.option = [](int id) -> int {"))
    for name, field in (("HOS_OPT_FP_HEIGHT", "fp_height"), ("HOS_OPT_FP_OFFSET", "fp_offset")):
        if "if (id == %s) return opts.%s;" % (name, field) not in table:
            raise SystemExit("the host cannot see the %s row" % name)
    read = [int(n) if n.isdigit() else ids[n] for n in re.findall(r"\bid == (\w+)", table)]
    if len(read) != len(set(read)):
        raise SystemExit("vk_replay.cpp: an option id is read twice: %s" % sorted(read))

    # the rows: beside the switch, in hundredths of a metre, scales that stop at their ends
    for row in ('{TAB_CONTROLS, "First person height", &opts.fp_height, 50, 250, 5, tx_metres,',
                '{TAB_CONTROLS, "First person offset", &opts.fp_offset, 0, 100, 5, tx_metres,'):
        if row not in menu:
            raise SystemExit("the Controls tab lost a first person row: " + row)
        if not block(menu, menu.index(row)).rstrip().endswith("nullptr, false, true}"):
            raise SystemExit(row.split('"')[1] + " takes a restart or turns the Quality preset")
    for fn in ("bool is_slider(", "bool stops_at_ends("):
        line = menu[menu.index(fn):menu.index("\n", menu.index(fn))]
        for field in ("fp_height", "fp_offset"):
            if "&opts.%s" % field not in line:
                raise SystemExit("%s does not take the %s row: a scale" % (fn.split("(")[0], field))
    if "int fp_height = 150;" not in header or "int fp_offset = 15;" not in header:
        raise SystemExit("out of the box the eye is not 1.50 m up, 0.15 m along the view")
    # (a row is saved under its name: the two keys are the rows' names, and no other row's)
    keys = [name.lower().replace(" ", "_") for name in re.findall(r'\{TAB_[A-Z]+, "([^"]+)", &opts\.', menu)]
    if keys.count("first_person_height") != 1 or keys.count("first_person_offset") != 1:
        raise SystemExit("the rows are not saved as first_person_height and first_person_offset")

    # live: the rows are read at every view, the environment over them for a run
    for fn, name, least in (("fp_up", "HOS_OPT_FP_HEIGHT", 150), ("fp_forward", "HOS_OPT_FP_OFFSET", 15)):
        body = block(fp, fp.index("static double %s(void) {" % fn))
        if "rx_option(%s, %d)" % (name, least) not in body:
            raise SystemExit("%s does not read the menu's row" % fn)
        if body.index("rx_option") < body.index("getenv") or "return forced" not in body:
            raise SystemExit("%s caches the menu's row, or the environment does not win" % fn)
    # the rest tilt's correction, no row of its own: HOS_FP_PITCH over the default for a run, and clamped at the camera's
    # own up limit so it never points above where the game would
    pitch = block(fp, fp.index("static double fp_pitch_correct(void) {"))
    if 'getenv("HOS_FP_PITCH")' not in pitch or "0.12" not in pitch:
        raise SystemExit("the pitch correction is not HOS_FP_PITCH over a 0.12 default")
    if "LIMITS_AT" not in fp or "pitch < least" not in fp:
        raise SystemExit("the corrected pitch is not clamped at the camera's own up limit")
    if "| | First person height | 0.50 m to 2.50 m, in steps of 0.05 | 1.50 m |" not in readme or \
       "| | First person offset | 0.00 m to 1.00 m, in steps of 0.05 | 0.15 m |" not in readme:
        raise SystemExit("readme.md's option table has no first person place rows")
    print("PASS: first person's eye height and offset are the menu's, live")


if __name__ == "__main__":
    main()
