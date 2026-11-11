// Bounded reuse of CPU shader lowering. Hashes only locate candidates: every byte of
// the control section and code/constants must match before a result can be reused.
#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <unordered_map>
#include <utility>
#include <vector>

namespace mkwvk {
template<class Value, size_t ControlSize>
class StageCache {
    struct Entry {
        std::array<uint8_t, ControlSize> control;
        std::vector<uint8_t> area;
        Value value;
    };
    std::unordered_multimap<uint64_t, Entry> entries;
    size_t used = 0;
    const size_t budget, max_entries;
public:
    explicit StageCache(size_t budget_bytes, size_t count = 4096) : budget(budget_bytes), max_entries(count) {}
    const Value* find(uint64_t key, const uint8_t* control, const std::vector<uint8_t>& area) const {
        const auto range = entries.equal_range(key);
        for (auto it = range.first; it != range.second; ++it)
            if (it->second.area == area && !std::memcmp(it->second.control.data(), control, ControlSize))
                return &it->second.value;
        return nullptr;
    }
    void insert(uint64_t key, const uint8_t* control, const std::vector<uint8_t>& area,
                const Value& value, size_t value_bytes) {
        // Include inline storage and dynamic payloads. Node/bucket overhead is also
        // bounded by max_entries; oversized stages do not evict useful small ones.
        if (!max_entries || sizeof(Entry) > budget || area.size() > budget - sizeof(Entry) ||
            value_bytes > budget - sizeof(Entry) - area.size()) return;
        const size_t size = sizeof(Entry) + area.size() + value_bytes;
        if (size > budget - used || entries.size() >= max_entries) {
            entries.clear();
            used = 0;
        }
        Entry entry{{}, area, value};
        std::memcpy(entry.control.data(), control, ControlSize);
        entries.emplace(key, std::move(entry));
        used += size;
    }
    size_t bytes() const { return used; }
};
} // namespace mkwvk
