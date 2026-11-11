# Performance comparisons

Use a disposable save and a private game folder, including options and writable caches.
Keep game-derived fixtures, captures, binaries and results under ignored `work/`.
Match the player's saved aspect ratio, quality settings, output size and effect state explicitly;
the analysis launcher's default 16:9 window is not an ultrawide performance baseline.
Use `--saved-aspect` to inherit the copied options' Ultrawide selection.
Verify effective render and swapchain dimensions in the log before comparing results.

An acknowledged input does not prove scene arrival. Verify the destination, advancing
frames and screenshots before measuring. Test first-use loading separately from warm play.
A successful build or an average of 60 FPS does not establish smooth displayed gameplay.

## Recording and analysis

`analysis_api.py start --present-trace` writes `native-presents.csv` into the private run directory.
The trace records every native present-call return, independently of screenshot cadence. It does
not measure physical display presentation or GPU completion. Preserve the session descriptor,
options, binary hashes, save hashes, input timings, screenshots and scene start/end native frame IDs.
A forced process stop can lose the last second of buffered trace data; analyze only a fully flushed
segment. The analyzer rejects missing frames and inconsistent timestamps instead of certifying a
partial segment:

```sh
python3 -I scripts/analyze_present_trace.py work/runs/<run>/native-presents.csv \
  --first-frame <first-scene-frame> --last-frame <last-scene-frame>
```

It reports mean FPS, frame-time percentiles, longest frame, frames exceeding the target budget and
the slowest sliding window spanning at least one second. An average over 60 FPS cannot hide a
single over-budget frame. Scene coverage and visual correctness remain separate checks.

Scene playlists now record native counters immediately before and after each API
operation, including a failed operation when its ending counter remains available.
Run with `--present-trace`, then analyze the playlist report after its trace tail
has flushed:

```sh
python3 -I scripts/analyze_scene_cases.py work/runs/<run>/scene-cases-<id>.json
```

The analyzer requires the report's own session/process identity and trace. The
inclusive measured range is `frame_before + 1` through `frame_after`; it retains
the first interval crossing the request boundary. External load calls, event calls
and setup/assertion calls appear separately. An event call still includes its
validation, dispatch, internal map changes, lifecycle settling and input cleanup.
A wait call measures only the observed suffix of an already-running event. These
are conservative operation intervals, not exact cinematic timeline boundaries.
No-frame calls, missing/unflushed frames or malformed traces are unavailable rather
than passing. Failed/incomplete playlists cannot receive a positive aggregate event
verdict. The report never sets `performance_certified`: screenshots, complete scene
coverage, displayed behavior and DLSS/native counter separation still need review.

Use `--frame-generation 0` for native-throughput comparisons. For DLSS, keep the copied model
preferences fixed (`--dlss5`) and measure model evaluations separately from native frames.
`--fps-target 60..240` is a diagnostic minimum engine limiter target, not a guarantee of achieved
FPS or correct game speed above 60. Validate timing and animation before treating uncapped results
as playable. `--profile` enables slow-frame logs and all-thread sampling while `stacks.txt.go`
exists in the run directory. With DLSS enabled it also enables layer/helper timing logs
(`DLSSNR_TIME=1`, every 30 model frames); these timers include synchronization and
are not isolated GPU kernel measurements. Sampled runs are diagnostic, not clean performance baselines.

Warm caches consistently, compare the same scene interval, and do not run compilers or unrelated
CPU/GPU tests during timed sections. Include cold starts separately; warming is not a fix for
first-use stalls. Repeat the baseline after the candidate to identify drift.


## Optional renderer timing collectors

Private analysis runs can forward `--present-stages` and `--stage-trace` to a
renderer with separately supplied collectors. This API change does not implement
those collectors. Confirm support and actual output before interpreting a run;
record the exact renderer version alongside the session manifest. CPU wall-time
buckets do not measure GPU execution time, and instrumentation overhead requires
a matching disabled comparison.

See [runtime-api.md](runtime-api.md) for the optional switches and scene controls.
