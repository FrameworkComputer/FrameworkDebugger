#!/usr/bin/env bash

# Only works on NPCX EC chips
# Every Framework system, except 11-13th Gen Intel
#
# Using bare UART adapter with manual reset/flashmode buttons
# Usage:
# 0. Connect USB-UART adapter to EC UART (TX, RX, GND)
# 1. Hold down flashmode button (5.1k from EC UART TX to GND)
# 2. Press and release EC reset button (RST short to GND)
# 3. Run this script to flash
#    ./flash_manual_ec.sh ~/Downloads/sunflower/
#    Where the folder contains ec.bin and npcx_monitor.bin
#    If the adapter shows up at a different port, set it in an environment variable:
#    env FLASHUART=ttyUSB1 ./flash_manual_ec.sh ~/Downloads/sunflower/
# 4. Press and release EC reset button to boot EC again
#
# Useful to combine with the gh command
# > gh run download -R FrameworkComputer/ec -D temp
# > ./flash_manual_ec.sh temp/
# Or with chromium chroot build
# > ./flash_manual_ec.sh ~/chromiumos/src/platform/ec/build/zephyr/marigold/output/

FLASHUART=${FLASHUART:-ttyUSB0}

FLASH_SRC="$1/ec.bin"
MONITOR="$1/npcx_monitor.bin"
echo "USING ${FLASH_SRC} to flash EC"

#### DO FLASH
echo "Using NUVOTON Tool ./uartupdatetool" 
./uartupdatetool --port ${FLASHUART} --opr wr --addr 0x200c3020 --file ${MONITOR}
./uartupdatetool --port ${FLASHUART} --opr wr --auto --addr 0x0000 --file ${FLASH_SRC}
