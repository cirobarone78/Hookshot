# Optional Linux DLSS5VKLayer adapter

This developer adapter launches an independently supplied
[DLSS5VKLayer](https://github.com/bmitch87/DLSS5VKLayer) helper and Vulkan layer in a
private session. It does not download, bundle or install the bridge or model,
and does not register a desktop-wide Vulkan layer. This is separate from
Hookshot's built-in NVIDIA DLSS integration.

The patches target external revision `c77b64c9826a3b7c741c8b160fbd0b2c29a8eae3`
(release 0.3.2-1). That project's AGPL-3.0 license continues to apply to its source
and patched derivatives. No model DLLs, external binaries or game data are included.

## Transport and presentation fixes

- `stable-host-mappings.patch` keeps the full shared-memory regions mapped at stable
  addresses on 64-bit Linux. Model resize must not unmap pages while Vulkan still
  imports them. It releases compositions before closing mappings at device teardown.
- `present-completion.patch` uses image-owned completion semaphores, so presentation
  cannot wait on only the original application's render while composition still writes.
- `swapchain-access.patch` covers capture and composition accesses in swapchain layout
  transitions, including the final write before presentation.

The adapter creates transport storage under private tmpfs `/dev/shm`, validates its
filesystem, and removes it only after target/helper shutdown. Regular file mappings
caused host-memory-import failures in local NVIDIA testing; there is no disk fallback.
Stable virtual reservations do not alone commit every page, but the external helper's
imports can commit approximately 507 MiB of shared storage. This is additional to
model, driver and game memory.

Apply patches to a clean checkout of the pinned revision, in the order above. Keep
that checkout under `work/dlss5/source`. Build it using its own build instructions.
The experimental GPU-image transport is not part of this adapter or patch set.

## Private integration manifest

Create `integration.json` in a private base directory with:

- `version`: a descriptive bridge version;
- absolute `proton` and `steam_root` paths;
- `artifacts`: entries `helper`, `layer`, `shmctl` and `model`, each with absolute
  `path` and verified `sha256`;
- a matching Vulkan layer manifest in `BASE/layers`.

The adapter checks artifact hashes before launching. The base owns its dedicated
Proton prefix and session lock. Do not reuse another application's prefix.
Logs and archived session descriptors remain in `BASE/runs`.

```sh
python3 -I scripts/dlss5_api.py --base /absolute/private/base run -- /path/to/program
python3 -I scripts/dlss5_api.py status /path/printed/by/launch/session.json
python3 -I scripts/dlss5_api.py set /path/to/session.json workingscale 0.75
```

`run --preferences /absolute/settings.json -- COMMAND` uses a separate preferences
file. Otherwise the adapter uses the base's preferences. CLI `set` changes the live
session; Python `save_preferences()` persists settings. Ended sessions return archived
status and cannot recreate transport storage. Shutdown targets only the dedicated
prefix and waits for its server to exit, including when the helper has already died.

Ready status does not prove successful inference. Check advancing `helper_frames`,
`model_up=1` and the actual composed window. Native frame counts, model evaluations
and displayed frames measure different things. No stable-60-FPS guarantee is made.

## Validation

```sh
python3 -I -B tests/test_dlss5_api.py
python3 -I -B tests/test_dlss5_control.py
python3 -I -B tests/test_dlss5_controls.py
python3 -I -B tests/test_dlss5_menu.py
python3 -I -B tests/test_dlss5_mapping.py
python3 -I -B tests/test_dlss5_present_sync.py
```

Lifecycle tests use authored executables. The optional mapping and synchronization
tests compile actual functions from the pinned, patched local checkout with authored
fixtures; they skip when the external source or required compiler/headers are absent.
They cover stable addresses across resize, partial mapping failures, teardown,
delayed composition, image-owned waits, missing original waits and recovery paths.
`DLSS5_LAYER_SOURCE` overrides the layer file; protocol/headers still come from the
pinned checkout. `dlss5_present_vulkan.cpp` supplies a separate real-Vulkan harness.

These checks establish transport/lifecycle behavior, not neural image quality,
complete gameplay coverage or a performance improvement. Model visual evaluation
and real scene timing remain separate acceptance checks.

## Native settings control bridge

The adapter exposes `HOS_DLSS5_CONTROL` only to its child game. It names a private
session directory with a versioned file protocol; the renderer does not map or
interpret the external project's shared-memory ABI. The native F1 Graphics page
provides the basic controls and an advanced section for all 19 settings, plus model
status. Controls are unavailable outside an active adapter session. The adapter
no longer exports the former F10 menu hook. Filesystem work stays on the native
client worker, and helper control/persistence stays on the adapter worker.

`state` is an atomic ASCII `key=value` snapshot, capped at 4096 bytes: `protocol=1`,
`ack`, `available`, `helper_state`, `model_up`, `error`, and all 19 documented
`SETTINGS` keys. Float settings use integer hundredths; enum/bool values are
unchanged. `request` has `protocol=1`, a positive monotonically increasing
uint64 `sequence`, and all 19 settings. The adapter validates the complete request
before applying any key, ignores stale sequences, acknowledges invalid complete
requests with an error, and saves preferences after successful application.
The external commands are not transactional: a command failure reports actual
settings where readable and never persists a partially applied full request.
Untouched values retain their original precision when saved.

The native page writes a new uint64 nonce to `poll` at most twice a second while
open. Every new nonce refreshes and rewrites `state`, even if values did not
change. Otherwise the adapter only checks file metadata; it launches no periodic
control subprocesses during gameplay. IPC/persistence runs on the adapter's
worker, which stops before helper teardown. The native client must treat missing,
stale or unavailable state as unavailable controls and initialize its next
request sequence above the acknowledged sequence.
