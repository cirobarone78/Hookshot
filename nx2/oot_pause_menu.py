"""A sixth button on the pause menu's Menu page, "Recomp Options", that opens the Insert menu: the calls into
host/oot_pause_menu.c, put into the lifted C (nx2/oot_patches.py apply, for the build of LIFE_BUILD_ID). Its pane is the layout's
(nx2/pause_layout.py).

All or none: every edit's text is looked for in the whole lift first, and the edits are made only when each is found
exactly once.
"""


def head(fn):
    return "void f_%s(Ctx *__restrict A64_NOESC c) {\n" % fn


def renamed(fn, body):
    """The function's own body kept as f_<fn>_game, and f_<fn> the host's call (which runs f_<fn>_game itself). The call's
    line is the function's definition line (nx2/lifted_c.py HEAD), so split_hot keeps both together; the _game names are
    declared at the top (DECL), in every piece"""
    return ("void f_%s(Ctx *__restrict A64_NOESC c) { %s }   /* (nx2/oot_pause_menu.py) */\n"
            "void f_%s_game(Ctx *__restrict A64_NOESC c) {\n") % (fn, body, fn)


def at_entry(fn, call):
    return head(fn) + "    %s   /* (nx2/oot_pause_menu.py) */\n" % call


# (old text, new text): each found once in the whole lift
EDITS = [
    # the pause menu's Menu page made (f_80f99400: its five buttons Pa_Button_00..04 of PaSystemMenu_00): the sixth after them
    (head("80f99400"), renamed("80f99400", "hos_pausebtn_build(c, f_80f99400_game);")),
    # a button's state changes (f_80ad5310(control, state)): the sixth button's control noted, to know when the cursor is on it
    (head("80ad5310"), at_entry("80ad5310", "if (hos_pausebtn_state(c)) return;")),
    # the page destroyed (f_80aa2ad0, the base of its destructor, shared with other screens): the sixth button forgotten
    (head("80aa2ad0"), at_entry("80aa2ad0", "hos_pausebtn_gone(c);")),
]
DECL = ("void f_80f99400_game(Ctx *__restrict A64_NOESC c);\n"
        "void hos_pausebtn_build(Ctx *c, A64Fn game);\n"
        "int hos_pausebtn_state(Ctx *c);\n"
        "void hos_pausebtn_gone(Ctx *c);\n")
INCLUDE = '#include "a64.h"\n'
MARK = "(nx2/oot_pause_menu.py)"


def count(texts):
    """How many times each edit is to be made, or was, over the files' texts (one already edited counts its new text)"""
    return [sum(t.count(new) if MARK in t else t.count(old) for t in texts) for old, new in EDITS]


def edit(text):
    """One file's text with the edits it holds made (the others are left to the files that hold them)"""
    if MARK in text:
        return text   # (edited before)
    out = text
    for old, new in EDITS:
        if out.count(old) == 1:
            out = out.replace(old, new, 1)
    if out != text:
        out = out.replace(INCLUDE, INCLUDE + DECL, 1)
    return out
