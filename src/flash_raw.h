#ifndef _FLASH_RAW_H_
#define _FLASH_RAW_H_

#include <Arduino.h>
#include <usb_serial.h>
#include <core_pins.h>


#ifdef ARDUINO_TEENSY41
int8_t flexspi_begin(void);
void flexspi_ip_command(uint32_t index, uint32_t addr);
void flexspi_ip_read(uint32_t index, uint32_t addr, void *data, uint32_t length);
void flexspi_ip_write(uint32_t index, uint32_t addr, const void *data, uint32_t length);
#endif 


int32_t flash_write(uint32_t addr, uint32_t size, void * src);
int32_t flash_read(uint32_t addr, uint32_t size, void * dst);
int32_t flash_erase(uint32_t addr, uint32_t size);
void flash_chip_erase(void);
#endif