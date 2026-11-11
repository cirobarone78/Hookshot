# Bounded native presentation

`RX_VK_ASYNC_PRESENT=1` enables a three-image presentation queue for native frames.
It is off by default, and frame generation remains a separate path. Each owned
source-format image has a timeline: an odd value publishes its capture, and the
following even value releases its presentation read. The renderer submits the
capture before publishing the worker job. Reuse waits for the previous release.
The worker executes the real Vulkan Present call and retains its slot until that
call returns. It never retains caller-owned Vulkan structures past their API call.

Hidden or out-of-date output submits a ready-to-consumed transition, preserving
slot reuse. Failed capture submission is not admitted. Source format, crop and
native-PQ interpretation travel with the frame. Source size/format changes drain
queued jobs and the device before replacing resources. Transitions between native,
direct and interpolated output drain earlier work. Queue depth is bounded at three;
additional overlap can increase latency. The renderer's existing process-lifetime
worker model is retained; this does not add a renderer unload contract.

## Queue selection

`RX_VK_PRESENT_QUEUE=0` retains the existing graphics queue. Mode `1` requests a
separate compute-family queue, subject to surface support. Mode `2` requests a
second queue from the graphics family, when available. It falls back when the
selected family or queue cannot serve the surface. These modes are opt-in.

On a separate queue, present_out releases the main submit mutex before the external
Present call. On a single queue, submission stays serialized. An injected Vulkan
layer must also synchronize independent queues separately for overlap to survive;
the external DLSS5VKLayer changes are maintained in that repository.

## Locking and lifetime

The worker never acquires replay_mu. Recorder foreign_wait snapshots only already
published work; its decoder executes Vulkan commands without replay_mu/native.mu
or the presentation mutex. Capture submit crosses the recorder queue boundary
before publishing the job. Slot reuse therefore waits on a signal already enqueued
by the worker, rather than work requiring future producer progress. Image replacement
uses device_wait_idle_locked, including separate-present-queue exclusion.

## Trace

`RX_VK_ASYNC_PRESENT_LOG=/absolute/path.csv` records source frame IDs and host-clock
nanoseconds for source call, enqueue, worker start, actual Present begin/return and
worker completion, plus VkResult and acceptance. Only success/suboptimal Present
returns count as accepted. Accepted present_end_ns intervals measure worker cadence;
worker_ns minus queued_ns measures host queue delay. Source-to-acceptance time
includes capture, backpressure and presentation submission. These are not scanout
measurements or input-to-photon latency. Hidden/failed frames remain rows with
accepted=0. Opt-in logging flushes each row; enable it on both comparison sides.

## Validation and limits

Production-function tests exercise bounded FIFO/backpressure, slot reuse, source
format/crop, resize drain, partial allocation cleanup, failed capture, hidden output,
frame-generation transitions and trace clock epoch. Existing WSI/capture fixtures
cover image dimensions, capture ownership, geometry, semaphore routing and injected
submission/device-loss failures. These CPU tests do not replace GPU validation.

An earlier integrated build was exercised on Linux/NVIDIA with an external ordered
neural helper: normal output, helper death/restart and actual swapchain resize and
restore completed. A matched same-artifact A/B/A with async native output, a second
graphics queue and the corresponding external layer measured 52.37 / 62.21 / 52.63
stationary FPS: +18.50% against the two reference runs' mean. The model workspace
was 576x324 and settings were unchanged. Accepted worker cadence agreed with source
cadence. That result applies to the combination on that workload; it is not an
isolated native-queue gain, a current-rebase gameplay result or a 120-FPS claim.
Other GPUs, operating systems, physical scanout and end-to-end latency were not
validated. Material tables, packet encoding and visibility changes are outside
this change.
