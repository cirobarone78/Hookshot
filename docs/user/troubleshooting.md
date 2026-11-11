# Troubleshooting

Find your problem by what you see, and try the fix next to it. If nothing here helps, send a bug report: the first
section says what to include.

- [Collecting what we need for a bug report](#collecting-what-we-need-for-a-bug-report)
- [The game won't start or crashes](#the-game-wont-start-or-crashes)
- [Picture problems](#picture-problems)
- [Performance and stutter](#performance-and-stutter)
- [Linux](#linux)
- [Linux: udmabuf warning](#linux-udmabuf-warning)
- [Builder problems](#builder-problems)
- [hookshot_env.txt](#hookshot_envtxt)

## Collecting what we need for a bug report

**The game's log.** `hookshot_log.txt` in the game folder holds the last run. The four runs before it are kept as
`hookshot_log.1.txt` (the most recent) to `hookshot_log.4.txt`, so if you started the game again after a crash, the
crash is in `hookshot_log.1.txt`. If you start the game from a terminal, it prints the log there instead.

**On Linux, when Play closes at once.** If you press **Play** in the builder and the game closes before it writes a
log, look for `hookshot_startup.log` in the game folder. It holds what the game printed while starting (up to 64 KB)
and its exit status.

**When a build fails on Windows.** The builder shows what went wrong, with a **Copy for a bug report** link under it.
It copies the builder's version, your Windows version, the error and the last 200 lines of the build log, ready to
paste into a report.

**What to include in a report:**

| | |
|---|---|
| Version | The Hookshot version, shown in the in-game menu's banner and on the [releases page](https://github.com/NotRexed/Hookshot/releases) you downloaded from |
| Where | Where you were in the game, and what you were doing |
| Graphics card | Its model, and your driver version if you know it |
| Log | `hookshot_log.txt` from the run that had the problem |
| Picture | A screenshot or a short video, for anything you can see |

Open a report on the [issue page](https://github.com/NotRexed/Hookshot/issues/new/choose). **Never send game files**:
not the `.nup`, not `romfs` or `exefs`, and not the built game folder.

## The game won't start or crashes

| What you see | What to do |
|---|---|
| "Hookshot supports build e0f3ccfa" or "This version isn't supported" | Your game isn't the supported version. Check that you chose the right game with update v131072 installed (see [What you need](install.md#what-you-need)) |
| The game opens and closes, or the log says "device lost" | Update your graphics driver. If it keeps happening, try **Mesh shaders: Compute** on the Graphics tab, then restart |
| Steam Deck: the game freezes and closes in Kokiri Forest or inside the Great Deku Tree, and `journalctl -k` shows `gfx_0.0.0 timeout` | Add `RX_VK_MESH_NOCULL=2c56dc1006942f74` to [`hookshot_env.txt`](#hookshot_envtxt). Everything is still drawn. `RX_VK_SKIP_CODE=2c56dc1006942f74` also avoids the freeze, but some models go missing |
| The game is in the wrong language | Open `language.txt` in the game folder, change the code to one of those listed in it, save, and start the game again. Updates keep the language you set |

## Picture problems

| What you see | What to do |
|---|---|
| A place has a wrong texture, or a floor or wall is missing | Look for `hookshot_damaged_files.txt` in the game folder. The build writes it when your game dump is incomplete (about 23.3 GB, where a complete one is about 23.8 GB). It lists each damaged file and what was put in its place. Dump the game again and build from the new dump; the file then goes away |
| A message says your graphics card has no mesh shader support, and parts of the picture are missing | Your card or driver can't run the game's scenery at all. Update the driver. On a card without mesh shaders the game normally uses a slower compute path instead; this message means even that isn't available |
| Objects are missing or flicker, or the card crashes in one place | Set **Mesh shaders** on the Graphics tab to **Compute** and restart. The game then runs its scenery as compute shaders, which is usually a little slower but avoids driver problems with mesh shaders |
| AMD: blocky textures, solid rectangles in the sky, or courtyard surfaces that are much too dark | Try the [AMD texture workaround](#amd-texture-workaround) |

### AMD texture workaround

On some AMD cards a few textures come out blocky or wrong. To work around it, the game can keep those textures
uncompressed instead of converting them to a compressed format:

1. Open the [in-game menu](settings.md) and go to the **Debug** tab.
2. Under **Developer**, set **ASTC as RGBA8** to **On**.
3. Restart the game.

This uses much more video memory, and on a card without memory to spare it can cause stalls. It fixes these texture
artifacts only; it doesn't change lighting. To undo it, set the row back to **Off** and restart.

`RX_VK_ASTC_RGBA8=1` in [`hookshot_env.txt`](#hookshot_envtxt) does the same. While that line is there, the menu row
shows "Set by RX_VK_ASTC_RGBA8" and can't be changed; remove the line to choose in the menu again.

## Performance and stutter

| What you see | What to do |
|---|---|
| Short stutters the first time you see something | Normal: the graphics card is finishing setting up what it draws there. Passing through the same place again is smooth. You can help remove these stutters for everyone: [send your pipeline list](#send-your-pipeline-list) |
| Windows, NVIDIA: stutter in places you've already seen, at every start | The driver's shader cache is too small to keep everything the game prepares (about 2 GB on the first start). In the NVIDIA Control Panel, open **Manage 3D settings** and set **Shader Cache Size** to **Unlimited** (or 10 GB). On Linux the game raises this limit itself |
| Low frame rate, or stalls that come and go | Pick a lower **Quality preset** on the Graphics tab, or a smaller **VRAM budget** if your card has little video memory. On Linux with an AMD card, check for the [udmabuf warning](#linux-udmabuf-warning) |

### Send your pipeline list

The first time the game meets a new pipeline (a combination of shaders and drawing state), it has to build it on the
spot, and that stutters. Releases ship a list of known pipelines and build them before the title screen. Your play adds
to that list:

1. Open the menu, go to the **Debug** tab and choose **Save my pipeline list** (under Developer). Or press **Save my
   pipeline list** on the builder's launcher page for your game.
2. It saves `hookshot-pipelines-<date>.zip` in your Downloads folder, copies a filled-in report to the clipboard, and
   opens the [Submit your pipelines](https://github.com/NotRexed/Hookshot/issues/2034) issue in your browser.
3. Attach the zip to a comment there, paste the report, and say where you played.

The zip holds only `hookshot_pipeline_states.bin` (shader hashes, formats and drawing state: no game code, game data or
personal information) and the report (version, system, graphics card and driver, resolution, upscaler, frame
generation, HDR, and the mods the game loaded). Nothing is uploaded for you.

### Reporting low FPS or stutter

A performance report is most useful when it compares like with like:

1. Wait until the shaders are prepared, then walk through the slow spot **twice**. Note whether the slowdown goes away
   on the second pass or lasts until you restart the game.
2. If it got slower after an update, compare the same spot with the same settings on both versions, if you still have
   the older one.
3. Turn **Frame generation** off for these runs, so the FPS counts the game's own frames. Keep the resolution,
   upscaler and frame rate cap the same.

Attach the log from the slow run, and the one from the older version if you have it. Say where the FPS dropped, and
make sure the lines around the drop are there: those with `presents`, `GPU time`, `waits for shaders or pipelines`,
`VRAM:` and `memory heaps`.

If `GPU time` stays high, do one more run with `RX_VK_PASS_TIMING=1` in [`hookshot_env.txt`](#hookshot_envtxt). Every
600 frames the log then says which parts of the frame take the GPU's time. Send that log as well, but keep the first
one for the FPS comparison, because the timing itself slows the game a little. Remove the line afterwards.

## Linux

| What you see | What to do |
|---|---|
| The game doesn't start, or the picture is broken | The game needs a Vulkan 1.3 driver. Update Mesa or the NVIDIA driver. `vulkaninfo \| grep mesh` should list `VK_EXT_mesh_shader`; without it the game uses its slower compute path |
| The log says `WARNING: /dev/udmabuf permission denied` | See [Linux: udmabuf warning](#linux-udmabuf-warning) |
| Play closes and there's no `hookshot_log.txt` | Look at `hookshot_startup.log` in the game folder (see [above](#collecting-what-we-need-for-a-bug-report)) |

## Linux: udmabuf warning

On Linux the game shares memory with the graphics card through the kernel's `/dev/udmabuf` device. If your user can't
open it, the game falls back to a slower method, and prints this warning on start and in `hookshot_log.txt`:

```text
WARNING: /dev/udmabuf permission denied; GPU imports may be slower, especially on AMD/RADV.
```

**Who needs it.** Players with an AMD card, where the fallback is much slower. **With an NVIDIA card on NVIDIA's own
driver, ignore the warning**: that driver doesn't use the device, and the fallback isn't slow there. The game checks
before it knows which card you have, so it warns everyone.

**Check.** Look at who owns the device, and which groups you're in:

```sh
ls -l /dev/udmabuf
id
```

If the device doesn't exist at all, load its kernel module first (your distribution has to provide it):

```sh
sudo modprobe udmabuf
```

**Fix.** Pick one of these. All of them need an administrator (`sudo`).

1. **For a desktop session on this PC (recommended).** Create `/etc/udev/rules.d/70-hookshot-udmabuf.rules` with
   this line:

   ```text
   SUBSYSTEM=="misc", KERNEL=="udmabuf", TAG+="uaccess"
   ```

   This gives the device to whoever is logged in at the PC (with systemd-logind). The file name must sort before
   `73-seat-late.rules`, so keep the `70-`. It doesn't cover users who log in over SSH, or services.

2. **For SSH or service users.** Create a dedicated `udmabuf` group, add only the user who runs the game, and put
   this line in the same file instead:

   ```text
   SUBSYSTEM=="misc", KERNEL=="udmabuf", GROUP="udmabuf", MODE="0660"
   ```

3. **Join the group that already owns the device** (the group shown by `ls -l`), then log out and back in. Only do
   this if access to that group's other devices is fine: if the group is `kvm`, it also gives access to
   virtualization.

After options 1 or 2, reload the rules and apply them:

```sh
sudo udevadm control --reload-rules
sudo udevadm trigger --action=add /sys/class/misc/udmabuf
```

After a group change, log out and back in (or restart the service) so it takes effect.

**Don't** run the game as root, and don't make the device writable by everyone.

## Builder problems

| What you see | What to do |
|---|---|
| "Your antivirus removed part of the build tools" | A false alarm on unsigned programs. Restore the files from Windows Security's **Protection history**, or add `%LOCALAPPDATA%\HookshotBuilder` to its exclusions, then press **Repair** |
| Windows setup says the Builder's files are incomplete, or the Builder won't start after installing | Run the official `HookshotBuilder.exe` setup again. If it reports missing startup files again, check your antivirus's quarantine or protection history for files removed from that folder, restore them or add an exclusion, then retry. Installing .NET separately doesn't help: the Builder carries its own runtime. You can still start an already-built game from `hookshot.exe` in its folder |
| "This version isn't supported. Hookshot needs build e0f3ccfa." | The game files you chose aren't the supported version (see [What you need](install.md#what-you-need)) |
| The build stopped with an error | On Windows, press **Copy for a bug report** and paste it into a [report](https://github.com/NotRexed/Hookshot/issues/new/choose) |

## hookshot_env.txt

Some fixes on this page ask you to add a line to `hookshot_env.txt`. It's a plain text file in the game folder, next
to `hookshot_options.ini`; create it if it isn't there. Each line is one setting, written `NAME=value`:

```text
RX_VK_ASTC_RGBA8=1
```

The game reads it at every start. Lines starting with `#` are notes. It only takes the game's own settings (names
starting with `RX_`, `HOS_`, `HOOKSHOT_`, `EDEN_`, `NVN_` or `SDL_`) and no file or folder paths; anything else is left
out, and the log says so. To undo a setting, delete its line.

Most settings have a row in the [in-game menu](settings.md), which is the easier way to change them. The full list of
switches is in the [switch reference](../dev/switches.md).
