#pragma once
// Test-only Arduino stand-in. Does not access a board or serial port.
#include <cstdint>
#include <cstdio>
#include <deque>
#include <string>
#include <vector>
#define IRAM_ATTR
#define OUTPUT 1
#define INPUT 0
#define HIGH 1
#define LOW 0
inline uint32_t mockNow = 0;
inline int mockAdc = 2048;
inline int mockGdo = LOW;
inline bool mockGdoInputConfigured = false;
inline uint32_t millis() { return mockNow; }
inline void delay(unsigned ms) { mockNow += ms; }
inline void pinMode(int pin, int mode) {
  if(pin==27) mockGdoInputConfigured=(mode==INPUT);
}
inline void digitalWrite(int, int) {}
inline int digitalRead(int) { return mockGdo; }
inline void analogReadResolution(int) {}
inline int analogRead(int) { return mockAdc; }
struct MockSerial {
  std::deque<unsigned char> input;
  std::string output;
  void begin(unsigned) {}
  int available() { return static_cast<int>(input.size()); }
  int read() { int value=input.front(); input.pop_front(); return value; }
  template<typename... A> int printf(const char* format, A... args) {
    char text[1024]; int n=std::snprintf(text,sizeof(text),format,args...);
    if(n>0) output.append(text,static_cast<size_t>(n)<sizeof(text)?n:sizeof(text)-1);
    return n;
  }
};
inline MockSerial Serial;
