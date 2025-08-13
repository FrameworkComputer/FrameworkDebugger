
#ifndef IO_CONFIG_H
#define IO_CONFIG_H

#if defined(ARDUINO_TEENSY31) || defined(ARDUINO_TEENSY36)

#define PIN_RX1 0
#define PIN_TX1 1
#define PIN_RX2 9
#define PIN_TX2 10
#define PIN_RX3 7
#define PIN_TX3 8

#elif ARDUINO_TEENSY41

#define PIN_RX1 0
#define PIN_TX1 1
#define PIN_RX2 7
#define PIN_TX2 8
#define PIN_RX3 15
#define PIN_TX3 14

#elif ARDUINO_TEENSY40
#define PIN_RX1 0
#define PIN_TX1 -1
#define PIN_RX2 7
#define PIN_TX2 8
#define PIN_RX3 15
#define PIN_TX3 14
#endif

#define DEFAULT_PIN_SWCLK  23
#define DEFAULT_PIN_SWDIO 22
#define DEFAULT_PIN_NRESET 21 
#define DEFAULT_PIN_TDI 20
#define DEFAULT_PIN_TDO 24
#if ARDUINO_TEENSY40
#define DEFAULT_PIN_LED_CONNECTED 19 
#define DEFAULT_PIN_LED_RUNNING 25
#else 
#define DEFAULT_PIN_LED_CONNECTED 34 
#define DEFAULT_PIN_LED_RUNNING 35
#endif
extern int pin_swclk; 
extern int pin_swdio; 
extern int pin_nreset; 
extern int pin_tdi; 
extern int pin_tdo; 
extern int pin_led_connected; 
extern int pin_led_running; 

#if defined(ARDUINO_TEENSY31) || defined(ARDUINO_TEENSY36)

#define SPI_WP 6
#define SPI_MOSI 11
#define SPI_MISO 12
#define SPI_SCK 14 
#define SPI_CS 15

#elif ARDUINO_TEENSY41
#define SPI_WP 6
#define SPI_MOSI 11
#define SPI_MISO 12
#define SPI_SCK 13
#define SPI_CS 10

#elif ARDUINO_TEENSY40
#define SPI_WP 6
#define SPI_MOSI 11
#define SPI_MISO 12
#define SPI_SCK 13
#define SPI_CS 10

#define SPI1_CS 28
#define SPI1_DO 26
#define SPI1_DI 1
#define SPI1_SCK 27
#endif

#define BUTTON_HOST_POWER 16
#define BUTTON_HOST_RESET 17

#endif
