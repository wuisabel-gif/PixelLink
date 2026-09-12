# ESP32 + CC1101 real telemetry

This firmware sends actual ESP32 `millis()` uptime and optionally a raw GPIO34
ADC reading. It does not generate images or simulated sensor values. Use two
ESP32 DevKit boards (`esp32dev`) and two matching CC1101 modules/antennas.
The application frame and USB JSON envelopes are specified in `protocol.md`.

## Wiring and electrical safety

Power off before wiring. **CC1101 supply and signal logic are 3.3 V ONLY: never
connect the module to 5 V, VIN, or 5 V logic.** Share ground. Use short SPI wires,
a stable 3.3 V supply with adequate current capacity, and local decoupling near
the radio. Identify the actual module pin labels; module connector orders vary.

| CC1101 signal | ESP32 DevKit GPIO |
| --- | --- |
| VCC | regulated 3V3 (not VIN/5V) |
| GND | GND |
| SCK | 18 |
| SO / MISO | 19 |
| SI / MOSI | 23 |
| CSn / NSS | 5 |
| GDO0 | 4 |
| GDO2 | 27 |

RadioLib construction is `Module(5, 4, RADIOLIB_NC, 27)`; there is no reset pin.
GDO0 is the receive interrupt. GDO2 is also required for RadioLib's transmit
completion handling. GPIO5 is an ESP32 strapping pin: do not externally force
it to an incompatible level during reset. Verify board/module-specific wiring.

**Attach a correctly matched antenna before arming.** Module RF matching,
antenna band, and local authorization must match the chosen frequency. Driver
acceptance is not permission to transmit. No frequency is supplied by default.
The firmware accepts only the RadioLib CC1101 subbands 300–348, 387–464, and
779–928 MHz; many frequencies in those ranges are not permitted for your use.
The requested 0 dBm setting and low packet rate do not establish regulatory
compliance, certified output power, duty cycle compliance, or spectral purity.

Optional ADC: connect a real, conditioned signal to GPIO34 and common ground.
Never apply 5 V, negative voltage, or a signal exceeding the ESP32's 3.3 V rail.
Use suitable protection/division where required; an unconnected enabled input
will float. Firmware selects 12-bit readings (0–4095); this is **raw ADC**, not
voltage, temperature, or battery percentage. No calibration is implied. ADC is
disabled on every boot, and disabled frames carry the sentinel 65535.

## Build, test, and flash

PlatformIO Core is required; the initial build may download toolchains and
libraries. Dependencies are pinned to Espressif32 platform 6.12.0 and
`jgromes/RadioLib@7.7.1`. The version was verified against the official RadioLib
tagged `library.properties` (not inferred from an example).

From the repository root:

```sh
pio run -d firmware -e transmitter -e receiver
python3 firmware/test/run_native.py
```

Native tests use a local C++11 compiler (`CXX` may override `c++`) with Address
and Undefined Behavior sanitizers. They compile the exact header-only codec
used on-device, compare all three independent repository golden fixtures,
round-trip fields, and reject wrong lengths, single-bit corruption, and invalid
schema fields even with a recomputed CRC. Parent host tests additionally mock
firmware control behavior; neither suite substitutes for RF tests.

**Only with the device owner's explicit authority**, flash one role to each
board, replacing `PORT` with that board's serial port:

```sh
pio run -d firmware -e receiver -t upload --upload-port PORT
pio run -d firmware -e transmitter -t upload --upload-port PORT
pio device monitor -b 115200 -p PORT
```

These are instructions, not actions performed during implementation. Do not
flash over USB or over the air, or authorize a transmission, without permission.
There is no over-the-air updater in this project. `PIXELLINK_NODE_ID` is a
compile-time override (1–65535, default 1); runtime `NODE` is usually easier.

## Serial commands and safe startup

115200 baud. Commands are case-sensitive ASCII, terminated with LF or CRLF,
maximum 80 characters excluding LF (79 plus CR for CRLF). Overlong/non-ASCII
lines are discarded through the next newline, producing an error. Partial
lines do not execute. Work per loop is bounded; constant input cannot starve
the TX lease check. Output is newline-delimited JSON, plus possible ESP32 ROM
boot chatter. Status is emitted at boot, after state changes, on request, and
every five seconds, including role, state, frequency, node ID, ADC enable, and
remaining lease milliseconds. Negative driver/custom error codes are diagnostic,
not telemetry.

