// (hookshot) The staged matrix route's self-test (eden/.../mma_staged.h): random HMMA.16816.F16 problems, multiplied on the GPU
// by the route's own function, checked against the software function's arithmetic (emit_spirv_warp.cpp
// DefineSoftwareMatrixFunction: f32 FMAs in k order from C, rounded to f16 after k 0..7 and after 8..15) done here on the CPU.
// vk_coopmat.cpp runs it before it turns the route on; work/mma-test2 runs the same code standalone over many more problems.
// No Vulkan here: build() makes the module, make_data() its buffer, check() reads the buffer back.
//
// The shader: workgroups of four subgroups of 32 lanes (as OoT's networks: 128 lanes; Hookshot pins 32 lanes, full
// subgroups), each subgroup doing kSteps multiplies one after another, as a network does: C from the buffer (subnormal ones
// too), C = RZ (a constant zero, as HMMA_nx2 makes it), C = an earlier multiply's D (an accumulation chain), an A used
// again. The problems check, besides the route's arithmetic, each kind of problem and each place of D on its own. The shared
// block is the translator's (one u32 array): kProgramWords words of "the program's own" shared memory first, each
// invocation's word written before and read back after (the scratch must not touch them), then the scratch, where
// PlanStagedScratch puts it. The module declares what the translator's staged programs do (SignedZeroInfNanPreserve for 16
// and 32 bits, the Vulkan memory model, emit_spirv.cpp, with the program's own shared memory non-private and its barriers
// making it available and visible, EmitContext::DefineMatrixRoute), so the driver compiles the multiplies as it will in the
// game.
#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include <sirit/sirit.h>

#include "shader_recompiler/backend/spirv/mma_staged.h"

