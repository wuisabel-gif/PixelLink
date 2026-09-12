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
- `docs/protocol.md`: radio packet and USB message formats
- `tests/`: automated tests and shared packet fixtures
