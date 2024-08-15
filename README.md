# Framework Debug Tools

## Introduction

Framework laptops are capable of being debugged and programmed from a
variety of interfaces. This document describes all of them and offers some
tips on what hardware is needed.

Here's a short list:

* EC & CPU [UART](https://en.wikipedia.org/wiki/Universal_asynchronous_receiver-transmitter) (aka serial port), both open and closed case
* EC [JTAG](https://en.wikipedia.org/wiki/JTAG)
* PD SWD
* SOC SPI Flash (BIOS)

## CCD

EC & CPU UARTs can be accessed without opening the DUT (Device Under Test,
aka the framework laptop) up by connecting to the USB Type-C ports on the
right of the device (side with the power button).

The USB Type-C port needs to be told to go to debug accessory mode
(see [USB Type-C Cable and Connector Specifications](https://www.usb.org/document-library/usb-type-cr-cable-and-connector-specification-release-23), section "Chapter B, Debug Accessory Mode").
Then the UART TX and RX can be connected to the SBU lines (TODO: which way?).

The upper port is going to have EC UART.

The lower port is going to have CPU UART.

Note: Inserting the debugger into the DUT in the flipped orientation will
swap RX and TX, resulting in not much happening.

Note 2: This is similar to [Chrome OS CCD](https://chromium.googlesource.com/chromiumos/third_party/hdctools/+/main/docs/ccd.md),
**but not quite**. Chromebooks use D+ & D- USB from the GSC over the SBU
lines instead of simple UART signals.

Note 3: If you happen to have a [Chrome OS Servo v4](https://chromium.googlesource.com/chromiumos/third_party/hdctools/+/main/docs/servo_v4.md) there's a way it can be configured to do this kind of UART debugging (TODO: add this in),
despite UART not being common on chromebooks. That feature was added to debug
some Android phones.

Thank you [@DHowett for the blog post](https://www.howett.net/posts/2023-04-framework-ec-card)
that inspired this document and tool incubation.

TODO: Add Josh Cook's https://i2clabs.com.au/ec-debug-expansion-card/

### Making a Framework CCD Adaptor from Scratch

One needs a [USB Type-C Male breakout board](https://www.digikey.com/en/products/detail/saiko-systems-ltd./BRK-USB-CPV3.0/15283090)
and some kind of UART interface (FTDI or any other 3.3V UART breakout / cable
will probably work fine).

Note: A female breakout board does not work as Type-C cables do not pass both CC signals.

Type C Male (toward DUT) | UART Interface Board (eg: FTDI)
------------------------ | ------------------------
A8 (SBU 1)               | 1k (Note 1) resistor to TX (TODO: which way?)
B8 (SBU 2)               | 1k resistor to RX
A4, A9, B4, B9 (VBUS)    | VBUS, 5V
A5 (CC1)                 | 22 kΩ resistor to VBUS (Note 2)
B5 (CC2)                 | 56 kΩ resistor to VBUS
A1, A12, B1, B12 (GND)   | GND

Note 1: The 1k resistor is for safety and power sequencing (eg: not
killing either the DUT or the interface board if it's off while the
other is on, or if the RX/TX is flipped). Feel free to substitute with
something else (or 0 ohm) in a pinch.

Note 2: The table above describes the Rp/Rp (both pullup to VBUS) configuration.
Rd/Rd to GND should also work.

## Open Case Debugging

For this you'll need to connect to various connectors on the board. You will
have to open the DUT (and cope with the blinking red LEDs due to chassis
intrusion). Most likely the connectors themselves will not be populated on
production boards so you will have to solder them yourself.
See each connector for part numbers.

### JECDB

This connector provides a way to program/debug the EC, see the EC booting,
then see the CPU boot logs.

While the EC is very chatty and even offers a console, the CPU will probably
not say anything unless the software (firmware and/or OS) is told to use the
serial port.

TODO: Describe connector location.

10 pin connector, 0.5mm pitch, flat flex cable:

* [Connector](https://www.molex.com/en-us/products/part-detail/5034801000),
[DigiKey (WM1389CT-ND)](https://www.digikey.com/en/products/detail/molex/5034801000/2356624)
* [Flex Cable](https://www.molex.com/en-us/products/part-detail/0151660111),
[DigiKey (WM21810-ND)](https://www.digikey.com/en/products/detail/molex/0151660111/3280993).

TODO: figure out if we have this publicly documented somewhere else on github.

Pinout:

1. 3VL_EC
2. UART_0_CRXD_DTXD
3. EC_JTAG_TMS
4. EC_JTAG_TCK
5. EC_JTAG_TDO
6. EC_UART0_TX
7. EC_UART0_RX
8. UART_0_CTXD_DRXD
9. EC_RST#
10. GND

TODO: Figure out & Document voltage references across all boards.

### JSPI

This connector can be used to reflash the BIOS chip. This is useful for
SOC BIOS/Firmware developers (eg: coreboot) and perhaps even unbricking
from a failed BIOS upgrade.

Note: While one can reflash the BIOS with this connector the CPU might not
always boot any BIOS (eg: self signed coreboot).

TODO: Describe connector location.

6 pin connector, 0.5mm pitch, flat flex cable:

* [Connector](https://www.molex.com/en-us/products/part-detail/5034800600),
[Digikey (WM1387CT-ND)](https://www.digikey.com/en/products/detail/molex/5034800600/2356622)
* [Flex Cable](https://www.molex.com/en-us/products/part-detail/0151660063),
[Digikey (WM25052-ND)](https://www.digikey.com/en/products/detail/molex/0151660063/3280945) (ignore the 10 pin picture on molex's website, it's 6 pin)

Pinout:

1. GND
2. SOC_SPI_0_CLK
3. SOC_SPI_0_D1
4. SOC_SPI_0_D0
5. SOC_SPI_0_CS#0
6. 3V_SPI

TODO: Figure out & Document voltage references across all boards.

TODO: Figure out how to avoid leaks when flashing

### JPD

This connector can be used to flash and debug the PD chips. Unless you're
really into USB Type-C and have the Cypress SDK ready you probably don't
care about this.

TODO: Describe connector location.

6 pin connector, 0.5mm pitch, flat flex cable:

* [Flex Cable](https://www.molex.com/en-us/products/part-detail/0151660063),
[Digikey (WM25052-ND)](https://www.digikey.com/en/products/detail/molex/0151660063/3280945) (ignore the 10 pin picture on molex's website, it's 6 pin)
* [Connector](https://www.molex.com/en-us/products/part-detail/5034800600),
[Digikey (WM1387CT-ND)](https://www.digikey.com/en/products/detail/molex/5034800600/2356622)

Pinout:

1. VCC
2. GND
3. XRES
4. SWD_CLK
5. SWD_IO

## Framework Light Debug Tool

A tool to interface to all of the above interfaces was developed. It can either
be used in a open case or closed case configuration. It's in an expansion
card form factor, so it can be docked inside a DUT.

TODO: Link or perhaps delete section for now.