namespace mma_staged_test {

constexpr uint32_t kLanes = 32;
constexpr uint32_t kSubgroups = 4;       // (a workgroup's: 128 lanes, as the networks')
constexpr uint32_t kSteps = 8;           // (multiplies a subgroup does, one after another)
constexpr uint32_t kProgramWords = 135;  // (the program's own shared memory before the scratch: not a multiple of 64 bytes)
constexpr uint32_t kSentinel = 0x5a5a0000u;
enum Step : uint32_t { kOwnC, kZeroC, kChainC, kSameA };
constexpr Step kStepKind[kSteps] = {kOwnC, kZeroC, kChainC, kSameA, kOwnC, kChainC, kZeroC, kOwnC};
constexpr uint32_t kChainFrom[kSteps] = {0, 0, 0, 2, 0, 4, 0, 0};   // (kChainC: whose D is its C; kSameA: whose A it takes)

inline std::array<uint32_t, 3> workgroup() { return {kSubgroups * kLanes, 1, 1}; }
inline uint32_t problems(uint32_t groups) { return groups * kSubgroups * kSteps; }
// the buffer, u32 words: each problem's 32 lanes x 8 words in (a0..a3, b0, b1, c0, c1), then their 2 words of D, then a
// word for each invocation (its own shared word read back)
inline uint32_t in_at(uint32_t p, uint32_t t) { return (p * kLanes + t) * 8; }
inline uint32_t out_at(uint32_t groups, uint32_t p, uint32_t t) { return problems(groups) * kLanes * 8 + (p * kLanes + t) * 2; }
inline uint32_t check_at(uint32_t groups, uint32_t invocation) { return problems(groups) * kLanes * 10 + invocation; }
inline uint32_t words(uint32_t groups) { return check_at(groups, groups * kSubgroups * kLanes); }

// ---- f16 on the CPU
inline uint32_t bits_of(float f) { uint32_t x; std::memcpy(&x, &f, 4); return x; }
inline float float_of(uint32_t x) { float f; std::memcpy(&f, &x, 4); return f; }
inline float from_half(uint16_t h) {
    const uint32_t sign = (uint32_t)(h & 0x8000) << 16, exp = (h >> 10) & 0x1f, man = h & 0x3ff;
    if (!exp) {
        const float f = std::ldexp((float)man, -24);
        return sign ? -f : f;
    }
    if (exp == 31) return float_of(sign | 0x7f800000 | (man << 13));
    return float_of(sign | ((exp - 15 + 127) << 23) | (man << 13));
}
/// emit_spirv_warp.cpp's round_half, operation for operation: f32 to the nearest f16, ties to even, subnormals kept
inline float round_half(float value) {
    const uint32_t bits = bits_of(value);
    const uint32_t magnitude = bits & 0x7fffffffu;
    const uint32_t tie = (magnitude >> 13) & 1;
    const uint32_t rounded = (magnitude + 0xfffu + tie) & ~0x1fffu;
    const uint32_t normal = rounded >= 0x47800000u ? 0x7f800000u : rounded;
    const float scaled = float_of(magnitude) * 16777216.0f;
    const uint32_t subnormal = bits_of(std::nearbyint(scaled) * 0x1p-24f);
    const uint32_t finite = magnitude >= 0x38800000u ? normal : subnormal;
    const uint32_t result = magnitude >= 0x7f800000u ? magnitude : finite;
    return float_of(result | (bits & 0x80000000u));
}
/// an f16 value (or an infinity) as f16 bits
inline uint16_t half_bits(float f) {
    const uint32_t x = bits_of(f), sign = (x >> 16) & 0x8000, mag = x & 0x7fffffffu;
    if (mag >= 0x7f800000u) return (uint16_t)(sign | 0x7c00 | (mag > 0x7f800000u ? 0x200 : 0));
    if (mag >= 0x38800000u) return (uint16_t)(sign | ((((mag >> 23) - 127 + 15) & 0x1f) << 10) | ((mag >> 13) & 0x3ff));
    return (uint16_t)(sign | (uint32_t)std::lround(std::ldexp(float_of(mag), 24)));
}
/// the spacing of f16 values at |x|
inline double ulp16(double x) {
    x = std::fabs(x);
    if (!(x < 65536.0)) return 32.0;
    if (x < 0x1p-14) return 0x1p-24;
    int e;
    std::frexp(x, &e);   // (x = f * 2^e, f in [0.5, 1))
    return std::ldexp(1.0, e - 11);
}

// the console's fragment positions: lane t (g = t/4, i = t%4), element e (two a register, low half first)
inline void console_a(int t, int e, int& r, int& k) { const int g = t / 4, i = t % 4; r = g + ((e >> 1) & 1) * 8; k = 2 * i + (e & 1) + (e >> 2) * 8; }
inline void console_b(int t, int e, int& k, int& n) { const int g = t / 4, i = t % 4; k = 2 * i + (e & 1) + (e >> 1) * 8; n = g; }
inline void console_c(int t, int e, int& r, int& n) { const int g = t / 4, i = t % 4; r = g + (e >> 1) * 8; n = 2 * i + (e & 1); }

/// One problem as matrices of f16 bits
struct Problem {
    uint16_t a[16][16], b[16][8], c[16][8];
};
/// How far apart the route's f32 sum of a half of K and the software function's may be, in f32 roundings (2^-24) of the sum
/// of the terms' magnitudes: the software function's 8 FMAs, each within one; the route's sum, its products aligned to the
/// largest and truncated (RDNA4: within 2^-22.3 of their magnitudes, work/mma-test2/diag: 4 counted), and its addition of C,
/// one; 13, and room for a card that truncates more. (It was 36. On an RX 9070 XT no element of 16.8 million went past
/// HMMA's two f16 roundings by more than 0.33 of one)
inline constexpr double kSumRoundings = 16.0;
/// The software function's arithmetic for D[r][n]: d, the sum after k 0..7 as it was rounded (mid), and bounds of how far
/// the route's f32 sums of the two halves may be from its own (kSumRoundings)
struct Reference {
    float d, mid;
    double error_first, error_second;
};
inline Reference reference(const Problem& q, int r, int n) {
    Reference out{};
    float acc = from_half(q.c[r][n]);
    double magnitude = std::fabs((double)acc);
    for (int k = 0; k < 8; k++) {
        const float p = from_half(q.a[r][k]) * from_half(q.b[k][n]);   // (exact in f32)
        acc = std::fmaf(from_half(q.a[r][k]), from_half(q.b[k][n]), acc);
        magnitude += std::fabs((double)p);
    }
    out.error_first = kSumRoundings * magnitude * 0x1p-24;
    acc = out.mid = round_half(acc);
    magnitude = std::fabs((double)acc);
    for (int k = 8; k < 16; k++) {
        const float p = from_half(q.a[r][k]) * from_half(q.b[k][n]);
        acc = std::fmaf(from_half(q.a[r][k]), from_half(q.b[k][n]), acc);
        magnitude += std::fabs((double)p);
    }
    out.error_second = kSumRoundings * magnitude * 0x1p-24;
    out.d = round_half(acc);
    return out;
}
/// a double to the nearest f16, ties to even, subnormals kept (one rounding)
inline float round_half_exact(double x) {
    const double m = std::fabs(x);
    if (!(m < 65520.0)) return (float)std::copysign(m != m ? m : INFINITY, x);
    int e;
    std::frexp(m, &e);                                      // (m = f * 2^e, f in [0.5, 1))
    const double quantum = std::ldexp(1.0, std::max(e - 11, -24));
    return (float)(std::nearbyint(x / quantum) * quantum);  // (exact: a power of two, and nearbyint ties to even)
}
/// HMMA's two roundings over exact sums (no f32 rounding at all): what a multiply whose sums are exact gives. The sums
/// of 22-bit products of f16 values are exact in a double here (their exponents span less than 53 bits)
inline float exact_two_step(const Problem& q, int r, int n) {
    double acc = from_half(q.c[r][n]);
    for (int k = 0; k < 8; k++) acc += (double)from_half(q.a[r][k]) * from_half(q.b[k][n]);
    acc = round_half_exact(acc);
    for (int k = 8; k < 16; k++) acc += (double)from_half(q.a[r][k]) * from_half(q.b[k][n]);
    return round_half_exact(acc);
}

// ---- the inputs: a few kinds of problem, by problem index
struct Random {
    uint64_t s;
    uint32_t next() { s ^= s << 13, s ^= s >> 7, s ^= s << 17; return (uint32_t)(s >> 16); }
    uint32_t below(uint32_t n) { return next() % n; }
};
enum Kind : uint32_t { kTypical, kWide, kExact, kCancel, kLarge, kKinds };
inline const char* kind_name(uint32_t k) {
    static const char* const names[kKinds] = {"typical", "wide", "exact", "cancel", "large"};
    return k < kKinds ? names[k] : "?";
}
/// (by the problem's index p; its step is p % kSteps: the wide problem at 4 takes its own C, zeros and subnormals among them)
inline Kind kind_of(uint32_t p) {
    static constexpr Kind order[16] = {kTypical, kWide, kTypical, kCancel, kWide, kTypical, kExact, kTypical,
                                       kCancel, kTypical, kWide, kLarge, kTypical, kCancel, kWide, kTypical};
    return order[p % 16];
}
inline uint16_t random_half(Random& r, int lo, int hi) {   // (biased exponent in [lo, hi], 0: subnormal or zero; either sign)
    const uint32_t e = (uint32_t)(lo + (int)r.below((uint32_t)(hi - lo + 1)));
    return (uint16_t)((r.below(2) << 15) | (e << 10) | r.below(1024));
}
/// A problem's values: every sum stays below f16's largest (an infinity would meet B's padding zeros: mma_staged.h)
inline uint16_t value_of(Random& r, Kind kind) {
    switch (kind) {
    case kTypical: return random_half(r, 9, 16);                  // (|x| 2^-6 .. 4: products < 16)
    case kWide: return r.below(8) ? random_half(r, 0, 18) : 0;    // (zeros, subnormals .. 16)
    case kCancel: return random_half(r, 15, 19);                  // (1 .. 32)
    default: return random_half(r, 16, 20);                       // (kLarge: 2 .. 32, sums to ~16k)
    }
}
inline Problem make_problem(uint64_t seed, uint32_t p) {
    Random r{seed ^ (0x9e3779b97f4a7c15ull * (p + 1))};
    for (int i = 0; i < 8; i++) r.next();
    Problem q{};
    const Kind kind = kind_of(p);
    if (kind == kExact) {   // (small integers: every product and sum exact in f16, as vk_coopmat.cpp's test_multiply)
        const auto half = [](int v) { return half_bits((float)v); };
        for (int m = 0; m < 16; m++)
            for (int k = 0; k < 16; k++) q.a[m][k] = half(((m * 7 + k * 3 + 1 + (int)p) % 5) - 2);
        for (int k = 0; k < 16; k++)
            for (int n = 0; n < 8; n++) q.b[k][n] = half(((k * 5 + n * 11 + 2 + (int)p) % 4) - 1);
        for (int m = 0; m < 16; m++)
            for (int n = 0; n < 8; n++) q.c[m][n] = half(((m * 3 + n * 13 + (int)p) % 9) - 4);
        return q;
    }
    for (int m = 0; m < 16; m++)
        for (int k = 0; k < 16; k++) q.a[m][k] = value_of(r, kind);
    for (int k = 0; k < 16; k++)
        for (int n = 0; n < 8; n++) q.b[k][n] = value_of(r, kind);
    for (int m = 0; m < 16; m++)   // (C: wide problems' as their values, zeros and subnormals too; the others' 2^-6 .. 2^4)
        for (int n = 0; n < 8; n++) q.c[m][n] = kind == kWide ? value_of(r, kind) : random_half(r, 9, 18);
    if (kind == kCancel) {   // (C takes back much of the first 8 k's sum and the last 8 cancel: the rounding at k = 8 decides)
        for (int m = 0; m < 16; m++) {
            for (int k = 8; k < 16; k++) q.a[m][k] = (uint16_t)(q.a[m][k] ^ (k & 1 ? 0x8000 : 0));
            for (int n = 0; n < 8; n++) {
                float s = 0;
                for (int k = 0; k < 8; k++) s += from_half(q.a[m][k]) * from_half(q.b[k][n]);
                q.c[m][n] = half_bits(round_half(-s * (0.5f + 0.25f * (float)r.below(3))));
            }
        }
    }
    return q;
}

/// the problem a step reads (kSameA takes its A from step kChainFrom; kZeroC's C is zero; kChainC's C is filled in by check())
inline Problem step_problem(uint64_t seed, uint32_t p) {
    Problem q = make_problem(seed, p);
    const uint32_t h = p % kSteps;
    if (kStepKind[h] == kSameA) {
        const Problem from = make_problem(seed, p - h + kChainFrom[h]);
        std::memcpy(q.a, from.a, sizeof q.a);
    }
    if (kStepKind[h] == kZeroC) std::memset(q.c, 0, sizeof q.c);
    return q;
}

inline std::vector<uint32_t> make_data(uint32_t groups, uint64_t seed) {
    std::vector<uint32_t> data(words(groups), 0xffffffffu);
    for (uint32_t p = 0; p < problems(groups); p++) {
        const Problem q = step_problem(seed, p);
        for (int t = 0; t < 32; t++) {
            uint32_t* w = &data[in_at(p, (uint32_t)t)];
            int r0, c0, r1, c1;
            for (int e = 0; e < 8; e += 2)
                console_a(t, e, r0, c0), console_a(t, e + 1, r1, c1), w[e / 2] = q.a[r0][c0] | (uint32_t)q.a[r1][c1] << 16;
            for (int e = 0; e < 4; e += 2)
                console_b(t, e, r0, c0), console_b(t, e + 1, r1, c1), w[4 + e / 2] = q.b[r0][c0] | (uint32_t)q.b[r1][c1] << 16;
            for (int e = 0; e < 4; e += 2)
                console_c(t, e, r0, c0), console_c(t, e + 1, r1, c1), w[6 + e / 2] = q.c[r0][c0] | (uint32_t)q.c[r1][c1] << 16;
        }
    }
    return data;
}

// ---- the module
/// The scratch the module uses: where PlanStagedScratch puts it after kProgramWords words, for a workgroup of
/// kSubgroups subgroups. limit: the device's maxComputeSharedMemorySize
inline Shader::Backend::SPIRV::StagedScratch scratch_for(uint32_t limit) {
    return Shader::Backend::SPIRV::PlanStagedScratch(kProgramWords * 4, workgroup(), limit);
}
/// Workgroups of kSubgroups subgroups, kSteps multiplies each through the route's function, over one storage buffer at set
/// 0 binding 0. scratch: scratch_for(limit), which must fit
inline std::vector<uint32_t> build(const Shader::Backend::SPIRV::StagedScratch& scratch, uint32_t groups) {
    using namespace Sirit;
    namespace SB = Shader::Backend::SPIRV;
    Module m{0x00010600};
    m.AddCapability(spv::Capability::Shader);
    m.AddCapability(spv::Capability::Float16);
    m.AddCapability(spv::Capability::GroupNonUniform);
    m.AddCapability(spv::Capability::CooperativeMatrixKHR);
    m.AddExtension("SPV_KHR_cooperative_matrix");
    m.AddCapability(spv::Capability::SignedZeroInfNanPreserve);
    m.AddExtension("SPV_KHR_vulkan_memory_model");
    m.AddCapability(spv::Capability::VulkanMemoryModel);
    m.AddCapability(spv::Capability::VulkanMemoryModelDeviceScope);
    m.SetMemoryModel(spv::AddressingModel::Logical, spv::MemoryModel::VulkanKHR);
    const Id void_t = m.TypeVoid(), u32 = m.TypeUInt(32), f16 = m.TypeFloat(16), f32 = m.TypeFloat(32);
    const Id u32x2 = m.TypeVector(u32, 2), u32x3 = m.TypeVector(u32, 3), u32x4 = m.TypeVector(u32, 4);
    const Id f16x2 = m.TypeVector(f16, 2), f32x2 = m.TypeVector(f32, 2);
    const SB::StagedTypes types{u32, f16, f32, u32x2, u32x4, f16x2, f32x2};
    const auto c32 = [&](uint32_t v) { return m.Constant(u32, v); };
    const Id runtime = m.TypeRuntimeArray(u32);
    m.Decorate(runtime, spv::Decoration::ArrayStride, 4U);
    const Id block = m.TypeStruct(runtime);
    m.Decorate(block, spv::Decoration::Block);
    m.MemberDecorate(block, 0U, spv::Decoration::Offset, 0U);
    const Id buf = m.AddGlobalVariable(m.TypePointer(spv::StorageClass::StorageBuffer, block), spv::StorageClass::StorageBuffer);
    m.Decorate(buf, spv::Decoration::DescriptorSet, 0U);
    m.Decorate(buf, spv::Decoration::Binding, 0U);
    const Id buf_word = m.TypePointer(spv::StorageClass::StorageBuffer, u32);
    // (the shared block as the translator makes it without the explicit layout: one u32 array, the scratch in it)
    const Id shared_type = m.TypeArray(u32, c32(scratch.size / 4));
    const Id shared = m.AddGlobalVariable(m.TypePointer(spv::StorageClass::Workgroup, shared_type), spv::StorageClass::Workgroup);
    const Id shared_word = m.TypePointer(spv::StorageClass::Workgroup, u32);
    const auto input = [&](Id type, spv::BuiltIn builtin) {
        const Id v = m.AddGlobalVariable(m.TypePointer(spv::StorageClass::Input, type), spv::StorageClass::Input);
        m.Decorate(v, spv::Decoration::BuiltIn, builtin);
        return v;
    };
    const Id workgroup_id = input(u32x3, spv::BuiltIn::WorkgroupId);
    const Id subgroup_id = input(u32, spv::BuiltIn::SubgroupId);
    const Id lane_id = input(u32, spv::BuiltIn::SubgroupLocalInvocationId);
    const auto word = [&](Id index) { return m.OpAccessChain(shared_word, shared, index); };
    const Id multiply = SB::MakeStagedMatrixFunction(m, types, word, lane_id, subgroup_id, scratch.offset / 4);

    const Id main = m.OpFunction(void_t, spv::FunctionControlMask::MaskNone, m.TypeFunction(void_t));
    m.AddLabel();
    const Id wg_id = m.OpLoad(u32x3, workgroup_id);
    const Id wg = m.OpCompositeExtract(u32, wg_id, 0U);
    const Id sg = m.OpLoad(u32, subgroup_id);
    const Id lane = m.OpLoad(u32, lane_id);
    const auto buf_at = [&](Id index) { return m.OpAccessChain(buf_word, buf, c32(0), index); };
    const auto add = [&](Id x, uint32_t v) { return m.OpIAdd(u32, x, c32(v)); };
    const auto mul = [&](Id x, uint32_t v) { return m.OpIMul(u32, x, c32(v)); };
    const Id sg_lanes = mul(sg, kLanes);
    const Id invocation = m.OpIAdd(u32, sg_lanes, lane);
    const Id wg_sgs = mul(wg, kSubgroups);
    const Id wg_sg = m.OpIAdd(u32, wg_sgs, sg);
    // (the program's own shared memory and barriers as the translator makes them on this route: non-private, the barriers making
    // the shared memory available and visible, EmitContext::DefineMatrixRoute)
    const auto barrier = [&] {
        const Id scope = c32((uint32_t)spv::Scope::Workgroup);
        const Id semantics = c32((uint32_t)(spv::MemorySemanticsMask::AcquireRelease | spv::MemorySemanticsMask::WorkgroupMemory |
                                            spv::MemorySemanticsMask::MakeAvailable | spv::MemorySemanticsMask::MakeVisible));
        m.OpControlBarrier(scope, scope, semantics);
    };
    constexpr auto nonprivate = spv::MemoryAccessMask::NonPrivatePointer;
    // (the program's own shared words: one an invocation, from the block's start)
    const Id sentinel = m.OpBitwiseOr(u32, invocation, c32(kSentinel));
    m.OpStore(word(invocation), sentinel, nonprivate);
    barrier();
    Id d_of[kSteps]{}, a_of[kSteps]{};
    const Id zero_c = m.ConstantComposite(u32x2, c32(0), c32(0));
    for (uint32_t h = 0; h < kSteps; h++) {
        const Id wg_sg_steps = mul(wg_sg, kSteps);
        const Id p = add(wg_sg_steps, h);
        const Id p_lanes = mul(p, kLanes);
        const Id p_lane = m.OpIAdd(u32, p_lanes, lane);
        const Id in = mul(p_lane, 8);
        Id w[8];
        for (uint32_t j = 0; j < 8; j++) {
            const Id at = add(in, j);
            w[j] = m.OpLoad(u32, buf_at(at));
        }
        Id a = m.OpCompositeConstruct(u32x4, w[0], w[1], w[2], w[3]);
        const Id b = m.OpCompositeConstruct(u32x2, w[4], w[5]);
        Id c = m.OpCompositeConstruct(u32x2, w[6], w[7]);
        if (kStepKind[h] == kZeroC) c = zero_c;   // (as HMMA_nx2 makes C = RZ: a constant)
        if (kStepKind[h] == kChainC) c = d_of[kChainFrom[h]];
        if (kStepKind[h] == kSameA) a = a_of[kChainFrom[h]];
        a_of[h] = a;
        d_of[h] = m.OpFunctionCall(u32x2, multiply, a, b, c);
        const Id out_lane = mul(p_lane, 2);
        const Id out = add(out_lane, problems(groups) * kLanes * 8);
        for (uint32_t j = 0; j < 2; j++) {
            const Id at = add(out, j);
            const Id value = m.OpCompositeExtract(u32, d_of[h], j);
            m.OpStore(buf_at(at), value);
        }
    }
    barrier();
    const Id own = m.OpLoad(u32, word(invocation), nonprivate);
    const Id wg_lanes = mul(wg, kSubgroups * kLanes);
    const Id global = m.OpIAdd(u32, wg_lanes, invocation);
    const Id own_at = add(global, check_at(groups, 0));
    m.OpStore(buf_at(own_at), own);
    m.OpReturn();
    m.OpFunctionEnd();
    m.AddEntryPoint(spv::ExecutionModel::GLCompute, main, "main", buf, shared, workgroup_id, subgroup_id, lane_id);
    m.AddExecutionMode(main, spv::ExecutionMode::LocalSize, kSubgroups * kLanes, 1U, 1U);
    m.AddExecutionMode(main, spv::ExecutionMode::SignedZeroInfNanPreserve, 16U);
    m.AddExecutionMode(main, spv::ExecutionMode::SignedZeroInfNanPreserve, 32U);
    return m.Assemble();
}

// ---- the check
struct Report {
    uint32_t problems = 0, elements = 0;
    uint32_t differ = 0;        // (elements not the software function's)
    uint32_t differ_exact = 0;  // (elements not exact_two_step's: HMMA's roundings over exact sums)
    uint32_t beyond = 0;        // (elements further from it than the roundings allow: one f16 ulp of the sum at k = 8, one of
                                //  D, and the f32 error bounds of the two sums)
    uint32_t exact_bad = 0;     // (elements of the small-integer problems not exact)
    uint32_t unwritten = 0;     // (D words never written)
    uint32_t own_bad = 0;       // (the program's own shared words changed)
    uint32_t differ_kind[kKinds]{};
    uint32_t elements_kind[kKinds]{};
    uint32_t differ_at[16][8]{};  // (the differing elements by their place in D: one lane's or one element's error shows there)
    uint32_t ulps_of_d[6]{};    // (the differing elements by their difference in f16 ulps of D: 1, 2, 3-4, 5-16, 17-256, more)
    double max_ulp = 0;         // (the largest difference, in f16 ulps of D)
    double max_ulp_mid = 0;     // (... in f16 ulps of the sum at k = 8)
    double max_share = 0;       // (... as a share of what the roundings allow)
    double max_sum_roundings = 0;   // (... past the two f16 roundings, in f32 roundings of the terms' magnitudes: kSumRoundings)
    std::string worst;
    /// the largest share of a kind's elements that differ, per mille (which: that kind)
    double kind_per_mille(uint32_t* which = nullptr) const {
        double most = 0;
        for (uint32_t k = 0; k < kKinds; k++) {
            const double rate = elements_kind[k] ? 1000.0 * differ_kind[k] / elements_kind[k] : 0.0;
            if (rate > most) {
                most = rate;
                if (which) *which = k;
            }
        }
        return most;
    }
    /// the most elements that differ at one place of D
    uint32_t most_at_one_place() const {
        uint32_t most = 0;
        for (const auto& row : differ_at)
            for (const uint32_t n : row) most = std::max(most, n);
        return most;
    }
    /// Nothing beyond the bound, the small-integer problems exact, every output written, the program's own shared words
    /// kept, and at most max_differ_per_mille of the elements differing by a rounding, and of any kind's at most
    /// max_kind_per_mille, and of the problems' at any place of D at most max_place_per_mille (each at least 4 elements): a
    /// bug in one kind of problem or one lane's elements stays far under the share of them all. On an RX 9070 XT (RADV),
    /// 64 runs of the self-test's size: at most 0.37 per mille in all, 0.85 of a kind's (large), 4 of 1024 at one place;
    /// and a wrong step in 3% of the large problems' elements (2 per mille in all) failed only by its kind
    bool passed(uint32_t max_differ_per_mille, uint32_t max_kind_per_mille = 8, uint32_t max_place_per_mille = 24) const {
        if (!elements || beyond || exact_bad || unwritten || own_bad ||
            (uint64_t)differ * 1000 > (uint64_t)elements * max_differ_per_mille)
            return false;
        for (uint32_t k = 0; k < kKinds; k++)
            if ((uint64_t)differ_kind[k] * 1000 > std::max<uint64_t>((uint64_t)elements_kind[k] * max_kind_per_mille, 4000))
                return false;
        return (uint64_t)most_at_one_place() * 1000 <= std::max<uint64_t>((uint64_t)problems * max_place_per_mille, 4000);
    }
    void add(const Report& o) {
        problems += o.problems, elements += o.elements, differ += o.differ, differ_exact += o.differ_exact;
        beyond += o.beyond, exact_bad += o.exact_bad, unwritten += o.unwritten, own_bad += o.own_bad;
        for (uint32_t k = 0; k < kKinds; k++) differ_kind[k] += o.differ_kind[k], elements_kind[k] += o.elements_kind[k];
        for (uint32_t r = 0; r < 16; r++)
            for (uint32_t n = 0; n < 8; n++) differ_at[r][n] += o.differ_at[r][n];
        for (uint32_t k = 0; k < 6; k++) ulps_of_d[k] += o.ulps_of_d[k];
        max_ulp = std::max(max_ulp, o.max_ulp), max_ulp_mid = std::max(max_ulp_mid, o.max_ulp_mid);
        max_sum_roundings = std::max(max_sum_roundings, o.max_sum_roundings);
        if (o.max_share > max_share || worst.empty()) max_share = std::max(max_share, o.max_share), worst = o.worst;
    }
};

/// data: the buffer after the dispatch of build(scratch, groups) over make_data(groups, seed)
inline Report check(const std::vector<uint32_t>& data, uint32_t groups, uint64_t seed) {
    Report rep;
    rep.problems = problems(groups);
    const auto half = [&](uint32_t w, int e) { return (uint16_t)(e & 1 ? w >> 16 : w & 0xffff); };
    const auto finite = [](double v) { return std::isinf(v) ? std::copysign(65536.0, v) : v; };
    for (uint32_t p = 0; p < rep.problems; p++) {
        Problem q = step_problem(seed, p);
        const uint32_t h = p % kSteps;
        const bool exact = kind_of(p) == kExact && (kStepKind[h] == kOwnC || kStepKind[h] == kZeroC);
        if (kStepKind[h] == kChainC) {   // (C is what the GPU made for the earlier step: each multiply checked on its own inputs)
            const uint32_t from = p - h + kChainFrom[h];
            for (int t = 0; t < 32; t++)
                for (int e = 0; e < 4; e++) {
                    int r, n;
                    console_c(t, e, r, n);
                    q.c[r][n] = half(data[out_at(groups, from, (uint32_t)t) + e / 2], e);
                }
        }
        for (int t = 0; t < 32; t++) {
            const uint32_t* w = &data[out_at(groups, p, (uint32_t)t)];
            if (w[0] == 0xffffffffu || w[1] == 0xffffffffu) rep.unwritten++;
            for (int e = 0; e < 4; e++) {
                int r, n;
                console_c(t, e, r, n);
                const Reference want = reference(q, r, n);
                const float got = from_half(half(w[e / 2], e));
                rep.elements++;
                rep.elements_kind[kind_of(p)]++;
                if (got != exact_two_step(q, r, n)) rep.differ_exact++;
                if (got == want.d || (std::isnan(got) && std::isnan(want.d))) continue;
                rep.differ++;
                rep.differ_kind[kind_of(p)]++;
                rep.differ_at[r][n]++;
                const double diff = std::fabs(finite(got) - finite(want.d));
                const double ulp_d = ulp16(std::max(std::fabs(finite(got)), std::fabs(finite(want.d))));
                const double allowed = ulp16(finite(want.mid)) + ulp_d + want.error_first + want.error_second;
                const double share = diff / allowed;
                const double past_roundings = diff - ulp16(finite(want.mid)) - ulp_d;
                if (past_roundings > 0)
                    rep.max_sum_roundings = std::max(rep.max_sum_roundings,
                                                     past_roundings * kSumRoundings / (want.error_first + want.error_second));
                if (std::isnan(got) || std::isnan(want.d) || share > 1.0) rep.beyond++;
                if (exact) rep.exact_bad++;
                rep.max_ulp = std::max(rep.max_ulp, diff / ulp_d);
                const double in_ulps = diff / ulp_d;
                rep.ulps_of_d[in_ulps <= 1 ? 0 : in_ulps <= 2 ? 1 : in_ulps <= 4 ? 2 : in_ulps <= 16 ? 3 : in_ulps <= 256 ? 4 : 5]++;
                rep.max_ulp_mid = std::max(rep.max_ulp_mid, diff / ulp16(finite(want.mid)));
                if (share > rep.max_share || rep.worst.empty()) {
                    rep.max_share = std::max(rep.max_share, share);
                    char line[240];
                    std::snprintf(line, sizeof line, "problem %u (%s, step %u) lane %d D[%d][%d] %.9g, the software function "
                                  "%.9g (the sum at k = 8 %.9g)", p, kind_name(kind_of(p)), h, t, r, n, got, want.d, want.mid);
                    rep.worst = line;
                }
            }
        }
    }
    for (uint32_t i = 0; i < groups * kSubgroups * kLanes; i++)
        if (data[check_at(groups, i)] != (kSentinel | (i % (kSubgroups * kLanes)))) rep.own_bad++;
    return rep;
}

/// One line for a log
inline std::string summary(const Report& r) {
    char line[640];
    uint32_t kind = 0;
    const double kind_rate = r.kind_per_mille(&kind);
    std::snprintf(line, sizeof line,
                  "%u problems, %u elements: %u differ from the software function by a rounding (max %.3g f16 ulps of D, "
                  "%.2f of the bound of HMMA's roundings), %u beyond it, %u from exact sums rounded as HMMA rounds; %.2f per "
                  "mille of a kind's at most (%s), %u at one place of D; %u exact-problem errors, %u unwritten, %u of the "
                  "program's own shared words changed",
                  r.problems, r.elements, r.differ, r.max_ulp, r.max_share, r.beyond, r.differ_exact, kind_rate,
                  kind_name(kind), r.most_at_one_place(), r.exact_bad, r.unwritten, r.own_bad);
    return line;
}

} // namespace mma_staged_test
