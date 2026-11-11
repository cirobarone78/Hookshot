# Upscaling, frame generation and latency

Hookshot can draw the 3D scene smaller than your screen and enlarge it with an upscaler, add generated frames for
smoother motion, and cut input delay with NVIDIA Reflex or AMD Anti-Lag 2. All of these are on the
[Graphics tab](settings.md#graphics). This page helps you choose.

- [Which upscaler?](#which-upscaler)
- [Getting DLSS](#getting-dlss)
- [Getting FSR 4](#getting-fsr-4)
- [Frame generation](#frame-generation)
- [Input delay: Reflex and Anti-Lag 2](#input-delay-reflex-and-anti-lag-2)
- [Is it working?](#is-it-working)

## Which upscaler?

| Your card | Try first | Notes |
|---|---|---|
| NVIDIA RTX | **NVIDIA DLSS** | Needs DLSS in your build ([below](#getting-dlss)). Set **Sharpness** to about 80%: DLSS is softer than the game's own |
| Newer AMD | **AMD FSR 4** | Needs FSR 4 in your build ([below](#getting-fsr-4)). The row only offers it if AMD's files support your card; otherwise use FSR 3.1 |
| Any other card | **Game's own** or **AMD FSR 3.1** | FSR 3.1 is in every build and runs on most cards |
| A slow card | **Off (no upscaling)** with a lower Render resolution | The fastest choice; edges are rough |

Then pick the **Render resolution**: the share of the screen the 3D is drawn at. Lower is faster and softer.

- **Auto** lets the game lower it when the card is busy, as on the Switch.
- With DLSS or FSR 4, **Quality (67%)** is a good start. **Native** draws at full size and only smooths edges
  (DLAA, or FSR 4's Native AA): the sharpest and the most demanding.
- On a card with 8 GB of video memory or less, DLSS at Native can run out of memory in busy areas and stutter.
  Quality or Balanced is safer there.

## Getting DLSS

DLSS uses NVIDIA's files, which Hookshot can't ship. The builder downloads them for you if you ask:

1. In the builder, tick **NVIDIA DLSS (downloads NVIDIA's SDK under NVIDIA's license)** before you press **Build the
   game**. On Windows it shows NVIDIA's license first; the box stays ticked only if you accept.
2. After the build, choose **NVIDIA DLSS** in the Upscaler row.

A game you've already built without it needs building again with the box ticked. Updates keep it.

NVIDIA's files stay on your PC. Don't share a game folder that was built with them.

## Getting FSR 4

FSR 4 uses AMD's files, which Hookshot can't ship either.

- **Windows:** tick **AMD FSR 4 (downloads AMD's runtime under AMD's license)** in the builder before you build. It
  shows AMD's license first. Then choose **AMD FSR 4** in the Upscaler row.
- **Linux:** the builder doesn't offer FSR 4 yet. It works in a game built from source with `--fsr` and a Vulkan FSR 4
  library (`amd_fidelityfx_upscaler_vk.so`, such as fsr4-vk's) in the game folder: see the
  [developer guide](../dev/building.md).

If the files are missing, the Upscaler row says so and offers the other choices.

## Frame generation

**Frame generation** adds frames between the game's own. Motion looks smoother, at the cost of a little input delay,
and fast motion or camera cuts can show flaws.

- **Auto** adds as many frames as your display's refresh rate needs. **2x** doubles the frame rate, **3x** triples
  it, and so on up to 8x.
- With the **Game frame rate cap** at 60 and Frame generation at 2x, you see up to 120 frames a second.
- **Frame generation by: Auto** uses NVIDIA DLSS Frame Generation on RTX 40 series and newer cards, when DLSS, FSR 3.1
  or FSR 4 is the Upscaler. Otherwise Hookshot's built-in generator makes the frames. **Built-in** always uses
  Hookshot's.
- **Frame pacing: On** shows frames at an even interval. That means less stutter for up to one frame more delay.
  It only matters while Frame generation is on.

When you measure performance, turn Frame generation off so the frame counter shows the game's own frames.

## Input delay: Reflex and Anti-Lag 2

**NVIDIA Reflex** (NVIDIA cards) and **AMD Anti-Lag 2** (AMD cards) start each frame as late as they can, so what you
press shows up sooner. Each row only appears if your card and driver support it.

- Reflex works with frame generation too. **On + Boost** also keeps the card's clocks up.
- Anti-Lag 2 isn't used while Frame generation is on.

## Is it working?

Turn on the **FPS counter** on the [Gameplay tab](settings.md#gameplay). With frame generation on, it shows the game's
own frame rate beside the total. **Frame time** and **Graph** add how long each frame takes, and the 1% low.

`hookshot_log.txt` in the game folder also says whether DLSS or FSR 4 started, and why not if they didn't: look for
lines starting `vk: NVIDIA DLSS:` or `vk: AMD FSR 4:`. If something's wrong, see
[troubleshooting](troubleshooting.md).
