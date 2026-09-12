#pragma once
#include <stddef.h>
#include <stdint.h>

namespace pixellink {
constexpr size_t kFrameSize = 28;
struct Telemetry {
  uint8_t flags;
  uint16_t node_id;
  uint32_t boot_id, sequence, uptime_ms;
  uint16_t adc_raw;
};
inline uint32_t crc32(const uint8_t* p, size_t n) {
  uint32_t c = 0xffffffffu;
  while (n--) {
    c ^= *p++;
    for (unsigned i = 0; i < 8; ++i) c = (c >> 1) ^ (0xedb88320u & (0u - (c & 1u)));
  }
  return c ^ 0xffffffffu;
}
inline void put16(uint8_t* p, uint16_t v) { p[0] = v; p[1] = v >> 8; }
inline void put32(uint8_t* p, uint32_t v) { for (unsigned i=0;i<4;++i) p[i] = v >> (8*i); }
inline uint16_t get16(const uint8_t* p) { return uint16_t(p[0]) | (uint16_t(p[1]) << 8); }
inline uint32_t get32(const uint8_t* p) {
  uint32_t v=0; for (unsigned i=0;i<4;++i) v |= uint32_t(p[i]) << (8*i); return v;
}
inline bool valid(const Telemetry& t) {
  return t.node_id != 0 && !(t.flags & ~1u) &&
    ((t.flags & 1u) ? t.adc_raw <= 4095 : t.adc_raw == 65535);
}
inline bool encode(const Telemetry& t, uint8_t* out, size_t n) {
  if (!out || n != kFrameSize || !valid(t)) return false;
  out[0]='P'; out[1]='X'; out[2]='L'; out[3]='T'; out[4]=1; out[5]=t.flags;
  put16(out+6,t.node_id); put32(out+8,t.boot_id); put32(out+12,t.sequence);
  put32(out+16,t.uptime_ms); put16(out+20,t.adc_raw); put16(out+22,0);
  put32(out+24,crc32(out,24)); return true;
}
inline bool decode(const uint8_t* in, size_t n, Telemetry& out) {
  if (!in || n != kFrameSize || in[0]!='P' || in[1]!='X' || in[2]!='L' ||
      in[3]!='T' || in[4]!=1 || get16(in+22)!=0 || get32(in+24)!=crc32(in,24)) return false;
  Telemetry t{in[5],get16(in+6),get32(in+8),get32(in+12),get32(in+16),get16(in+20)};
  if (!valid(t)) return false;
  out=t; return true;
}
} // namespace pixellink
