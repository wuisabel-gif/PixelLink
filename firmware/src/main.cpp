#include <Arduino.h>
#include <SPI.h>
#include <RadioLib.h>
#include <Preferences.h>
#include <esp_system.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include "telemetry_codec.h"

#ifndef PIXELLINK_TX
#error Select transmitter or receiver environment
#endif
#ifndef PIXELLINK_NODE_ID
#define PIXELLINK_NODE_ID 1
#endif
static_assert(PIXELLINK_NODE_ID >= 1 && PIXELLINK_NODE_ID <= 65535, "Invalid node ID");
CC1101 radio = new Module(5, 4, RADIOLIB_NC, 27);
constexpr const char* role = PIXELLINK_TX ? "tx" : "rx";
constexpr uint32_t leaseMs = 60000;
bool configured=false, armed=false, adcEnabled=false, initialized=false;
float frequency=0;
uint16_t nodeId=PIXELLINK_NODE_ID;
uint32_t bootId=0, sequenceNumber=0, armedAt=0, lastTx=0, lastStatus=0, rxStarted=0;
volatile bool received=false;
const char* state="unconfigured";
void IRAM_ATTR onReceive() { received=true; }
void error(int code, const char* message) {
  // Messages are constant strings, never user input.
  Serial.printf("{\"type\":\"error\",\"code\":%d,\"message\":\"%s\"}\n",code,message);
}
void status() {
  const uint32_t elapsed=millis()-armedAt;
  Serial.printf("{\"type\":\"status\",\"role\":\"%s\",\"state\":\"%s\",\"frequency_mhz\":%.6f,\"node_id\":%u,\"adc_enabled\":%s,\"lease_remaining_ms\":%lu}\n",
    role,state,frequency,nodeId,adcEnabled?"true":"false",
    static_cast<unsigned long>(armed && elapsed<leaseMs ? leaseMs-elapsed : 0));
}
void disarm() { armed=false; if(configured) state=PIXELLINK_TX?"disarmed":"receiving"; }
void fail(int code, const char* message) {
  armed=false; configured=false; frequency=0; state="error";
  if(initialized) radio.standby();
  error(code,message); status();
}
bool legalDriverBand(float f) {
  return isfinite(f) && ((f>=300 && f<=348)||(f>=387 && f<=464)||(f>=779 && f<=928));
}
bool startRx() {
  received=false;
  int16_t rc=radio.startReceive();
  if(rc!=RADIOLIB_ERR_NONE) { fail(rc,"start_receive_failed"); return false; }
  rxStarted=millis(); state="receiving"; return true;
}
bool configure(float f) {
  disarm(); configured=false; frequency=0; state="unconfigured";
  if(initialized) radio.standby();
  if(!legalDriverBand(f)) { fail(-1001,"invalid_frequency"); return false; }
  // begin() selects 2-FSK; no radio initialization occurs until an explicit
  // FREQ command or validated, explicitly saved NVS settings are present.
  initialized=true;
  int16_t rc=radio.begin(f,38.4,20.0,135.0,0,16);
  if(rc==RADIOLIB_ERR_NONE) rc=radio.setOOK(false);
  if(rc==RADIOLIB_ERR_NONE) rc=radio.setSyncWord(0xD3,0x91,0,false);
  if(rc==RADIOLIB_ERR_NONE) rc=radio.variablePacketLengthMode(pixellink::kFrameSize);
  if(rc==RADIOLIB_ERR_NONE) rc=radio.setCrcFiltering(true);
  if(rc!=RADIOLIB_ERR_NONE) { fail(rc,"radio_configuration_failed"); return false; }
  configured=true; frequency=f; state=PIXELLINK_TX?"disarmed":"ready";
#if !PIXELLINK_TX
  radio.setPacketReceivedAction(onReceive);
  if(!startRx()) return false;
#endif
  return true;
}
// Single NVS blob avoids mixing frequency and node across interrupted saves.
struct Saved { uint32_t magic; float frequency; uint16_t node; uint16_t reserved; };
void save() {
  if(!configured) { error(-1002,"configure_before_save"); return; }
  Preferences p;
  if(!p.begin("pixellink",false)) { error(-1003,"nvs_open_failed"); return; }
  Saved s{0x50584c31,frequency,nodeId,0};
  bool ok=p.putBytes("config",&s,sizeof(s))==sizeof(s); p.end();
  if(!ok) error(-1004,"nvs_save_failed");
}
void restore() {
  Preferences p;
  if(!p.begin("pixellink",true)) return; // virgin devices have no namespace
  Saved s{};
  bool ok=p.getBytesLength("config")==sizeof(s) && p.getBytes("config",&s,sizeof(s))==sizeof(s);
  p.end();
  if(!ok) return;
  if(s.magic!=0x50584c31 || !s.node || s.reserved || !legalDriverBand(s.frequency)) {
    error(-1005,"invalid_saved_settings"); return;
  }
  nodeId=s.node; configure(s.frequency); // never restore ARM or ADC
}
void command(char* line) {
  if(strcmp(line,"STATUS")==0) { status(); return; }
  if(strcmp(line,"TX DISARM")==0) { disarm(); status(); return; }
  if(strncmp(line,"FREQ ",5)==0) {
    char* end=nullptr; float f=strtof(line+5,&end);
    // Reject signs, exponent notation, whitespace, NaN, and trailing text.
    bool syntax=line[5]!=0; unsigned dots=0;
    for(char* p=line+5;*p;++p) if(*p=='.') { if(++dots>1) syntax=false; }
      else if(*p<'0'||*p>'9') syntax=false;
    if(!syntax || end==line+5 || *end) { fail(-1001,"invalid_frequency"); return; }
    configure(f); status(); return;
  }
  if(strcmp(line,"SAVE")==0) { save(); status(); return; }
  if(strcmp(line,"CLEAR")==0) {
    disarm(); if(initialized) radio.standby();
    configured=false; frequency=0; state="unconfigured"; nodeId=PIXELLINK_NODE_ID; adcEnabled=false;
    Preferences p;
    if(p.begin("pixellink",false)) { if(!p.clear()) error(-1006,"nvs_clear_failed"); p.end(); }
    else error(-1003,"nvs_open_failed");
    status(); return;
  }
#if PIXELLINK_TX
  if(strcmp(line,"TX ARM")==0) {
    if(!configured) { error(-1002,"configure_before_arm"); return; }
    armed=true; armedAt=millis(); state="armed"; status(); return;
  }
  if(strncmp(line,"NODE ",5)==0) {
    uint32_t n=0; bool ok=line[5]!=0;
    for(char* p=line+5;*p;++p) {
      if(*p<'0'||*p>'9'||n>65535) { ok=false; break; }
      n=n*10+(*p-'0');
    }
    if(!ok||n==0||n>65535) { error(-1007,"invalid_node"); return; }
    disarm(); nodeId=static_cast<uint16_t>(n); status(); return;
  }
  if(strcmp(line,"ADC ON")==0 || strcmp(line,"ADC OFF")==0) {
    disarm(); adcEnabled=strcmp(line,"ADC ON")==0; status(); return;
  }
#endif
  error(-1008,"unknown_or_role_forbidden_command");
}
void serialCommands() {
  static char line[81]; static size_t used=0; static bool rejected=false;
  // Bounded per loop so a continuous USB writer cannot starve lease expiry/RX.
  for(unsigned budget=0;budget<128 && Serial.available();++budget) {
    int c=Serial.read();
    if(c=='\n') {
      if(rejected) error(-1009,"invalid_or_overlong_command");
      else { if(used && line[used-1]=='\r') --used; line[used]=0; if(used) command(line); }
      used=0; rejected=false;
    } else if(!rejected) {
      if(used>=80 || (c!='\r' && (c<32 || c>126))) rejected=true;
      else line[used++]=static_cast<char>(c);
    }
  }
}
void setup() {
  Serial.begin(115200);
  pinMode(5,OUTPUT); digitalWrite(5,HIGH);
  // RadioLib polls GDO2 during blocking TX but begin() initializes only GDO0.
  // ESP32 needs its input buffer enabled explicitly before digitalRead works.
  pinMode(27,INPUT);
  SPI.begin(18,19,23,5);
  bootId=esp_random();
#if PIXELLINK_TX
  analogReadResolution(12); pinMode(34,INPUT);
#endif
  restore(); status();
}
void loop() {
  if(armed && uint32_t(millis()-armedAt)>=leaseMs) { disarm(); status(); }
  serialCommands();
  uint32_t now=millis();
#if PIXELLINK_TX
  if(armed && uint32_t(now-armedAt)>=leaseMs) { disarm(); status(); }
  if(configured && armed && uint32_t(now-lastTx)>=1000) {
    lastTx=now;
    pixellink::Telemetry t{static_cast<uint8_t>(adcEnabled?1:0),nodeId,bootId,
      sequenceNumber++,millis(),static_cast<uint16_t>(adcEnabled?analogRead(34):65535)};
    uint8_t frame[pixellink::kFrameSize];
    if(!pixellink::encode(t,frame,sizeof(frame))) { fail(-1010,"invalid_local_measurement"); }
    else {
      // RadioLib's transmit has bounded start/end timeouts; no retries/ACKs.
      int16_t rc=radio.transmit(frame,sizeof(frame));
      if(rc!=RADIOLIB_ERR_NONE) fail(rc,"transmit_failed");
    }
  }
#else
  if(configured && received) {
    received=false;
    const size_t len=radio.getPacketLength();
    // Drain complete bounded FIFO payload even for wrong lengths so status
    // bytes remain aligned. Packet mode caps valid incoming length at 28.
    uint8_t frame[64];
    if(len==0 || len>sizeof(frame)) {
      // readData resets the driver's cached packet length even for a bad
      // FIFO length; cap the destination and discard its status unconditionally.
      radio.readData(frame,sizeof(frame));
      error(-1011,"invalid_packet_length");
    } else {
      int16_t rc=radio.readData(frame,len);
      pixellink::Telemetry decoded{};
      if(rc!=RADIOLIB_ERR_NONE) error(rc,"receive_crc_or_radio_error");
      else if(len!=pixellink::kFrameSize) error(-1011,"invalid_packet_length");
      else if(!pixellink::decode(frame,len,decoded)) error(-1012,"invalid_application_frame");
      else {
        char hex[57]; const char* digits="0123456789abcdef";
        for(size_t i=0;i<len;++i) { hex[2*i]=digits[frame[i]>>4]; hex[2*i+1]=digits[frame[i]&15]; }
        hex[56]=0;
        float rssi=radio.getRSSI(); uint8_t lqi=radio.getLQI();
        if(isfinite(rssi) && lqi<=127)
          Serial.printf("{\"type\":\"packet\",\"frame\":\"%s\",\"rssi_dbm\":%.1f,\"lqi\":%u}\n",hex,rssi,lqi);
        else error(-1013,"invalid_radio_metadata");
      }
    }
    if(configured) startRx();
  }
  // Rare recovery of a stuck/incomplete FIFO. 10007 ms deliberately avoids
  // phase locking to the one-second transmitter. A recovery may lose one frame.
  if(configured && uint32_t(millis()-rxStarted)>=10007) startRx();
#endif
  if(uint32_t(now-lastStatus)>=5000) { lastStatus=now; status(); }
  delay(1);
}
