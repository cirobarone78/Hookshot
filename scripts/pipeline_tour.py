"""The pipeline tour: plays the game unattended, from a new save through every debug Teleport destination as child and as
adult, with the items, their effects and the menus, so that its graphics pipelines are met and written to the pipeline state list
(gpu/vk/vk_draw.cpp: hookshot_pipeline_states.bin). The parts' lists become the tour's source of the list a release ships,
assets/pipeline_states/tour.bin.xz (nx2/pipeline_states.py tour): the first start prepares those pipelines before the title.

    python -I scripts/pipeline_tour.py tour --game <game folder> --out <dir> [--name play] [--parts ...] [--publish] [--env ...] [--ini ...]
    python -I scripts/pipeline_tour.py run  --game <game folder> --out <dir> [--name play] [--part <part>] [--first <stop>] [--stops N]
                                            [--skip-opening] [--env NAME=VALUE ...] [--ini key=value ...] [--window WxH] [--dry-run]
    python -I scripts/pipeline_tour.py merge --out <file> <list> ...
    python -I scripts/pipeline_tour.py report <out>/<name>

run: one game. The game folder is used as it is, so give it a copy (cp -a --reflink=always): its hookshot_pipelines.bin (the pipeline
notes), hookshot_pipeline_states.bin and hookshot_pipeline_states_shipped.bin are moved aside for the run (a precompiled pipeline is
not noted again, and only what this run meets counts) and put back after it. The run starts with no save at all (an empty data folder
of its own, <out>/<name>/data): the title, New Game, the opening, then control of Link, checked by the game accepting a teleport.
Then every item (the Debug tab's inventory), the pause menu's pages, and each destination: the teleport, its loading, the camera all
around, the sword, the shield and an item, until no new pipeline came for a while. Everything is driven through the live input file
(HOS_INPUT_LIVE) and its "!cheat <action>" lines, the Insert menu's Debug tab actions; nothing reaches the desktop, and no
controller is opened (HOS_NO_SDL). Waits are counted in the game's frames (RX_VK_FRAME_LOG) and the presses' times too
(HOS_INPUT_FRAME_CLOCK), so the game can run faster than real time: no window (HOS_HEADLESS), the smallest output (640x360: a
pipeline's key has formats and state, not sizes), frame pacing off, the rate cap at 240 with a 60th of a second of game time a
frame (HOS_FPS_MAX=240, HOS_FPS_STEP=0): fps / 60 times real time. Each step has a limit: a step that does not happen fails the run, it does not wander.
--env and --ini run it under other settings (RX_VK_FORCE_MESH_FALLBACK=1, dlss=0, hdr=1, HOS_HANDHELD=1); the options file is
restored. --window shows it on a Sway workspace instead.

tour: the parts one after another, one game at a time, in a reflinked copy of the game folder, in games of --chunk stops (a
fresh game each), at nice 19 on --cpus, each under the memory guard (MEM: it waits for memory before a game, and ends a game that
holds too much or leaves the machine too little, the next game going on from there; on Linux the game runs in a systemd scope
with a MemoryMax), --lock NAME: each game under oot-status's lock; merged; --publish writes the repository's tour list from
them (nx2/pipeline_states.py tour, with the GPU, build, settings and route the runs logged).

value: each step's pipelines over runs that the players' lists (the shipped list's contrib/ sources) and the other steps do not
have, its seconds, and which steps add too little to keep.

Each run writes <out>/<name>/: states.bin (its list), report.txt and report.json (the pipelines and programs after each step, the new
ones each added, its frames and wall time), log.txt (the game's log) and steps.txt (what was sent, at which frame).

Standard library only. The actions' numbers come from host/hos_main.c, gpu/vk/oot_cheat_items.h and gpu/vk/vk_menu.cpp.
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILES = ("hookshot_pipelines.bin", "hookshot_pipeline_states.bin", "hookshot_pipeline_states_shipped.bin")
LIST = "hookshot_pipeline_states.bin"

# no window, no sound, no controller, no pacing, game time a frame per frame with the rate cap at 240, the smallest output,
# the script's input alone, text at once, no frame generation
BASE_ENV = {
    "HOS_HEADLESS": "1",
    "HOS_NO_SDL": "1",
    "HOS_AUDIO": "0",
    "HOS_INPUT_EXCLUSIVE": "1",
    "HOS_INPUT_SCRIPT_BACKGROUND": "1",
    "HOS_INPUT_FRAME_CLOCK": "1",
    "HOS_OOT_CHEATS": "1",
    "HOS_OOT_PROTECT_HEARTS": "1",
    "HOS_NO_PACING": "1",
    "HOS_REALTIME_STEP": "0",
    "HOS_FPS_MAX": "240",
    "HOS_FPS_STEP": "0",
    "HOS_FPS_TARGET": "240",
    "HOS_FPS_LOG": "1",
    "HOS_OUTPUT_RES": "640x360",
    "HOS_TEXT_SPEED": "3",
    "HOOKSHOT_NO_UPDATE_CHECK": "1",
    "HOS_DISCORD": "0",
    "RX_VK_FRAMEGEN": "0",
    "HOS_RT_POOL_MB": "320",     # (render target pool: 640x360 needs far less than the default 512 MB)
    "RX_VK_SHOT_EVERY": "600",   # (with RX_VK_SHOTS, set per run: a small picture every 600 frames, to see where a run got stuck)
    "RX_VK_SHOT_W": "320",
    "RX_VK_SHOT_H": "180",
}
FPS = 60   # (the game's frames a second of game time: the presses' clock)
# the options for the run (its own copy of hookshot_options.ini, restored after it): the cheapest of each that does not take passes or
# formats away. The output 640x360 (as HOS_OUTPUT_RES), the upscaler the game's own (dlss=0), render scale 50%, no frame generation, sharpening or HDR, text at once. The
# speed is the environment's (BASE_ENV): the cap at 240 (HOS_FPS_MAX: the vsync events and the game's limiter) with every frame a
# 60th of a second of game time (HOS_FPS_STEP=0: host/nn_vi.c realtime_step), so the game runs fps / 60 times faster than real time
BASE_INI = {"output_res": "640x360", "dlss": "0", "upscaling": "0", "resolution": "4", "frame_generation": "0", "sharpness": "0", "hdr": "0",
            "frame_rate_cap": "0", "game_speed": "0", "text_speed": "3", "fps_counter": "0", "frame_pacing": "0",
            "discord_status": "0"}


# ---- the Debug tab's actions, as the source has them ----

def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


def define(text, name):
    m = re.search(r"#define\s+%s\s+(\d+)" % name, text)
    if not m:
        raise SystemExit("pipeline_tour: %s not found" % name)
    return int(m.group(1))


def bancs(main):
    """Each destination's maps, child and adult (None: none), as host/hos_main.c's oot_destinations has them"""
    table = main.split("oot_destinations[] = {", 1)[1].split("\n};", 1)[0]
    q = r'(NULL|"[^"]*")'
    out = []
    for m in re.finditer(r"\{%s,\s*%s,\s*%s,\s*%s," % (q, q, q, q), table):
        out.append(tuple(None if v == "NULL" else v.strip('"') for v in (m.group(1), m.group(4))))
    return out


def actions(root_read=read):
    """The action numbers and the lists they index: {teleport, age, item, teleports: [(name, adult_only)], items: {pouch name: index}}"""
    main, items_h, menu = root_read("host/hos_main.c"), root_read("gpu/vk/oot_cheat_items.h"), root_read("gpu/vk/vk_menu.cpp")
    names = re.search(r"teleport_names\[\]\s*=\s*\{(.*?)\};", menu, re.S)
    notes = re.search(r"teleport_notes\[\]\s*=\s*\{(.*?)\};", menu, re.S)
    if not names or not notes:
        raise SystemExit("pipeline_tour: the teleport list not found in gpu/vk/vk_menu.cpp")
    labels = re.findall(r'"((?:[^"\\]|\\.)*)"', names.group(1))
    note_list = [n.strip() for n in notes.group(1).split(",")]
    destinations = len(re.findall(r"\},\s*/\*", main.split("oot_destinations[]", 1)[1].split("};", 1)[0]))
    if destinations != len(labels) or len(note_list) != len(labels):
        raise SystemExit("pipeline_tour: %d teleport names, %d notes, %d destinations" % (len(labels), len(note_list), destinations))
    items = re.findall(r'OOT_ITEM\("[^"]*",\s*"([^"]+)",\s*(\d)\)', items_h)
    return {
        "teleport": define(main, "OOT_TELEPORT_ACTION"),
        "age": define(main, "OOT_AGE_ACTION"),
        "state": define(main, "OOT_STATE_ACTION"),
        "bancs": bancs(main),
        "item": define(items_h, "OOT_CHEAT_ITEM_ACTION"),
        "teleports": [(label, "adult only" in note) for label, note in zip(labels, note_list)],
        "dungeons": int(re.search(r'\{"Dungeons", (\d+)\}', menu).group(1)),
        "items": {name: (i, int(kind)) for i, (name, kind) in enumerate(items)},
    }


QUEST_ITEMS = ("Item_Medal_", "Item_Stone_", "Item_Melody_")
# Stops left out: a scene starts there that waits for something the tour does not do, and the map can then not be left
LEFT_OUT = {("adult", "Sacred Forest Meadow"): "Sheik's lesson starts on arrival and waits for the ocarina to be played",
            # (runs 2-4, ~/.cache/hookshot-work/tour/route-value.txt: what only these met, against everything else)
            ("child", "Lost Woods"): "20 pipelines no other stop met", ("adult", "Lost Woods"): "7",
            ("child", "Sacred Forest Meadow"): "4",
            # (pipeline_tour.py value over runs 2-4 and the short runs: what each stop met that neither the players' lists in
            # assets/pipeline_states/contrib nor any other kept stop has; under 10 is not worth the stop's 15-30 s)
            ("adult", "Kokiri Forest"): "4 pipelines no other stop or player's list has", ("child", "Graveyard"): "4",
            ("child", "Death Mountain Crater"): "4 (the gameover part still goes there)", ("adult", "Shadow Temple"): "2",
            ("adult", "Dodongo's Cavern"): "6", ("adult", "Gerudo Training Ground"): "7", ("adult", "Haunted Wasteland"): "7",
            ("child", "Ice Cavern"): "6", ("child", "Ganon's Castle"): "9", ("child", "Spirit Temple"): "4"}
# Rooms no Teleport destination reaches, by the game's own map and start position names ("!teleport <map> <start>": host/hos_main.c):
# the boss arenas and the sages' rooms, and the boss rush's rooms (DreamWorld). The "extras" part visits them, the child ones
# first; it is not one of the tour's default parts. (label, map, start position, age)
# Measured (a short run): Gohma_BattleStartPos loads the Deku Tree but the picture stays black, and no teleport is taken from there
# after ("result 0", as in the Haunted Wasteland); the run added 36 pipelines the tour list lacked. These are the events' own start
# positions, not the entrances' (NextStartPos): each wants its own arrival event, still to find. Until then each needs a game of
# its own (--part extras --first <label> --stops 1)
EXTRAS = [
    ("Gohma's room", "InsideTheDekuTree", "Gohma_BattleStartPos", "child"),
    ("Deku Tree, after Gohma", "InsideTheDekuTree", "StartPos_Get_StoneOfForest", "child"),
    ("King Dodongo's room", "DodongoCavern", "StartPos_Get_StoneOfFire", "child"),
    ("Barinade's room", "InsideJabuJabuBelly", "StartPos_StoneOfWater", "child"),
    ("Big Octo's room", "InsideJabuJabuBelly", "StartPos_Get_StoneOfWater_MiddleBoss", "child"),
    ("Boss rush", "DreamWorld", "StartPos_SubEvent_AllBossBattle", "child"),
    ("Phantom Ganon's room", "ForestTemple", "StartPos_SageOfForest", "adult"),
    ("Volvagia's room", "FireTemple", "StartPos_SageOfFire", "adult"),
    ("Morpha's room", "WaterTemple", "StartPos_SageOfWater", "adult"),
    ("Dark Link's room", "WaterTemple", "StartPos_SageOfWater_MiddleBoss", "adult"),
    ("Bongo Bongo's room", "ShadowTemple", "StartPos_SageOfShadow", "adult"),
    ("Shadow Temple's ship", "ShadowTemple", "StartPos_SageOfShadow_BattleOnShip", "adult"),
    ("Twinrova's room", "SpiritTemple", "StartPos_SageOfSpirit", "adult"),
    ("Ganondorf's room", "GanonCastle", "RestartPos_Ganondorf_BossBattle", "adult"),
    ("Ganon's arena", "GanonCastle", "FinalBattle_BossInStartPos", "adult"),
]
# The same rooms with the boss's own entrance scene as the arrival event (the teleport's third word: "!teleport <map> <start>
# <event>", in place of Dm_SY_BancChangeArrive), to try: --part extras --first "<label>, its entrance scene" --stops 1
BOSS_IN = {"Gohma's room": "Dm_Deku_BossIn", "King Dodongo's room": "Dm_DodongoCave_BossIn",
           "Barinade's room": "Dm_InsideJabu_Jabu_BossIn", "Phantom Ganon's room": "Dm_ForestTemple_BossIn",
           "Volvagia's room": "Dm_FireTemple_BossIn", "Morpha's room": "Dm_WaterTemple_BossIn",
           "Bongo Bongo's room": "Dm_ShadowTemple_BossIn", "Twinrova's room": "Dm_SpiritTemple_BossIn",
           "Ganondorf's room": "Dm_InsideGanonCastle_BossIn", "Ganon's arena": "Dm_FinalBattle_BossIn"}
EXTRAS += [(label + ", its entrance scene", banc, start, age) for label, banc, start, age in list(EXTRAS) if label in BOSS_IN]
# Game Over: the "gameover" part (its own run: hearts are not protected there) takes Link, a child, to the crater, whose heat
# empties his hearts; A now and then chooses Continue on the Game Over screen
GAME_OVER_AT = "Death Mountain Crater"
GAME_OVER_FRAMES = 60 * 75     # (the heat takes a child's three hearts in ~45 s; Try Again, back in the crater by ~60 s)
GAME_OVER_PRESS_FROM = 60 * 40
# Stops the game does not teleport out of (the request is refused: "result 0"), visited last in their part
LAST = {"Haunted Wasteland"}
# Where Link uses his items and their effects (one picked from the pause menu, a different one each time): a few stops per age,
# not every one. The rest only look around
# Overworld stops seen at night too (the Debug tab's clock: !cheat 100 + hour), then back to noon. Measured on a short run: Hyrule
# Field +4 pipelines at night, Kakariko +10, for ~10 s each: none by default (add names here for a run that wants them)
NIGHT_AT = set()
TIME_ACTION = 100
ACT_AT = {"Kokiri Forest", "Hyrule Field", "Lake Hylia", "Death Mountain Crater", "Zora's Domain", "Gerudo Valley",
          "Inside the Deku Tree", "Fire Temple", "Water Temple", "Shadow Temple"}


def items_unlock(a):
    """Every item Link can have (kind 0: unlocked once), the quantities filled (kind 1: +60)"""
    out = []
    for name, (i, kind) in a["items"].items():
        if name.startswith("Armor_Child_Mask_") and name != "Armor_Child_Mask_Truth":
            continue   # (one mask slot: the last one added is the one kept)
        if name.startswith(QUEST_ITEMS):
            continue   # (the story's flags: medallions, stones and songs start scenes that wait for the player)
        out.append(a["item"] + i * 256 + (200 if kind == 0 else 64 + 60))
    return out


# ---- the route ----
# Presses: <seconds>:<button>[+<button>][/<ms>] (docs/development.md, "Input for scripted runs"), here in game time.
# The buttons as the remake has them: B the sword (held: the spin attack), R the shield, ZL a target, A a roll, ZR the item on the
# item button; PLUS the pause menu, whose pages ZL and ZR turn (Collection, Equipment, Items, System) and B closes; on its Items
# page the stick moves the cursor and A puts the item on the item button.

def presses(items):
    return ",".join("%g:%s" % (t, b) for t, b in items)


LOOK = presses([(0, "RLEFT/1500"), (1.5, "RUP/400"), (1.9, "RRIGHT/700"), (2.6, "RDOWN/700"), (3.3, "RUP/300"),
                (0, "LUP/600"), (0.6, "LDOWN/600")])
LOOK_SPAN = 3.7
ACT = presses([(0, "B"), (0.35, "B"), (0.7, "B/900"), (1.7, "R/500"), (2.3, "ZL/300"), (3.2, "ZR/600"),
               (4, "ZR"), (4.6, "ZR/600")])   # (no A: next to someone it starts a conversation)
# Presses that end what holds a map change back (a conversation, a question, an item's prompt), one every second in turn
UNSTICK = ["0:A/100", "0:B/100", "0:LDOWN/150,0.3:A/100", "0:B/100", "0:LUP/150,0.3:A/100", "0:B/100,0.4:B/100"]
ACT_SPAN = 5.4


def pause_pick(k):
    """The pause menu's pages, then on the Items page the k-th item put on the item button (a cursor walk that differs from stop to
    stop), and closed. ZL three times first: from whatever page it opened on to the first, then ZR twice to Items"""
    seq, t = [(0, "PLUS")], 0.8
    for b in ("ZL", "ZL", "ZL", "ZR", "ZR"):
        seq.append((t, b))
        t += 0.45
    walk = ["LDOWN"] * (k % 5) + ["LRIGHT"] * ((k // 5) % 4)
    for b in walk:
        seq.append((t, b + "/120"))
        t += 0.25
    seq += [(t, "A"), (t + 0.4, "B"), (t + 0.9, "B")]
    return presses(seq), t + 1.3


PAUSE_TOUR = presses([(0, "PLUS"), (0.8, "ZR"), (1.5, "ZR"), (2.2, "ZR"), (2.9, "ZR"), (3.6, "ZL"), (4.3, "ZL"), (5, "ZL"),
                      (5.7, "ZL"), (6.4, "B"), (6.9, "B")])
PAUSE_SPAN = 7.4
PAUSE_PAGES = False   # (measured: 0 pipelines the item stops' own pause menu visits and the players' lists lack, for 8 s)

# Water: at these stops Link arrives swimming; A held dives (the scales are given). As adult the pause menu's Equipment page then
# puts on the iron boots and the Zora tunic (its cursor starts on the Echo Gem in a new game: up is the iron boots, right then down
# the tunics' row), the stop is reached again, and Link walks the lake's bottom; the boots come off after
DIVE_AT = {"Lake Hylia"}
DIVE = presses([(0, "A/4000")])
DIVE_SPAN = 4.5
UNDERWATER_GEAR = presses([(0, "PLUS"), (0.8, "ZL"), (1.2, "ZL"), (1.6, "ZL"), (2.0, "ZR"), (2.6, "UP"), (3.0, "A"), (3.5, "RIGHT"),
                           (3.9, "DOWN"), (4.3, "RIGHT"), (4.7, "RIGHT"), (5.1, "A"), (5.6, "B"), (6.1, "B")])
GEAR_SPAN = 6.6
BOOTS_OFF = presses([(0, "PLUS"), (0.8, "ZL"), (1.2, "ZL"), (1.6, "ZL"), (2.0, "ZR"), (2.6, "LEFT"), (3.0, "LEFT"), (3.4, "LEFT"),
                     (3.8, "A"), (4.3, "B"), (4.8, "B")])   # (from the Zora tunic: left three times is the iron boots again)
BOOTS_SPAN = 5.3


PARTS = ("all", "child", "adult", "opening", "child-overworld", "child-dungeons", "adult-overworld", "adult-dungeons", "dungeons",
         "extras", "gameover")


def plan_stops(a, part="all", stops=None, first=None):
    """The destinations a part visits, in order: [(age, index)]. opening: none (the new game's opening alone, watched whole);
    child-overworld, dungeons (both ages) and adult-overworld split the route in three"""
    adult_only = {i for i, (_, only) in enumerate(a["teleports"]) if only}
    first_dungeon = dungeons_from(a)
    child = [("child", i) for i in range(len(a["teleports"])) if i not in adult_only]
    adult = [("adult", i) for i in range(len(a["teleports"]))]
    over = lambda plan: [(age, i) for age, i in plan if i < first_dungeon]
    under = lambda plan: [(age, i) for age, i in plan if i >= first_dungeon]
    plan = {"all": child + adult, "child": child, "adult": adult, "opening": [], "child-overworld": over(child),
            "dungeons": under(child) + under(adult), "adult-overworld": over(adult), "child-dungeons": under(child),
            "adult-dungeons": under(adult), "extras": [], "gameover": []}[part]
    plan = [(age, i) for age, i in plan if (age, a["teleports"][i][0]) not in LEFT_OUT]
    # (a stop the game will not teleport out of goes last: the next map change after it is the next run's)
    ages = [age for age, _ in plan]
    plan = sorted(plan, key=lambda x: (ages.index(x[0]), a["teleports"][x[1]][0] in LAST))   # (last within its age)
    if first and part not in ("extras", "gameover", "opening"):   # (a run that starts again at a stop: "<name>" or "<name> (<age>)", as the report names them)
        labels = ["%s (%s)" % (a["teleports"][i][0], age) for age, i in plan]
        at = [k for k, (lab, (age, i)) in enumerate(zip(labels, plan)) if first in (lab, a["teleports"][i][0])]
        if not at:
            raise SystemExit("pipeline_tour: no stop %r in this part" % first)
        plan = plan[at[0]:]
    return plan[:stops] if stops is not None else plan


def dungeons_from(a):
    """The first dungeon's index in the teleport list (vk_menu.cpp teleport_sections: "Dungeons")"""
    return a.get("dungeons", len(a["teleports"]))


def route(a, part="all", stops=None, first=None):
    """The steps of a run: ("newgame",), ("items",), ("press", text, span, label), ("age",), ("visit", age, index, k).
    The pause menu's pages once, in the opening part or a whole run"""
    steps = [("newgame",), ("items",)]
    if PAUSE_PAGES and part in ("all", "child", "opening"):
        steps.append(("press", PAUSE_TOUR, PAUSE_SPAN, "pause menu pages"))
    age = "child"
    for k, (want, i) in enumerate(plan_stops(a, part, stops, first)):
        if want != age:
            steps += [("age",), ("items",)]   # (the adult's equipment is only given to the adult: a child's add is lost)
            age = want
        steps.append(("visit", want, i, k))
    if part == "gameover":   # (hearts not protected: the crater's heat takes them, the Game Over screen, Continue)
        steps.append(("gameover", [n for n, _ in a["teleports"]].index(GAME_OVER_AT)))
    if part == "extras":
        extras = [x for x in EXTRAS if x[3] == "child"] + [x for x in EXTRAS if x[3] == "adult"]
        if first:
            at = [k for k, x in enumerate(extras) if x[0] == first]
            if not at:
                raise SystemExit("pipeline_tour: no extra stop %r" % first)
            extras = extras[at[0]:]
        for x in extras[:stops] if stops is not None else extras:
            if x[3] != age:
                steps += [("age",), ("items",)]
                age = x[3]
            steps.append(("extra",) + x)
    return steps


# ---- the list ----

def state_tool():
    spec = importlib.util.spec_from_file_location("pipeline_states", os.path.join(ROOT, "nx2", "pipeline_states.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def list_counts(tool, path):
    """(pipelines, programs, records) of a list, as nx2/pipeline_states.py reads and counts them (whatever its format)"""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return 0, 0, set()
    try:
        recs = tool.read(path)
    except SystemExit:
        return 0, 0, set()
    m = re.search(r"of (\d+) programs", tool.describe(recs))
    return len(recs), int(m.group(1)) if m else 0, set(recs)


# ---- the game ----

# ---- memory ----
# One game holds 4 to 14 GB (the guest memory is shared memory, touched as the game goes, and not given back; the program cache's
# file pages come on top and can be dropped). This PC-wide guard keeps a run from taking the machine down: before a game starts
# there must be MIN_FREE_GB available and at most MAX_SWAP_GB of swap in use (else it waits, WAIT_S at most, then gives up); while
# it runs, the game's own memory (anonymous + shared: what cannot be dropped) and the machine's are read once a second, and
# - past SOFT_MB after a stop: the run ends there and the tour goes on in a fresh game (one game's memory only grows),
# - past HARD_MB, under FLOOR_GB available or past MAX_SWAP_GB + 4 of swap: the game is stopped at once, its list kept, and the
#   tour waits for memory and goes on from the stop it was at.
# On Linux with systemd the game also runs in a scope of its own with MemoryMax (SCOPE_GB) and little swap: should all of that
# fail, the kernel ends the game, not the desktop or the terminal it was started from.
MEM = {"min_free_gb": 8.0, "max_swap_gb": 16.0, "floor_gb": 3.0, "soft_mb": 9000, "hard_mb": 12000, "wait_s": 1800, "scope_gb": 16}


def meminfo(text=None):
    """/proc/meminfo: (GB available, GB of swap in use); (None, None) where there is none"""
    if text is None:
        try:
            with open("/proc/meminfo") as f:
                text = f.read()
        except OSError:
            return None, None
    kb = {}
    for line in text.splitlines():
        k, _, v = line.partition(":")
        if v.strip():
            kb[k] = int(v.split()[0])
    if "MemAvailable" not in kb:
        return None, None
    return kb["MemAvailable"] / 1048576, (kb.get("SwapTotal", 0) - kb.get("SwapFree", 0)) / 1048576


def held_mb(status_text):
    """A process's memory that cannot be dropped, MB (/proc/<pid>/status: RssAnon + RssShmem)"""
    kb = {}
    for line in status_text.splitlines():
        k, _, v = line.partition(":")
        if k in ("RssAnon", "RssShmem", "VmRSS"):
            kb[k] = int(v.split()[0])
    return (kb.get("RssAnon", 0) + kb.get("RssShmem", 0)) // 1024


def start_problem(mem, info):
    """Why a game may not start now (None: it may)"""
    free, swap = info
    if free is None:
        return None
    if free < mem["min_free_gb"]:
        return "%.1f GB available, a game wants %.0f" % (free, mem["min_free_gb"])
    if swap > mem["max_swap_gb"]:
        return "%.1f GB of swap in use, at most %.0f" % (swap, mem["max_swap_gb"])
    return None


def run_problem(mem, info, held):
    """Why a running game must stop at once (None: it may go on)"""
    free, swap = info
    if held is not None and held > mem["hard_mb"]:
        return "the game holds %d MB, at most %d" % (held, mem["hard_mb"])
    if free is not None and free < mem["floor_gb"]:
        return "%.1f GB available, under %.0f" % (free, mem["floor_gb"])
    if swap is not None and swap > mem["max_swap_gb"] + 4:
        return "%.1f GB of swap in use, over %.0f" % (swap, mem["max_swap_gb"] + 4)
    return None


def wait_memory(mem, read=meminfo, sleep=time.sleep, clock=time.monotonic, say=print):
    """Until a game may start: None, or why it still may not after mem["wait_s"]"""
    end, said = clock() + mem["wait_s"], None
    while True:
        why = start_problem(mem, read())
        if why is None:
            return None
        if clock() >= end:
            return why
        if why != said:
            say("pipeline tour: waits for memory: %s" % why, flush=True)
            said = why
        sleep(10)


def scope_prefix(mem, run=subprocess.run):
    """systemd-run's scope for the game (MemoryMax, a little swap), or [] where there is none"""
    if not mem.get("scope_gb") or not shutil.which("systemd-run") or os.environ.get("OOT_NO_SCOPE"):
        return []
    pre = ["systemd-run", "--user", "--scope", "--quiet", "--collect", "-p", "MemoryMax=%dG" % mem["scope_gb"],
           "-p", "MemorySwapMax=2G", "--"]
    try:
        if run(pre + ["true"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20).returncode != 0:
            return []
    except (OSError, subprocess.TimeoutExpired):
        return []
    return pre


class MemoryStop(Exception):
    """The game stopped for memory (not a failure of the route: the tour goes on from `at` in a fresh game)"""
    def __init__(self, why, soft=False):
        Exception.__init__(self, why)
        self.soft = soft


class Failed(Exception):
    pass


class Game:
    """The game, its log and its frames: what was sent, at which frame"""
    def __init__(self, game, data, run_dir, env, dry=False, mem=None, prefix=()):
        self.game, self.run_dir, self.dry = game, run_dir, dry
        self.mem = mem
        self.peak = 0           # (the most the game held, MB: anonymous + shared memory)
        self.checked = 0.0
        self.live = os.path.join(run_dir, "live.txt")
        self.log_path = os.path.join(run_dir, "log.txt")
        self.frames_path = os.path.join(run_dir, "frames.csv")
        self.list_path = os.path.join(game, LIST)
        self.steps = open(os.path.join(run_dir, "steps.txt"), "w", encoding="utf-8")
        self.t0 = time.monotonic()
        self.pos = self.fpos = 0
        self.frame = 0          # (presents so far: the frame log's lines)
        self.draws = 0          # (the last "a frame: N draws")
        self.draw_lines = 0
        self.speed = []         # (the game clock's speeds the log gave: 1.0 is real time)
        self.fps = []           # (the frame rates the same lines gave)
        self.map = None         # (the map the last teleport check named)
        self.marks = []         # (the current step's parts: [(what, records so far)])
        self.proc = None
        if dry:
            return
        open(self.live, "w").close()
        full = dict(os.environ)
        full.update(env)
        full["XDG_DATA_HOME"] = data
        full["HOS_INPUT_LIVE"] = self.live
        full["RX_VK_FRAME_LOG"] = self.frames_path
        exe = os.path.join(game, "bin", "hookshot")
        if not os.path.exists(exe):
            exe = os.path.join(game, "hookshot")
        self.logf = open(self.log_path, "wb")
        self.proc = subprocess.Popen(list(prefix) + [exe], cwd=game, env=full, stdout=self.logf, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, start_new_session=True)

    def now(self):
        return time.monotonic() - self.t0

    def note(self, what):
        self.steps.write("%8.1f s %7d  %s\n" % (self.now(), self.frame, what))
        self.steps.flush()

    def send(self, line):
        self.note(line)
        if not self.dry:
            with open(self.live, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def alive(self):
        return self.dry or self.proc.poll() is None

    def poll(self):
        """New log lines since the last poll; the frame count brought up to date"""
        if self.dry:
            return []
        try:
            with open(self.frames_path, "rb") as f:
                f.seek(self.fpos)
                chunk = f.read()
            cut = chunk.rfind(b"\n") + 1
            self.fpos += cut
            self.flines = getattr(self, "flines", 0) + chunk[:cut].count(b"\n")
            self.frame = max(self.frame, self.flines)
        except OSError:
            pass
        with open(self.log_path, "rb") as f:
            f.seek(self.pos)
            chunk = f.read()
        cut = chunk.rfind(b"\n") + 1
        self.pos += cut
        lines = chunk[:cut].decode("utf-8", "replace").splitlines()
        for line in lines:
            m = re.search(r"vk: \d+ presents, [\d.]+ fps; a frame: (\d+) draws", line)
            if m:
                self.draws, self.draw_lines = int(m.group(1)), self.draw_lines + 1
            m = re.search(r"vk: (\d+) presents, ", line)
            if m and int(m.group(1)) > self.frame:   # (no frame log without a window: the presents the log counts, 120 apart)
                self.frame = int(m.group(1))
            m = re.search(r"vi: game clock [\d.]+: [\d.]+ a second of wall time \(speed ([\d.]+)\) at ([\d.]+) fps", line)
            if m:
                self.speed.append(float(m.group(1)))
                self.fps.append(float(m.group(2)))
        return lines

    def tick(self):
        if not self.dry:
            time.sleep(0.05)
        lines = self.poll()
        if not self.alive():
            raise Failed("the game ended")
        if self.mem and time.monotonic() - self.checked >= 1:
            self.checked = time.monotonic()
            why = run_problem(self.mem, meminfo(), self.held())
            if why:
                raise MemoryStop(why)
        return lines

    def held(self):
        """The game's memory that cannot be dropped, MB (its most so far kept in peak); None where it cannot be read"""
        try:
            with open("/proc/%d/status" % self.proc.pid) as f:
                mb = held_mb(f.read())
        except (OSError, AttributeError, ValueError):
            return None
        self.peak = max(self.peak, mb)
        return mb

    def frames(self, n, limit_s=300):
        """n frames of the game (the dry run: none)"""
        if self.dry:
            return
        end, until = time.monotonic() + limit_s, self.frame + n
        while self.frame < until:
            self.tick()
            if time.monotonic() > end:
                raise Failed("%d frames did not come in %d s" % (n, limit_s))

    def memory(self):
        """The game's resident memory in MB (Linux): {rss, anon, shmem} (guest memory is shared: shmem), {} elsewhere"""
        out = {}
        try:
            with open("/proc/%d/status" % self.proc.pid) as f:
                for line in f:
                    k, _, v = line.partition(":")
                    if k in ("VmRSS", "RssAnon", "RssShmem"):
                        out[{"VmRSS": "rss", "RssAnon": "anon", "RssShmem": "shmem"}[k]] = int(v.split()[0]) // 1024
        except (OSError, AttributeError, ValueError):
            pass
        return out

    def list_len(self):
        """The records in the list so far (its size: a 12-byte head, then records of the size it gives)"""
        if self.dry:
            return 0
        try:
            with open(self.list_path, "rb") as f:
                head = f.read(12)
            return (os.path.getsize(self.list_path) - 12) // max(1, struct.unpack_from("<I", head, 8)[0])
        except (OSError, struct.error):
            return 0

    def mark(self, what):
        """A step's part (arrived, looked, items used...): the list's length now, for `value --sub`"""
        self.marks.append((what, self.list_len()))

    def list_size(self):
        try:
            return os.path.getsize(self.list_path)
        except OSError:
            return 0

    def settle(self, quiet, most):
        """Frames until the list has had no new pipeline for `quiet` frames, `most` at most"""
        if self.dry:
            return
        start, size, since = self.frame, self.list_size(), self.frame
        while self.frame - start < most:
            self.tick()
            now = self.list_size()
            if now != size:
                size, since = now, self.frame
            elif self.frame - since >= quiet:
                return

    def stop(self, grace=15):
        if self.dry or self.proc.poll() is not None:
            return
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
            self.proc.wait(grace)
        except (subprocess.TimeoutExpired, ProcessLookupError):
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.proc.wait()


STATE_RE = re.compile(r'cheats: state: map "([^"]*)", reserved "([^"]*)", event playing (\d), loading (\d), (child|adult)')


def state_of(line):
    """The game's answer to "!cheat <state action>" (host/hos_main.c oot_log_state): {map, reserved, event, loading, age}"""
    m = STATE_RE.search(line)
    if not m:
        return None
    return {"map": m.group(1), "reserved": m.group(2), "event": m.group(3) == "1", "loading": m.group(4) == "1", "age": m.group(5)}


class Poll:
    """The game's state, asked every `every` frames through the live input; .new is a state that came since the last look"""
    def __init__(self, g, every=60):
        self.g, self.every, self.next_at, self.last, self.new = g, every, 0, None, None

    def step(self, lines):
        self.new = None
        for line in lines:
            st = state_of(line)
            if st:
                self.last = self.new = st
        if self.g.frame >= self.next_at:
            self.g.send("!cheat %d" % self.g.actions["state"])
            self.next_at = self.g.frame + self.every


def teleport(g, action, want, limit_frames=60 * 60 * 3, limit_s=300):
    """A map change (a teleport or the age switch): sent, sent again while the game is busy (an event playing, a request in
    progress, a map loading) or when it did not take it; done once the game's state says it is in the map wanted (want(state)),
    nothing loading and no event playing (the arrival's own scene over). Returns that state"""
    line = action if isinstance(action, str) else "!cheat %d" % action   # (or a "!teleport <map> <start>" line)
    if g.dry:
        g.note(line)
        return {"map": "?"}
    start, end = g.frame, time.monotonic() + limit_s
    poll = Poll(g)
    state, again_at = "send", 0
    busy_since, unstick_at, unstick, refused = None, 0, 0, 0
    while True:
        if state == "send" and g.frame >= again_at:
            g.send(line)
            state, again_at = "wait", g.frame + 600   # (no answer in 10 s of game time: the action was not read, again)
        elif state == "wait" and g.frame >= again_at:
            state = "send"
        lines = g.tick()
        for line in lines:
            said = line.split("cheats: ", 1)[1] if "cheats: " in line else ""
            if said.startswith("teleport") and ("ignored" in said or "waits until" in said or "unavailable" in said):
                state, again_at = "send", g.frame + 30   # (busy: again in half a second of game time)
                if "waits until" in said:   # (an event: one the tour started, a conversation or a prompt, may wait for a button)
                    busy_since = g.frame if busy_since is None else busy_since
                    if g.frame - busy_since > 240 and g.frame >= unstick_at:
                        g.send(UNSTICK[unstick % len(UNSTICK)])
                        unstick, unstick_at = unstick + 1, g.frame + 60
            elif "has no " in said or "age toggle undone" in said or "request not built" in said:
                raise Failed("the game refused: " + said)
            elif said.startswith("teleport ") and "request sent" in said and said.rstrip().endswith("result 0"):
                refused += 1   # (the event manager did not take it: in the Haunted Wasteland it never does)
                if refused >= 5:
                    raise Failed("the game did not take map change %s five times" % action)
                state, again_at = "send", g.frame + 120
            elif said.startswith("teleport ") and "request sent" in said:
                state, again_at = "sent", g.frame + 900
        if state == "sent":
            poll.step(lines)
            st = poll.new
            if st and want(st) and not st["loading"] and not st["event"]:
                return st
            if st and g.frame >= again_at and not st["reserved"] and not st["loading"] and not want(st):
                g.note("not taken (%s): again" % st)   # (sent between two events of a cutscene: the game let it go)
                state, again_at = "send", g.frame
        if g.frame - start > limit_frames or time.monotonic() > end:
            raise Failed("map change %s: not done after %d frames (%s, last state %s)" % (action, g.frame - start, state,
                                                                                            poll.last))


# The opening's scenes skipped (which of these does it was not narrowed down: together they took a run to control at frame ~12500
# instead of ~21100, at the cost of ~180 of the opening's own pipelines, which the part that watches it whole still finds)
SKIP = presses([(0, "PLUS/1200"), (1.4, "MINUS/300"), (1.9, "B/700"), (2.8, "X")])
SKIP_EVERY = 216


def new_game(g, limit_s=1200, skip=False):
    """From no save: A at the title until New Game starts, then through the opening (A now and then: its text), until the game's
    state says Link is in a map with no event playing and nothing loading, three times in a row a second apart: control.
    Returns the phases' (frame, s)"""
    phases = {}
    if g.dry:
        g.note("new game")
        return phases
    end = time.monotonic() + limit_s
    title = False
    next_a, next_skip, calm = 0, 0, 0
    poll = Poll(g)
    while calm < 3:
        lines = g.tick()
        if g.draws >= 15 and not title:
            title = True
            phases["title"] = (g.frame, round(g.now(), 1))
            g.note("title")
        if title:
            poll.step(lines)
            st = poll.new
            if st:
                if "player" not in phases:
                    phases["player"] = (g.frame, round(g.now(), 1))
                    g.note("Link is there: %s" % st)
                calm = calm + 1 if st["map"] and not st["event"] and not st["loading"] else 0
            if g.frame >= next_a:
                g.send("0:A/100")
                next_a = g.frame + 45
            if skip and "player" in phases and g.frame >= next_skip:
                g.send(SKIP)
                next_skip = g.frame + SKIP_EVERY
        if time.monotonic() > end:
            raise Failed("new game: %s after %d s (last state %s)" % ("no control" if title else "no title", limit_s, poll.last))
    phases["control"] = (g.frame, round(g.now(), 1))
    g.note("control: %s" % poll.last)
    return phases


# ---- a run to watch (Linux, Sway): a window on the test workspace ----

def sway(*args):
    return subprocess.run(["swaymsg"] + list(args), capture_output=True, text=True).stdout


def sway_nodes():
    try:
        stack = [json.loads(sway("-t", "get_tree") or "{}")]
    except ValueError:
        return
    while stack:
        node = stack.pop()
        yield node
        stack += node.get("nodes", []) + node.get("floating_nodes", [])


def sway_window(pid, limit=120):
    """The rect of the game's window (x, y, w, h), once Sway has it; None without"""
    end = time.monotonic() + limit
    while time.monotonic() < end:
        for node in sway_nodes():
            if node.get("pid") == pid:
                r = node["rect"]
                return r["x"], r["y"], r["width"], r["height"]
        time.sleep(0.25)
    return None


class Watch:
    """--window: the game's window moved to the test workspace (the focus given back), floating at 16:9 as wide as that output
    is. The move is checked (a window not yet mapped ignores it) and tried again. (No recording of the screen region: a window
    the desktop's user moves leaves the region on whatever is there)"""
    def __init__(self, g, workspace, slot=0):
        before = next((n.get("id") for n in sway_nodes() if n.get("focused")), None)
        if not sway_window(g.proc.pid):
            g.note("no window found to move")
            return
        try:
            out = next(w["rect"] for w in json.loads(sway("-t", "get_workspaces")) if str(w.get("num")) == str(workspace))
        except (ValueError, StopIteration):
            out = None
        rect = None
        for _ in range(40):
            if out:
                w = out["width"] - out["width"] % 16
                h = w * 9 // 16
                y = out["y"] + slot * h if out["height"] >= 2 * h else out["y"] + (out["height"] - h) // 2
                sway("[pid=%d] move container to workspace %s, floating enable, resize set %d %d, move absolute position %d %d" % (
                    g.proc.pid, workspace, w, h, out["x"], y))
            else:
                sway("[pid=%d] move container to workspace %s" % (g.proc.pid, workspace))
            time.sleep(0.5)
            rect = sway_window(g.proc.pid, 5)
            if rect and (not out or (out["x"] <= rect[0] < out["x"] + out["width"] and out["y"] <= rect[1] < out["y"] + out["height"])):
                break
        else:
            g.note("the window did not move to workspace %s" % workspace)
        if before is not None:
            sway("[con_id=%d] focus" % before)
        g.note("window at %s on workspace %s" % (rect, workspace))
    def stop(self):
        pass


# ---- a run ----

def set_ini(path, pairs):
    """The options file with these keys set: the original's text, to put back"""
    old = open(path, encoding="utf-8").read() if os.path.exists(path) else None
    lines = (old or "").splitlines()
    for key, value in pairs:
        for k, line in enumerate(lines):
            if line.split("=", 1)[0] == key:
                lines[k] = "%s=%s" % (key, value)
                break
        else:
            lines.append("%s=%s" % (key, value))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return old


def write_report(run_dir, rows, meta):
    total = rows[-1]["pipelines"] if rows else 0
    out = ["pipeline tour %s%s: %d pipelines, %d programs (the program cache holds %s), %.0f s, %s frames%s" % (
        meta["name"], "" if meta.get("completed", True) else " (NOT COMPLETED: %s)" % (meta.get("error") or
                                                                                    "memory, %d stops left" % len(meta.get("left") or [])), total,
        rows[-1]["programs"] if rows else 0, meta.get("program_cache") or "?", meta["seconds"], meta.get("frames", "?"),
        ", game speed %.1fx at %.0f fps (medians)" % (meta["speed"], meta.get("fps") or 0) if meta.get("speed") else "")]
    if meta.get("peak_mb") or meta.get("memory_stop"):
        out.append("memory: the game held %s MB at most%s" % (meta.get("peak_mb") or "?", "; stopped: %s; left: %s" % (
            meta["memory_stop"], ", ".join(meta.get("left") or []) or "none") if meta.get("memory_stop") else ""))
    out.append("settings: %s" % " ".join("%s=%s" % kv for kv in sorted(meta["env"].items())))
    if meta.get("ini"):
        out.append("options: %s" % " ".join(meta["ini"]))
    out.append("%7s %7s %7s %7s %6s %6s %6s %6s  %s" % ("at s", "took s", "frames", "total", "new", "progs", "rss MB", "shm MB", "step"))
    for r in rows:
        mem = r.get("memory") or {}
        out.append("%7.0f %7.1f %7d %7d %6d %6d %6s %6s  %s" % (r["seconds"], r.get("took", 0), r.get("frames", 0), r["pipelines"],
                                                             r["new"], r["programs"], mem.get("rss", "-"), mem.get("shmem", "-"),
                                                             r["stop"]))
    text = "\n".join(out) + "\n"
    with open(os.path.join(run_dir, "report.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(run_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "stops": rows}, f, indent=1)
    return text


def run(args):
    a = actions()
    steps = route(a, args.part, args.stops, args.first)
    run_dir = os.path.join(os.path.abspath(args.out), args.name)
    os.makedirs(run_dir, exist_ok=True)
    env = dict(BASE_ENV)
    if args.window:   # (a window: no headless run, the window's size)
        env.pop("HOS_HEADLESS", None)   # (the output stays 640x360, scaled into the window)
        env["HOS_WINDOW_SIZE"] = args.window
        env["HOS_WINDOW_NOACTIVATE"] = "1"
    if args.part == "gameover":
        env["HOS_OOT_PROTECT_HEARTS"] = "0"
    for kv in args.env:
        k, _, v = kv.partition("=")
        if v == "-":
            env.pop(k, None)
        else:
            env[k] = v
    game = os.path.abspath(args.game)
    tool = state_tool()
    mem = mem_settings(args)
    prefix = []
    if not args.dry_run and mem:
        why = wait_memory(mem)
        if why:   # (nothing touched yet: the tour may try again later)
            print("pipeline tour %s: not started, memory: %s" % (args.name, why), flush=True)
            with open(os.path.join(run_dir, "report.json"), "w", encoding="utf-8") as f:
                json.dump({"meta": {"name": args.name, "part": args.part, "completed": False, "error": "memory: " + why,
                                    "memory_wait": why, "left": stop_labels(a, steps)}, "stops": []}, f, indent=1)
            return 3
        prefix = scope_prefix(mem)
    aside = os.path.join(game, ".pipeline_tour_aside")
    data = os.path.join(run_dir, "data")
    old_ini = None
    if not args.dry_run:
        if os.path.exists(aside):
            raise SystemExit("pipeline_tour: %s exists (an earlier run did not end): put its files back first" % aside)
        os.makedirs(aside)
        for name in STATE_FILES:
            if os.path.exists(os.path.join(game, name)):
                os.replace(os.path.join(game, name), os.path.join(aside, name))
        shutil.rmtree(data, ignore_errors=True)
        os.makedirs(data)   # (no save: the run makes its own)
        ini = dict(BASE_INI)
        ini.update(kv.split("=", 1) for kv in args.ini)
        old_ini = set_ini(os.path.join(game, "hookshot_options.ini"), sorted(ini.items()))
    rows, seen = [], set()
    if not any(kv.startswith("RX_VK_SHOTS=") for kv in args.env):   # (--env RX_VK_SHOTS=-: none)
        env["RX_VK_SHOTS"] = os.path.join(run_dir, "shots")
    if not args.dry_run and env.get("RX_VK_SHOTS"):
        os.makedirs(env["RX_VK_SHOTS"], exist_ok=True)
    if not args.dry_run and hasattr(os, "sched_setaffinity"):   # (the game inherits them)
        if args.cpus:
            os.sched_setaffinity(0, cpu_list(args.cpus))
        os.nice(max(0, args.nice - os.nice(0)))
    g = Game(game, data, run_dir, env, args.dry_run, mem, prefix)
    g.actions = a
    watch = Watch(g, args.workspace, args.slot) if args.window and not args.dry_run else None
    error = None
    mark = [0.0, 0]
    misses = acts = 0
    dived = False

    def count(label):
        nonlocal seen
        n, progs, recs = list_counts(tool, g.list_path) if not args.dry_run else (0, 0, set())
        rows.append({"stop": label, "seconds": round(g.now(), 1), "took": round(g.now() - mark[0], 1), "frames": g.frame - mark[1],
                     "pipelines": n, "programs": progs, "new": len(recs - seen), "memory": g.memory() if not g.dry else {},
                     "marks": g.marks})
        g.marks = []
        seen |= recs
        g.note("%s: %d pipelines (+%d), %d programs" % (label, n, rows[-1]["new"], progs))
        mark[0], mark[1] = g.now(), g.frame

    memory_stop, left, hard = None, [], False
    try:
        for at, step in enumerate(steps):
            kind = step[0]
            if mem and not args.dry_run and kind in ("visit", "extra") and at and stop_labels(a, steps[:at]):
                held = g.held()   # (between stops: a game past the soft limit ends here, a fresh one does the rest)
                if held is not None and held > mem["soft_mb"]:
                    raise MemoryStop("the game holds %d MB after a stop, a fresh game from here on (over %d)"
                                     % (held, mem["soft_mb"]), soft=True)
            if kind == "newgame":
                phases = new_game(g, skip=args.skip_opening)
                count("new game: title, opening, Link's house")
                rows[-1]["phases"] = phases
            elif kind == "items":
                for n in items_unlock(a):   # (one a live poll: the game keeps the last action a poll read, host/nn_hid.c)
                    g.send("!cheat %d" % n)
                    if not g.dry:
                        time.sleep(0.07)
                g.frames(30)
                count("every item")
            elif kind == "press":
                g.send(step[1])
                g.frames(int(step[2] * FPS))
                g.settle(30, 120)
                count(step[3])
            elif kind == "age":
                teleport(g, a["age"], lambda st: st["age"] == "adult")
                count("age switched: adult")
            elif kind == "gameover":
                banc = a["bancs"][step[1]][0]
                teleport(g, a["teleport"] + step[1], lambda st: st["map"] == banc)
                count("%s (child), hearts not protected" % GAME_OVER_AT)
                end = g.frame + GAME_OVER_FRAMES
                while g.frame < end and not g.dry:   # (the heat; then A: Continue)
                    g.frames(180)
                    if g.frame > end - GAME_OVER_FRAMES + GAME_OVER_PRESS_FROM:
                        g.send("0:A/100")
                count("Game Over")
            elif kind == "extra":
                _, label, banc, start_pos, age = step
                event = BOSS_IN.get(label.split(", its entrance scene")[0]) if label.endswith(", its entrance scene") else None
                try:
                    where = teleport(g, "!teleport %s %s" % (banc, start_pos) + (" " + event if event else ""),
                                     lambda st, banc=banc: st["map"].startswith(banc), limit_frames=60 * 60 * 2)
                except Failed as e:
                    misses += 1
                    g.note("missed: %s" % e)
                    count("%s (%s): MISSED" % (label, age))
                    if misses >= 3:
                        raise Failed("three stops in a row missed: %s" % e)
                    continue
                misses = 0
                g.note("arrived: %s" % where)
                g.send(LOOK)
                g.frames(int(LOOK_SPAN * FPS))
                g.settle(150, 600)
                count("%s (%s)" % (label, age))
            elif kind == "visit":
                _, age, i, k = step
                name = a["teleports"][i][0]
                banc = a["bancs"][i][0 if age == "child" else 1]
                try:
                    where = teleport(g, a["teleport"] + i, lambda st, banc=banc, age=age: st["map"] == banc and st["age"] == age,
                                     limit_frames=60 * 60 * 2)
                except Failed as e:   # (one stop missed, said in the report; three in a row end the run)
                    misses += 1
                    g.note("missed: %s" % e)
                    count("%s (%s): MISSED" % (name, age))
                    if misses >= 3:
                        raise Failed("three stops in a row missed: %s" % e)
                    continue
                misses = 0
                g.note("arrived: %s" % where)
                g.mark("arrive")
                if name in DIVE_AT:
                    g.send(DIVE)
                    g.frames(int(DIVE_SPAN * FPS))
                g.send(LOOK)
                g.frames(int(LOOK_SPAN * FPS))
                g.mark("look")
                if name in DIVE_AT and age == "adult" and not dived:
                    dived = True
                    count("%s (%s)" % (name, age))
                    g.send(UNDERWATER_GEAR)
                    g.frames(int(GEAR_SPAN * FPS))
                    try:   # (arrived again, in the water: with the boots Link sinks to the bottom)
                        teleport(g, a["teleport"] + i, lambda st: True, limit_frames=60 * 60)
                        g.frames(300)
                        g.send(LOOK)
                        g.frames(int(LOOK_SPAN * FPS))
                        g.settle(150, 600)
                        count("%s (%s) underwater" % (name, age))
                    except Failed as e:
                        g.note("underwater missed: %s" % e)
                    g.send(BOOTS_OFF)
                    g.frames(int(BOOTS_SPAN * FPS))
                    continue
                if name in ACT_AT:
                    pick, span = pause_pick(acts)
                    acts += 1
                    g.send(pick)
                    g.frames(int(span * FPS))
                    g.send(ACT)
                    g.frames(int(ACT_SPAN * FPS))
                    g.mark("items")
                g.settle(150, 600)   # (on once no new pipeline came for 2.5 s of game time, 10 s at most)
                count("%s (%s)" % (name, age))
                if name in NIGHT_AT and i < dungeons_from(a):
                    g.send("!cheat %d" % (TIME_ACTION + 22))
                    g.frames(60)
                    g.send(LOOK)
                    g.frames(int(LOOK_SPAN * FPS))
                    g.settle(150, 600)
                    count("%s (%s) at night" % (name, age))
                    g.send("!cheat %d" % (TIME_ACTION + 12))
                    g.frames(60)
    except MemoryStop as e:
        memory_stop, hard = str(e), not e.soft
        left = stop_labels(a, steps[at:])   # (the stop it was at, again: a hard stop cut it short)
        g.note("MEMORY: %s; left: %s" % (memory_stop, left))
        print("pipeline tour %s: memory: %s" % (args.name, memory_stop), flush=True)
        if not left:
            error = "memory: " + memory_stop
    except Failed as e:
        error = str(e)
        g.note("FAILED: " + error)
    finally:
        if watch:
            watch.stop()
        g.stop(3 if hard else 15)
        if not args.dry_run:
            if os.path.exists(g.list_path):
                shutil.copyfile(g.list_path, os.path.join(run_dir, "states.bin"))
            for name in STATE_FILES:
                if os.path.exists(os.path.join(game, name)):
                    os.replace(os.path.join(game, name), os.path.join(run_dir, name))
                if os.path.exists(os.path.join(aside, name)):
                    os.replace(os.path.join(aside, name), os.path.join(game, name))
            os.rmdir(aside)
            if old_ini is not None:
                with open(os.path.join(game, "hookshot_options.ini"), "w", encoding="utf-8") as f:
                    f.write(old_ini)
    speed = sorted(g.speed)[len(g.speed) // 2] if g.speed else None
    fps = sorted(g.fps)[len(g.fps) // 2] if g.fps else None
    meta = {"name": args.name, "part": args.part, "seconds": round(g.now(), 1), "frames": g.frame, "env": env, "ini": args.ini,
            "completed": error is None and not left, "error": error, "speed": speed, "fps": fps,
            "memory_stop": memory_stop, "memory_soft": memory_stop is not None and not hard, "left": left, "peak_mb": g.peak or None,
            "program_cache": program_cache_count(g.log_path) if not args.dry_run else None}
    print(write_report(run_dir, rows, meta), end="")
    return 1 if error is not None else 4 if left else 0


def stop_labels(a, steps):
    """The stops of steps, as --first takes them: "<name> (<age>)", an extra stop by its label"""
    out = []
    for step in steps:
        if step[0] == "visit":
            out.append("%s (%s)" % (a["teleports"][step[2]][0], step[1]))
        elif step[0] == "extra":
            out.append(step[1])
    return out


def mem_settings(args):
    """The memory guard's limits (MEM, --mem key=value over them), None with --no-mem-guard"""
    if getattr(args, "no_mem_guard", False):
        return None
    mem = dict(MEM)
    for kv in getattr(args, "mem", []) or []:
        k, _, v = kv.partition("=")
        if k not in mem:
            raise SystemExit("pipeline_tour: --mem %s: one of %s" % (kv, ", ".join(sorted(MEM))))
        mem[k] = type(MEM[k])(float(v))
    return mem


def cpu_list(text):
    """"0-3,12-15" -> {0, 1, 2, 3, 12, 13, 14, 15}"""
    out = set()
    for piece in text.split(","):
        lo, _, hi = piece.partition("-")
        out.update(range(int(lo), int(hi or lo) + 1))
    return out


def program_cache_count(log_path):
    """The programs the program cache holds, as the run's start logged them"""
    try:
        text = open(log_path, encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    m = re.findall(r"vk: precompile: (\d+) programs", text)
    return int(m[-1]) if m else None


def chunks(a, part, size, limit=None):
    """A part's stops in runs of `size` (a fresh game each: one game's memory grows by about 1 GB an area and is not given back):
    [(first stop's label or None, stops)]. The opening part, or size 0: one run"""
    plan = plan_stops(a, part, limit)
    if not plan:
        return [(None, None)]
    if not size:
        size = len(plan)
    return [("%s (%s)" % (a["teleports"][plan[k][1]][0], plan[k][0]), min(size, len(plan) - k)) for k in range(0, len(plan), size)]


def part_runs(a, part, size, start, say=print, limit=None):
    """A part's games, one after another: its chunks of `size` stops, each a fresh game; a game the memory guard ended (start's
    code 4, or 3: not started) goes on from the stops it left in another fresh game, and a stop the guard ended twice in a row is
    left out. start(first, stops, k) runs game k and returns (code, its report's meta). Returns [(k, code)]; it ends early when
    a game could not start for memory or failed"""
    out, k = [], 0
    for first, stops in chunks(a, part, size, limit):
        stuck = None
        while True:
            code, meta = start(first, stops, k)
            out.append((k, code))
            k += 1
            left = meta.get("left") or []
            if code == 3:
                say("tour: part %s ends: no memory to start a game (%s)" % (part, meta.get("memory_wait")), flush=True)
                return out
            if code != 4 or not left:
                break
            if left[0] == stuck:   # (the same stop ended by the guard twice: left out)
                say("tour: %s left out: the game ran out of memory there twice" % left[0], flush=True)
                left = left[1:]
                if not left:
                    break
            stuck = left[0] if meta.get("memory_stop") and not meta.get("memory_soft") else None
            first, stops = left[0], len(left)
        if code not in (0, 4):
            return out
    return out


def tour(args):
    """The parts one after another (one game at a time: one game can hold 14 GB), each in a reflinked copy of the game folder
    and in games of --chunk stops, under the memory guard; then merged"""
    a = actions()
    parts = args.parts.split(",")
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    t0 = time.monotonic()
    copy = os.path.abspath(args.game).rstrip("/") + "-tour"
    if not os.path.exists(copy):
        subprocess.run(["cp", "-a", "--reflink=always", os.path.abspath(args.game), copy], check=True)
    results = []
    lock = [args.oot_status, "--lock", args.lock, "--priority", "low"] + (["--shared"] if args.lock_shared else []) + ["--"] \
        if args.lock else []

    def start_for(part):
        def start(first, stops, k):
            name = "%s-%s" % (args.name, part) + ("-%d" % k if first or k else "")
            cmd = lock + [sys.executable, "-I", os.path.abspath(__file__), "run", "--game", copy, "--out", out, "--name", name,
                          "--part", part, "--nice", str(args.nice)] + sum((["--env", e] for e in args.env), []) + \
                sum((["--ini", i] for i in args.ini), []) + sum((["--mem", m] for m in args.mem), [])
            if args.no_mem_guard:
                cmd.append("--no-mem-guard")
            if first:
                cmd += ["--first", first, "--stops", str(stops)]
            if part != "opening" and ("opening" in parts or part != parts[0] or k):
                cmd.append("--skip-opening")   # (the opening is watched whole once: by its own part, else by the first)
            if args.cpus:
                cmd += ["--cpus", args.cpus]
            if args.window:
                cmd += ["--window", args.window]
            print("tour: %s" % name, flush=True)
            code = subprocess.run(cmd).returncode
            results.append((part, os.path.join(out, name), code))
            try:
                with open(os.path.join(out, name, "report.json"), encoding="utf-8") as f:
                    meta = json.load(f)["meta"]
            except (OSError, ValueError, KeyError):
                meta = {}
            return code, meta
        return start

    try:
        for part in parts:
            runs = part_runs(a, part, args.chunk, start_for(part), limit=args.stops)
            if runs and runs[-1][1] == 3:
                break   # (no memory: the tour ends here, what it has merged)
    finally:
        if not args.keep:
            shutil.rmtree(copy, ignore_errors=True)
    rc = 0 if all(code in (0, 4) for _, _, code in results) else 1
    order = sorted(results, key=lambda r: (parts.index(r[0]), r[1]))
    have = [os.path.join(d, "states.bin") for _, d, _ in order if os.path.exists(os.path.join(d, "states.bin"))]
    merged = os.path.join(out, "%s.bin" % args.name)
    if have:
        merge(argparse.Namespace(out=merged, lists=have))
    if args.publish and have and (not rc or args.publish_partial):
        rc = publish(have, [d for _, d, _ in order], parts)
    elif args.publish:
        print("tour %s: not published (a run failed or made no list: --publish-partial publishes anyway)" % args.name)
    print("tour %s: %.0f s in all, parts %s, %d runs%s" % (args.name, time.monotonic() - t0, ",".join(parts), len(results),
                                                         "" if not rc else " (a run failed)"))
    return rc


def publish(lists, run_dirs, parts, sources=None):
    """nx2/pipeline_states.py tour: the repository's tour list replaced by these, its note from what the runs logged"""
    gpu = build = ""
    settings, minutes = {}, 0.0
    for d in run_dirs:
        try:
            log = open(os.path.join(d, "log.txt"), encoding="utf-8", errors="replace").read()
            meta = json.load(open(os.path.join(d, "report.json"), encoding="utf-8"))["meta"]
        except (OSError, ValueError, KeyError):
            continue
        m = re.search(r"vk: (.+?), Vulkan [\d.]+, driver (\S+); mesh shaders", log)
        gpu = gpu or (m and "%s (driver %s)" % (m.group(1), m.group(2))) or ""
        m = re.search(r"hookshot (v\S+(?: \(source \w+\))?)", log)
        build = build or (m and m.group(1)) or ""
        settings = settings or {k: v for k, v in meta.get("env", {}).items() if k.startswith(("HOS_OUTPUT", "HOS_FPS", "RX_VK"))}
        minutes += meta.get("seconds", 0) / 60
    ini = " ".join("%s=%s" % kv for kv in sorted(BASE_INI.items()))
    cmd = [sys.executable, "-I", os.path.join(ROOT, "nx2", "pipeline_states.py"), "tour"] + lists + [
        "--gpu", gpu or "unknown", "--build", build or "unknown",
        "--settings", ini + " " + " ".join("%s=%s" % kv for kv in sorted(settings.items())),
        "--route", "scripts/pipeline_tour.py, parts %s, from a new save (%.0f minutes of runs)" % (", ".join(parts), minutes)]
    if sources:
        cmd += ["--dir", sources]
    return subprocess.run(cmd).returncode


def merge(args):
    """The lists merged by nx2/pipeline_states.py (its format, whatever it is), and how much each added"""
    tool = state_tool()
    seen = set()
    for path in args.lists:
        n, progs, recs = list_counts(tool, path)
        print("%s: %d pipelines, %d programs, %d not in the lists before it" % (path, n, progs, len(recs - seen)))
        seen |= recs
    ran = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "nx2", "pipeline_states.py"), "--out", args.out] + args.lists)
    return ran.returncode


# ---- what each step is worth ----
# Steps the route needs whatever they add: without them no later step happens
NEEDED = ("new game:", "every item", "age switched")
NEEDED_END = (" / arrive", ", hearts not protected")   # (a stop's arrival with --sub; the Game Over's way there)


def run_steps(tool, run_dir, sub=False):
    """A run's steps: [(label, seconds, {records})], the list sliced at each step's count (the game only appends to it). sub:
    a step with marks (arrive, look, items) split at them, "<step> / <part>", the rest "<step> / settle" (seconds: the step's)"""
    with open(os.path.join(run_dir, "report.json"), encoding="utf-8") as f:
        rows = json.load(f)["stops"]
    path = os.path.join(run_dir, "states.bin")
    recs = tool.read(path) if os.path.exists(path) and os.path.getsize(path) else []
    (recs,), _ = tool.as_v2([recs], force=True)   # (version 1 runs compared with version 2 lists; those that do not convert left out)
    out, prev = [], 0
    for r in rows:
        n = min(r["pipelines"], len(recs))
        if sub and r.get("marks"):
            at = prev
            for what, m in r["marks"] + [("settle", n)]:
                m = max(at, min(m, n))
                out.append(("%s / %s" % (r["stop"], what), r.get("took", 0), set(recs[at:m])))
                at = m
        else:
            out.append((r["stop"], r.get("took", 0), set(recs[prev:n])))
        prev = max(prev, n)
    return out


def worth(runs, against=(), floor=10):
    """Each step's worth over runs: [{step, runs, seconds, met, beyond, only, kept}] in route order. met: the pipelines it met
    (over all its runs), beyond: those not in the `against` records (the players' lists), only: of those, the ones no other kept step
    met. Steps whose `only` is under `floor` are cut one at a time, the least worth a second first, the others then counted again
    (two steps that meet the same pipelines: one is kept); the steps the route needs (NEEDED) are kept whatever they add"""
    against = set(against)
    met, secs, order = {}, {}, []
    for steps in runs:
        for label, took, recs in steps:
            if label not in met:
                met[label], secs[label] = set(), []
                order.append(label)
            met[label] |= recs
            secs[label].append(took)
    beyond = {k: v - against for k, v in met.items()}
    kept = set(order)
    holders = {}   # (a pipeline: how many kept steps met it)
    for k in order:
        for r in beyond[k]:
            holders[r] = holders.get(r, 0) + 1
    only = lambda k: sum(1 for r in beyond[k] if holders[r] == (1 if k in kept else 0))
    median = lambda k: sorted(secs[k])[len(secs[k]) // 2]
    while True:
        weak = [(only(k) / max(1.0, median(k)), -median(k), k) for k in kept if not k.startswith(NEEDED) and not k.endswith(NEEDED_END)
                and only(k) < floor]
        if not weak:
            break
        k = min(weak)[2]   # (the least a second; of equals, the slowest)
        kept.discard(k)
        for r in beyond[k]:
            holders[r] -= 1
    return [{"step": k, "runs": len(secs[k]), "seconds": median(k), "met": len(met[k]), "beyond": len(beyond[k]), "only": only(k),
             "kept": k in kept} for k in order]


def value(args):
    """The steps of runs, each with what it added that the players' lists (the shipped list's contrib/ sources) and the other
    steps do not have, and whether it is worth keeping"""
    tool = state_tool()
    against = []
    if not args.no_contrib:
        for src in tool.sources(tool.sources_dir()):
            if os.path.basename(src) != tool.TOUR:
                against += tool.read(src)
    for path in args.against:
        against += tool.read(path)
    (against,), _ = tool.as_v2([against], force=True)
    runs = [run_steps(tool, d, args.sub) for d in args.runs]
    rows = worth(runs, against, args.floor)
    print("%d runs; against %d pipelines (%s)" % (len(runs), len(set(against)),
                                                 "players' lists" if not args.no_contrib else "") + " ".join(args.against))
    print("%6s %6s %6s %6s %4s  %-5s %s" % ("met", "beyond", "only", "secs", "runs", "", "step"))
    for r in rows:
        print("%6d %6d %6d %6.0f %4d  %-5s %s" % (r["met"], r["beyond"], r["only"], r["seconds"], r["runs"],
                                                 "keep" if r["kept"] else "CUT", r["step"]))
    cut = [r for r in rows if not r["kept"]]
    print("cut %d of %d steps: %.0f s of %.0f (median seconds a run)" % (len(cut), len(rows), sum(r["seconds"] for r in cut),
                                                                        sum(r["seconds"] for r in rows)))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=1)
    return 0


def report(args):
    with open(os.path.join(args.run, "report.json"), encoding="utf-8") as f:
        r = json.load(f)
    print(write_report(args.run, r["stops"], r["meta"]), end="")
    return 0


def stopped(signum, frame):
    raise KeyboardInterrupt   # (SIGTERM as SIGINT: the run's finally ends the game and puts the game folder's files back)


def main(argv=None):
    signal.signal(signal.SIGTERM, stopped)
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--game", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--name", default="play")
    r.add_argument("--part", choices=PARTS, default="all")
    r.add_argument("--cpus", help="the CPUs the game may use (Linux), e.g. 0-3,12-15")
    r.add_argument("--nice", type=int, default=5, help="the game's niceness (default 5: the desktop stays responsive)")
    r.add_argument("--stops", type=int, help="only the first N stops")
    r.add_argument("--first", metavar="STOP", help="start the route at this stop (its name, or \"<name> (<age>)\"): after a failure")
    r.add_argument("--env", action="append", default=[], help="NAME=VALUE over the run's switches (NAME=- drops one)")
    r.add_argument("--ini", action="append", default=[], help="key=value in hookshot_options.ini for the run")
    r.add_argument("--window", metavar="WxH", help="a window (on a Sway workspace) instead of the headless run")
    r.add_argument("--workspace", default="10", help="the Sway workspace the window goes to (default 10)")
    r.add_argument("--slot", type=int, default=0, help="with --window: the window's place on the workspace, one under the other")
    r.add_argument("--skip-opening", action="store_true", help="skip the opening's scenes once Link is there")
    r.add_argument("--dry-run", action="store_true", help="the steps, without the game")
    r.add_argument("--mem", action="append", default=[], metavar="KEY=VALUE",
                   help="the memory guard's limits over its defaults (%s)" % ", ".join("%s=%s" % kv for kv in sorted(MEM.items())))
    r.add_argument("--no-mem-guard", action="store_true", help="no memory guard (no waiting, no limits, no scope)")
    t = sub.add_parser("tour")
    t.add_argument("--game", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--name", default="play")
    t.add_argument("--parts", default="opening,child-overworld,dungeons,adult-overworld")
    t.add_argument("--cpus", default="6-11,18-23", help="the CPUs the game may use (default 6-11,18-23: off the desktop's)")
    t.add_argument("--nice", type=int, default=19, help="the games' niceness (default 19)")
    t.add_argument("--mem", action="append", default=[], metavar="KEY=VALUE", help="the memory guard's limits (run --help)")
    t.add_argument("--no-mem-guard", action="store_true")
    t.add_argument("--lock", metavar="NAME", help="each game under oot-status --lock NAME (low priority: others go first)")
    t.add_argument("--lock-shared", action="store_true", help="with --lock: the shared mode")
    t.add_argument("--oot-status", default="oot-status")
    t.add_argument("--env", action="append", default=[])
    t.add_argument("--ini", action="append", default=[])
    t.add_argument("--keep", action="store_true", help="keep the parts' game folder copy")
    t.add_argument("--stops", type=int, help="only each part's first N stops (a short test)")
    t.add_argument("--chunk", type=int, default=8, help="stops a game, then a fresh one (one game grows ~1 GB an area); 0: no limit")
    t.add_argument("--publish-partial", action="store_true", help="--publish even when a run failed")
    t.add_argument("--window", metavar="WxH", help="the game in a window (on Sway workspace 10)")
    t.add_argument("--publish", action="store_true",
                   help="write the repository's tour list (assets/pipeline_states/tour.bin.xz and tour.md) from the parts' lists")
    m = sub.add_parser("merge")
    m.add_argument("--out", required=True)
    m.add_argument("lists", nargs="+")
    s = sub.add_parser("report")
    s.add_argument("run")
    v = sub.add_parser("value", help="each step's new pipelines and seconds over runs, and the steps worth cutting")
    v.add_argument("runs", nargs="+", help="run folders (<out>/<name>: report.json and states.bin)")
    v.add_argument("--against", action="append", default=[], help="a list whose pipelines count as had already")
    v.add_argument("--no-contrib", action="store_true", help="not against the players' lists in assets/pipeline_states/contrib")
    v.add_argument("--floor", type=int, default=10, help="a step that alone adds fewer pipelines than this is cut (default 10)")
    v.add_argument("--sub", action="store_true", help="the stops' parts apart (arrive, look, items, settle), where runs marked them")
    v.add_argument("--json")
    a = p.parse_args(argv)
    return {"run": run, "tour": tour, "merge": merge, "report": report, "value": value}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
