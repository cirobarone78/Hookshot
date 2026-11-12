"""The staged matrix route starts on its own only where it was tested: Mesa RADV.

AMD's own driver lists 16x16x16 f16 cooperative matrices on RDNA2 too, which has no matrix hardware, and has crashed
building such pipelines there (Lichii #633). So the route, and its self-test, run by default only with VK_DRIVER_ID_MESA_RADV;
RX_VK_MMA_STAGED=1 asks for it on any driver (and first, where the console's 16x8x16 is there too), RX_VK_MMA_STAGED=0
never. A driver that is not asked for and not RADV must not reach the self-test.

python -I -B tests/test_mma_staged_driver.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COOPMAT = ROOT / "gpu" / "vk" / "vk_coopmat.cpp"


def main():
    src = COOPMAT.read_text(encoding="utf-8")
    start = src.index("bool staged_multiplies(")
    body = src[start:src.index("\n}\n", start)]
    if "bool asked)" not in body[:body.index("{")]:
        raise SystemExit("staged_multiplies is not told whether RX_VK_MMA_STAGED=1 asked for the route")
    gate = "else if (!asked && dev.driver_id != VK_DRIVER_ID_MESA_RADV)"
    if gate not in body:
        raise SystemExit("the staged route is not held to Mesa RADV unless asked for")
    if body.index(gate) > body.index("test_staged(why)"):
        raise SystemExit("the self-test runs before the driver is checked: an untested driver still builds its pipelines")
    caller = src[src.index("void coopmat_init()"):]
    if "const bool staged_first = staged_env && std::atoi(staged_env) == 1;" not in caller:
        raise SystemExit("RX_VK_MMA_STAGED=1 no longer asks for the route")
    if '"the software function", staged_first)' not in caller:
        raise SystemExit("coopmat_init does not pass RX_VK_MMA_STAGED=1 on as the ask")
    if "const bool staged = !staged_off &&" not in caller:
        raise SystemExit("RX_VK_MMA_STAGED=0 no longer keeps the route off")
    print("the staged route: Mesa RADV by default, any driver when asked, never with RX_VK_MMA_STAGED=0")


if __name__ == "__main__":
    main()
