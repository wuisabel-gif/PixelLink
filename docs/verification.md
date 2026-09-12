# Hardware migration verification

These checks validate software and firmware builds. They do not establish RF
range, electrical correctness, actual packet delivery through antennas, or
sensor accuracy. No board was flashed and no physical radio was exercised.

## Checks run

| Check | Result |
| --- | --- |
| Python discovery, including legacy regression tests | 59 tests passed |
| Node application-logic tests, legacy and hardware dashboards | 7 tests passed |
| Native C++ codec with independent golden frames | 3 suites passed with ASan/UBSan |
| Actual firmware control code with mock peripherals | TX and RX passed; also manually run with ASan/UBSan |
| PlatformIO transmitter build, `esp32dev` | Passed |
| PlatformIO receiver build, `esp32dev` | Passed |
| Source distribution and wheel | Built; required assets/firmware/tests included, caches excluded |
| Installed wheel outside the source tree | Hardware routes/assets served; no-device state stayed empty |

The Python tests include an operating-system pseudo-terminal: fixture bytes go
through pyserial, the real serial-reader thread, packet validation, and the HTTP
API. It exercises fragmented input, ROM-style chatter, oversized lines, exact
recording, and confirms the host sends no serial commands. Separate tests check
reconnect, logging limits, duplicate/out-of-order sequence values, boot sessions,
wrap, malformed numbers, and bounded storage.

The native firmware control tests compile `firmware/src/main.cpp` against fake
Arduino, RadioLib, and Preferences headers. They verify no unconfigured TX,
explicit arming, lease expiry including timer wrap, disarming after configuration
or radio errors, ADC/node changes, saved configuration without saved ARM/ADC,
and that the receiver role never calls transmit. These mocks intentionally do
not pretend to verify real RadioLib SPI behavior or an ESP32's electrical timing.

The codec suites use the same header as the board builds, with independently
produced bytes from `tests/fixtures/telemetry_vectors.json`. They check exact
encoding, every single-bit corruption, lengths, and schema validation even if a
bad field's CRC is recomputed.

## Reproduce from the repository root

```sh
source .venv/bin/activate
python -m unittest discover -s tests -v
node --test tests/frontend.test.cjs tests/telemetry_frontend.test.cjs
python firmware/test/run_native.py
pio run -d firmware -e transmitter -e receiver
```

Node tests execute JavaScript with small DOM/canvas stand-ins and real HTTP
services; they are not browser-layout tests. A native C++17 compiler is needed
for firmware control tests; the standalone codec runner also needs sanitizer
support. The Python suite skips control compilation if no native compiler is
available and skips pseudo-terminal tests where the OS/pyserial is unavailable.

Firmware dependencies are pinned in `firmware/platformio.ini`. Local successful
builds used Espressif32 6.12.0, RadioLib 7.7.1, and the classic ESP32 DevKit target.
Board build outputs are under `firmware/.pio/build/{transmitter,receiver}/` and
are excluded from version control and source distributions.

## Physical acceptance checklist — not yet performed

1. Verify board/module pin labels, 3.3 V wiring, common ground, and matched antennas.
2. Verify boot without saved settings is unconfigured and never transmits.
3. Choose an authorized matching frequency and configure receiver and transmitter.
4. Verify receiver SAVE survives closing/reopening USB and an actual board reset.
5. Explicitly arm TX; confirm real uptime advances and node/boot/sequence fields agree.
6. Verify manual DISARM and the 60-second lease stop transmissions on the real hardware.
7. Verify mismatched frequency stops packet reception while USB remains connected.
8. Reset the transmitter and verify a new boot session appears without automatic arming.
9. Only after proper conditioning, enable ADC and compare readings with known inputs.
10. Record observed packet delivery under stated antenna, distance, power, and environment
    conditions. Do not interpret sequence gaps as exclusively RF loss or RSSI as distance.

A receive watchdog can drop a packet in progress when recovering after 10,007 ms
without an interrupt. It is deliberately not synchronized to the one-second TX
interval, but its behavior still needs evaluation on physical hardware.
