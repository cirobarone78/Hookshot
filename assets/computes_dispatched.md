# The compute programs play dispatches

`computes_dispatched.txt` lists the compute programs the game was seen to dispatch, by their program hashes only: one 16-digit hex
key a line, sorted (the keys of the game's own `hookshot_computes.bin`). It holds no game code or data: a hash names a program the
player's own `hookshot_shaders.bin` has.

`nx2/make_game.py` writes it into the game folder as `hookshot_computes_shipped.bin`, in `hookshot_computes.bin`'s format (`HKCOMP1\0`,
then little-endian `u64` keys). With **Compile shaders** on **Most** (the
default) or **Later**, the preparation before play gives these programs every texture variant and the other compute programs their
base variant only; the other variants are built behind the game while it is played (`gpu/vk/prepare_play.h`). On **All** every
program gets every variant before play, as before.

Made from the `hookshot_computes.bin` of 53 local game folders (the developer's play and test runs, 2026-11-11): 622 of the 4,127
compute programs. To add to it, add another folder's `hookshot_computes.bin` keys and keep the file sorted, each key once.
