"""The Upscaler's default without matrix hardware (AMD FSR 3.1) is settled after the device knows its push-descriptor limit,
and stays a default until the player moves the Upscaler row.

fsr3::supported() reads dev.max_push_descriptors and caches its answer for the run: asked before create_device reads the limit,
it said no on the very GPUs the default is for, and FSR 3.1 left the Upscaler row too. While the player has not chosen
(upscaler_default=1 in the options file) the default is settled again at each start, so another GPU, or a run with
RX_VK_MMA_SOFTWARE=1, gets its own; the Upscaler row, or the Render resolution row moving between engines, makes it the player's.

python -I -B tests/test_upscaler_default.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"


def main():
    main_cpp = (VK / "vk_main.cpp").read_text(encoding="utf-8")
    limit = main_cpp.index("dev.max_push_descriptors = pp.maxPushDescriptors;")
    call = main_cpp.index("menu_upscaler_default(coopmat_software());")
    if call < limit:
        raise SystemExit("vk_main.cpp: the Upscaler's default is settled before the push-descriptor limit is read")
    if main_cpp.count("menu_upscaler_default(") != 1:
        raise SystemExit("vk_main.cpp: the Upscaler's default is settled more than once")
    menu = (VK / "vk_menu.cpp").read_text(encoding="utf-8")
    save = menu[menu.index("void save() {"):menu.index("void menu_init() {")]
    for needle, where, why in (
        ('if (opts.upscaler_default) fputs("upscaler_default=1\\n", f);', save, "save() does not keep an unchosen Upscaler"),
        ('key == "upscaler_default"', save, "save() writes upscaler_default twice (its old line kept)"),
        ('if (!strcmp(line, "upscaler_default")) opts.upscaler_default = atoi(eq + 1) != 0;', menu, "menu_init() does not read it"),
        ("v = ur::step_engine(upscaler(), dir, upscalers_available()), opts.upscaler_default = false;", menu,
         "the Upscaler row does not make the choice the player's"),
        ("opts.dlss = up, opts.upscaler_default = false;", menu, "the Render resolution row's engine change does not either"),
        ("if (!has_options) opts.upscaler_default = true;", menu, "a first start does not settle the default"),
    ):
        if needle not in where:
            raise SystemExit(f"vk_menu.cpp: {why}")
    settle = menu[menu.index("void menu_upscaler_default(bool software_matrices) {"):]
    settle = settle[:settle.index("\n}\n")]
    for needle in ("if (!opts.upscaler_default) return;", "opts.dlss = upscaler_rows::GAME;",
                   "if (!software_matrices || !fsr3::supported()) return;", "opts.dlss = upscaler_rows::FSR3;"):
        if needle not in settle:
            raise SystemExit(f"vk_menu.cpp menu_upscaler_default: missing {needle}")
    print("the Upscaler's default: settled after the push-descriptor limit, kept a default until the player chooses ok")


if __name__ == "__main__":
    main()
