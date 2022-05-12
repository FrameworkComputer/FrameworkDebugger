#ifndef _SPIHW_TEENSYSPI_H_
#define _SPIHW_TEENSYSPI_H_
/* This will give spi_set_speed if needed. A bit illogically maybe, but anyways... */
#include "frser-flashapi.h"
#include <Arduino.h>
#if defined(ARDUINO_TEENSY40) || defined(ARDUINO_TEENSY41)
#define SPI_CS_PIN 10
#define SPI_DO_PIN 11
#define SPI_DI_PIN 12
#define SPI_SCK_PIN 13
#else 
#define SPI_CS_PIN 15
#define SPI_DO_PIN 11
#define SPI_DI_PIN 12
#define SPI_SCK_PIN 14

#endif

#if defined(ARDUINO_TEENSY40)
#define SPI1_CS_PIN 28
#define SPI1_DO_PIN 26
#define SPI1_DI_PIN 1
#define SPI1_SCK_PIN 27
#elif defined(ARDUINO_TEENSY41)
#define SPI2_CS_PIN 51
#define SPI2_DO_PIN 50
#define SPI2_DI_PIN 54
#define SPI2_SCK_PIN 49
#endif


void spi_init(void);
uint8_t spi_uninit(void);
uint8_t spi_txrx(const uint8_t c);

void spi_set_port(int spi_port);
//#define FRSER_ASYNC_SPI_API
//void spi_awrite_fast(uint8_t d);
//void spi_awrite(uint8_t d);
//uint8_t spi_aread(void);

/* Async SPI API:
 * write_fast: assumes SPI idle*, starts a transfer
 * write: will wait for space (or use a FIFO if available)
 * read: returns the byte associated with the last write_fast / write (=will wait for transfer complete).
 *
 * *SPI is idle after spi_read / spi_txrx / spi_init.
 * Do NOT:
 * write* + write_fast
 * (no write)/read + read
 * - those undefined actions can lead to anything, including infinite loop/reset/undefined TX value/things appearing to work.
 * Note: spi_txrx is allowed to be write_fast + read. thus do not write* + spi_txrx.
 */

void spi_init_cond(void);


/* These can be functions if it makes sense, but these compile to so few instructions. */
void spi_select(void);
/* delay because slow pullup. */
void spi_deselect(void);


#endif
