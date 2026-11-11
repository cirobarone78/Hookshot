"""The presenter thread (RX_VK_PRESENT_THREAD=1) keeps the presents in order, one out at most, and off the swapchain's remaking.

present_out hands a present to the presenter thread only from present_image (it alone sets the copy's fence; frame generation's
present_commit paces its presents itself) and with NVIDIA Reflex off (its markers belong to the game's thread). The presenter waits
for the copy's fence before it presents, and takes the replay's queue lock only around vkQueuePresentKHR. The game's thread waits
while the frame before's present is still out; a present made directly waits for the one handed over with the queue's lock let go;
the swapchain is made again only with the presenter idle, and the wait for that comes before the queue's lock (the presenter takes
it). The presenter never makes a swapchain itself: an out-of-date or suboptimal present asks the next present_image for one.

python -I -B tests/test_present_thread.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def need(cond, why):
    if not cond:
        raise SystemExit("FAIL: " + why)


def main():
    vk = ROOT / "gpu" / "vk"
    replay = (vk / "vk_replay.cpp").read_text(encoding="utf-8")
    main_cpp = (vk / "vk_main.cpp").read_text(encoding="utf-8")

    out = block(replay, "static void present_out(uint32_t index, std::unique_lock<std::mutex>& qk) {")
    hand = out[: out.index("present_hand_off(")]
    need("present_copy_done && !pi.pNext && present_thread_on()" in hand,
         "a present is handed over from frame generation or with Reflex on")
    need("qk.unlock();" in hand, "the queue's lock is held while the game's thread hands a present over")
    rest = out[out.index("present_hand_off("):]
    need("qk.unlock();\n        present_thread_drain();\n        qk.lock();" in rest and
         rest.index("present_thread_drain();") < rest.index("vkQueuePresentKHR"),
         "a present made directly may go out before the one handed over, or waits for it with the queue's lock held")

    image = block(replay, "void present_image(")
    need("present_copy_done = f.done;\n    present_out(index, qk);\n    present_copy_done = VK_NULL_HANDLE;" in image,
         "present_image does not let its present (and only it) be handed over")
    for site in ("reflex_swapchain_stale() || hdr_changed || vsync_changed) {", "if (res == VK_ERROR_OUT_OF_DATE_KHR) {"):
        at = image[image.index(site):]
        need(at.index("present_thread_drain();") < at.index("std::lock_guard qk(dev.present_mu);"),
             "present_image remakes the swapchain without first waiting for the presenter, outside the queue's lock")
    commit = block(replay, "bool present_commit(")
    need("present_out(p.index, qk);" in commit and "present_copy_done" not in commit,
         "frame generation's paced presents are handed over")

    give = block(replay, "void present_hand_off(uint32_t index, VkFence done) {")
    need(give.index("presenter.cv.wait(lk, [] { return !presenter.busy; });") < give.index("presenter.busy = true"),
         "a present is handed over before the one before is made")

    loop = block(replay, "void presenter_loop() {")
    need(loop.index("vkWaitForFences(dev.device, 1, &done") < loop.index("vkQueuePresentKHR"),
         "the presenter presents before the copy is done (the driver's wait comes back)")
    need("std::lock_guard qk(dev.present_mu);\n            res = vkQueuePresentKHR(dev.queue, &pi);" in loop,
         "on the replay's queue the presenter presents without the queue's lock, or holds it longer")
    need("std::lock_guard pq(dev.present_queue_mu)" in loop, "the presents' own queue is used without its lock")
    need("presenter.busy = false" in loop and "notify_all" in loop, "the presenter does not say it is done")
    need("create_swapchain" not in loop and "reflex_presented" not in loop,
         "the presenter makes a swapchain itself, or sets Reflex's present marker")
    finish = block(replay, "void present_finish(VkResult res, bool on_presenter) {")
    need("on_presenter && (res == VK_ERROR_OUT_OF_DATE_KHR || res == VK_SUBOPTIMAL_KHR)" in finish and "swap_resize" in finish,
         "an out-of-date present on the presenter does not ask for a new swapchain")

    make = block(main_cpp, "bool create_swapchain(uint32_t width, uint32_t height) {")
    need(make[make.index("{") + 1:].lstrip().startswith("present_thread_drain();"),
         "create_swapchain does not wait for the presenter first")
    on = block(replay, "bool present_thread_on() {")
    need('getenv("RX_VK_PRESENT_THREAD")' in on and "atoi(e) != 0" in on, "the switch is not RX_VK_PRESENT_THREAD, off by default")
    print("PASS: the presenter thread waits for the copy, keeps the presents in order and off the swapchain's remaking")


if __name__ == "__main__":
    main()
