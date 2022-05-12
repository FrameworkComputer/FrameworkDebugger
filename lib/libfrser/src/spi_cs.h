
#ifndef _SPI_CS_H_
#define _SPI_CS_H_
#include <Arduino.h>
#include <core_pins.h>
/* These can be functions if it makes sense, but these compile to so few instructions. */
//#define spi_select() do {   digitalWrite(15, LOW); } while(0)
/* delay because slow pullup. */
//#define spi_deselect() do { digitalWrite(15, HIGH); delayMicroseconds(1); } while(0);

#endif
