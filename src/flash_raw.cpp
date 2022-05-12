#include "flash_raw.h"

#include <usb_serial.h>

#if 0
extern "C" {
  extern uint8_t external_psram_size;
}
//#define FLASH_MEMMAP 1 //Use memory-mapped access

#define FLASH_SIZE_MB 32


uint8_t _spiffs_region;
static const uint32_t flashBaseAddr[3] = { 0x800000u,  0x800000u};
static const uint32_t eramBaseAddr = 0x07000000u;
static char flashID[8];
static const void* extBase = (void*)0x70000000u;
static const uint32_t blocksize = 4096; //or 32k or 64k (set correct flash commands above)
static uint32_t flashCapacity[3] = {FLASH_SIZE_MB * 1024u * 1024u,  8u * 1024u * 1024u};

#define LUT0(opcode, pads, operand) (FLEXSPI_LUT_INSTRUCTION((opcode), (pads), (operand)))
#define LUT1(opcode, pads, operand) (FLEXSPI_LUT_INSTRUCTION((opcode), (pads), (operand)) << 16)
#define CMD_SDR         FLEXSPI_LUT_OPCODE_CMD_SDR
#define ADDR_SDR        FLEXSPI_LUT_OPCODE_RADDR_SDR
#define READ_SDR        FLEXSPI_LUT_OPCODE_READ_SDR
#define WRITE_SDR       FLEXSPI_LUT_OPCODE_WRITE_SDR
#define DUMMY_SDR       FLEXSPI_LUT_OPCODE_DUMMY_SDR
#define MODE8_SDR		FLEXSPI_LUT_OPCODE_MODE8_SDR
#define PINS1           FLEXSPI_LUT_NUM_PADS_1
#define PINS4           FLEXSPI_LUT_NUM_PADS_4

// IDs
//Manufacturers codes

// Error management
#define ERROR_0 0 // Success    
#define ERROR_1 1 // Data too long to fit the transmission buffer on Arduino
#define ERROR_2 2 // received NACK on transmit of address
#define ERROR_3 3 // received NACK on transmit of data
#define ERROR_4 4 // Serial seems not available
#define ERROR_5 5 // Not referenced device ID
#define ERROR_6 6 // Unused
#define ERROR_7 7 // Fram chip unidentified
#define ERROR_8 8 // Number of bytes asked to read null
#define ERROR_9 9 // Bit position out of range
#define ERROR_10 10 // Not permitted opération
#define ERROR_11 11 // Memory address out of range


bool flash_wait(uint32_t timeout) {
  uint8_t val;
  uint32_t t = millis();
  FLEXSPI_IPRXFCR = FLEXSPI_IPRXFCR_CLRIPRXF; // clear rx fifo
  do {
	if(_spiffs_region == 0) {
		flexspi_ip_read(8, flashBaseAddr[_spiffs_region], &val, 1 );
	} else {
		flexspi_ip_read(5, flashBaseAddr[_spiffs_region], &val, 1 );
	}
    if (timeout && (millis() - t > timeout)) {
	return 1; }
  } while  ((val & 0x01) == 1);
  return 0;
}

 int32_t flash_erase(uint32_t addr, uint32_t size) {
  int s = size;
  while (s > 0) { //TODO: Is this loop needed, or is size max 4096?
    flexspi_ip_command(11, flashBaseAddr[_spiffs_region]);  //write enable
    flexspi_ip_command(12, addr);
#ifdef FLASH_MEMMAP
    arm_dcache_delete((void*)((uint32_t)extBase + addr), size);
#endif
    addr += blocksize;
    s -= blocksize;
    flash_wait(0); //TODO: Can we wait at the beginning intead?
  }
  return 0;
}

 int32_t flash_read(uint32_t addr, uint32_t size, void * dst) {
  uint8_t *p;
  p = (uint8_t *)extBase;
  p += addr;
    FLEXSPI_IPRXFCR = FLEXSPI_IPRXFCR_CLRIPRXF; // clear rx fifo

#ifdef FLASH_MEMMAP
  memcpy(dst, p, size);
#else
	flexspi_ip_read(5, addr, dst, size);
#endif
  return 0;
}

 int32_t flash_write(uint32_t addr, uint32_t size, void * src) {
  if(_spiffs_region == 0) {
	flexspi_ip_command(11, flashBaseAddr[_spiffs_region]);  //write enable
	flexspi_ip_write(13, addr, src, size);
  } else {
	  flexspi_ip_write(6, addr, src, size);
  }
#ifdef FLASH_MEMMAP
  arm_dcache_delete((void*)((uint32_t)extBase + addr), size);
#endif
  if(_spiffs_region == 0) 
	flash_wait(0); //TODO: Can we wait at the beginning instead?
  return 0;
}

void flash_chip_erase(void) {
  flexspi_ip_command(11, flashBaseAddr[_spiffs_region]);
  Serial.println("Erasing... (may take some time)");
  uint32_t t = millis();
  FLEXSPI2_LUT60 = LUT0(CMD_SDR, PINS4, 0x60); //Chip erase
  flexspi_ip_command(15, flashBaseAddr[_spiffs_region]);
#ifdef FLASH_MEMMAP
  arm_dcache_delete((void*)((uint32_t)extBase + flashBaseAddr[_spiffs_region]), flashCapacity[_spiffs_region]);
#endif
  while (flash_wait(500)) {
    Serial.print(".");
  }
  t = millis() - t;
  Serial.printf("\nChip erased in %d seconds.\n", t / 1000);
}
#endif