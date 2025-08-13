/*
	This file was part of bbflash, now frser-m328lpcspi.
	Copyright (C) 2013, Hao Liu and Robert L. Thompson

	This program is free software: you can redistribute it and/or modify
	it under the terms of the GNU General Public License as published by
	the Free Software Foundation, either version 3 of the License, or
	(at your option) any later version.

	This program is distributed in the hope that it will be useful,
	but WITHOUT ANY WARRANTY; without even the implied warranty of
	MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
	GNU General Public License for more details.

	You should have received a copy of the GNU General Public License
	along with this program.  If not, see <http://www.gnu.org/licenses/>.
*/
#ifndef NIBBLE_H_
#define NIBBLE_H_

bool nibble_init(void) {return true;}
void nibble_cleanup(void) {}
void clocked_nibble_write(uint8_t value) {}
void clocked_nibble_write_hi(uint8_t value) {}
uint8_t clocked_nibble_read(void) {return 0;}
void nibble_start(uint8_t start) {}
void nibble_hw_init(void) {}
void nibble_set_dir(uint8_t dir) {}
uint8_t nibble_read(void) {return 0;}
void nibble_write(uint8_t data) {};
void nibble_abort(void) {};


#define clock_cycle() do { } while(0)

#endif /* NIBBLE_H_ */
