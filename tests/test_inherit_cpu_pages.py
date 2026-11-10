"""A retired pool's mirror is inherited over everything but the pages the CPU wrote since its last sync.

mirror_make fills a remade pool's new mirror from guest memory, then copies the retired pools' mirrors over their part
(what the GPU wrote there and nowhere else, issue 1151's foliage records). The whole copy also put back old values over
pages the CPU had written since the old mirror's last sync: the captures that go over it after hold only the last
submissions' pages, and a scene change takes many. Leaving the Deku Tree through the blue warp after Gohma, the
dungeon's values came back over what the game wrote while the next area loaded, and the outdoors came out washed white
until the cutscene (issue 508, tracked in 1004).

The pages the CPU wrote are told from the GPU's own stamps (memory_stamp) by a CPU-only generation, stamped where the
CPU's writes are collected and where a capture takes its pages; the inheritance skips a page whose CPU generation is past
the retired mirror's synced_gen. This checks those three places in gpu/vk/vk_memory.cpp.
python -I -B tests/test_inherit_cpu_pages.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def body(source, head):
    start = source.index(head)
    return source[start:source.index("\n}\n", start)]


def main():
    source = (ROOT / "gpu" / "vk" / "vk_memory.cpp").read_text(encoding="utf-8")

    collect = body(source, "void memory_collect_written(")
    if not re.search(r"stamp_page\(pages\[i\], g\);\s*stamp_cpu_page\(pages\[i\], g\);", collect):
        raise SystemExit("FAIL: memory_collect_written no longer stamps the CPU's pages with their own generation")

    if not re.search(r"for \(uint32_t p : c->pages\) stamp_page\(p, g\), stamp_cpu_page\(p, g\);", source):
        raise SystemExit("FAIL: a capture's pages are no longer stamped with the CPU's generation")

    stamp = body(source, "void memory_stamp(")
    if "stamp_cpu_page" in stamp:
        raise SystemExit("FAIL: memory_stamp (the GPU's and the host's writes) stamps the CPU's generation: the "
                         "GPU-written records would no longer be inherited")

    make = body(source, "bool mirror_make(Pool& pool) {")
    inherit = make[make.index("retired_pools"):make.index("mirror made with the GPU's contents")]
    if "cpu_page_gen(page) > r.synced_gen" not in inherit:
        raise SystemExit("FAIL: the inheritance no longer skips the pages the CPU wrote since the old mirror's sync")
    if "page_gen(page) > r.synced_gen" in inherit.replace("cpu_page_gen(page) > r.synced_gen", ""):
        raise SystemExit("FAIL: the inheritance tests page_gen, which the GPU's own writes stamp too")
    if re.search(r"VkBufferCopy part\{a - r\.lo, a - p->lo, b - a\}", inherit):
        raise SystemExit("FAIL: the inheritance copies the retired mirror's whole range again")
    print("PASS: a retired mirror is inherited over all but the pages the CPU wrote since its last sync")


if __name__ == "__main__":
    main()
