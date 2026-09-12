// Compile the actual firmware with test-only device stand-ins.
// This exercises control flow, not SPI timings, RF, or electrical behavior.
#include <cassert>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>
#include "../firmware/src/main.cpp"

static void issue(const char* text) {
  std::vector<char> line(text,text+std::strlen(text)+1);
  command(line.data());
}
static void resetRuntime(bool eraseSaved=true) {
  configured=armed=adcEnabled=initialized=false;
  frequency=0; nodeId=1; bootId=sequenceNumber=armedAt=lastTx=lastStatus=rxStarted=0;
  received=false; state="unconfigured";
  mockNow=0; mockAdc=2048; mockGdo=LOW;
  Serial.input.clear(); Serial.output.clear();
  radio.beginResult=radio.txResult=radio.readResult=radio.rxResult=0;
  radio.transmissions.clear(); radio.incoming.clear(); radio.starts=0; radio.idleCalls=0;
  if(eraseSaved) mockSaved.clear();
}
static void queue(const std::string& text) {
  for(unsigned char c:text) Serial.input.push_back(c);
  while(Serial.available()) serialCommands();
}

int main() {
  resetRuntime(); setup();
  assert(!configured && !armed && frequency==0);
  issue("TX ARM");
  mockNow=10000; loop();
  assert(radio.transmissions.empty());
  issue("FREQ 433.5"); // A numeric fixture; the mock cannot radiate.
  assert(configured && !armed);
  mockNow=12000; loop();
  assert(radio.transmissions.empty());

#if PIXELLINK_TX
  issue("TX ARM");
  loop();
  assert(armed && radio.transmissions.size()==1);
  pixellink::Telemetry decoded{};
  auto sent=radio.transmissions.back();
  assert(pixellink::decode(sent.data(),sent.size(),decoded));
  assert(decoded.flags==0 && decoded.adc_raw==65535 && decoded.node_id==1);
  assert(decoded.boot_id==0x12345678u);
  const auto count=radio.transmissions.size();
  mockNow=armedAt+leaseMs; loop();
  assert(!armed && radio.transmissions.size()==count);

  mockNow=0xfffffff0u;
  issue("TX ARM");
  mockNow=uint32_t(armedAt+leaseMs-2); loop();
  assert(armed);
  mockNow=uint32_t(armedAt+leaseMs); loop();
  assert(!armed);

  issue("TX ARM"); issue("NODE 42");
  assert(!armed && nodeId==42);
  issue("TX ARM"); issue("ADC ON");
  assert(!armed && adcEnabled);
  issue("TX ARM"); mockNow+=1000; loop();
  sent=radio.transmissions.back();
  assert(pixellink::decode(sent.data(),sent.size(),decoded));
  assert(decoded.flags==1 && decoded.adc_raw==2048 && decoded.node_id==42);

  issue("SAVE");
  assert(!mockSaved.empty());
  resetRuntime(false); setup();
  assert(configured && frequency==433.5f && nodeId==42);
  assert(!armed && !adcEnabled); // Neither is restored from NVS.

  issue("TX ARM"); issue("FREQ nan");
  assert(!armed && !configured);
  issue("FREQ 433.5"); issue("TX ARM");
  radio.txResult=-7; mockNow+=1000; loop();
  assert(!armed && !configured);
  radio.txResult=0;
  issue("FREQ 433.5"); issue("TX ARM");
  radio.beginResult=-2; issue("FREQ 433.5");
  assert(!armed && !configured);
  radio.beginResult=0;
  issue("FREQ 433.5");
  queue("TX ARM"+std::string(100,' ')+'\n');
  assert(!armed);
  queue(std::string("TX ARM\0",7)+"\n");
  assert(!armed);
  queue("TX ARM\r\n");
  assert(armed);
  issue("CLEAR");
  assert(!armed && !configured && mockSaved.empty());
  std::cout << "TX control: boot/configuration gates, lease/wrap, payload, ADC/NODE disarm, NVS, errors, malformed commands passed\n";
#else
  assert(std::strcmp(state,"receiving")==0);
  issue("TX ARM"); issue("NODE 42"); issue("ADC ON");
  mockNow=13000; loop();
  assert(!armed && !adcEnabled && nodeId==1 && radio.transmissions.empty());
  pixellink::Telemetry payload{1,7,12,3,3000,2048};
  radio.incoming.resize(pixellink::kFrameSize);
  assert(pixellink::encode(payload,radio.incoming.data(),radio.incoming.size()));
  Serial.output.clear(); onReceive(); loop();
  assert(Serial.output.find("\"type\":\"packet\"")!=std::string::npos);
  assert(Serial.output.find("\"rssi_dbm\":-61.5")!=std::string::npos);
  Serial.output.clear(); radio.incoming[24]^=1; onReceive(); loop();
  assert(Serial.output.find("\"type\":\"packet\"")==std::string::npos);
  assert(Serial.output.find("invalid_application_frame")!=std::string::npos);
  Serial.output.clear(); radio.readResult=-7; onReceive(); loop();
  assert(Serial.output.find("\"type\":\"packet\"")==std::string::npos);
  issue("SAVE"); resetRuntime(false); setup();
  assert(configured && !armed && !adcEnabled);
  issue("CLEAR");
  assert(!configured && !armed && mockSaved.empty());
  assert(radio.transmissions.empty());
  std::cout << "RX control: no TX, role gates, valid/corrupt packet forwarding, cached metadata, saved configuration passed\n";
#endif
}
