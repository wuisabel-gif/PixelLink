#pragma once
// Test-only radio. Transmit stores bytes in memory; no RF or hardware access.
#include "Arduino.h"
#include <algorithm>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <vector>
#define RADIOLIB_NC 0xffffffffu
#define RADIOLIB_ERR_NONE 0
class Module { public: Module(int,int,uint32_t,int) {} };
class CC1101 {
 public:
  CC1101(Module* module) : module_(module) {}
  ~CC1101() { delete module_; }
  int16_t beginResult=0, txResult=0, readResult=0, rxResult=0;
  unsigned starts=0, idleCalls=0;
  std::vector<std::vector<uint8_t>> transmissions;
  std::vector<uint8_t> incoming;
  int16_t begin(float,float,float,float,int,int) { return beginResult; }
  int16_t setOOK(bool) { return 0; }
  int16_t setSyncWord(uint8_t,uint8_t,uint8_t,bool) { return 0; }
  int16_t variablePacketLengthMode(size_t) { return 0; }
  int16_t setCrcFiltering(bool) { return 0; }
  int16_t standby() { ++idleCalls; return 0; }
  int16_t startReceive() { ++starts; return rxResult; }
  int16_t finishReceive() { return 0; }
  void setPacketReceivedAction(void (*)()) {}
  int16_t transmit(uint8_t* p,size_t n) {
    assert(mockGdoInputConfigured && "GPIO27/GDO2 must be configured as INPUT before TX polling");
    transmissions.emplace_back(p,p+n); return txResult;
  }
  size_t getPacketLength() { return incoming.size(); }
  int16_t readData(uint8_t* out,size_t n) {
    if(n>incoming.size()) return -99;
    std::copy(incoming.begin(),incoming.begin()+n,out); return readResult;
  }
  float getRSSI() { return -61.5f; }
  uint8_t getLQI() { return 34; }
 private:
  Module* module_;
};
