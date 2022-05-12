/*
 * This file is part of the libfrser project.
 *
 * Copyright (C) 2015 Urja Rannikko <urjaman@gmail.com>
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA
 */

#include "main.h"
#include "spihw_teensyspi.h"
#include "frser-cfg.h"
#include <Arduino.h> 
#include <core_pins.h>
#include <SPI.h>
#include "spilib.h"

/* This is for the usage of the SPI module of the ATmega88/168/328, maybe others. */
/* Doesnt deal with CS. */

static uint8_t spi_initialized = 0;

#ifdef FRSER_FEAT_SPISPEED
static uint32_t spi_set_spd = 4000000; /* Max speed - F_CPU/2 */

static uint8_t flexspi_ctrl = 0;

uint32_t spi_set_speed(uint32_t hz) {
	/* We can set F_CPU / : 2,4,8,16,32,64,128 */

	spi_set_spd = hz;
	if (spi_initialized) { // change speed
		spi_init(); // re-init
	}
	return hz;
}
void spi_set_port(int spi_port) {
	spi_uninit();
	flexspi_ctrl = spi_port;
	spi_init();

}

void spi_init(void) {
	/* DDR and PORT settings come from elsewhere (maybe flash.c) */
	if (flexspi_ctrl == 0) {
		pinMode(SPI_CS_PIN, OUTPUT); 
		pinMode(SPI_SCK_PIN, OUTPUT); 
		SPI.setSCK(SPI_SCK_PIN); 
		SPI.begin(); 
		SPI.setSCK(SPI_SCK_PIN);

		SPI.beginTransaction(SPISettings(spi_set_spd, MSBFIRST, SPI_MODE0));
	}else if (flexspi_ctrl == 1){
#ifdef ARDUINO_TEENSY41
		SPI2.setMISO(SPI2_DI_PIN);
		SPI2.setMOSI(SPI2_DO_PIN);
		SPI2.setSCK(SPI2_SCK_PIN);
		SPI2.begin();
		SPI2.setMISO(SPI2_DI_PIN);
		SPI2.setMOSI(SPI2_DO_PIN);
		SPI2.setSCK(SPI2_SCK_PIN);
		SPI2.beginTransaction(SPISettings(spi_set_spd, MSBFIRST, SPI_MODE0));
#elif defined(ARDUINO_TEENSY40)
		SPI1.setMISO(SPI1_DI_PIN);
		SPI1.setMOSI(SPI1_DO_PIN);
		SPI1.setSCK(SPI1_SCK_PIN);
		SPI1.begin();
		SPI1.setMISO(SPI1_DI_PIN);
		SPI1.setMOSI(SPI1_DO_PIN);
		SPI1.setSCK(SPI1_SCK_PIN);
		SPI1.beginTransaction(SPISettings(spi_set_spd, MSBFIRST, SPI_MODE0));
#endif
	}
	spi_initialized = 1;
}
#else

#endif

uint8_t spi_uninit(void) {
	if (spi_initialized) {
		if (flexspi_ctrl == 0) {
			SPI.endTransaction(); 
		} else if (flexspi_ctrl ==1) {
#if defined(ARDUINO_TEENSY41)
			SPI2.endTransaction(); 
#elif  defined(ARDUINO_TEENSY40)
			SPI1.endTransaction(); 
#endif
		}
		spi_initialized = 0;
		return 1;
	}
	return 0;
}


uint8_t spi_txrx(const uint8_t c) {
	if (flexspi_ctrl == 0) {
		return SPI.transfer(c);
	}else if (flexspi_ctrl ==1){
#if defined(ARDUINO_TEENSY41)
		return SPI2.transfer(c);
#elif defined(ARDUINO_TEENSY40)
		return SPI1.transfer(c);
#endif
	}
	return 0;
}



/* This is here only to keep spi_initialized a static variable,
 * hidden from other bits of code. */

void spi_init_cond(void) {
	if (!spi_initialized) spi_init();
}


void flash_set_safe(void) {
	spi_uninit();
	if (flexspi_ctrl == 0) {
		pinMode(SPI_CS_PIN, INPUT); //SS
		pinMode(SPI_DO_PIN, INPUT);
		pinMode(SPI_DI_PIN, INPUT);
		pinMode(SPI_SCK_PIN, INPUT);
	}else if (flexspi_ctrl ==1){
#if defined(ARDUINO_TEENSY41)
		pinMode(SPI2_CS_PIN, INPUT); //SS
		pinMode(SPI2_DO_PIN, INPUT);
		pinMode(SPI2_DI_PIN, INPUT);
		pinMode(SPI2_SCK_PIN, INPUT);
#elif defined(ARDUINO_TEENSY40)
		pinMode(SPI1_CS_PIN, INPUT); //SS
		pinMode(SPI1_DO_PIN, INPUT);
		pinMode(SPI1_DI_PIN, INPUT);
		pinMode(SPI1_SCK_PIN, INPUT);
#endif
	}
}

void flash_select_protocol(uint8_t allowed_protocols) {
	(void)allowed_protocols;
}

void flash_spiop(uint32_t s, uint32_t r) {
	spi_spiop(s,r);
}


/* These can be functions if it makes sense, but these compile to so few instructions. */
void spi_select(void) {
	if (flexspi_ctrl == 0) {
		digitalWrite(SPI_CS_PIN, LOW);

#if defined(ARDUINO_TEENSY40) || defined(ARDUINO_TEENSY41)
	}else if (flexspi_ctrl ==1){
#if defined(ARDUINO_TEENSY41)
		digitalWrite(SPI2_CS_PIN, LOW);
#elif defined(ARDUINO_TEENSY40)
		digitalWrite(SPI1_CS_PIN, LOW);
#endif
#endif

	}
}
/* delay because slow pullup. */
void spi_deselect(void) {
	if (flexspi_ctrl == 0) {
		digitalWrite(SPI_CS_PIN, HIGH); 
#if defined(ARDUINO_TEENSY40) || defined(ARDUINO_TEENSY41)
	}else if (flexspi_ctrl ==1){
#if defined(ARDUINO_TEENSY41)
		digitalWrite(SPI2_CS_PIN, HIGH);
#elif defined(ARDUINO_TEENSY40)
		digitalWrite(SPI1_CS_PIN, HIGH);
#endif
#endif
	}


}

/* Select and deselect are not part of the "domain" of this .c / target-specific */
