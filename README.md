# PixelLink

PixelLink is a small radio telemetry project built around two ESP32 boards and two CC1101 modules. One board sends its uptime and an optional sensor input. The other receives the packets and passes them over USB to a dashboard on your computer.

The CC1101 handles FSK modulation and demodulation. The Python app checks the received packets and shows their contents, signal strength, and missing sequence numbers. If nothing is connected, the dashboard waits. It doesn't generate sample readings.

## Project status

The transmitter and receiver firmware compile, and the software tests pass. The project hasn't been tested with physical boards yet, so range and over-air reliability are still unverified.

This version sends telemetry, not images. It includes an older image-transfer simulator, but that runs separately and uses a different packet format.

## Hardware

- Two classic ESP32 DevKit boards (`esp32dev`)
- Two CC1101 modules for the same frequency band
- Matching antennas, USB cables, and wiring
- Optionally, a suitable analog sensor connected to the transmitter

The firmware uses the classic ESP32 pin layout, not the ESP32-C3 or S3 layout. See [the hardware guide](docs/hardware.md) for the wiring table and flashing instructions.

**The CC1101 uses 3.3 V power and logic. Do not connect it to 5 V.** Attach a suitable antenna before transmitting, and choose a frequency and operating conditions you are allowed to use in your location. No frequency is selected by default.

## Parts and prices

DigiKey US listed prices in USD, checked September 12, 2026. Quantities are for two nodes. This is a reference budget, not a ready-to-order kit: the ESP32 board was out of stock, and the M146 radio option needs different power and connector wiring from our generic CC1101 module.

