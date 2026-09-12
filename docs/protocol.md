# PixelLink hardware telemetry protocol v1

This protocol is for ESP32 + CC1101 telemetry, NOT the legacy image simulator.
RadioLib/CC1101 handle FSK modulation, synchronization and hardware packet CRC.
The host independently validates the application frame CRC before accepting data.

## RF application frame: 28 bytes

All multibyte integers are **little endian**. Python struct: `<4sBBHIIIHHI`.

| Offset | Bytes | Field |
| --- | ---: | --- |
| 0 | 4 | Magic: ASCII `PXLT` |
| 4 | 1 | Version: 1 |
| 5 | 1 | Flags: bit 0 = ADC sample valid; other bits must be zero |
| 6 | 2 | Node ID: 1–65535 |
| 8 | 4 | Boot ID: random uint32 generated on transmitter boot |
| 12 | 4 | Sequence: uint32, advances per attempted transmission, wraps |
| 16 | 4 | Transmitter uptime in milliseconds, uint32, wraps |
| 20 | 2 | ADC raw: 0–4095 if valid; otherwise exactly 65535 |
| 22 | 2 | Reserved: must be zero |
| 24 | 4 | CRC32/ISO-HDLC of bytes 0–23 (Python `zlib.crc32`) |

The boot ID separates transmitter restarts from sequence wrap. A node ID is
configured, not an authenticated identity. CRC detects corruption, not forgery.
ADC is optional, disabled by default, and must never be labeled temperature,
voltage, or battery percentage without a real sensor and calibration. Uptime is
always an actual ESP32 measurement. Do not use generated data in live mode.

## USB receiver stream

115200 baud, UTF-8 newline-delimited JSON. Maximum host input line: 1024 bytes.
ESP32 ROM boot chatter is possible; the host must ignore/count malformed lines
without terminating its serial reader. No terminal string is interpreted as code.

Accepted packet envelope:

```json
{"type":"packet","frame":"<56 hexadecimal characters>","rssi_dbm":-63.5,"lqi":42}
```

`frame` is the exact RF application payload. `rssi_dbm` is CC1101-reported RSSI,
not a calibrated instrument measurement; `lqi` is the raw 0–127 CC1101 LQI value,
not a percentage. RSSI/LQI are receiver observations, not protected by the RF
application CRC. They must be finite and range-checked by the host.

Status envelope:

```json
{"type":"status","role":"rx","state":"unconfigured","frequency_mhz":0}
```

Roles: `rx` or `tx`. States include `unconfigured`, `ready`, `receiving`, `armed`,
`disarmed`, `error`. Additional bounded diagnostic fields may be included.
Receiver errors use `{"type":"error","code":-7,"message":"..."}`. They do
not become telemetry samples or invented packet gaps.

## Radio profile

Both endpoints must share frequency, bitrate, deviation, bandwidth, sync word,
and packet mode. Baseline: 2-FSK, 38.4 kbit/s, 20 kHz deviation, 135 kHz RX
bandwidth, 16-bit preamble, sync bytes D3 91, hardware CRC enabled, variable-length
packet mode (application payload always 28 bytes), 0 dBm requested TX power.
Frequency is deliberately unset until explicitly configured. Module/antenna
band and local operating permissions must match; an accepted driver setting is
not proof of permission to transmit. The CC1101 profile is not compatible with
the simulator's IQ files. No image payload or ACK protocol is defined in v1.

## Honest host metrics

The host never reports simulated SNR, bit-error rate, or expected source values.
Count validated packets, duplicates, malformed serial messages, application CRC
failures, and observed forward sequence gaps separately. A gap is the number of
unobserved sequence values between validated packets in a node/boot session; it
can include RF loss, transmitter errors, USB loss, or time disconnected. It does
not prove RF loss alone, and cannot count packets missed before the first or
after the last observation. Out-of-order packets must not create huge unsigned
gaps or move the sequence high-water mark backward. Bound all history/session
storage and use monotonic local time for stale/disconnected status.
