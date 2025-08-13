/* This is an example for what frser.c requires from an uart.h */

#ifndef _UART_H_
#define _UART_H_
#include <Arduino.h>
#if defined(ARDUINO_TEENSY31) || defined(ARDUINO_TEENSY36)
#include <usb_serial3.h> 
#endif
/* These function names can be any, but to show the types. */
//uint8_t uart_recv(void);
//void uart_send(uint8_t val);
/* ------- */

/* ifdef FRSER_FEAT_UART_TIMEOUT */
//void uart_set_timeout(jmp_buf *buf);
/* endif */

/* These defines are what is really used: */
#define BAUD 115200

#define RECEIVE() SerialUSB2.read()
#define SEND(n) SerialUSB2.write(n)
#define ISDATA() SerialUSB2.available()
#define UART_BUFLEN 1280
#define UARTTX_BUFLEN 0

#endif
