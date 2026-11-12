// (hookshot) HMMA_nx2 on 16x16x16 cooperative matrices, staged through shared memory.
//
// The console's HMMA.16816.F16 is D(16x8) = A(16x16) * B(16x8) + C, each lane holding its share in registers in PTX
// mma.m16n8k16's layout: lane t (g = t/4, i = t%4) has A rows g and g+8 at k 2i, 2i+1 and 8+2i, 9+2i, B column g at
// those k, C and D rows g and g+8 at columns 2i, 2i+1 (two f16 a register, low half first). Where the cooperative
// matrices offer 16x8x16 and hold the same positions in each lane (NVIDIA), the native route only reorders a lane's
// elements (emit_spirv_warp.cpp). RADV on RDNA3/4 offers 16x16x16 only, and its lanes hold other positions (8 k of one
// row of A, 8 rows of one column of B and C): elements would have to cross lanes. Here each lane writes its fragments to
// its subgroup's scratch in shared memory, laid out as the matrices are; the subgroup loads them as cooperative matrices
// (the spec's row and column major layouts: nothing depends on which lane holds what), one OpCooperativeMatrixMulAddKHR
// multiplies, the product goes back to the scratch, and each lane reads its own words of it.
//
// Numerics. HMMA.F16 rounds its sum to f16 after each 8 columns of K (the software function, emit_spirv_warp.cpp, does
// the same: f32 FMAs from C in k order, rounded to f16 at k = 8 and 16). The multiply here is f16 x f16 -> f32 with a
// zero accumulator, the second half of K in B's padding columns 8..15 (B has 8 columns, the matrices 16):
//     B'[k][n] = k < 8 ? B[k][n] : 0      B'[k][n + 8] = k < 8 ? 0 : B[k][n]      (n < 8)
// so S = A * B' holds both halves' sums in f32, S[m][n] the first and S[m][n + 8] the second, and each lane rounds as
// HMMA does:
//     D[m][n] = f16( f16(C[m][n] + S[m][n]) + S[m][n + 8] )
// The products are exact in f32; the sums are not quite: RDNA4's v_wmma_f32_16x16x16_f16 aligns the products to the
// largest and truncates (1 + 0.75 f32 ulp gives 1: work/mma-test2/diag), within 2^-22 of the sum of the products'
// magnitudes, as NVIDIA's tensor cores also do. Where a sum lies that close to an f16 rounding boundary, D moves by one
// rounding: at most one f16 ulp of the k = 8 sum plus one of D (2.5 elements in 10000 on random problems, against the
// software function). C needs no staging (a constant zero accumulator, which RADV's compiler takes inline). The f16
// conversions are OpFConvert without a rounding decoration, as the translator's own (round to nearest even on
// RADV/ACO), and NoContraction: without it RADV's NIR took f32(f16(x)) for x and the rounding at k = 8 was gone.
// vk_coopmat.cpp's self-test measures all of it against the software function's arithmetic before the route is used
// (mma_staged). An infinite element of A meets B's padding zeros (inf * 0): its row of D is then NaN where the console
// gives an infinity.
//
// The scratch of a subgroup, kStagedWords u32 words from word `scratch` (64-byte aligned, after the program's own shared
// memory: PlanStagedScratch). The strides are padded past the matrices' rows and columns (8, 8 and 16 words), so that a
// subgroup's accesses spread over the banks: the lanes' stores of A and B' and the reads of S hit different banks, and
// chained multiplies ran 2.4 times as fast as unpadded on an RX 9070 XT, 2.9 times the software function's speed
//     +0    A, 16x16 f16, row major, kStagedRowA words a row
//     +192  B', 16x16 f16, column major, kStagedColumnB words a column
//     +384  S, 16x16 f32, column major, kStagedColumnS words a column
// Each multiply writes the whole of A and B' (B's zeros too), so nothing has to be cleared first. Two subgroup barriers:
// the stores before the loads, and S's store before its reads. The next multiply's stores come after this one's second
// barrier, which follows this one's loads; its S store comes after its first barrier, which follows this one's reads.
// A module with cooperative matrices and the Shader capability must declare the Vulkan memory model (spirv-val; the
// native route does too, emit_spirv.cpp), so the scratch's accesses are NonPrivatePointer and the barriers make them
// available and visible, as the program's own shared memory accesses and barriers are then (EmitContext::DefineMatrixRoute).
//
// It needs what the other routes need: all 32 lanes active at the multiply and the same multiply in each (uniform
// control flow), and subgroups of 32 lanes, whole (vk_draw.cpp pin_subgroup: a compute stage whose width is a multiple
// of 32 gets full subgroups).
#pragma once

