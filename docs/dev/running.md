# Running the game

How to start a built game by hand: its arguments, the switches it reads, scripted test runs, screenshots and
profiles. The full list of switches is in [switches](switches.md); the control bridge, which drives a running game from
a script, is in [automation](automation.md).

- [Where the game is](#where-the-game-is)
- [Command-line arguments](#command-line-arguments)
- [Running a standalone build](#running-a-standalone-build)
- [Switches and hookshot_env.txt](#switches-and-hookshot_envtxt)
- [Scripted input](#scripted-input)
- [Screenshots](#screenshots)
- [Headless and background runs](#headless-and-background-runs)
- [Profiling](#profiling)

## Where the game is

| Build | The game | Its files |
|---|---|---|
| Hookshot Builder, Windows | `bin\hookshot.exe` | The game folder |
| Hookshot Builder, Linux (AppImage) | `bin/hookshot` | The game folder |
| `make_game.py` from a source checkout | `hookshot.exe` or `hookshot` at the top of the game folder | The game folder |
| `nx2/build.py --standalone` | `work/sa/build/hookshot.exe` or `hookshot` | Named on the command line |

In a packaged folder, `hookshot.exe` or `hookshot` at the top is the launcher. It does not pass arguments on: start the
game in `bin` directly to use them.

The game writes its log to `hookshot_log.txt` in the game folder and keeps the four runs before as
`hookshot_log.1.txt` to `hookshot_log.4.txt`. Started from a terminal, it writes the log to the terminal instead.

## Command-line arguments

```text
hookshot [image.bin] [--romfs <dir>] [--user <dir>] [--trace] [--prepare-shaders]
```

| Argument | What it does |
|---|---|
| `image.bin` | The game image to run. Without it, the game uses the `image.bin`, `romfs` and saves of its own folder |
| `--romfs <dir>` | The extracted RomFS folder |
| `--user <dir>` | Where the game keeps saves, caches and temporary files. Default: `user` in the game folder on Windows, `~/.local/share/hookshot` on Linux; with an explicit image, `user` in the current folder |
| `--trace` | Log every Horizon OS call. The same as `HOS_TRACE=1` |
| `--prepare-shaders` | Prepare the shaders as the first start does, then exit without starting the game. Prints `@@done shaders`, or exits with 3 when there is no usable Vulkan device |

For example, to keep the saves somewhere else:

```powershell
cd "C:\Games\Hookshot"
.\bin\hookshot.exe --user "D:\Hookshot data"
```

```sh
cd ~/Games/Hookshot
./bin/hookshot --user "$HOME/hookshot-data"
```

## Running a standalone build

A build from the [stages](building.md#building-in-stages) has no game folder. Name its image, the RomFS and a saves
folder:

```sh
work/sa/build/hookshot work/sa/image/image.bin --romfs work/dump/romfs --user work/sa/user
```

On Windows, `scripts/run-vk.ps1` does this for you. It reads the RomFS from `work\dump.txt`, writes everything to
`work\runs\<name>\` (the log as `log.txt`, screenshots in `shots\`), and stops the game after the time given:

```powershell
powershell -File scripts/run-vk.ps1 -Window -Seconds 120 -Name start
```

| Parameter | Default | What it does |
|---|---|---|
| `-Seconds <n>` | 120 | How long the game runs before it is stopped |
| `-Name <name>` | `vk` | The run's folder under `work\runs` |
| `-ShotEvery <n>` | 300 | A screenshot every that many presented frames |
| `-Window` | off | Open a window, behind the one in front. Without it the run is headless |
| `-Sound` | off | Play sound. Without it the run is muted |
| `-Env "A=1;B=2"` | none | More switches for this run |
| `-Romfs <dir>` | from `work\dump.txt` | Another RomFS folder |
| `-MaxGB <n>` | 10 | Stop the game when its memory passes this |
| `-Priority <class>` | `High` | The game's process priority |
| `-Force` | off | Run even while another game run is going |

Screenshots reach gigabytes and are made from the game: delete `work\runs\<name>\shots` once you have looked at them,
and never commit them.

## Switches and hookshot_env.txt

The game reads its switches from the environment, and from `hookshot_env.txt` in the game folder (beside the executable
for a standalone build). The running game reads the file, not the builder. Each line is `NAME=VALUE`; blank lines,
lines without `=` and lines starting with `#` are skipped, and spaces around a line are ignored.

`hookshot_env.txt` is a file players pass around, so it takes only the game's own switches (names starting with
`RX_`, `HOS_`, `HOOKSHOT_`, `EDEN_`, `NVN_` or `SDL_`) and no paths. Switches that name a file or folder, and the
timed-input switches, are left out of it, and the log names each line it leaves out. [Switches](switches.md#setting-a-switch)
has the exact rules.

`HOS_ENV_FILE=<path>`, set in the environment, makes the game read that file instead and leave the player's
`hookshot_env.txt` alone. That file has none of the limits: scripted runs and switches that take a path go there.

A switch set in the environment wins over the same name in either file, and within a file a later line replaces an
earlier one. A switch that stands in for a menu row applies to that run only: `hookshot_options.ini` keeps the value
chosen in the menu.

## Scripted input

`HOS_INPUT_SCRIPT` presses buttons at set times, for repeatable test runs:

```text
HOS_INPUT_SCRIPT=50:A,52:A,80:LUP/4000
```

Each press is `<seconds>:<button>[+<button>...][/<ms held>]`, separated by commas, held 200 ms unless given. The
buttons are `A B X Y L R ZL ZR PLUS MINUS LS RS LEFT UP RIGHT DOWN`, and the stick directions `LUP LDOWN LLEFT LRIGHT
RUP RDOWN RLEFT RRIGHT`.

`HOS_INPUT_LIVE=<file>` takes presses in the same syntax from lines appended to that file while the game runs, timed
from when each line is read: a test can look at a screenshot and decide its next press. `HOS_INPUT_EXCLUSIVE=1` keeps
the player's devices out until 5 s after the last press, and `HOS_INPUT_FRAME_CLOCK=1` times the script in frames
rather than seconds of wall clock. [Switches](switches.md#scripted-test-runs) lists the rest.

Scripted presses are applied before the window-focus check, so they reach the game while its window is behind
another. A log line saying the game window is not in front does not mean they were dropped. The game still has to be
in a state that reads the controller. The keyboard and mouse always stay with the window in front.

For anything more than timed presses, use the [control bridge](automation.md): `HOS_CONTROL=<socket path>` and
`scripts/hookshot_ctl.py`.

## Screenshots

`RX_VK_SHOTS=<folder>` writes a PNG every 300 presented frames, as `vk_<frame>.png`, at 1280x720.
`RX_VK_SHOT_EVERY=<n>` changes the interval, and `RX_VK_SHOT_W` and `RX_VK_SHOT_H` the size. A headless run still
draws, offscreen, and takes its screenshots the same way. These switches name a folder, so they go in the environment
or a `HOS_ENV_FILE` file.

The flash detector, frame dumps, frame logs and pass probes build on the same capture; they are in
[switches](switches.md#pictures-frames-and-logs).

## Headless and background runs

| Switch | What it does |
|---|---|
| `HOS_HEADLESS=1` | No window. The renderer draws offscreen, for screenshots and frame dumps. The low-memory and movie notices are not shown |
| `HOS_WINDOW_NOACTIVATE=1` | Windows: the window opens behind the one in front, so a test run does not take the keyboard |
| `HOS_AUDIO=0` | No sound |

## Profiling

The game samples itself; scripts in `scripts/` read the samples and name the functions from the linker maps beside
`work/sa/build` (on Linux, from the binaries' own symbols). `RX_MAPS=<folder>` points them at another build, or on Linux
at a game folder.

| Switch | What it does |
|---|---|
| `HOS_PROFILE=<seconds>` | Every interval, log the busiest threads and their share of a core. Needed for `HOS_SAMPLE` |
| `HOS_SAMPLE=<name>` | Sample the thread whose name contains `<name>` every millisecond, and log its hottest places each interval. The `HOS_PROFILE` lines show the names |
| `HOS_SAMPLE_FILE=<file>` | With `HOS_SAMPLE`: also write every sample's whole stack, one line each |
| `HOS_SAMPLE_ALL=<file>` | While `<file>.go` exists, sample every game and renderer thread every 2 ms into `<file>` |

| Script | Reads | Shows |
|---|---|---|
| `python -I scripts/prof.py <stacks file> [top] [skip] [only]` | `HOS_SAMPLE_FILE` | Functions by inclusive and self share |
| `python -I scripts/crit.py <all file> [top]` | `HOS_SAMPLE_ALL` | The frame's critical path: what each thread waits in |
| `python -I scripts/vkprof.py <all file> [top] [prefix]` | `HOS_SAMPLE_ALL` | The renderer's threads |
| `python -I scripts/hotlist.py <all file> <out> [share] [max]` | `HOS_SAMPLE_ALL` | The hot lifted functions, as a list for the lift |
| `python -I scripts/cpu_report.py <run folder>... --maps <folder> --out report.md` | `HOS_SAMPLE_ALL` | A report by category, thread and function |

A sampled run on Windows, with `run-vk.ps1`:

```powershell
powershell -File scripts/run-vk.ps1 -Window -Seconds 180 -Name prof -Env "HOS_PROFILE=10;HOS_SAMPLE=<thread>;HOS_SAMPLE_FILE=stacks.txt"
python -I scripts/prof.py work/runs/prof/stacks.txt
```

`run-vk.ps1` starts the game in `work\runs\<name>`, so a bare file name lands there. The switches for frame logs,
frame dumps and GPU timing are in [switches](switches.md).
