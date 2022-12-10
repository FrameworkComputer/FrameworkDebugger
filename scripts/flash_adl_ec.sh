#!/bin/bash
CTRLUART=/dev/ttyACM0
FLASHUART=/dev/ttyACM2
if [ $# -eq 0 ]; then
  #no argument, try default location 
  FLASH_SRC=~/ec/build/hx30/ec.bin
else
  #allow specifying a file as argument
  FLASH_SRC=$1
fi

if [ -f "$FLASH_SRC" ]; then
  cp $FLASH_SRC ec.bin.tmp
else
  echo "No source file to flash was found at $FLASH_SRC"
  exit 1
fi

#clear any invalid commands from uart buffer
echo -e "\n" > ${CTRLUART}
#put ec into reset 
echo -e "\npin 21 0 opendrain\n" > ${CTRLUART}
#read INPUT < /dev/ttyACM0
sleep 1
#put teensy into serprog mode 
echo -e "\nterm 2 8\n" > ${CTRLUART}
#read INPUT < /dev/ttyACM0
sleep 1
#flashrom --programmer ch341a_spi -w ec.bin

truncate -s 1M ec.bin.tmp
flashrom -p serprog:dev=${FLASHUART}:115200,spispeed=2000000 -w ec.bin.tmp
rm ec.bin.tmp
#disable flashrom
echo -e "\nterm 2 2\n" > ${CTRLUART}
#read INPUT < /dev/ttyACM0
sleep 1
#take ec out of reset
echo -e "\npin 21 1\n" > ${CTRLUART}
#read INPUT < /dev/ttyACM0

