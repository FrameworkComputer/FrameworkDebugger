#!/bin/bash

CTRLUART=/dev/ttyACM0
FLASHUART=/dev/ttyACM1

if [ $# -eq 0 ]; then
	#no argument, try default locations
	search_paths=("${HOME}/software/ec-lotus/src/platform/ec/build/zephyr/lotus/output"\
		"${HOME}/chromiumos/src/platform/ec/build/zephyr/lotus/output")
  
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
echo -e "\n" > ${CTRLUART}
#put ec into reset 
echo -e "\npin 21 0 opendrain\n" > ${CTRLUART}
#read INPUT < /dev/ttyACM0
sleep 1

#enable 10k external pulldown on UART RX wired to pin 20
echo -e "\npin 4 0 opendrain\n" > ${CTRLUART}
sleep 1

# take out of reset
 echo -e "\npin 21 1\n" > ${CTRLUART}

#### DO FLASH 
../../uart-update-tool/Release/Uartupdatetool -port ${FLASHUART} -opr wr -addr 0x200c3020 -file ${MONITOR}
../../uart-update-tool/Release/Uartupdatetool -port ${FLASHUART} -opr wr -addr 0x0000 -file ${FLASH_SRC}


#### TAKE OUT OF RESET

#put ec into reset 
echo -e "\npin 21 0 opendrain\n" > ${CTRLUART}
#read INPUT < /dev/ttyACM0
sleep 1

#disable 10k external pulldown on UART RX wired to pin 20
echo -e "\npin 4 1 opendrain\n" > ${CTRLUART}
sleep 1


# take out of reset
echo -e "\npin 21 1\n" > ${CTRLUART}