#include <array>
#include <cstdint>

#include <sirit/sirit.h>

namespace Shader::Backend::SPIRV {

inline constexpr uint32_t kStagedRowA = 12;      // (u32 words between A's rows, 8 of them data; multiples of 4: 16 bytes)
inline constexpr uint32_t kStagedColumnB = 12;   // (between B''s columns, 8 of them data)
inline constexpr uint32_t kStagedColumnS = 20;   // (between S's columns, 16 of them data)
inline constexpr uint32_t kStagedB = 16 * kStagedRowA;
inline constexpr uint32_t kStagedS = kStagedB + 16 * kStagedColumnB;
inline constexpr uint32_t kStagedWords = kStagedS + 16 * kStagedColumnS;   // (a subgroup's scratch: 704 words)
inline constexpr uint32_t kStagedBytes = kStagedWords * 4;
inline constexpr uint32_t kStagedAlign = 64;    // (bytes: the scratch's start; the matrix loads and stores want 16)
// (Vulkan's VUID-RuntimeSpirv-OpCooperativeMatrixLoadKHR-08986: a cooperative matrix load's or store's pointer and stride are
// 16-byte multiples. RADV builds its shared memory accesses for them with that alignment (radv_nir_lower_cooperative_matrix.c),
// so an odd padding would read and write the wrong words there, and only the self-test at start would notice)
static_assert(kStagedRowA % 4 == 0 && kStagedColumnB % 4 == 0 && kStagedColumnS % 4 == 0, "strides of 16 bytes' multiples");
static_assert(kStagedB % 4 == 0 && kStagedS % 4 == 0 && kStagedWords % 4 == 0,
              "B', S and each subgroup's scratch (SubgroupId * kStagedWords on) at 16-byte multiples");
static_assert(kStagedAlign % 16 == 0, "the scratch's start at a 16-byte multiple");

/// Where a program's staged scratch goes: after its own shared memory, kStagedBytes for each subgroup of 32 lanes. fits is
/// false when the route cannot take the program (the software function then runs its multiplies): its width not a
/// multiple of 32 lanes (its subgroups would not be whole), or its shared memory with the scratch past the device's limit
struct StagedScratch {
    bool fits = false;
    uint32_t offset = 0;   // (bytes: the scratch's start in the shared block)
    uint32_t size = 0;     // (bytes: the shared block with the scratch)
};
inline StagedScratch PlanStagedScratch(uint32_t shared_bytes, const std::array<uint32_t, 3>& workgroup, uint32_t limit) {
    StagedScratch s;
    const uint64_t threads = uint64_t{workgroup[0]} * workgroup[1] * workgroup[2];
    if (workgroup[0] == 0 || workgroup[0] % 32 != 0 || threads == 0) return s;
    const uint64_t offset = (uint64_t{shared_bytes} + kStagedAlign - 1) / kStagedAlign * kStagedAlign;
    const uint64_t size = offset + threads / 32 * kStagedBytes;
    if (size > limit) return s;
    s.fits = true;
    s.offset = static_cast<uint32_t>(offset);
    s.size = static_cast<uint32_t>(size);
    return s;
}

struct StagedTypes {
    Sirit::Id u32, f16, f32, u32x2, u32x4, f16x2, f32x2;
};

/// Defines the function D (u32x2) = HMMA(A (u32x4), B (u32x2), C (u32x2)): the lane's fragments in the console's layout,
/// for the whole subgroup, through its scratch at u32 word scratch_word + SubgroupId * kStagedWords of the shared block.
/// word(index) gives a Workgroup pointer to the block's u32 word index (an id); lane_input and subgroup_input are the
/// SubgroupLocalInvocationId and SubgroupId input variables. Call it outside any function; the result is the function
/// to OpFunctionCall. Each instruction is its own statement: the order of a call's arguments is the C++ compiler's
/// choice, and the module should not depend on it
template <typename WordPointer>
Sirit::Id MakeStagedMatrixFunction(Sirit::Module& m, const StagedTypes& t, const WordPointer& word,
                                   Sirit::Id lane_input, Sirit::Id subgroup_input, uint32_t scratch_word) {
    using Sirit::Id;
    static_assert(kStagedColumnB == kStagedRowA, "B' takes A's lane offsets");
    const auto u = [&](uint32_t v) { return m.Constant(t.u32, v); };
    const Id subgroup_scope = u(static_cast<uint32_t>(spv::Scope::Subgroup));
    const Id semantics = u(static_cast<uint32_t>(spv::MemorySemanticsMask::AcquireRelease |
                                                 spv::MemorySemanticsMask::WorkgroupMemory |
                                                 spv::MemorySemanticsMask::MakeAvailable |
                                                 spv::MemorySemanticsMask::MakeVisible));
    constexpr auto nonprivate = spv::MemoryAccessMask::NonPrivatePointer;
    const Id sixteen = u(16);
    const auto matrix = [&](Id component, spv::CooperativeMatrixUse use) {
        const Id use_id = u(static_cast<uint32_t>(use));
        return m.TypeCooperativeMatrixKHR(component, subgroup_scope, sixteen, sixteen, use_id);
    };
    const Id a_type = matrix(t.f16, spv::CooperativeMatrixUse::MatrixAKHR);
    const Id b_type = matrix(t.f16, spv::CooperativeMatrixUse::MatrixBKHR);
    const Id s_type = matrix(t.f32, spv::CooperativeMatrixUse::MatrixAccumulatorKHR);
    const Id row_major = u(static_cast<uint32_t>(spv::CooperativeMatrixLayout::RowMajorKHR));
    const Id column_major = u(static_cast<uint32_t>(spv::CooperativeMatrixLayout::ColumnMajorKHR));
    const Id stride_a = u(kStagedRowA);
    const Id stride_b = u(kStagedColumnB);
    const Id stride_s = u(kStagedColumnS);
    const Id f32_zero = m.Constant(t.f32, 0.0f);
    const Id function_type = m.TypeFunction(t.u32x2, t.u32x4, t.u32x2, t.u32x2);

    const Id function = m.OpFunction(t.u32x2, spv::FunctionControlMask::DontInline, function_type);
    const Id a = m.OpFunctionParameter(t.u32x4);
    const Id b = m.OpFunctionParameter(t.u32x2);
    const Id c = m.OpFunctionParameter(t.u32x2);
    m.AddLabel();
    const auto add = [&](Id base, uint32_t value) { return value ? m.OpIAdd(t.u32, base, u(value)) : base; };
    const auto store = [&](Id base, uint32_t offset, Id value) {
        const Id index = add(base, offset);
        const Id pointer = word(index);
        m.OpStore(pointer, value, nonprivate);
    };
    const auto load = [&](Id base, uint32_t offset) {
        const Id index = add(base, offset);
        const Id pointer = word(index);
        return m.OpLoad(t.u32, pointer, nonprivate);
    };
    const auto barrier = [&] { m.OpControlBarrier(subgroup_scope, subgroup_scope, semantics); };
    // (NoContraction on the roundings' arithmetic: without it the driver may take f32(f16(x)) for x and fuse the additions
    // with the conversions, as RADV's NIR did (its "float -> float -> float" folding), and the rounding at k = 8 was gone)
    const auto exact = [&](Id value) {
        m.Decorate(value, spv::Decoration::NoContraction);
        return value;
    };

    // the subgroup's scratch, and the lane's places in it
    const Id lane_any = m.OpLoad(t.u32, lane_input);
    const Id subgroup = m.OpLoad(t.u32, subgroup_input);
    const Id lane = m.OpBitwiseAnd(t.u32, lane_any, u(31));
    const Id own = m.OpIMul(t.u32, subgroup, u(kStagedWords));
    const Id scratch = add(own, scratch_word);
    const Id g = m.OpShiftRightLogical(t.u32, lane, u(2));
    const Id i = m.OpBitwiseAnd(t.u32, lane, u(3));
    const Id g_row = m.OpIMul(t.u32, g, stride_a);
    const Id g_row_i = m.OpIAdd(t.u32, g_row, i);
    const Id at_a = m.OpIAdd(t.u32, scratch, g_row_i);   // (A's row g, word i; B''s column g, word i, kStagedB on)
    const Id i_columns = m.OpIMul(t.u32, i, u(2 * kStagedColumnS));
    const Id i_columns_g = m.OpIAdd(t.u32, i_columns, g);
    const Id at_s = m.OpIAdd(t.u32, scratch, i_columns_g);   // (S's column 2i, row g, kStagedS on)

    // A: row g has a0 (k 2i, 2i+1) and a2 (k 8+2i..: 4 words on), row g + 8 a1 and a3
    const Id a0 = m.OpCompositeExtract(t.u32, a, 0U);
    const Id a1 = m.OpCompositeExtract(t.u32, a, 1U);
    const Id a2 = m.OpCompositeExtract(t.u32, a, 2U);
    const Id a3 = m.OpCompositeExtract(t.u32, a, 3U);
    const Id b0 = m.OpCompositeExtract(t.u32, b, 0U);
    const Id b1 = m.OpCompositeExtract(t.u32, b, 1U);
    store(at_a, 0, a0);
    store(at_a, 8 * kStagedRowA, a1);
    store(at_a, 4, a2);
    store(at_a, 8 * kStagedRowA + 4, a3);
    // B': column g has k 0..7 (b0, at k 2i) then zeros, column g + 8 zeros then k 8..15 (b1)
    store(at_a, kStagedB, b0);
    store(at_a, kStagedB + 4, u(0));
    store(at_a, kStagedB + 8 * kStagedColumnB, u(0));
    store(at_a, kStagedB + 8 * kStagedColumnB + 4, b1);
    barrier();
    const Id a_pointer = word(scratch);
    const Id ma = m.OpCooperativeMatrixLoadKHR(a_type, a_pointer, row_major, stride_a, nonprivate);
    const Id b_index = add(scratch, kStagedB);
    const Id b_pointer = word(b_index);
    const Id mb = m.OpCooperativeMatrixLoadKHR(b_type, b_pointer, column_major, stride_b, nonprivate);
    const Id zero = m.OpCompositeConstruct(s_type, f32_zero);
    const Id ms = m.OpCooperativeMatrixMulAddKHR(s_type, ma, mb, zero);
    const Id s_index = add(scratch, kStagedS);
    const Id s_pointer = word(s_index);
    m.OpCooperativeMatrixStoreKHR(s_pointer, ms, column_major, stride_s, nonprivate);
    barrier();

    // S[row][column] is word kStagedS + kStagedColumnS * column + row: the lane's row g at columns 2i, 2i+1 (at_s, a
    // column on), row g + 8 8 words on, and the second half of K (columns 8..15) 8 columns on
    Id d[2];
    for (uint32_t row = 0; row < 2; ++row) {
        const uint32_t o = kStagedS + row * 8;
        const Id first0 = load(at_s, o);
        const Id first1 = load(at_s, o + kStagedColumnS);
        const Id second0 = load(at_s, o + 8 * kStagedColumnS);
        const Id second1 = load(at_s, o + 9 * kStagedColumnS);
        const Id first_words = m.OpCompositeConstruct(t.u32x2, first0, first1);
        const Id first = m.OpBitcast(t.f32x2, first_words);
        const Id second_words = m.OpCompositeConstruct(t.u32x2, second0, second1);
        const Id second = m.OpBitcast(t.f32x2, second_words);
        const Id c_word = m.OpCompositeExtract(t.u32, c, row);
        const Id c_half = m.OpBitcast(t.f16x2, c_word);
        const Id c_float = exact(m.OpFConvert(t.f32x2, c_half));
        const Id sum_first = exact(m.OpFAdd(t.f32x2, c_float, first));
        const Id mid = exact(m.OpFConvert(t.f16x2, sum_first));   // (HMMA's rounding after k 0..7)
        const Id mid_float = exact(m.OpFConvert(t.f32x2, mid));
        const Id sum = exact(m.OpFAdd(t.f32x2, mid_float, second));
        const Id result = exact(m.OpFConvert(t.f16x2, sum));      // (and after k 8..15)
        d[row] = m.OpBitcast(t.u32, result);
    }
    const Id out = m.OpCompositeConstruct(t.u32x2, d[0], d[1]);
    m.OpReturnValue(out);
    m.OpFunctionEnd();
    return function;
}

} // namespace Shader::Backend::SPIRV
