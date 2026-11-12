"""Validate HMMA_nx2's matrix routes in real translated SPIR-V, without game files or a GPU.

python nx2/test_hmma_staged_spirv.py --headers <SPIRV-Headers/include> --spirv-val spirv-val [--cxx clang++]
Builds the renderer's Eden IR/SPIR-V and Sirit sources with tests/hmma_staged_ir.cpp: one compute program with two HMMA_nx2
and its own shared memory exchanged over a barrier, emitted on the native, software and staged routes
(backend/spirv/mma_staged.h, mma_route.h), the staged one also with the explicit workgroup layout, with 8- and 16-bit shared
stores, and on programs it cannot take (software, or native where that route checks out too), and the staged self-test's
module (gpu/vk/vk_mma_staged_test.h). On the staged route's Vulkan memory model every Workgroup access must be non-private
and every barrier (BAR, the subgroup's before LDSM, MEMBAR) make memory available and visible; the other routes' modules keep
the translator's accesses as they were. The staged modules keep the float modes the self-test's module declares.
"""
# SPDX-License-Identifier: GPL-3.0-or-later
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}", "--headers", "{spirv_headers}", "--spirv-val", "{spirv_val}"]
# (spirv-val: SPIRV-Tools comes with the Linux runner's packages, not on Windows)
RUN_ALL_SKIP = {"windows": "needs spirv-val: checked on Linux"}

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cxx', default='clang++')
    parser.add_argument('--headers', type=Path, required=True)
    parser.add_argument('--spirv-val', default='spirv-val')
    args = parser.parse_args()
    vk = ROOT / 'gpu/vk'
    # (the fixture's profile keeps the float modes the renderer's does: vk_shader.cpp's make_profile, for every program)
    shader = (vk / 'vk_shader.cpp').read_text(encoding='utf-8')
    profile = shader[shader.index('Shader::Profile make_profile()'):]
    profile = profile[:profile.index('\n}\n')]
    assert 'p.support_fp16_signed_zero_nan_preserve = p.support_fp32_signed_zero_nan_preserve = true;' in profile, \
        ('vk_shader.cpp make_profile no longer keeps SignedZeroInfNanPreserve for 16 and 32 bits for every program: the '
         'staged self-test (vk_mma_staged_test.h) and tests/hmma_staged_ir.cpp declare both')
    sources = sorted({p for directory in ('eden/shader_recompiler/backend/spirv',
                      'eden/shader_recompiler/frontend/ir', 'eden/shader_recompiler/ir_opt', 'sirit/src')
                      for p in (vk / directory).rglob('*.cpp')})
    flags = ['-std=c++20', '-O1', '-D_CRT_SECURE_NO_WARNINGS', '-DVK_NO_PROTOTYPES', '-DMKWVK_INCLUDES=2']
    for header in ('algorithm', 'cstdio', 'cstdlib', 'cstring', 'functional', 'map', 'string', 'vector'):
        flags += ['-include', header]
    flags += ['-I' + str(p) for p in (vk / 'compat', ROOT / 'gpu/compat', vk / 'eden', ROOT / 'gpu/third_party/suyu',
              vk / 'sirit/include', vk / 'sirit/src', vk, args.headers)]
    work = ROOT / 'work'
    work.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='hmma-staged-', dir=work) as temp:
        folder = Path(temp).resolve()
        exe = folder / 'fixture.exe'
        subprocess.run([args.cxx, *flags, str(ROOT / 'tests/hmma_staged_ir.cpp'), *map(str, sources), '-o', str(exe)],
                       check=True)
        emitted = subprocess.run([str(exe), str(folder)], check=True, capture_output=True, text=True)
        print(emitted.stdout, end='')
        held = {}
        for line in emitted.stdout.splitlines():
            name, *fields = line.split()
            held[name] = dict(field.split('=') for field in fields)
        names = ('native', 'software', 'software-bytes', 'staged', 'staged-explicit', 'staged-bytes', 'staged-narrow',
                 'staged-full', 'staged-native', 'staged-narrow-native', 'selftest')
        for name in names:
            subprocess.run([args.spirv_val, '--target-env', 'vulkan1.3', str(folder / (name + '.spv'))], check=True)
        own_words = 284 // 4
        scratch = held['scratch']
        staged_words = int(scratch['size']) // 4
        assert int(scratch['offset']) == 320 and staged_words == 80 + 4 * int(scratch['words_per_subgroup']), scratch
        # the program's own shared memory: a store, its three barriers (BAR, the subgroup's before LDSM, MEMBAR.CTA), a load,
        # and two stores at the end; the staged function's: 8 stores of the fragments and 8 loads of the sums, and its 2
        # subgroup barriers
        own_access, staged_access = 4, 16
        own_barriers, staged_barriers = 3, 2
        # native: the multiplies on 16x8 matrices, inline; the Vulkan memory model; the program's own shared memory, its
        # accesses and its barrier as the translator has always made them (NVIDIA's route is unchanged)
        assert held['native'] == dict(model='vulkan', muladd='2', load='0', store='0', calls='0', functions='1',
                                      subgroup_id='0', shared_elements=str(own_words), shared_access=str(own_access),
                                      shared_nonprivate='0', barriers=str(own_barriers), barriers_visible='0',
                                      preserve_bits='48', route='native'), held['native']
        # software: two calls of the shuffle function; GLSL450, where shared memory is coherent as it is
        assert held['software'] == dict(model='glsl450', muladd='0', load='0', store='0', calls='2', functions='2',
                                        subgroup_id='0', shared_elements=str(own_words), shared_access=str(own_access),
                                        shared_nonprivate='0', barriers=str(own_barriers), barriers_visible='0',
                                        preserve_bits='48', route='software'), held['software']
        # staged: two calls of one function with one multiply, two loads and a store; SubgroupId; the scratch in the block. On
        # the Vulkan memory model every Workgroup access is non-private and every barrier makes memory available and visible,
        # the program's own exchange over its barrier too
        for name in ('staged', 'staged-explicit'):
            assert held[name] == dict(model='vulkan', muladd='1', load='2', store='1', calls='2', functions='2',
                                      subgroup_id='1', shared_elements=str(staged_words),
                                      shared_access=str(own_access + staged_access),
                                      shared_nonprivate=str(own_access + staged_access),
                                      barriers=str(own_barriers + staged_barriers),
                                      barriers_visible=str(own_barriers + staged_barriers), preserve_bits='48',
                                      route='staged'), (name, held[name])
        # with 8- and 16-bit stores: the compare-exchange functions' loads of the word non-private too
        bytes_ = held['staged-bytes']
        assert bytes_['shared_access'] == bytes_['shared_nonprivate'] and int(bytes_['shared_access']) == own_access + staged_access + 2, bytes_
        assert bytes_['barriers'] == bytes_['barriers_visible'] == str(own_barriers + staged_barriers), bytes_
        assert held['software-bytes']['shared_nonprivate'] == '0' and held['software-bytes']['barriers_visible'] == '0', held['software-bytes']
        # a program the route cannot take keeps the software function, its shared memory its own
        for name in ('staged-narrow', 'staged-full'):
            assert held[name] == held['software'], (name, held[name])
        # ... or goes native, where the native route checks out too (RX_VK_MMA_STAGED=1 on a card with 16x8x16)
        assert held['staged-narrow-native'] == held['native'], held['staged-narrow-native']
        assert held['staged-native'] == held['staged'], held['staged-native']
        # (each module's route above is PlanMatrixRoute's, which vk_shader.cpp and vk_draw.cpp decide by: the one it was emitted on)
        # the self-test's module: the route's function, and its own shared words and barriers as the translator's staged programs
        selftest = held['selftest']
        assert selftest['model'] == 'vulkan' and selftest['muladd'] == '1', selftest
        assert selftest['shared_access'] == selftest['shared_nonprivate'] and selftest['barriers'] == selftest['barriers_visible'], selftest
        # ... and the float modes the game's staged programs keep (SignedZeroInfNanPreserve for 16 and 32 bits: vk_shader.cpp's
        # make_profile, the staged route taking only programs with f16), so the test vouches for the arithmetic they get
        assert selftest['preserve_bits'] == held['staged']['preserve_bits'] == '48', (selftest, held['staged'])
    print('PASS: native, software and staged HMMA_nx2 modules validate; the staged scratch follows the program\'s own '
          'shared memory, its Workgroup accesses non-private and its barriers making them visible; programs the staged route '
          'cannot take keep the software function, or go native where that checks out')


if __name__ == '__main__':
    main()
