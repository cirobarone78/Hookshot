// (hookshot) The pipelines the notes predict (vk_draw.cpp predict_run builds them when the shaders are prepared). The notes
// (hookshot_pipelines.bin) name the pipelines play built: a program and the draw state that went with it. Most programs of the game
// are in no note, and their first draw builds their pipeline in play. Each is predicted the "1x1" way: the vertex layout of the notes
// whose vertex program is the same module (else the layout most programs with its vertex inputs had), and the targets the notes of
// its fragment module had (else those most programs with its outputs had). One pipeline for each pair of what it takes, with the
// state of the first note that had each part
#include <algorithm>
#include <cstring>
#include <memory>
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
using Class = std::vector<uint32_t>;
struct Face {
    uint64_t vs = 0, fs = 0;             // the vertex (or mesh) and fragment modules, by their SPIR-V (0: no fragment stage)
    Class vs_inputs;                    // canonical location/numeric32 signature; empty: exact module only
    uint32_t vs_locs = 0, fs_locs = 0;   // generic inputs read, colour outputs written
};
/// The locations of a module's Input (storage 1) or Output (3) variables
uint32_t spirv_locations(const std::vector<uint32_t>& w, uint32_t storage) {
    std::unordered_map<uint32_t, uint32_t> loc;
    std::unordered_set<uint32_t> var;
    for (size_t i = 5; i < w.size();) {
        const uint32_t op = w[i] & 0xFFFF, n = w[i] >> 16;
        if (!n || i + n > w.size()) break;
        if (op == 71 && n >= 4 && w[i + 2] == 30) loc[w[i + 1]] = w[i + 3];     // OpDecorate Location
        else if (op == 59 && n >= 4 && w[i + 3] == storage) var.insert(w[i + 2]);   // OpVariable
        i += n;
    }
    uint32_t mask = 0;
    for (const uint32_t id : var)
        if (const auto l = loc.find(id); l != loc.end() && l->second < 32) mask |= 1u << l->second;
    return mask;
}
/// Generic vertex inputs: the same locations must also consume the same numeric32 class.
/// Unknown representations stay eligible for exact-module matching, never generic fallback.
Class spirv_vertex_inputs(const std::vector<uint32_t>& w) {
    if (w.size() < 5) return {};
    std::unordered_map<uint32_t, uint32_t> types, pointers, loc, vars;
    std::unordered_set<uint32_t> builtin, component;
    for (size_t i = 5; i < w.size();) {
        const uint32_t op = w[i] & 0xFFFF, n = w[i] >> 16;
        if (!n || i + n > w.size()) return {};
        if (op == 73 || op == 74 || op == 75) return {};   // grouped decorations: exact module only
        if (op == 22 && n == 3 && w[i + 2] == 32) types[w[i + 1]] = 1;   // F32
        else if (op == 21 && n == 4 && w[i + 2] == 32 && w[i + 3] <= 1)
            types[w[i + 1]] = w[i + 3] ? 2 : 3;   // S32 / U32
        else if (op == 23 && n == 4 && w[i + 3] >= 2 && w[i + 3] <= 4) {
            if (auto t = types.find(w[i + 2]); t != types.end()) types[w[i + 1]] = t->second;
        } else if (op == 32 && n == 4 && w[i + 2] == 1) {
            if (auto t = types.find(w[i + 3]); t != types.end()) pointers[w[i + 1]] = t->second;
        } else if (op == 59 && n >= 4 && w[i + 3] == 1) vars[w[i + 2]] = w[i + 1];
        else if (op == 71 && n >= 4) {
            if (w[i + 2] == 30) loc[w[i + 1]] = w[i + 3];
            else if (w[i + 2] == 11) builtin.insert(w[i + 1]);
            else if (w[i + 2] == 31 && w[i + 3]) component.insert(w[i + 1]);
        }
        i += n;
    }
    uint32_t mask = 0, numeric[32]{};
    for (const auto& [id, type] : vars) {
        if (builtin.count(id)) continue;
        const auto l = loc.find(id), t = pointers.find(type);
        if (l == loc.end() || l->second >= 32 || t == pointers.end() || component.count(id)) return {};
        const uint32_t bit = 1u << l->second;
        if (mask & bit) return {};   // component-packed or overlapping locations are not represented
        mask |= bit, numeric[l->second] = t->second;
    }
    Class signature{mask};
    for (uint32_t i = 0; i < 32; i++)
        if (mask >> i & 1) signature.insert(signature.end(), {i, numeric[i]});
    return signature;
}
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

std::vector<std::unique_ptr<PipeNote>> predict_pipelines(const std::vector<std::unique_ptr<PipeNote>>& notes, size_t* programs) {
    std::unordered_map<std::pair<uint64_t, uint64_t>, Face, PairHash> faces;
    program_cache_each([&](const KeptProgram& k) {
        Face f;
        for (const auto& [stage, spirv] : k.stages) {
            const uint64_t h = fnv(spirv.data(), spirv.size() * 4);
            if (stage == VK_SHADER_STAGE_VERTEX_BIT) {
                f.vs = h, f.vs_locs = spirv_locations(spirv, 1);
                f.vs_inputs = spirv_vertex_inputs(spirv);
            }
            else if (stage == VK_SHADER_STAGE_TASK_BIT_EXT || stage == VK_SHADER_STAGE_MESH_BIT_EXT)
                f.vs = h, f.vs_locs = 0, f.vs_inputs = Class{0};
            else if (stage == VK_SHADER_STAGE_FRAGMENT_BIT) f.fs = h, f.fs_locs = spirv_locations(spirv, 3);
        }
        faces[{k.key, k.variant}] = f;
    });
    std::unordered_map<uint64_t, Seen> vh, fh, fsig;
    std::unordered_map<Class, Seen, ClassHash> vsig;
    std::unordered_map<Class, const PipeNote*, ClassHash> vdonor, odonor;
    std::unordered_set<std::pair<uint64_t, uint64_t>, PairHash> noted;
    for (const auto& n : notes) {
        const std::pair<uint64_t, uint64_t> pv{n->prog, n->variant};
        const auto it = faces.find(pv);
        if (it == faces.end()) continue;
        const Face& f = it->second;
        const Class v = vertex_class(*n, f.vs_locs), o = output_class(*n);
        vh[f.vs].add(v, pv), fh[f.fs].add(o, pv), fsig[f.fs_locs].add(o, pv);
        if (!f.vs_inputs.empty()) vsig[f.vs_inputs].add(v, pv);
        vdonor.try_emplace(v, n.get()), odonor.try_emplace(o, n.get());
        noted.insert(pv);
    }
    const auto find = [](const auto& m, const auto& k) -> const Seen* {
        const auto it = m.find(k);
        return it == m.end() ? nullptr : &it->second;
    };
    std::vector<std::unique_ptr<PipeNote>> out;
    *programs = 0;
    for (const auto& [pv, f] : faces) {
        if (noted.count(pv)) continue;
        const std::vector<Class> vc = candidates(find(vh, f.vs), f.vs_inputs.empty() ? nullptr : find(vsig, f.vs_inputs));
        const std::vector<Class> oc = candidates(find(fh, f.fs), find(fsig, f.fs_locs));
        if (vc.empty() || oc.empty()) continue;
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
    return out;
}

} // namespace mkwvk
