# Framework Debug Tools

## Introduction

Framework laptops are capable of being debugged and programmed from a
variety of interfaces. This document describes all of them and offers some
tips on what hardware is needed.

Here's a short list:

* [EC](https://en.wikipedia.org/wiki/Embedded_controller) &
  CPU [UART](https://en.wikipedia.org/wiki/Universal_asynchronous_receiver-transmitter) (aka serial port), both open and closed case
* EC [JTAG](https://en.wikipedia.org/wiki/JTAG)
* PD SWD
* SOC SPI Flash (BIOS)

## CCD (Closed Case Debug)

EC & CPU UARTs can be accessed without opening the DUT (Device Under Test,
aka the framework laptop) up by connecting to the USB Type-C ports on the
right of the device (side with the power button).

The USB Type-C port needs to be told to go to debug accessory mode
(see [USB Type-C Cable and Connector Specifications](https://www.usb.org/document-library/usb-type-cr-cable-and-connector-specification-release-23), section "Chapter B, Debug Accessory Mode").
Then the UART TX and RX can be connected to the SBU lines (see [below section](#making-a-framework-ccd-adaptor-from-scratch) for pinout).

The one of the ports is going to have EC UART (generally top right port of
a 13 inch), another has the CPU UART.

Note: Inserting the debugger into the DUT in the flipped orientation will
swap RX and TX, resulting in not much happening.

Note 2: This is similar to [Chrome OS CCD](https://chromium.googlesource.com/chromiumos/third_party/hdctools/+/main/docs/ccd.md),
**but not quite**. Chromebooks use D+ & D- USB from the GSC over the SBU
lines instead of simple UART signals.

Note 3: If you happen to have a [Chrome OS Servo v4](https://chromium.googlesource.com/chromiumos/third_party/hdctools/+/main/docs/servo_v4.md)
there's a way it can be configured to do this kind of UART debugging,
despite UART not being common on chromebooks. That feature was added to debug
some Android phones. If you're still interested in this method,
`dut-control sbu_uart_sel:uart` is what you're looking for, and
perhaps `dut-control sbu_flip_sel:on`.

Thank you [@DHowett for the blog post](https://www.howett.net/posts/2023-04-framework-ec-card)
that inspired this document and tool incubation.

### Making a Framework CCD Adaptor from Scratch

One needs a [USB Type-C Male breakout board](https://www.digikey.com/en/products/detail/saiko-systems-ltd./BRK-USB-CPV3.0/15283090)
and some kind of UART interface (FTDI or any other 3.3V UART breakout / cable
will probably work fine).

Note: A female breakout board does not work as Type-C cables do not pass both CC signals.

Type C Male (toward DUT)          | UART Interface Board (eg: FTDI)
--------------------------------- | ------------------------
A5 (CC1)                          | 5.1 kΩ resistor to GND (Note 1)
B5 (CC2)                          | 5.1 kΩ resistor to GND
A8 (SBU 1) dut uart TX (Note 3)   | 1k (Note 2) resistor to debugger TX
B8 (SBU 2) dut uart RX            | 1k resistor to debugger RX
A4, A9, B4, B9 (VBUS)             | Do not inject power into this from an interface board! The DUT will also be sourcing 5V on this, use only as a signal that the DUT is alive.
A1, A12, B1, B12 (GND)            | GND

Note 1: The table above describes the Rd/Rd (both pullup to GND) configuration,
this makes the DUT provide voltage on VBUS (useful in some cases if you want
to power sections of a debug card).

Note 2: The 1k resistor is for safety and power sequencing (eg: not
killing either the DUT or the interface board if it's off while the
other is on, or if the RX/TX is flipped). Feel free to substitute with
something else (or 0 ohm) in a pinch.

Note 3: On a laptop, A8 (SBU 1) (aka dut TX) pin is on the same side of the
Type-C port as the keyboard (aka [C panel](https://www.blackview.hk/blog/computers/laptop-a-b-c-d-sides)).
B9 (SBU 2) (aka dut RX) is toward the bottom of the device (D panel)

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
not say anything unless the software (firmware and/or OS) [is told to use the
serial port](#cpu-uart).

This connector is usually placed near the EC chip, usually bottom right area
of the board, near the keyboard connector and possibly even near the BIOS chip.
This area of the board is usually farther away from the main CPU, memory,
storage and beefy power stuff for space reasons.

This connector generally comes unpopulated on mass production boards,
one needs to buy and solder it to make use of the signals.

10 pin connector, 0.5mm pitch, flat flex cable:

* [Connector](https://www.hirose.com/product/p/CL0580-0412-7-10),
[DigiKey (H125812CT-ND)](https://www.digikey.com/en/products/detail/hirose-electric-co-ltd/FH19C-10S-0-5SH-10/4283386)
* [Flex Cable](https://www.molex.com/en-us/products/part-detail/0151660111),
[DigiKey (WM21810-ND)](https://www.digikey.com/en/products/detail/molex/0151660111/3280993).

Pinout:

1. 3VL_EC
2. UART_0_CRXD_DTXD
3. EC_JTAG_TMS
4. EC_JTAG_TCK
5. EC_JTAG_TDO
6. ECTX_DRX 
7. ECRX_DTX
8. UART_0_CTXD_DRXD
9. EC_RST#
10. GND

#### Voltage References

Warning: Do not inject voltage on any pins when the device on the other side
(EC or CPU, as applicable) is off. Doing so will cause current leaks that
will cause troubles using the debugger and at worst might damange the DUT.

All EC pins are referenced to the `3VL_EC` rail (and also happens to be
3.3V on every device we made so far).

`EC_RST#` is an OD rail with a pullup on the DUT. Do not output high on
this rail as it might cause a short when the board gets reset in other ways.

CPU UARTs unfortunatelly do not have a voltage reference pin.
In order to avoid leaks we generally implemented a pattern of open drain
level shifters on the DUT side. All you have to do to use these pins safely
is use an open drain for DEBUG_TX_DUT_RX and a hiz input
(without a debugger pullup) for DEBUG_RX_DUT_TX. The CPU UART pins are
generally 3.3V. In a pinch they can be used directly with a uart interface,
but those pins should only be connected after CPU turns on, and
disconnected before a shutdown or a reboot.

### JSPI

This connector can be used to reflash the BIOS chip. This is useful for
SOC BIOS/Firmware developers (eg: coreboot) and perhaps even unbricking
from a failed BIOS upgrade.

Note: While one can reflash the BIOS with this connector the CPU might not
always boot any BIOS (eg: self signed coreboot).

This connector is usually placed near the BIOS chip. It's labeled
on the silkscreen using the "JSPI" label.

This connector generally comes unpopulated on mass production boards,
one needs to buy and solder it to make use of the signals.

6 pin connector, 0.5mm pitch, flat flex cable:

* [Connector](https://www.hirose.com/product/p/CL0580-0409-2-10),
[Digikey (H125824CT-ND)](https://www.digikey.com/en/products/detail/hirose-electric-co-ltd/FH19C-6S-0-5SH-10/4283419)
* [Flex Cable](https://www.molex.com/en-us/products/part-detail/0151660063),
[Digikey (WM25052-ND)](https://www.digikey.com/en/products/detail/molex/0151660063/3280945) (ignore the 10 pin picture on molex's website, it's 6 pin)

Pinout:

1. GND
2. SOC_SPI_0_CLK
3. SOC_SPI_0_MISO
4. SOC_SPI_0_MOSI
5. SOC_SPI_0_CS#
6. SPI_VCC

#### Voltage References

All SPI pins are referenced to the SPI_VCC rail. SPI_VCC is generally
what powers the spi flash chip as well.

Board     | SPI_VCC
--------- | ----
Dogwood   | 1.8V
Lilac     | 1.8V
Marigold  | 1.8V
Azalea    | 1.8V
Lotus     | 1.8V
Tulip     | 1.8V
ADL       | 3.3V
Sunflower | 3.3V
Iris      | 3.3V
Banshee   | 3.3V
TGL       | 3.3V

On later boards we have guaranteed to have 33 ohm resistors between the SPI flash
and the CPU, meaning if a debugger is used, the debugger will win a drive fight.

Injecting VCC into the motherboard is not recommended. The CPU should be
turned on, kept in a quiet state, then the SPI flash programmed based
on the voltage reference. Turning on either SPI_VCC or raising the
voltage of any of the SPI pins while the CPU is off causes leaks that might
damage hardware.

#### ROM Flash

The flash chip itself uses WSON8 8x6mm footprint.
Unfortunately it cannot be flashed using the traditional clips that work on SOIC8 chips.
But you can get special pogo pin connectors to press onto the chips leads and flash it.
Or get a WSON8 socket.

### JPD

This connector can be used to flash and debug the PD chips. Unless you're
really into USB Type-C and have the Cypress SDK ready you probably don't
care about this.

This connector is generally placed near the top of the board (though possibly
under a heatsink, particularly on the 16 inch). Usually on each side of the
device near the type-C ports.

This connector generally comes unpopulated on mass production boards,
one needs to buy and solder it to make use of the signals.

6 pin connector, 0.5mm pitch, flat flex cable:

* [Connector](https://www.hirose.com/product/p/CL0580-0409-2-10),
[Digikey (H125824CT-ND)](https://www.digikey.com/en/products/detail/hirose-electric-co-ltd/FH19C-6S-0-5SH-10/4283419)
* [Flex Cable](https://www.molex.com/en-us/products/part-detail/0151660063),
[Digikey (WM25052-ND)](https://www.digikey.com/en/products/detail/molex/0151660063/3280945) (ignore the 10 pin picture on molex's website, it's 6 pin)

Pinout:

1. VCC
2. GND
3. XRES
4. SWD_CLK
5. SWD_IO

## EC UART

Once connected to the EC UART (either open case or closed case, see above), the
Embedded Controller's command prompt can be reached. The UART settings are
`115200 8N1`.

`help` will give a list of available commands. `help $command` for help
specific to a certain command.

Interesting commands:
* `powerbtn` - simulates button press
* `apshutdown` - forces CPU off
* `version` - gives the EC version (generally matches BIOS version)

## CPU UART

Once connected to the CPU UART (either open case or closed case, see above)
the port can be used for a variety of uses:

### Linux

Once the `Advanced > Serial Console` BIOS option is enabled, a new `/dev/ttyS4`
device will show up under Linux (at least on AMD systems).

This serial device is useful to manage a linux system even in cases where doing
it over the display is less desired (ex: debugging crashes, lights out
management over the text console without KVMs involving screen output)

#### Kernel console

`console=ttyS4,115200` can be added to the kernel command line (just before an
entry of `console=tty0`, otherwise you might not see any more output on the
normal screen). This way the kernel will output any messages to the UART
console as well. `loglevel=9` is also useful for debugging the kernel messages
while doing this. If there's someone listening on the other end of the UART
port any kernel crashes or restarts might be easier to root cause.

#### Getty

One can login to the linux system via this UART console, a
[getty](https://en.wikipedia.org/wiki/Getty_(unix)) can be started:
`sudo systemctl enable --now getty@ttyS4.service`

Note: the getty will use the currently configured baud rate. If you're already
using the kernel console instructions above, this will be 115200, otherwise
you might have to adjust the systemd job for the desired serial settings.

Once the service is enabled a login prompt will appear on the uart console.
With the appropriate authetication the system can be managed over the UART
console with no other graphics or networking running.

### BIOS

The BIOS settings can be managed through the CPU UART console by enabling
`Advanced > Console Redirect Configuration > Console Serial Redirect`.
It's also worth double-checking if the
`Advanced > Console Redirect Configuration > MMIO_UART0 (FCH) > PortEnable`
setting is set to Enabled.

Once that's done, the BIOS should be visible as soon as the next reboot on the
UART console. The uart settings of the serial monitor match the settings
configured in the bios, the default is 115200 8N1.

Normal boot keys like F2 and F12 should also work to interrupt the boot process.
