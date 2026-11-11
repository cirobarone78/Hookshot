# Renderer CPU work and diagnostic traces

This change reduces repeated CPU work while retaining submitted-memory and texture
lifetime checks. It does not promise 60 FPS in every scene or with external effects.

## Behavior

- Preserve the Linux launch CPU allowance when querying process affinity. Pin the
  synchronous presentation thread to the renderer's reserved core; explicit `HOS_PIN`
  settings retain precedence. Background renderer workers avoid that reserved core.
- Reuse the thread-local descriptor writer within one descriptor build and retain
  resolved handles for shader answer validation. Live-memory diagnostic modes still
  reread handles. Texture slot versions and canonical type checks remain mandatory.
- Cache stage lowering by full control/code content, with bounded per-thread storage.
  `RX_VK_STAGE_CACHE=0` restores the uncached path for comparison.
- Retain upstream's 32-slot submitted-page cache and direct capture reads. The earlier
  local page-copy and block-copy experiments are superseded; `RX_VK_SUBMITTED_PAGES=1`
  selects upstream's one-slot comparison policy.
- Order overlapping deferred uniform writes with transfer dependencies. Adjacent or
  disjoint ranges do not need an additional barrier.
- Preserve the presentation aspect in diagnostic screenshots and retain per-frame
  dimensions with asynchronous readbacks. Thumbnail averages use actual sample counts;
  flash history is reset when capture dimensions change.

The upstream descriptor-invalidation, upload-deferral, swapchain-recovery and compute
preloading policies are preserved. No duplicate compute-cache format is introduced.

## Optional diagnostics

`RX_VK_PRESENT_STAGES=1` reports CPU wall-time buckets around presentation every 120
calls. Accepted Vulkan presents are not physical display timestamps.
`RX_VK_STAGE_TRACE=/absolute/file.csv` records bounded renderer stage intervals with
wall time and thread CPU time. `RX_VK_PROF_FINE=1` separates program/texture operations.
These modes add measurement overhead and should be disabled for baseline comparisons.

`analyze_stage_trace.py` and `export_renderer_timeline.py` consume recorded stage and
native-present CSVs. Nested work must not be added to its inclusive parent. Temporal
overlap is correlation; wall time minus thread CPU includes descheduling as well as
waiting. GPU execution time requires GPU timestamps.

`RX_VK_CAPTURE_CPU_UNCACHED=1` is an opt-in diagnostic for uncached capture buffers.
Its extra CPU snapshot payload is bounded to 128 MiB per capture and 256 MiB total;
allocation failure or budget exhaustion preserves the existing mapped-buffer path.
It has no demonstrated consistent FPS advantage and is not enabled by default.
`RX_VK_SUBMITTED_BLOCK_COPY` likewise remains an explicit experiment.

## Validation

The game-free tests compile production fragments with authored data. They cover
uniform-write ordering, submitted-page generations and aliases, stage-cache collisions
and eviction, handle-domain validation, capture bounds/geometry, trace accounting,
process affinity and synchronous/asynchronous render pin policy.

Use identical saved settings, output dimensions, scene intervals and warmed caches
for performance comparisons. Report cold starts separately. Keep generated fixtures,
saves, images, binaries and logs local; native present-call averages alone do not
establish complete scene coverage or smooth displayed gameplay.
