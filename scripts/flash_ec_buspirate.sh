#!/bin/bash

DEVICE=${DEVICE:-"/dev/serial/by-id/usb-Bus_Pirate_Bus_Pirate_5"}
CTRLUART=(${DEVICE}*-if00)
FLASHUART=$(basename $(readlink ${DEVICE}*-if00))

if [ $# -eq 0 ]; then
	#no argument, try default locations
	search_paths=("${HOME}/software/ec-lotus/src/platform/ec/build/zephyr/azalea/output"\
		"${HOME}/chromiumos/src/platform/ec/build/zephyr/azalea/output")
  
	for search in ${search_paths[@]}
	do
		if [ -d $search ] 
		then
			echo "${search} exists"
			FLASH_SRC="${search}/ec.bin"
			MONITOR="${search}/npcx_monitor.bin"
		fi
	done
else
  #allow specifying a file as argument
  FLASH_SRC="$1/ec.bin"
  MONITOR="$1/npcx_monitor.bin"
fi
echo "USING ${FLASH_SRC} to flash EC"

#clear any invalid commands from uart buffer
echo -e "n\r\n" > ${CTRLUART}
# Put EC into reset by pulling nRESETI_R (pin 2 on buspirate) low
echo -e "\r\na 2\r\n" > ${CTRLUART}
#read INPUT < ${CTRLUART}
sleep 1

#enable 10k external pulldown on UART RX wired to pin 20
echo -e "\r\na 6\r\n" > ${CTRLUART}
sleep 1

# take out of reset
 echo -e "\r\n@ 2\r\n" > ${CTRLUART}
sleep 1

# Bridge UART via the BusPirate
# This turns the current UART consle to the bus pirate into a bridge to the EC
# After we're done, to exit, you have press the buspirate button
echo -e "\r\nbridge\r\n" > ${CTRLUART}

sleep 1

#### DO FLASH
echo "Using NUVOTON Tool ./uartupdatetool" 
./uartupdatetool --port ${FLASHUART} --opr wr --addr 0x200c3020 --file ${MONITOR}
./uartupdatetool --port ${FLASHUART} --opr wr --auto --addr 0x0000 --file ${FLASH_SRC}

read -p "Press button on buspirate" userinput

#### TAKE OUT OF RESET

#put ec into reset 
echo -e "\r\na 2\r\n" > ${CTRLUART}
#read INPUT < ${CTRLUART}
sleep 1

# Enable BusPirate's 10k internal pulldown on UART RX wired to IO6
echo -e "\r\n@ 6\r\n" > ${CTRLUART}
sleep 1


# take out of reset
echo -e "\r\n@ 2\r\n" > ${CTRLUART}
