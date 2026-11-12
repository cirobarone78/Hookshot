"""Host-cached AutoReadback ring for polled GPU-written textures (gpu/vk/vk_texture.cpp, gpu/vk/vk_replay.cpp).

Checks the source invariants:
- finish_recording records texture_end_recording(r.cmd, r.value) after end_pass and before memory_end_submission, while
  bench_replay passes 0 so an already-reached pushed value cannot mark a slot ready before the benchmark submission runs.
- destroy_later calls auto_rb_forget(tex) before retiring the texture's image.
- flush_finish invalidates [f.offset, f.offset + total) via invalidate_mapped_range(f.alloc, f.offset, total) when
  f.alloc is non-null, so slots 1..3 on non-coherent host-cached memory invalidate their own slot range rather than offset 0.
- texture_flush_to_guest checks env_on("RX_VK_NO_AUTO_READBACK"), verifies vk_timeline_completed() >= rb.slot_val[slot]
  after vk_timeline_wait, sets both f.offset and f.alloc, and falls back to flush_texture(*t, lo, hi) on timeout/miss.
- texture_end_recording drops rings that go unpolled past kMaxUnpolledWrites via auto_rb_forget(*t).

python -I -B tests/test_auto_readback_ring.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def body(src, signature):
    """the text of the function that starts with signature, up to its closing brace at column 0"""
    start = src.index(signature)
    return src[start:src.index("\n}\n", start)]


def check(cond, msg):
    if not cond:
        raise SystemExit("FAIL: " + msg)


def main():
    replay = (ROOT / "gpu" / "vk" / "vk_replay.cpp").read_text(encoding="utf-8")
    tex = (ROOT / "gpu" / "vk" / "vk_texture.cpp").read_text(encoding="utf-8")
    vma = (ROOT / "gpu" / "vk" / "vk_vma.cpp").read_text(encoding="utf-8")

    fin = body(replay, "void finish_recording(uint64_t value) {")
    check("end_pass(r.cmd);" in fin and "texture_end_recording(r.cmd, r.value);" in fin
          and "memory_end_submission(r.cmd);" in fin,
          "finish_recording must call end_pass, texture_end_recording(r.cmd, r.value), and memory_end_submission")
    check(fin.index("end_pass(r.cmd);") < fin.index("texture_end_recording(r.cmd, r.value);")
          < fin.index("memory_end_submission(r.cmd);"),
          "texture_end_recording must run after end_pass and before memory_end_submission in finish_recording")

    bench = body(replay, "void bench_replay(const std::vector<uint64_t>& handles) {")
    check("texture_end_recording(r.cmd, 0);" in bench and "texture_end_recording(r.cmd, value);" not in bench,
          "bench_replay must pass 0 to texture_end_recording so an already-reached value cannot mark a slot ready")

    dl = body(tex, "void destroy_later(Texture& tex) {")
    check("auto_rb_forget(tex);" in dl and dl.index("auto_rb_forget(tex);") < dl.index("dead.push_back("),
          "destroy_later must call auto_rb_forget(tex) before retiring the texture")

    check("void invalidate_mapped_range(VmaAllocation allocation, uint64_t offset, uint64_t size)" in vma
          and "vmaInvalidateAllocation(vma, allocation, offset, size);" in vma,
          "vk_vma.cpp must define invalidate_mapped_range forwarding offset to vmaInvalidateAllocation")

    ff = body(tex, "bool flush_finish(Flush& f, bool gpu_ok) {")
    check("if (ok && !flush_uncached() && f.alloc) invalidate_mapped_range(f.alloc, f.offset, total);" in ff,
          "flush_finish must guard f.alloc and invalidate [f.offset, f.offset + total) via invalidate_mapped_range")

    end_rec = body(tex, "void texture_end_recording(VkCommandBuffer cmd, uint64_t value) {")
    check("!value || !t->gpu_written || !flushable(*t)" in end_rec,
          "texture_end_recording must clear ready and skip copying when value is 0 or texture is not flushable")
    check("++rb.unpolled_writes > Texture::AutoReadback::kMaxUnpolledWrites" in end_rec
          and "auto_rb_forget(*t);" in end_rec,
          "texture_end_recording must retire rings that exceed kMaxUnpolledWrites without a poll")

    ftg = body(tex, "int texture_flush_to_guest(uint64_t lo, uint64_t size) {")
    check('env_on("RX_VK_NO_AUTO_READBACK")' in ftg,
          "texture_flush_to_guest must use env_on for RX_VK_NO_AUTO_READBACK")
    check("if (rb.slot_val[slot]) vk_timeline_wait(rb.slot_val[slot]);" in ftg
          and "if (vk_timeline_completed() >= rb.slot_val[slot]) {" in ftg,
          "texture_flush_to_guest must wait for slot_val and verify vk_timeline_completed() >= rb.slot_val[slot]")
    check("f.offset = (uint64_t)slot * rb.slot_sz;" in ftg
          and "f.alloc = rb.alloc;" in ftg,
          "texture_flush_to_guest fast path must set both f.offset and f.alloc on Flush")
    check("if (!served_from_ring) {" in ftg
          and "flushed_ok = flush_texture(*t, lo, hi);" in ftg[ftg.index("if (!served_from_ring) {"):],
          "texture_flush_to_guest must fall back to flush_texture when not served from the ring")

    print("PASS: AutoReadback ring ordering, slot range invalidation, timeout fallback, and retirement invariants hold")


if __name__ == "__main__":
    main()