| Command | Behavior |
| --- | --- |
| `FREQ <MHz>` | Both roles: decimal number only, no units/sign/exponent. Disarms first; success installs the entire profile, RX starts receiving. Invalid input or any configuration error unconfigures and disarms. Does not save. |
| `TX ARM` | TX only, requires successful configuration. Starts/renews a 60-second lease. At most one attempt per second; no automatic renewal. |
| `TX DISARM` | Stops future TX attempts immediately after any already-running bounded radio call. RX accepts it harmlessly and continues receiving. |
| `STATUS` | Reports current settings; no configuration change. |
| `NODE <id>` | TX only, decimal 1–65535. Valid change disarms; does not reset boot ID/sequence or automatically save. |
| `ADC ON` / `ADC OFF` | TX only. Disarms; enable/disable the real GPIO34 sample. Not persisted. |
| `SAVE` | Requires configuration. Explicitly saves frequency and node ID together to NVS; does not save or change ARM/ADC. |
| `CLEAR` | Disarms, stops radio, clears saved settings, sets frequency to zero, resets node to build default and ADC off. NVS errors are reported. |

A new device starts unconfigured: **no radio initialization at a default
frequency and no transmission**. With explicitly saved settings, reboot
validates/restores the frequency and node; RX resumes receiving and TX remains
disarmed. Failed restore/configuration never enables TX. Commands and status
are not authenticated: physical USB access is trusted.

Receiver workflow: issue `FREQ <your-authorized-MHz>`, verify receiving status,
issue `SAVE`, close the serial monitor, then open the live host dashboard on
that port. A port-open reset will restore the explicitly saved RX settings.
Only one program can own the serial port at a time. `SAVE` is optional when
settings need only survive the current boot. `CLEAR` removes persistence.

Transmitter workflow: choose `FREQ <your-authorized-MHz>`, optionally `NODE 42`
and `ADC ON`, inspect `STATUS`, then explicitly issue `TX ARM`. The lease
expires after 60 seconds and is safe across `millis()` wrap. Renew manually
with another `TX ARM` only when continued transmission is authorized. Renewal
does not bypass the one-second interval. Frequency/configuration changes,
valid NODE/ADC commands, boot, CLEAR, or a radio transmission error disarm.
There are no retries, ACKs, automatic pairing, or automatic arming. Boot ID
uses ESP32 `esp_random()` once per boot; sequence advances per attempted TX
(including failed radio attempts) and wraps at uint32. Uptime is sampled using
`millis()`; no fabricated data enter the live path.

## RF profile and receive handling

2-FSK, 38.4 kbit/s, 20 kHz deviation, 135 kHz RX bandwidth, 16-bit preamble,
sync D3 91 with no tolerated sync errors, variable-length packets capped at
28 bytes, hardware CRC enabled, requested TX power 0 dBm. Radio registers
quantize nominal settings; both devices use identical settings/library.
Every configuration call is checked; failure leaves TX disarmed/unconfigured.

RX uses interrupt-driven `startReceive()` rather than blocking indefinitely.
It emits a packet only after `readData()` reports success, exact length 28,
and the shared codec validates magic/version/flags/node/ADC/reserved/application
CRC32. Hardware CRC errors and malformed payloads are diagnostic-only. RSSI and
LQI come from the radio's appended packet status cached by `readData()`, before
restarting RX, not an invented signal-quality estimate. Raw LQI is 0–127.
A 10007 ms no-interrupt recovery restarts RX to clear a stuck/incomplete FIFO;
this may discard a packet in progress, but avoids the TX's one-second phase.
RadioLib's TX call uses bounded start/end timeouts; serial commands resume
after that call. RX code contains no call to transmit or startTransmit.

Official API source references used for implementation:

```text
https://raw.githubusercontent.com/jgromes/RadioLib/7.7.1/library.properties
https://raw.githubusercontent.com/jgromes/RadioLib/7.7.1/src/modules/CC1101/CC1101.h
https://raw.githubusercontent.com/jgromes/RadioLib/7.7.1/src/modules/CC1101/CC1101.cpp
https://github.com/jgromes/RadioLib/tree/7.7.1/examples/CC1101
```

## Validation boundary

Both PlatformIO roles were built and native golden-vector tests were run.
No ESP32 was flashed, no RF transmission was authorized/performed, and no
physical wiring, RF interoperability, receiver sensitivity, antenna match,
power output, ADC accuracy, or regulatory compliance was physically verified.
Before deployment, an authorized operator must check safe boot/no-TX, lease
expiry, wrong-frequency/no-packet behavior, real uptime/ADC readings, reboot
session separation, USB reconnect/SAVE behavior, and packet capture against the
protocol on the actual matched hardware.
