// Session-local external enhancement controls. No external shared-memory ABI or
// helper process runs on the renderer/menu thread.
#pragma once
#include <array>
#include <charconv>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <string>
#include <string_view>
#include <thread>
#ifdef _WIN32
#include <windows.h>
#endif

namespace mkwvk::dlss5_controls {
enum Setting { Enabled, ApplyModel, Compare, CompareSplit, Detail, Colour, Sharpness, Intensity,
    LocalTone, LocalStructure, SkinStructure, AutoMask, Style, Preset, WorkingScale, Bypass, Transfer,
    MotionQuality, MotionPixels, Count };
struct Spec { const char* key; int lo, hi; bool advanced; };
inline constexpr std::array<Spec, Count> specs{{
    {"enabled",0,1,false},{"applymodel",0,1,true},{"compare",0,2,false},{"comparesplit",0,100,false},
    {"detail",0,400,false},{"colour",0,400,false},{"sharpness",0,100,false},{"intensity",0,400,false},
    {"localtone",0,400,true},{"localstructure",0,400,true},{"skinstructure",-100,400,true},
    {"automask",0,1,true},{"style",0,2,false},{"preset",0,15,false},{"workingscale",25,100,false},
    {"bypass",0,1,true},{"transfer",0,2,true},{"mvecquality",0,2,true},{"mvecpixels",0,3,true}}};
// ShmInitDefaults plus the adapter's native-detail startup defaults, in UI
// units. test_dlss5_menu.py checks every value against Python DEFAULT_SETTINGS.
inline constexpr std::array<int, Count> defaults{{
    1,1,0,50,100,100,0,100,100,100,-100,1,0,0,50,0,2,1,2}};
struct State {
    std::array<int, Count> values{};
    uint64_t ack = 0;
    int available = 0, helper_state = 0, model_up = 0, error = 0;
    bool valid = false;
};
template<class T> bool number(std::string_view text, T& value) {
    const auto result = std::from_chars(text.data(), text.data()+text.size(), value);
    return result.ec == std::errc{} && result.ptr == text.data()+text.size();
}
inline State parse(std::string_view text) {
    State state;
    if (text.size() > 4096) return state;
    std::array<bool, Count+6> seen{};
    while (!text.empty()) {
        const auto end = text.find('\n');
        auto line = text.substr(0, end);
        text = end == text.npos ? std::string_view{} : text.substr(end+1);
        const auto equal = line.find('=');
        if (equal == line.npos || !equal) return {};
        const auto key = line.substr(0,equal), value = line.substr(equal+1);
        int slot = -1;
        for (int i=0;i<Count;++i) if (key==specs[i].key) slot=i;
        if (slot>=0) {
            int v;
            if (!number(value,v) || v<specs[slot].lo || v>specs[slot].hi) return {};
            state.values[slot]=v;
        } else {
            constexpr const char* names[] = {"protocol","ack","available","helper_state","model_up","error"};
            for (int i=0;i<6;++i) if (key==names[i]) slot=Count+i;
            if (slot<0) return {};
            uint64_t v;
            if (!number(value,v)) return {};
            switch (slot-Count) {
            case 0: if (v!=1) return {}; break;
            case 1: state.ack=v; break;
            case 2: if(v>1)return {};state.available=int(v);break;
            case 3: if(v>16)return {};state.helper_state=int(v);break;
            case 4: if(v>1)return {};state.model_up=int(v);break;
            case 5: if(v>1)return {};state.error=int(v);break;
            }
        }
        if (seen[slot]) return {};
        seen[slot]=true;
    }
    for (bool found:seen) if(!found)return {};
    state.valid=true;
    return state;
}
inline std::string request(uint64_t sequence, const std::array<int,Count>& values, bool reset=false) {
    if (!sequence || (reset && values!=defaults)) return {};
    std::string text="protocol=1\nsequence="+std::to_string(sequence)+"\n";
    for(int i=0;i<Count;++i) {
        if(values[i]<specs[i].lo || values[i]>specs[i].hi)return {};
        text+=std::string(specs[i].key)+"="+std::to_string(values[i])+"\n";
    }
    if(reset)text+="reset=1\n";
    return text;
}
inline bool replace(const std::filesystem::path& path, const std::string& text) {
    auto temporary=path;temporary+=".native.tmp";
    { std::ofstream file(temporary,std::ios::binary|std::ios::trunc);
      if(!file || !file.write(text.data(),std::streamsize(text.size())) || !file.flush())return false; }
#ifdef _WIN32
    return MoveFileExW(temporary.c_str(),path.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)!=0;
#else
    std::error_code error;std::filesystem::rename(temporary,path,error);return !error;
#endif
}
inline State read(const std::filesystem::path& path) {
    std::ifstream file(path,std::ios::binary);char bytes[4097];
    if(!file)return {};
    file.read(bytes,sizeof bytes);
    if(file.bad() || file.gcount()>4096)return {};
    State state=parse(std::string_view(bytes,size_t(file.gcount())));
    std::error_code error;
    const auto stamp=std::filesystem::last_write_time(path,error);
    if(error || std::filesystem::file_time_type::clock::now()-stamp>std::chrono::seconds(5))state.available=0;
    return state;
}
class Client {
    std::filesystem::path directory_;
    std::thread thread_;
    std::mutex mutex_;
    std::condition_variable wake_;
    bool stop_=false, open_=false;
    std::string outgoing_;
    State observed_;
    uint64_t revision_=0, consumed_=0, sequence_=0, poll_=0;
    void loop() {
        auto next=std::chrono::steady_clock::now();
        for(;;) {
            std::string outgoing;bool open;
            { std::unique_lock lock(mutex_);
              wake_.wait_until(lock,next,[&]{return stop_ || !outgoing_.empty();});
              if(stop_)return;
              open=open_;outgoing.swap(outgoing_); }
            if(open || !outgoing.empty()) {
                bool ok=outgoing.empty() || replace(directory_/"request",outgoing);
                ok=replace(directory_/"poll",std::to_string(++poll_)+"\n") && ok;
                State state=read(directory_/"state");
                if(!ok)state.available=0,state.error=1;
                { std::lock_guard lock(mutex_);observed_=state;++revision_; }
            }
            next=std::chrono::steady_clock::now()+std::chrono::milliseconds(500);
        }
    }
    bool submit(const std::array<int,Count>& next, bool reset=false) {
        if(!available() || sequence_==UINT64_MAX)return false;
        const auto text=request(sequence_+1,next,reset);
        if(text.empty())return false;
        {std::lock_guard lock(mutex_);outgoing_=text;++sequence_;values=next;}
        wake_.notify_one();return true;
    }
public:
    std::array<int,Count> values{};
    State state;
    int advanced=0, status_value=0;
    explicit Client(const char* directory=nullptr) {
        if(directory && *directory) {
            try {
                auto path=std::filesystem::path(reinterpret_cast<const char8_t*>(directory));
                if(path.is_absolute())directory_=std::move(path);
            } catch(const std::filesystem::filesystem_error&) { /* invalid UTF-8 path: no session controls */ }
        }
        for(int i=0;i<Count;++i)values[i]=specs[i].lo;
    }
    ~Client() {
        {std::lock_guard lock(mutex_);stop_=true;}wake_.notify_one();
        if(thread_.joinable())thread_.join();
    }
    bool configured() const {return !directory_.empty();}
    int setting(const int* value) const {for(int i=0;i<Count;++i)if(value==&values[i])return i;return -1;}
    bool available() const {return state.valid && state.available;}
    bool pending() const {return sequence_>state.ack;}
    bool tick(bool open) {
        if(!configured())return false;
        if(open && !thread_.joinable()) {
            try { thread_=std::thread([this]{loop();}); }
            catch(const std::system_error&) {state.valid=true;state.available=0;state.error=1;return true;}
        }
        std::unique_lock lock(mutex_,std::try_to_lock);
        if(!lock)return false;
        open_=open;
        if(consumed_==revision_)return false;
        consumed_=revision_;state=observed_;
        if(state.valid && state.ack>=sequence_)values=state.values,sequence_=state.ack;
        return true;
    }
    bool set(int index,int value) {
        if(index<0 || index>=Count)return false;
        auto next=values;next[index]=value;
        return submit(next);
    }
    bool can_reset() const {return available() && !pending() && sequence_!=UINT64_MAX;}
    bool reset() {return can_reset() && submit(defaults,true);}
    const char* status() const {
        if(!state.valid)return "Connecting...";
        if(!state.available)return "Unavailable";
        if(state.error)return "Change failed";
        if(pending())return "Applying...";
        if(!values[Enabled])return "Off";
        return state.model_up ? "Active" : "Starting model...";
    }
};
} // namespace mkwvk::dlss5_controls
