"""Compile and run the memory priority rules (gpu/vk/memory_priority.h; no game/GPU), and check the renderer still wires
them in: the extensions asked for with their switch, VMA told, every VMA create-info given the default priority (left at
{}, VMA passes 0, the lowest, once the extension is on), and the textures' pass."""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "g++"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu/vk"

NEEDLES = {
    "vk_main.cpp": ['#include "memory_priority.h"', 'env_on("RX_VK_MEMORY_PRIORITY")',
                    "VK_EXT_MEMORY_PRIORITY_EXTENSION_NAME", "VK_EXT_PAGEABLE_DEVICE_LOCAL_MEMORY_EXTENSION_NAME",
                    "dev.memory_priority = dev.memory_priority && mprio.memoryPriority",
                    "dev.pageable_memory = dev.memory_priority && dev.pageable_memory && pageable.pageableDeviceLocalMemory"],
    "vk_vma.cpp": ['#include "memory_priority.h"', "VMA_ALLOCATOR_CREATE_EXT_MEMORY_PRIORITY_BIT",
                   "if (!info.dedicatedMemory || !info.allocationInfo.deviceMemory) return 0;"],
    "vk_texture.cpp": ['#include "memory_priority.h"', 'memory_priority::idle_presents(getenv("RX_VK_PRIORITY_IDLE"))',
                       "if (dev.pageable_memory && frame_no % 60 == 0) texture_priorities();",
                       "set_allocation_priority(t->allocation, want)", 'env_on("RX_VK_LOG_PRIORITY")'],
    "vk_loader.h": ["X(vkSetDeviceMemoryPriorityEXT)"],
}

# Every VMA create-info declared in gpu/vk (VMA itself is fetched at build time, not in the tree), however it is
# initialized: a copy of another (= ai) keeps that one's priority; any other ({}, {...}, = {...} or none) sets .priority
# in its initializer or in the WINDOW lines after it. Fewer than MIN_DECLS found means the rule no longer sees them.
DECL = re.compile(r"\bVma(?:Allocation|Pool)CreateInfo\s+(\w+)\s*(\{[^;]*?\}|=\s*[^;]+)?\s*;")
COPY = re.compile(r"=\s*\w+$")
WINDOW = 15
MIN_DECLS = 10


def check_source():
    for name, needles in NEEDLES.items():
        src = (VK / name).read_text(encoding="utf-8")
        for needle in needles:
            if needle not in src:
                raise SystemExit(f"{name} no longer has: {needle}")
    unset, found = [], 0
    for path in sorted([*VK.rglob("*.cpp"), *VK.rglob("*.h")]):
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines):
            m = DECL.search(line)
            if not m:
                continue
            found += 1
            init = (m.group(2) or "").strip()
            if COPY.fullmatch(init) or re.search(r"\.priority\s*=", init):
                continue
            after = "\n".join(lines[i + 1:i + 1 + WINDOW])
            if not re.search(rf"\b{re.escape(m.group(1))}\.priority\s*=", after):
                unset.append(f"{path.relative_to(ROOT)}:{i + 1}: {m.group(1)}")
    if unset:
        raise SystemExit("VMA create-infos without a priority (VMA would pass 0, the lowest):\n  " + "\n  ".join(unset))
    if found < MIN_DECLS:
        raise SystemExit(f"only {found} VMA create-infos found in gpu/vk (at least {MIN_DECLS} expected): the rule no longer sees them")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="memory-priority-") as tmp:
        exe = Path(tmp) / "memory-priority"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                        str(ROOT / "tests/test_memory_priority.cpp"), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
