#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <vector>
// A deliberately tiny NVS stand-in: this firmware stores one configuration blob.
inline std::vector<uint8_t> mockSaved;
class Preferences {
 public:
  bool begin(const char*,bool readOnly) { return !readOnly || !mockSaved.empty(); }
  void end() {}
  size_t putBytes(const char*,const void* bytes,size_t size) {
    const auto* p=static_cast<const uint8_t*>(bytes); mockSaved.assign(p,p+size); return size;
  }
  size_t getBytesLength(const char*) { return mockSaved.size(); }
  size_t getBytes(const char*,void* target,size_t size) {
    if(size<mockSaved.size()) return 0;
    std::memcpy(target,mockSaved.data(),mockSaved.size()); return mockSaved.size();
  }
  bool clear() { mockSaved.clear(); return true; }
};
