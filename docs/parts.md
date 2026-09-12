# Parts and prices

These are DigiKey US listed unit prices in USD, checked on September 12, 2026. Quantities cover two nodes. Prices and stock can change; shipping, tax, and any applicable tariffs are not included.

This is a reference budget, not a confirmed ready-to-order build. The exact ESP32 board was out of stock, and the CC1101 board listed here needs different wiring from the generic module in the hardware guide.

| Part | Quantity | Unit price | Line total | DigiKey |
| --- | ---: | ---: | ---: | --- |
| Espressif ESP32-DEVKITC-32E | 2 | $10.00 | $20.00 | [1965-ESP32-DEVKITC-32E-ND](https://www.digikey.com/en/products/detail/espressif-systems/ESP32-DEVKITC-32E/12091810) |
| M5Stack M146 CC1101 board with antenna, conditional alternative | 2 | $10.95 | $21.90 | [2221-M146-ND](https://www.digikey.com/en/products/detail/m5stack-technology-co-ltd/M146/28310339) |
| Adafruit 592 USB-A to Micro-B data cable, 3 ft | 2 | $2.95 | $5.90 | [1528-592-ND](https://www.digikey.com/en/products/detail/adafruit-industries-llc/592/10669955) |
| Adafruit 1950 female-to-female jumper wires, 20-pack | 1 pack | $1.95 | $1.95 | [1528-1961-ND](https://www.digikey.com/en/products/detail/adafruit-industries-llc/1950/6827084) |
| Adafruit 1954 male-to-female jumper wires, 20-pack | 1 pack | $1.95 | $1.95 | [1528-1964-ND](https://www.digikey.com/en/products/detail/adafruit-industries-llc/1954/6827087) |
| Optional: Adafruit 239 full-size 830-point breadboard | 2 | $5.95 | $11.90 | [1528-239-ND](https://www.digikey.com/en/products/detail/adafruit-industries-llc/239/7244929) |

**Listed-parts subtotal: $51.70 without breadboards, or $63.60 with two breadboards.** These totals are conditional on using the M146 option. They are not a quote for a validated drop-in replacement for the documented radio board.

## Check before ordering

### ESP32 availability

DigiKey showed zero stock for ESP32-DEVKITC-32E when checked, with an estimated replenishment date of April 14, 2027. That is a supplier estimate, not a guaranteed delivery date. Check the live listing or choose a separately verified, pin-compatible classic ESP32 board before ordering the rest.

The [Espressif DevKitC guide](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32/esp32-devkitc/user_guide.html) confirms the Micro-B USB connection and the GPIOs used by this project. An ESP32-C3 or S3 board is not an automatic substitute.

### The M146 radio is an alternative, not a drop-in part

No exact DigiKey listing for a jumper-ready 3.3 V CC1101 breakout matching our current wiring guide was verified. The M146 is a real CC1101-based board that has a published price, but it is designed for the M5Stack connector system.

According to the [M5Stack M146 documentation](https://docs.m5stack.com/en/module/Module_CC1101):

- Its radio range is 855 to 925 MHz. It is not a 433 MHz replacement.
- Each package includes one board and one SMA antenna, so two packages include two antennas. Check the antenna's band match for your intended frequency before use; a separate replacement antenna is not priced here.
- The assembled M146 board takes a 5 V input through M-Bus. This is different from the generic 3.3 V CC1101 breakout in our wiring table. **Do not apply 5 V to a bare CC1101 or to SPI/GDO signal pins. Do not wire the M146 by copying the generic power connection.**
- SPI and the two GDO signals are available on M-Bus, with DIP-switch routing for CS and GDO. The GDO routes must use different connector pins. They need to be wired to the GPIO assignments in our firmware, rather than assuming the M5Stack host's GPIO labels apply to a separate ESP32 DevKit.

The table includes both jumper types to cover male-pin and female-socket connections. An M146-specific wiring and power plan still needs to be checked before buying or powering this combination. No M146 hardware test has been performed, and this price list does not change the firmware or the generic wiring guide.

### What the total leaves out

- A USB-C adapter or hub if your computer has no USB-A ports
- Batteries, an enclosure, and a remote power supply
- An optional sensor and any input conditioning or calibration parts
- Extra connectors, power hardware, or adapters needed by the final radio wiring
- Replacement antennas if the supplied antennas do not match the intended band
- Shipping, tax, and tariffs

Breadboards are optional for prototyping; the table does not assume a particular board placement or header-spacing arrangement. The initial uptime-only radio test does not need a sensor.

## Price sources

All prices in the table came from the linked DigiKey US listings, not budget estimates. The manufacturer pages below provide additional descriptions and connector details:

- [ESP32-DevKitC V4 guide](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32/esp32-devkitc/user_guide.html)
- [M5Stack M146](https://docs.m5stack.com/en/module/Module_CC1101)
- [Adafruit 592 USB data cable](https://www.adafruit.com/product/592)
- [Adafruit 1950 jumper wires](https://www.adafruit.com/product/1950)

No items were purchased or added to a cart.
