# Notes for AI coding agents

Start with the [workflow](docs/dev/workflow.md): what to work on first, the hardware tiers a change must not break,
and the steps from claim to release. The open work, scored and sorted, is in the [worklist](docs/worklist.md): pick
from its top.

[CONTRIBUTING.md](CONTRIBUTING.md) applies to agents as to everyone, above all: **no game files, or anything made from
them, leave the PC.** The [developer documentation](docs/dev/README.md) has building, running, switches, the
architecture and testing.

What agents trip on:

- **Tests read the source.** Many checks in `tests/` find a function in a source file by its text, cut it out and
  compile it with stubs. Renaming or reshaping a function can break a check far from your change. Run
  `python -I -B tests/run_all.py` before every pull request, and update a broken check in the same pull request
  rather than weakening it. See [testing](docs/dev/testing.md).
- **The renderer's interface is versioned.** A change to `MkwVkHost` or `MkwVkRenderer` in `gpu/vk/vk_api.h` bumps
  `MKWVK_API_VERSION`.
- **Generated files are generated.** The `*_spv.h` headers in `gpu/vk/shaders/` and `gpu/vk/host_shaders/` are
  compiled from the shader beside them with glslang. Regenerate them; do not edit them.
- **Two platforms.** Windows builds with llvm-mingw, Linux with clang. Keep host code portable and paths UTF-8 (no
  `CP_ACP`; `tests/test_utf8_paths.py`).
- **No game in CI.** Checks must run without a dump. A run in the game is yours to do locally and report.

Pull requests open with why they are needed, in one or two plain sentences, and include screenshots when the change
shows on screen.