| Part | Qty | Unit price | Line total | Link |
| --- | ---: | ---: | ---: | --- |
| ESP32-DEVKITC-32E | 2 | $10.00 | $20.00 | [DigiKey](https://www.digikey.com/en/products/detail/espressif-systems/ESP32-DEVKITC-32E/12091810) |
| M5Stack M146 CC1101 board with antenna, alternative only | 2 | $10.95 | $21.90 | [DigiKey](https://www.digikey.com/en/products/detail/m5stack-technology-co-ltd/M146/28310339) |
| Adafruit 592 USB-A to Micro-B data cable | 2 | $2.95 | $5.90 | [DigiKey](https://www.digikey.com/en/products/detail/adafruit-industries-llc/592/10669955) |
| Adafruit 1950 female-to-female jumper wires, 20-pack | 1 | $1.95 | $1.95 | [DigiKey](https://www.digikey.com/en/products/detail/adafruit-industries-llc/1950/6827084) |
| Adafruit 1954 male-to-female jumper wires, 20-pack | 1 | $1.95 | $1.95 | [DigiKey](https://www.digikey.com/en/products/detail/adafruit-industries-llc/1954/6827087) |
| Optional: Adafruit 239 full-size breadboard | 2 | $5.95 | $11.90 | [DigiKey](https://www.digikey.com/en/products/detail/adafruit-industries-llc/239/7244929) |

**Listed-parts subtotal: $51.70, or $63.60 with the optional breadboards.** Shipping, tax, tariffs, batteries, sensors, USB-C adapters, and any extra radio-adapter hardware are not included.

Before buying the radio boards, read [the parts notes](docs/parts.md). The M146 is an 855 to 925 MHz M5Stack board with a 5 V board input, not the 3.3 V breakout used in our wiring guide. It is not a drop-in replacement or a 433 MHz option. Its power connection, DIP-switch routing, and antenna match need to be checked first. Do not apply 5 V to the CC1101 chip or its signal pins. No exact DigiKey listing for the documented generic breakout was verified.

## Getting started

### Build and flash the boards

Install PlatformIO Core, then run this from the repository root:

```sh
pio run -d firmware -e transmitter -e receiver
```

That command only builds the firmware. Follow [the hardware guide](docs/hardware.md#build-test-and-flash) to upload the receiver build to one board and the transmitter build to the other. Check the USB port before each upload.

### Configure the receiver

Open the receiver's serial monitor at 115200 baud with newline line endings. Replace the frequency placeholder with your chosen frequency in MHz:

```text
FREQ <YOUR_ALLOWED_FREQUENCY_MHZ>
SAVE
STATUS
```

`SAVE` keeps the settings across resets, including a reset caused by opening the USB port. Check that the status reports role `rx` and state `receiving`, then close the serial monitor before starting the dashboard.

### Start the dashboard

You'll need Python 3.10 or newer. From the repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[hardware]'
python -m pixellink ports
```

Choose the receiver's port from that list and replace the example below:

```sh
python -m pixellink serve --serial-port /dev/cu.YOUR_RECEIVER --port 8000
```

On Windows, the port might be `COM5`; on Linux, it might be `/dev/ttyUSB0`. Open `http://127.0.0.1:8000` in your browser. Stop the server with Ctrl+C. Only one program should use the receiver's serial port at a time.

You can also open the setup page without connecting a board:

```sh
python -m pixellink serve --port 8000
```

It will stay in waiting mode. Restart with `--serial-port` when you're ready to connect the receiver. The app only reads from that port; it doesn't configure the radio or enable transmission.

### Start a transmission test

On the transmitter's serial monitor, select the same frequency as the receiver:

```text
FREQ <YOUR_ALLOWED_FREQUENCY_MHZ>
NODE 1
TX ARM
```

`TX ARM` enables one packet per second for 60 seconds. Run it again to start another test, or use `TX DISARM` to stop early. The board never restores an armed state after a reset. Changing the frequency, node ID, or ADC setting also disarms it.

Start with uptime packets only. Once you've wired a suitable analog input to GPIO34, you can use `ADC ON`, followed by `TX ARM`. ADC readings are raw 12-bit counts, not temperature or battery voltage. Leave ADC off if the input is unconnected, and never connect a battery or 5 V signal directly to it.

Use `STATUS` to check settings. `SAVE` stores the frequency and node ID, but not the armed state or ADC setting. `CLEAR` removes saved settings and stops radio operation.

## What the dashboard shows

- Node ID, boot ID, packet sequence, and transmitter uptime
- Raw ADC readings when sampling is enabled
- CC1101-reported RSSI in dBm and raw LQI
- Observed sequence gaps, duplicates, and out-of-order packets
- USB connection status, receiver status, and time since the last packet
- Invalid input counts and recording status

RSSI isn't a distance measurement or SNR. LQI isn't a percentage. Sequence gaps tell you which packet numbers weren't observed, but they can't distinguish radio loss from transmitter errors, USB loss, or time spent disconnected. Packets missed before the first observation aren't counted.

The receiver checks both the radio's hardware CRC and an application CRC32. CRC detects corruption; it doesn't authenticate the sender. This is a telemetry prototype, not a safety-critical control system.

## Recording

To save accepted USB messages while the dashboard is running:

```sh
python -m pixellink serve --serial-port /dev/cu.YOUR_RECEIVER \
  --log received.jsonl --port 8000
```

Choose a new filename each time. The app won't overwrite an existing recording. Logs contain the original accepted JSON messages, including status and diagnostics. Logging stops at 64 MiB, but reception continues. Malformed messages are counted rather than saved as telemetry.

## Tests

Run these from the repository root:

```sh
python -m unittest discover -s tests -v
node --test tests/frontend.test.cjs tests/telemetry_frontend.test.cjs
python firmware/test/run_native.py
pio run -d firmware -e transmitter -e receiver
```

The JavaScript tests require Node. Native firmware tests require a C++ compiler, and the standalone codec tests also require sanitizer support.

Tests cover packet encoding, CRC checks, sequence handling, serial reconnects, the dashboard, and firmware arming behavior. Some use mock devices or virtual serial ports. Those tests don't replace checking the actual wiring and radio link. See [the verification notes](docs/verification.md) for details and the physical test checklist.

## Image simulator

The earlier software-only image experiment is still available:

```sh
python -m pixellink simulate --port 8001
```

It generates FSK waveforms, adds noise, and reconstructs an image from decoded packets. Its packets and I/Q files are not compatible with the CC1101 telemetry firmware. Details are in [the simulator notes](docs/simulation.md). The optional Pluto capture utility is separate too.

## Repository layout

- `firmware/`: transmitter and receiver firmware, plus the shared packet codec
- `pixellink/telemetry.py`: packet decoding, USB reader, and telemetry state
- `pixellink/telemetry_server.py`: local HTTP server
- `pixellink/telemetry_static/`: hardware dashboard
- `pixellink/core.py`, `server.py`, and `static/`: image simulator
- `docs/hardware.md`: wiring, flashing, and serial commands
- `docs/parts.md`: prices, sourcing notes, and radio-board differences
- `docs/protocol.md`: radio packet and USB message formats
- `tests/`: automated tests and shared packet fixtures
