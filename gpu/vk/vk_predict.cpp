// (hookshot) The pipelines the notes predict (vk_draw.cpp predict_run builds them when the shaders are prepared). The notes
// (hookshot_pipelines.bin) name the pipelines play built: a program and the draw state that went with it. Most programs of the game
// are in no note, and their first draw builds their pipeline in play. Each is predicted the "1x1" way: the vertex layout of the notes
// whose vertex program is the same module (else the layout most programs with its vertex inputs had), and the targets the notes of
// its fragment module had (else those most programs with its outputs had). One pipeline for each pair of what it takes, with the
// state of the first note that had each part
#include <algorithm>
#include <cstring>
#include <memory>
#include <mutex>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "vk_draw.h"
#include "vk_shader.h"

namespace mkwvk {
namespace {

uint64_t fnv(const void* p, size_t n, uint64_t h = 0xcbf29ce484222325ull) {
    for (size_t i = 0; i < n; i++) h = (h ^ ((const uint8_t*)p)[i]) * 0x100000001b3ull;
    return h;
}
/// The locations of a module's Input (storage 1) or Output (3) variables: each one (mask), those of an integer type (ints), and of
/// those the signed ones (sign). The program's key was made for those types (graphics_key: the vertex inputs' attribute types;
/// written_types: the colour outputs'), and the translator declares each variable with its type (GetAttributeType)
struct Locations {
    uint32_t mask = 0, ints = 0, sign = 0;
};
Locations spirv_locations(const std::vector<uint32_t>& w, uint32_t storage) {
    std::unordered_map<uint32_t, uint32_t> loc, var, inner;   // (variable: its pointer type; pointer, vector, array: what it holds)
    std::unordered_map<uint32_t, bool> ints;                  // (OpTypeInt: signed)
    for (size_t i = 5; i < w.size();) {
        const uint32_t op = w[i] & 0xFFFF, n = w[i] >> 16;
        if (!n || i + n > w.size()) break;
        if (op == 71 && n >= 4 && w[i + 2] == 30) loc[w[i + 1]] = w[i + 3];               // OpDecorate Location
        else if (op == 59 && n >= 4 && w[i + 3] == storage) var[w[i + 2]] = w[i + 1];      // OpVariable
        else if (op == 21 && n >= 4) ints[w[i + 1]] = w[i + 3] != 0;                       // OpTypeInt
        else if ((op == 23 || op == 28) && n >= 3) inner[w[i + 1]] = w[i + 2];             // OpTypeVector, OpTypeArray
        else if (op == 32 && n >= 4) inner[w[i + 1]] = w[i + 3];                           // OpTypePointer
        i += n;
    }
    Locations out;
    for (const auto& [id, type] : var) {
        const auto l = loc.find(id);
        if (l == loc.end() || l->second >= 32) continue;
        const uint32_t bit = 1u << l->second;
        out.mask |= bit;
        uint32_t t = type;
        for (int depth = 0; depth < 4; depth++) {
            const auto in = inner.find(t);
            if (in == inner.end()) break;
            t = in->second;
        }
        if (const auto it = ints.find(t); it != ints.end()) out.ints |= bit, out.sign |= it->second ? bit : 0;
    }
    return out;
}
struct Face {
    uint64_t vs = 0, fs = 0;             // the vertex (or mesh) and fragment modules, by their SPIR-V (0: no fragment stage)
    uint32_t vs_locs = 0, fs_locs = 0;   // generic inputs read, colour outputs written
    Locations vs_in, fs_out;
    int64_t at = 0;   // (its record's place in the file)
};
/// Whether a module whose variables at those locations have those types could be drawn with these attribute types (graphics_key's
/// for vertex inputs, color_types_of's for colour targets). Only a definite difference says no: an integer type where the module
/// has a float, a float where it has an integer, or the other signedness. The scaled types are let through: whether the translator
/// made them float or integer depends on the GPU (support_scaled_attributes)
bool types_fit(const Locations& l, uint32_t locs, const uint8_t types[], int count) {
    for (int i = 0; i < count; i++) {
        if (!(locs >> i & 1)) continue;
        const bool is_int = l.ints >> i & 1, is_signed = l.sign >> i & 1;
        switch ((Shader::AttributeType)types[i]) {
        case Shader::AttributeType::Float: if (is_int) return false; break;
        case Shader::AttributeType::SignedInt: if (!is_int || !is_signed) return false; break;
        case Shader::AttributeType::UnsignedInt: if (!is_int || is_signed) return false; break;
        default: break;
        }
    }
    return true;
}
using Class = std::vector<uint32_t>;
Class vertex_class(const PipeNote& n, uint32_t locs) {
    Class c{n.topo};
    bool streams[15]{};
    for (int i = 0; i < std::min(n.s.nvattr, 16); i++) {
        if (!(locs >> i & 1)) continue;
        const uint32_t a = n.s.vattr[i], stream = a >> 27;
        c.insert(c.end(), {(uint32_t)i, a & 0xFF, (a >> 8) & 0x3FFF, stream});
        if (stream < 15) streams[stream] = true;
    }
    c.push_back(~0u);
    for (uint32_t b = 0; b < 15; b++)
        if (streams[b]) c.insert(c.end(), {b, n.s.vstream[b].stride, n.s.vstream[b].divisor});
    return c;
}
Class output_class(const PipeNote& n) {
    Class c{n.samples};
    for (uint32_t i = 0; i < n.n && i < 8; i++) c.push_back(n.color_format[i]);
    c.push_back(n.has_depth ? n.depth_format : 0);
    return c;
}
struct ClassHash {
    size_t operator()(const Class& c) const { return (size_t)fnv(c.data(), c.size() * 4); }
};
struct PairHash {
    size_t operator()(const std::pair<uint64_t, uint64_t>& p) const { return (size_t)(p.first * 1099511628211ull ^ p.second); }
};
/// What a module or signature was noted with: each class, and the program variants that had it
struct Seen {
    std::vector<Class> order;   // (in the order first noted: ties go to the earliest)
    std::unordered_map<Class, std::unordered_set<std::pair<uint64_t, uint64_t>, PairHash>, ClassHash> by;
    void add(const Class& c, std::pair<uint64_t, uint64_t> pv) {
        auto [it, fresh] = by.try_emplace(c);
        if (fresh) order.push_back(c);
        it->second.insert(pv);
    }
};
/// Every class of an exact module, else the one most program variants of the signature had
std::vector<Class> candidates(const Seen* exact, const Seen* sig) {
    if (exact && !exact->order.empty()) return exact->order;
    if (!sig || sig->order.empty()) return {};
    const Class* best = nullptr;
    size_t most = 0;
    for (const Class& c : sig->order)
        if (sig->by.at(c).size() > most) most = sig->by.at(c).size(), best = &c;
    return {*best};
}

} // namespace

std::vector<std::unique_ptr<PipeNote>> predict_pipelines(const std::vector<std::unique_ptr<PipeNote>>& notes, size_t* programs,
                                                         PredictCounts* left_out) {
    std::unordered_map<std::pair<uint64_t, uint64_t>, Face, PairHash> faces;
    std::mutex faces_mu;
    program_cache_each([&](const KeptProgram& k) {
        Face f;
        for (const auto& [stage, spirv] : k.stages) {
            const uint64_t h = fnv(spirv.data(), spirv.size() * 4);
            if (stage == VK_SHADER_STAGE_VERTEX_BIT) f.vs = h, f.vs_in = spirv_locations(spirv, 1), f.vs_locs = f.vs_in.mask;
            else if (stage == VK_SHADER_STAGE_TASK_BIT_EXT || stage == VK_SHADER_STAGE_MESH_BIT_EXT) f.vs = h, f.vs_locs = 0, f.vs_in = {};
            else if (stage == VK_SHADER_STAGE_FRAGMENT_BIT) f.fs = h, f.fs_out = spirv_locations(spirv, 3), f.fs_locs = f.fs_out.mask;
        }
        f.at = k.at;
        std::lock_guard lk(faces_mu);   // (program_cache_each: on several threads, in no order: the later record wins, as in file order)
        auto [it, fresh] = faces.try_emplace({k.key, k.variant}, f);
        if (!fresh && it->second.at < f.at) it->second = f;
    });
    std::unordered_map<uint64_t, Seen> vh, vsig, fh, fsig;
    std::unordered_map<Class, const PipeNote*, ClassHash> vdonor, odonor;
    std::unordered_set<std::pair<uint64_t, uint64_t>, PairHash> noted;
    for (const auto& n : notes) {
        const std::pair<uint64_t, uint64_t> pv{n->prog, n->variant};
        const auto it = faces.find(pv);
        if (it == faces.end()) continue;
        const Face& f = it->second;
        const Class v = vertex_class(*n, f.vs_locs), o = output_class(*n);
        vh[f.vs].add(v, pv), vsig[f.vs_locs].add(v, pv), fh[f.fs].add(o, pv), fsig[f.fs_locs].add(o, pv);
        vdonor.try_emplace(v, n.get()), odonor.try_emplace(o, n.get());
        noted.insert(pv);
    }
    const auto find = [](const std::unordered_map<uint64_t, Seen>& m, uint64_t k) -> const Seen* {
        const auto it = m.find(k);
        return it == m.end() ? nullptr : &it->second;
    };
    // (a candidate whose types the program was not made for is left out: a draw with that vertex layout or those targets has
    // another program key (graphics_key), so no draw asks for that pipeline. The skinned programs' three variants by their bone
    // inputs (seed_program) all took the one layout their signature's notes had most, and two of the three could never be drawn
    // with it: each a pipeline of its own modules, a full compile. Exact modules' candidates always fit: their notes drew them)
    const auto vertex_fits = [](const Face& f, const PipeNote& n) {
        uint8_t types[16];
        for (int i = 0; i < 16; i++) types[i] = (uint8_t)attribute_type_of(n.s.vattr[i]);
        return types_fit(f.vs_in, f.vs_locs, types, 16);
    };
    const auto output_fits = [](const Face& f, const PipeNote& n) {
        uint8_t types[8];
        note_color_types(n, types);
        return types_fit(f.fs_out, f.fs_locs, types, 8);
    };
    PredictCounts counts;
    for (const auto& n : notes)   // (what play drew always fits: a note that does not says the rule is wrong; the log counts them)
        if (const auto it = faces.find({n->prog, n->variant}); it != faces.end())
            counts.notes_unfit += !vertex_fits(it->second, *n) || !output_fits(it->second, *n);
    std::vector<std::unique_ptr<PipeNote>> out;
    *programs = 0;
    for (const auto& [pv, f] : faces) {
        if (noted.count(pv)) continue;
        std::vector<Class> vc = candidates(find(vh, f.vs), find(vsig, f.vs_locs));
        std::vector<Class> oc = candidates(find(fh, f.fs), find(fsig, f.fs_locs));
        if (vc.empty() || oc.empty()) continue;
        const size_t all = vc.size() * oc.size();
        vc.erase(std::remove_if(vc.begin(), vc.end(), [&](const Class& v) { return !vertex_fits(f, *vdonor.at(v)); }), vc.end());
        const size_t vertex_kept = vc.size() * oc.size();
        oc.erase(std::remove_if(oc.begin(), oc.end(), [&](const Class& o) { return !output_fits(f, *odonor.at(o)); }), oc.end());
        counts.vertex_types += all - vertex_kept, counts.output_types += vertex_kept - vc.size() * oc.size();
        if (vc.empty() || oc.empty()) {
            counts.variants_unfit++;
            continue;
        }
        (*programs)++;
        for (const Class& v : vc)
            for (const Class& o : oc) {
                const PipeNote& V = *vdonor.at(v);
                auto n = std::make_unique<PipeNote>(*odonor.at(o));
                std::memcpy(n->s.vattr, V.s.vattr, sizeof n->s.vattr);
                n->s.nvattr = V.s.nvattr;
                std::memcpy(n->s.vstream, V.s.vstream, sizeof n->s.vstream);
                n->topo = V.topo;
                n->prog = pv.first, n->variant = pv.second;
                n->key = 0;
                out.push_back(std::move(n));
            }
    }
    if (left_out) *left_out = counts;
    return out;
}

} // namespace mkwvk
