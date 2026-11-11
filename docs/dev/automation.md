# Automation: the control bridge

The control bridge is a local socket inside the game process. Tests, scripts and coding agents use it to drive a
running game and read its state: press buttons, move the sticks, take screenshots, wait for the game to reach a state
or a map, read and change the Insert menu's settings, list the saves, and quit. Inputs are timed in game frames, and
every reply carries the frame it was made at.

Without the bridge, a test writes presses into a file the game polls (`HOS_INPUT_LIVE`), takes screenshots with
`RX_VK_SHOTS` and reads the frame rate and draw counts from the log. The bridge does the same through one connection,
with replies.

`scripts/hookshot_ctl.py` is its client. It needs only Python's standard library.

- [Quick start](#quick-start)
- [Turning it on](#turning-it-on)
- [The client](#the-client)
- [Protocol](#protocol)
- [Commands](#commands)
- [Saves](#saves)
- [Guest memory](#guest-memory)
- [Security model](#security-model)
- [Limits](#limits)
- [Implementation and tests](#implementation-and-tests)

## Quick start

On Linux, start a game folder with the bridge on and keep the socket's path in `HOS_CONTROL`, which the client reads:

```sh
export HOS_CONTROL=$(python -I scripts/hookshot_ctl.py launch ~/Games/Hookshot --data /tmp/oot-data --headless)
```

The first start prepares the shaders before the first frame, and the game reads no controller until then. Wait for
frame 1, then press A until the title and the file select are past and the game is in play:

```sh
python -I scripts/hookshot_ctl.py wait frame --frame 1 --timeout 900
until [ "$(python -I scripts/hookshot_ctl.py --json status | jq -r .state)" = play ]; do
    python -I scripts/hookshot_ctl.py press A --frames 8
    python -I scripts/hookshot_ctl.py wait present --frames 60
done
```

Then drive it:

```sh
python -I scripts/hookshot_ctl.py status                                 # frame, fps, draws, state, map
python -I scripts/hookshot_ctl.py stick L 0 1 --frames 90 --exclusive    # walk forward for 90 frames
python -I scripts/hookshot_ctl.py press A --frames 8
python -I scripts/hookshot_ctl.py sequence '0:A/8,60:A/8'                # frames: at 0 and at 60, held 8
python -I scripts/hookshot_ctl.py sequence '0:LUP/2000,2:A' --hos        # seconds and ms, as HOS_INPUT_LIVE
python -I scripts/hookshot_ctl.py shot out.png
python -I scripts/hookshot_ctl.py wait in_play --timeout 120
python -I scripts/hookshot_ctl.py option get text_speed
python -I scripts/hookshot_ctl.py option set text_speed 3
python -I scripts/hookshot_ctl.py teleport                               # the destinations
python -I scripts/hookshot_ctl.py teleport 1 --arrive 30                 # sent or refused, then arrived
python -I scripts/hookshot_ctl.py watch --events present,state --log "hid:"
python -I scripts/hookshot_ctl.py quit
```

## Turning it on

The bridge is off unless `HOS_CONTROL` names a socket:

```sh
HOS_CONTROL=/run/user/1000/hookshot/control.sock ./hookshot
```

On Windows the value is a named pipe, `\\.\pipe\<name>`; a bare name gets that prefix. When the bridge is on, the log
says so once: `control: listening on <path> (HOS_CONTROL: ...)`. The socket's folder must belong to the game's user
and be writable by no one else; otherwise the bridge stays off and the log says why (see
[Security model](#security-model)).

`hookshot_ctl.py launch <game folder>` does this for you. It makes a run folder of its own (mode 0700, in
`$XDG_RUNTIME_DIR`), starts `<game folder>/hookshot` (`hookshot.exe` on Windows) with the socket `control.sock` in it,
and sends the game's output to `log.txt` there. Shots taken with a relative path go to its `shots/` folder. It waits
until the bridge answers (600 s by default, `--timeout`), then prints the socket's path; with `--json` it prints the
socket, the process ID, the run folder and the log.

## The client

```
python -I scripts/hookshot_ctl.py [--sock S] [--json] COMMAND ...
```

`--sock` overrides `$HOS_CONTROL`. Each command prints plain lines; `--json` prints the replies as they come. Text
from the game, such as a log line's escape sequences, is printed with control characters as `?`.

| Command | What it does |
|---|---|
| `launch GAME_DIR [--data DIR] [--headless] [--env NAME=VALUE] [--run DIR] [--timeout S]` | Starts the game with the bridge on and prints the socket's path. `--data` sets `XDG_DATA_HOME` for the run, so it plays from saves of its own. `--headless` sets `HOS_HEADLESS=1`. `--env` adds a switch, and can be repeated |
| `launch ... --save FOLDER [--slot NN]` | Copies a save folder into the run's data folder before the start (see [Saves](#saves)). Linux only |
| `status` | Frame, frame rate, draws a frame, state, window, map, version |
| `press BUTTONS [--frames 8] [--at N] [--exclusive] [--no-wait] [--timeout S]` | Buttons held for some frames. `A`, `A+B`, `ZL+LUP`, `LX=-16000`. The reply comes once they are let go |
| `stick L\|R X Y [--frames 8] ...` | A stick at x, y, each from -1 to 1. Same options as `press` |
| `sequence SCRIPT [--hos] [--exclusive] [--no-wait] [--timeout S]` | Steps as `<at>:<buttons>[/<frames held>],...`. `--hos`: times in seconds and holds in ms, as `HOS_INPUT_SCRIPT` |
| `release [--all]` | Lets go of this client's queued inputs and those of clients that have gone; `--all`, every client's |
| `shot [PATH] [--after FRAME] [--timeout S]` | A PNG of the next present; prints its path |
| `wait EVENT [--frames N] [--frame N] [--state S] [--map NAME] [--timeout 60]` | Waits for an event: `present`, `frame`, `in_play`, `state`, `loading_start`, `loading_end`, `change`, `map` |
| `option get [NAME]`, `option set NAME VALUE` | The Insert menu's settings |
| `teleport [INDEX\|MAP] [--arrive SECS] [--timeout 10] [--no-wait]` | The debug teleport. Without a destination, lists them. `--arrive` then waits up to SECS for the map |
| `saves` | The save folder the game uses, its files, newest slot first |
| `slots [--thumbs DIR]` | One line a save slot: last written, sizes, scene; `*` marks the newest. `--thumbs` writes each slot's file-select picture as `DIR/slot_NN.jpg` |
| `watch [--events present,state,log,map] [--every 60] [--log TEXT] [--count N]` | Prints subscription events. `--log` alone watches log lines containing TEXT |
| `mem read ADDR SIZE [--format hex\|base64\|u8\|u16\|u32\|u64\|f32]` | Reads guest memory (needs `HOS_CONTROL_MEM=ro` or `rw`) |
| `mem write ADDR HEX` | Writes guest memory (needs `HOS_CONTROL_MEM=rw`) |
| `quit` | The game exits |
| `raw JSON` | Sends any request, such as `'{"cmd": "wait", "event": "frame", "frame": 9000}'` |

The exit status is 0 when done, 1 for an error reply, 2 when there is no game or the usage is bad, and 3 for a
timeout.

## Protocol

The protocol is newline-delimited JSON. Each request is one JSON object on one line, at most 64 KB. Each reply is one
line. It gives back the request's `id` (any JSON value, at most 200 characters as JSON; `null` when there is none) and
the current `frame`, the game's presents so far:

```
> {"id": 1, "cmd": "status"}
< {"id":1,"ok":true,"frame":5321,"protocol":1,"fps":59.8,"state":"play","stalled":false,"draws":2410.3,...}
```

Requests on one connection may be answered out of order: a `status` sent while a `wait` is pending is answered first.
Match replies by `id`. A line with an `"event"` key and no `"ok"` key is a subscription event (see `subscribe`).

On Linux a client may shut its sending side once its requests are sent
(`printf '...\n' | socat - UNIX-CONNECT:<path>`). The bridge then reads no more from it, ends its subscription,
answers what it waits for, and closes the connection once those replies are out. A Windows pipe has no half-close.

A `timeout` argument is in seconds, at most 3600.

### Errors

```
< {"id":7,"ok":false,"frame":5400,"error":"bad_request","message":"frames: 1 to 216000"}
```

| Error | When |
|---|---|
| `bad_json` | The line is not JSON (`id` is `null`) |
| `too_long` | A line over 64 KB; the rest of it is skipped and the connection goes on |
| `bad_request` | Not an object, no `cmd`, or a bad argument |
| `unknown_cmd` | No such command |
| `timeout` | A `wait`, `shot`, teleport or input did not finish before its `timeout` |
| `busy` | Too many requests waiting (64), inputs queued (256) or clients (8) |
| `unavailable` | The renderer is not up yet, or is not the Vulkan one (shots, settings); or a memory command that is not served |
| `forbidden` | A memory command that `HOS_CONTROL_MEM` does not allow |
| `out_of_range` | A memory address or range outside mapped guest memory |
| `not_found` | No such setting or teleport destination |
| `failed` | A shot could not be written, or a setting has nothing to choose on this PC |
| `refused` | The game turned a teleport down; the message says why |
| `cancelled` | A press that was waited on was let go by `release`, or a teleport was replaced by a later one |

### Frames and inputs

A frame is one present of the game's own; frames made by frame generation do not count. An input starts at the first
controller read after its request arrives, plus `at` frames, and is held for `frames` frames (each 1 to 216000). The
game reads the controller once a frame, so `"frames": 8` is 8 game frames.

The bridge's buttons are added to the player's. On the axes it sets, its sticks replace a script's
(`HOS_INPUT_SCRIPT`); the player's own pad, keys and mouse still count, the larger deflection winning. With
`"exclusive": true` the player's own devices are left out from the request until the input ends, as
`HOS_INPUT_EXCLUSIVE` does for scripts.

Buttons use the names `HOS_INPUT_SCRIPT` uses: `A B X Y L R ZL ZR PLUS MINUS LS RS LEFT UP RIGHT DOWN`. The stick
directions are `LUP LDOWN LLEFT LRIGHT RUP RDOWN RLEFT RRIGHT`, and `LX= LY= RX= RY=` set an axis from -32767 to 32767
(positive y is up). Names are given as `"A+B"` or `["A", "B"]`.

The reply comes once the input is over, with the frames it covered: `{"start": 5400, "end": 5408}`, where `end` is the
first frame without it. With `"wait": false` the reply is immediate: `{"queued": 1, "frames": 8}`. An input's default
`timeout` is its own length at 10 frames a second, plus 30 s.

An input sent with `"wait": false` stays queued after its client goes, so a one-shot `hookshot_ctl.py press --no-wait`
works, and is freed once it is over. An input that is waited on is let go when its client goes.

## Commands

### status

The frame, the frame rate over the last second, the draws a frame over the last ~300 ms, the state, the renderer's
presents (`replayed`, which a shot's `present` counts in), the picture's size, the map, and the version.

```
> {"id":1,"cmd":"status"}
< {"id":1,"ok":true,"frame":5321,"protocol":1,"fps":59.8,"state":"play","stalled":false,"draws":2410.3,"replayed":5320,
   "window":{"width":1280,"height":720},"uptime":95.2,"clients":1,"input":{"queued":0,"exclusive":false},
   "map":"KokiriForest_Child","game":{"event":false,"loading":false,"age":"child"},"version":"1.4.0-abc123",
   "renderer":"Vulkan: ..."}
```

`map` is the game's own name for the map (`Sequence_CurrentBanc`), read on the game's thread with the player's update
every 250 ms. It is the last one known, so it stays through loads and menus, and it is `null` until Link was first
seen. `game` says whether an event is playing (a cutscene, a map change's), whether a map is loading
(`Sequence_IsLoadingBanc`) and Link's age; it is `null` until then. A script that steps through places waits for
`event` and `loading` to be false before its next step.

`state` is a guess from the draws a frame:

| State | Meaning |
|---|---|
| `boot` | Nothing presented yet |
| `intro` | Under 11 draws, before any menu was seen |
| `menu` | 11 to 149 draws |
| `loading` | Under 11 draws, after a menu or play |
| `play` | 150 or more |
| `unknown` | No Vulkan renderer to count draws |

A new state has to hold for 300 ms before it is taken. `stalled` is true when no frame has come for a second.

### press, stick, sequence

**press**: `buttons`, `frames` (default 8), `at` (default 0), `exclusive`, `wait`, `timeout`.

```
> {"id":2,"cmd":"press","buttons":"A","frames":8}
< {"id":2,"ok":true,"frame":5410,"start":5401,"end":5409}
```

**stick**: `stick` (`L`, the default, or `R`), `x` and `y` from -1 to 1, then as `press`. Buttons can go with it.

```
> {"id":3,"cmd":"stick","stick":"L","x":0,"y":1,"frames":120,"exclusive":true}
```

**sequence**: `steps`, a list of press or stick objects each with its own `at`. Or `script`, `HOS_INPUT_SCRIPT`'s
syntax in frames, `<at>:<names>[/<frames held>],...`, held 8 frames unless given. With `"units": "hos"` the script's
times are in seconds and its holds in milliseconds, as `HOS_INPUT_SCRIPT` and `HOS_INPUT_LIVE` take them (60 frames a
second; held 200 ms unless given). The reply comes when the last step is over: `start` is the first step's start and
`end` the last step's end.

```
> {"id":4,"cmd":"sequence","script":"0:A/8,60:A/8"}
> {"id":5,"cmd":"sequence","script":"0:LUP/2000,2:A","units":"hos"}
> {"id":6,"cmd":"sequence","steps":[{"at":0,"buttons":"ZL","frames":30},{"at":10,"lx":-1,"frames":20}]}
```

### release

Lets go of the caller's queued inputs, and of those that clients which have gone left behind:
`{"released": 3, "all": false}`. Another connected client's inputs stay. With `"all": true`, every client's. Presses
that were waited on reply `cancelled`.

### shot

A PNG of the first present after the request, or after frame `after`. It is the size `RX_VK_SHOTS` writes (1280x720,
or `RX_VK_SHOT_W` x `RX_VK_SHOT_H`); the reply's `width` and `height` are read from the file. The `timeout` default is
30 s. Shots need the Vulkan renderer.

`path` defaults to `shots/shot_<n>_f<frame>.png` in the socket's folder, made 0700. A relative path is taken from the
socket's folder, not the game's. On Windows, where a pipe has no folder, that is
`%TEMP%\hookshot-control-<pipe name>\`, which also holds `shots\`. The file is written whole under another name, then
renamed, so the path in the reply is complete.

A shot is the game's own picture: the Insert menu and the FPS counter, drawn over it on the way to the window, are not
in it.

```
> {"id":7,"cmd":"shot","path":"/tmp/run/kokiri.png"}
< {"id":7,"ok":true,"frame":5440,"present":5432,"path":"/tmp/run/kokiri.png","width":1280,"height":720}
```

### wait

`event`, plus a `timeout` (default 60 s). The reply has the state and the frames waited: `{"state": "play",
"waited": 1203}`. A timeout replies `timeout`, with the state at that time.

| Event | Until |
|---|---|
| `present` | `frames` more frames (default 1) |
| `frame` | Frame number `frame` |
| `in_play` | The state is `play` (at once if it is) |
| `state` | The state is `state` |
| `loading_start` | The next change into `loading` |
| `loading_end` | The next change out of `loading` |
| `change` | The next change of state |
| `map` | The map is `map` (any case; at once if it is). Without `map`, the next change of map. The reply has `map` |

### option_get, option_set

**option_get**: the Insert menu's settings, or one of them by `name`. A name is the setting's key in
`hookshot_options.ini` (`text_speed`) or its row's name (`"Text speed"`), in any case, with `-` taken as `_`. The
settings are the rows with a value that the menu shows on this PC; a row for something the GPU cannot run is not
listed, nor are the section headings and the Debug tab's tools. The bridge finds a row by its key each time, so a key
stays valid when rows come and go or are renamed. `restart` marks a row that takes effect at the next start; `fixed`,
one with nothing to choose on this PC (the menu shows it greyed).

```
> {"id":8,"cmd":"option_get","name":"text_speed"}
< {"id":8,"ok":true,"frame":5500,"option":{"key":"text_speed","name":"Text speed","tab":"gameplay","value":0,
   "min":0,"max":3,"step":1,"restart":false,"fixed":false,"text":"Normal"}}
```

**option_set**: `name` and `value` (a number, or `true`/`false`). The value is set through the menu's own setter, as
Left and Right set it: cut to the row's range, the Quality preset turned to Custom unless the row is one it leaves
alone, a restart noted for the restart question, and kept in `hookshot_options.ini`. Rows whose arrows step through a
list of their own (the Upscaler, Render resolution, the output resolution) are walked in the arrows' order until they
reach the value; one that none of their steps reach on this PC leaves them, the Quality preset and the rest as they
were, and replies `failed`. A `fixed` row replies `failed` too. The reply has
the value before (`was`) and the setting as it is now. The menu's lock keeps a change apart from the menu's own frame.

```
> {"id":9,"cmd":"option_set","name":"FPS counter","value":true}
< {"id":9,"ok":true,"frame":5510,"was":0,"option":{"key":"fps_counter",...,"value":1,"text":"On"}}
```

### subscribe, unsubscribe

**subscribe** starts a stream of events on this connection until `unsubscribe` or a disconnect; another `subscribe`
replaces it. Arguments:

- `events`: any of `present`, `state`, `log` and `map`. Default `["present", "state"]`.
- `every`: frames between present events, 1 to 216000. Default 60.
- `log`: only log lines that contain this text. It also turns `log` on.

The events carry `sub`, the subscribe request's `id`:

```
< {"event":"present","sub":10,"frame":5600,"fps":59.9,"state":"play","draws":2405.0}
< {"event":"state","sub":10,"frame":5720,"state":"loading","from":"play","draws":5.0}
< {"event":"log","sub":10,"frame":5721,"line":"[hos sead::MainThread] ..."}
< {"event":"map","sub":10,"frame":5900,"map":"HyruleField_Child","from":"KokiriForest_Child"}
< {"event":"log_dropped","sub":10,"lines":40}
```

### teleport

The Debug tab's teleport, by destination: `to`, the destination's index or one of its maps' names (any case). Without
`to`, the reply lists the destinations: `{"destinations":[{"index":0,"child":"KokiriForest_Child","adult":
"KokiriForest_Adult"},...]}`; a destination with no map for an age has `null` there. The game takes a teleport at the
player's next update, in play, and goes to the map for Link's age.

The reply comes once the game took it, within `timeout` (default 10 s):

- `"sent": true` and `map`, the map it goes to. `wait map` then tells when it arrived. `accepted` is the game's event
  manager's own answer; `false` has been seen when the map then did not change.
- `refused`, with the game's reason: an event playing, a map loading, another teleport in the last 8 s, or no map
  for Link's age there.
- `timeout` when the game did not take it because Link is not being updated (the title, the file select, a pause, a
  load). The request is then withdrawn, so it does not happen later.
- `cancelled` when a later `teleport` replaced it before the game took it; one waits at a time.

With `"wait": false` the reply is immediate, with `"sent": null`. The game logs each teleport (`cheats: teleport ...`).
It changes the game as the menu's teleport does, and a save made after it keeps the new place.

```
> {"id":12,"cmd":"teleport","to":"HyruleField_Child"}
< {"id":12,"ok":true,"frame":6003,"teleport":1,"child":"HyruleField_Child","adult":"HyruleField_Adult","sent":true,
   "map":"HyruleField_Child"}
> {"id":13,"cmd":"wait","event":"map","map":"HyruleField_Child","timeout":30}
< {"id":13,"ok":true,"frame":6190,"state":"loading","waited":187,"map":"HyruleField_Child"}
```

### quit

Replies, then the game exits as when its window is closed: the log is flushed and the exit code is 0. The socket is
removed.

## Saves

**saves** needs no extra opt-in: it lists files and reads no game memory. It returns the folder the game's saves are
mounted from (`<data>/hookshot/save/<user id>` on Linux), read on the bridge's thread. A slot the game is writing at
that moment may show a size or time between two writes. It replies `unavailable` until the game has opened its saves.

```
> {"id":50,"cmd":"saves"}
< {"id":50,"ok":true,"frame":900,"path":"/tmp/run/data/hookshot/save/5a3c9e1f0b7d24680000000000000001","account":true,
   "option":true,"slots":[{"slot":"03","mtime":1762900000,"newest":true,"files":[{"name":"progress.sav","size":120724,
   "mtime":1762900000},{"name":"caption.sav","size":42239,"mtime":1762900000}],"caption":{"scene":"KokiriForest",
   "map":"KokiriForest/KokiriForest_Child","thumbnail":{"format":"jpeg","offset":1396,"size":40843}}}]}
```

Slots come newest first; `newest` marks the one the title's Continue loads. Times are Unix seconds. `caption` is there
only when the slot's `caption.sav` has the layout of this game's saves (the file select's preview): its scene and map
names, and where its picture, a 543x306 JPEG, is in the file. Those offsets were checked on Kokiri Forest saves only.

On the client side:

- `slots` prints one line a slot. `slots --thumbs DIR` writes each slot's picture as `DIR/slot_NN.jpg`, read from the
  save folder on this PC. It takes only digit slot names and a bounded slice of that slot's `caption.sav`.
- `launch --save FOLDER [--slot NN]` copies a save folder (`account.sav`, `option.sav`, `slot_NN/`) into the run's
  data folder before the game starts: `--data`, or `data/` in the run folder. With `--slot` (`03` or `slot_03`) only
  that slot is copied, so Continue loads it. The source is only read. A destination that already holds saves is
  refused, and so is a source folder that holds links or anything but plain files and folders. Linux only; on Windows
  the game keeps its saves in its own folder.

The save layout itself is described in [saves](../user/saves.md).

## Guest memory

Reading and writing the game's memory is a second opt-in, `HOS_CONTROL_MEM`, apart from `HOS_CONTROL`:

| `HOS_CONTROL_MEM` | Commands | Aliases |
|---|---|---|
| unset or empty | None: `mem_*` reply `forbidden`, with how to turn it on | |
| `ro` | `mem_read`, `mem_read_many` | `r`, `read` |
| `rw` | The reads, and `mem_write` | `readwrite` |

Case does not matter. Any other value logs a line once and leaves memory off; it never falls back to a more permissive
level.

**This is a debugging tool, not a safe sandbox.**

- `ro` exposes all of the game's memory to a client, including values the runtime keeps for itself.
- `rw` lets a client change that memory. A write can corrupt or crash the game and the runtime, and a corrupted state
  can be saved to disk. **Use a throwaway save.**
- The socket is already this user's only, so a client can reach no memory that another process of the same user could
  not already reach. The opt-in limits what the bridge itself will do, not who can connect.

Addresses are guest addresses: the image is at `0x80000000`, the heap at `0x1000000000`. An address or range outside
the memory the runtime has mapped (the image, the system region in use, the heap, or an address region) is an error,
`out_of_range`, never a fault. Each request reads or writes at most 1 MB, and its `timeout` defaults to 10 s.

Reads and writes are done on the game thread at a controller read, so a read is one frame's memory and a write lands
between frames. `mem_read_many` reads all its ranges in that one pass, so they are consistent with each other. Every
write is logged in `hookshot_log.txt` (`control: wrote N bytes to guest 0x...`). A write to memory the GPU reads goes
through the same soft write-watch the game's own CPU writes use, so it reaches the renderer's VRAM mirror at the next
frame's memory sync.

**mem_read**: `addr` and `size`, as whole numbers or as strings of decimal digits or `0x` and hex digits (a string
for an address past 2^53, which a JSON number cannot hold exactly; no sign, no octal). `format` is `hex` (default) or
`base64`.

```
> {"id":30,"cmd":"mem_read","addr":2147483648,"size":8}
< {"id":30,"ok":true,"frame":5000,"format":"hex","addr":2147483648,"size":8,"data":"030000141c300000"}
```

**mem_read_many**: `ranges`, a list of `{addr, size}` (at most 64), read in one pass. The reply has a `ranges` array,
each with its `addr`, `size` and `data`.

**mem_write** (`rw` only): `addr`, and the bytes as `hex` or `base64`.

```
> {"id":31,"cmd":"mem_write","addr":4300000000,"hex":"2a000000"}
< {"id":31,"ok":true,"frame":5001,"wrote":4,"addr":4300000000}
```

Named game values (scene, Link's position, health) are not served yet: the `symbols` command replies `unavailable`.

## Security model

- **Opt-in.** There is no socket unless `HOS_CONTROL` names one.
- **Local only.** A Unix domain socket on Linux and a named pipe on Windows, never TCP. The pipe refuses remote
  clients.
- **This user only.** The socket is created with mode 0600, with the umask set around `bind` too, and a client whose
  `SO_PEERCRED` user differs from the game's is turned away. The pipe's DACL grants the current user alone, and
  `FILE_FLAG_FIRST_PIPE_INSTANCE` keeps another process from owning the name first.
- **A folder of this user's.** The socket's folder must be owned by the game's user and writable by no one else, so
  not a shared `/tmp`. Otherwise another user could put a link or a socket of theirs where the bridge binds, removes a
  stale socket, or writes a shot by a relative path. `hookshot_ctl.py launch` makes such a folder. The path is always
  a file system path; there is no abstract socket name.
- **Nothing in the way is replaced.** A file at the path that is not a socket is left alone and the bridge stays off.
  A socket that a live game answers on is left alone too. A stale one, left by a game that ended, is removed.
- **Guest memory is a second opt-in**, `HOS_CONTROL_MEM` (see [Guest memory](#guest-memory)).
- **What a client can do.** Anything the player can do with a controller and the Insert menu's settings, but not its
  debug tools, apart from the teleport. It can also write a PNG to any path the game's user can write, list the save
  folder, and end the game.
- **The game never waits for a client.** The bridge's own thread does all the socket I/O. The controller's read takes
  one short lock that the bridge never holds over I/O. A client that sends nonsense gets errors; one that stops
  reading is dropped once 8 MB of replies wait for it; one that goes away mid-command has its presses let go.
- **The client trusts the game no further than it must.** `hookshot_ctl.py` may run outside a sandbox the game is in,
  so it checks what it does with the game's replies: `slots --thumbs` takes only digit slot names and a bounded slice
  of `caption.sav`, plain output shows control characters as `?`, and `launch --save` refuses a save folder with
  links, which could otherwise make the game write through them into this user's files.

## Limits

| Limit | Value |
|---|---|
| Request line | 64 KB; longer lines reply `too_long` and are skipped |
| Request `id` | 200 characters as JSON |
| Clients at once | 8 |
| Requests waiting | 64 |
| Inputs queued | 256 |
| An input's `at` and `frames` | 0 to 216000 and 1 to 216000 frames |
| Memory requests waiting | 8, each at most 1 MB and 64 ranges |
| Unread replies for one client | 8 MB, then the client is dropped |
| `timeout` | 3600 s |

Other known limits:

- **Windows** is built and its pipe tested in CI only (the windows-2022 runner). The bridge inside a Windows game
  build, `launch` on Windows, and refusing remote pipe clients (`PIPE_REJECT_REMOTE_CLIENTS`, which needs a second
  machine) are not tested.
- **The state is a guess** from the draws a frame. A scene with unusual counts can be misread. `game`'s `event` and
  `loading`, and `map`, are the game's own.
- **A teleport the game sent but that did not move Link** is reported through `accepted`, not as an error. Otherwise
  `wait map` times out.
- **The first `option_get` or `option_set`** after the start can wait, on the bridge's thread, for the start-up check
  of the upscalers (NVIDIA's NGX start takes about 3 s). The game does not wait for it, but other replies to every
  client do.
- **`HOS_CONTROL_MEM=rw` writes** were checked against the game's memory (written, read back, put back), not against
  the picture the GPU draws from a written value.

## Implementation and tests

The game side is `host/control.c`. It hooks into:

| File | What it gives the bridge |
|---|---|
| `host/nn_hid.c` | The controller's read, where inputs are applied |
| `gpu/vk/vk_replay.cpp` | Shots at a present |
| `gpu/vk/vk_menu.cpp` | The Insert menu's settings, through its own setter |
| `host/hos_thread.c` | Log lines |
| `host/hos_main.c` | The start, the current map and the debug teleport |
| `host/hos_mem.c` | Guest memory's bounds |
| `host/nn_fs.c` | The save folder |
| `host/rx_backend.c` | The renderer's side |

`tests/test_control.py` builds the bridge with a fake game (`tests/control_test.c`) and drives it over its real
transport: the Unix socket on Linux, the named pipe on Windows. On Windows it also checks the pipe's access control:
another first instance of the name and a second bridge on it are refused, and the DACL, read back through a client's
handle, is protected with a single entry for the current user. `tests/test_hookshot_ctl.py` drives the client
against a fake bridge on the same transports.
