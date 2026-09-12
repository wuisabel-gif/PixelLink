#include "telemetry_codec.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <cstdlib>
using namespace pixellink;
int main(int argc, char** argv) {
  assert(crc32(reinterpret_cast<const uint8_t*>("123456789"),9)==0xcbf43926u);
  if(argc==8) {
    Telemetry t{static_cast<uint8_t>(strtoul(argv[1],nullptr,10)),
      static_cast<uint16_t>(strtoul(argv[2],nullptr,10)),
      static_cast<uint32_t>(strtoull(argv[3],nullptr,10)),
      static_cast<uint32_t>(strtoull(argv[4],nullptr,10)),
      static_cast<uint32_t>(strtoull(argv[5],nullptr,10)),
      static_cast<uint16_t>(strtoul(argv[6],nullptr,10))};
    uint8_t frame[28]; assert(encode(t,frame,28));
    char hex[57]; for(unsigned i=0;i<28;++i) std::snprintf(hex+2*i,3,"%02x",frame[i]);
    assert(std::strcmp(hex,argv[7])==0);
    Telemetry decoded{}; assert(decode(frame,28,decoded));
    assert(decoded.flags==t.flags && decoded.node_id==t.node_id && decoded.boot_id==t.boot_id &&
      decoded.sequence==t.sequence && decoded.uptime_ms==t.uptime_ms && decoded.adc_raw==t.adc_raw);
    // Every single bit error must fail; no mutation reaches the output.
    for(unsigned i=0;i<28;++i) for(unsigned bit=0;bit<8;++bit) {
      frame[i]^=1u<<bit; assert(!decode(frame,28,decoded)); frame[i]^=1u<<bit;
    }
    assert(!decode(frame,27,decoded)); assert(!decode(frame,29,decoded));
    // Invalid fields with recalculated CRC still must fail schema validation.
    const unsigned offsets[]={0,4,5,6,20,22};
    for(unsigned offset:offsets) {
      uint8_t bad[28]; std::memcpy(bad,frame,28);
      if(offset==6) put16(bad+6,0);
      else if(offset==20) { bad[5]=1; put16(bad+20,4096); }
      else bad[offset]=0xff;
      put32(bad+24,crc32(bad,24)); assert(!decode(bad,28,decoded));
    }
    t.node_id=0; assert(!encode(t,frame,28));
    return 0;
  }
  std::fprintf(stderr,"Run via test/run_native.py\n"); return 2;
}
