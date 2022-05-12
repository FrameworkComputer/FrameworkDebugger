=== Multi purpose debugger - target controller 

Supports 
CMSIS-DAP 
Multiple serial terminals 
GPIO read/write/port register control. 


right now the backend uses raw hid reports for debug communication, terminal.py will open an interactive terminal to the device. 

= How to flash to the teensy board: 
pio run -e teensy41 --target upload
pio run -e teensy31 --target upload
pio run -e teensy36 --target upload


= Modifications required to teensy 3.1 codebase:

* For this to work you need to modify the teensy source code to set the RAWHID iInterface field to 2 to use the product string
around line 1136 in ~/.platformio/packages/framework-arduinoteensy/cores/teensy3/usb_desc.c
--------------------------------------
#ifdef RAWHID_INTERFACE
        // interface descriptor, USB spec 9.6.5, page 267-269, Table 9-12
        9,                                      // bLength
        4,                                      // bDescriptorType
        RAWHID_INTERFACE,                       // bInterfaceNumber
        0,                                      // bAlternateSetting
        2,                                      // bNumEndpoints
        0x03,                                   // bInterfaceClass (0x03 = HID)
        0x00,                                   // bInterfaceSubClass
        0x00,                                   // bInterfaceProtocol
        2,                                      // iInterface   <-------------------Modify this!


usb_desc.h 
--------------------------------------
Add the following to the usb definitions section after USB_EVERYTHING
#elif defined(USB_RAWHID_TRIPLESERIAL)
 #define VENDOR_ID		0x16C0
  #define PRODUCT_ID		0x048C
  #define RAWHID_USAGE_PAGE     0xFFAB  // recommended: 0xFF00 to 0xFFFF
  #define RAWHID_USAGE          0x0200  // recommended: 0x0100 to 0xFFFF
  #define MANUFACTURER_NAME	{'T','e','e','n','s','y','d','u','i','n','o'}
  #define MANUFACTURER_NAME_LEN	11
  #define PRODUCT_NAME		{'C','M','S','I','S','-','D','A','P'}
  #define PRODUCT_NAME_LEN	9
  #define EP0_SIZE		64
  #define NUM_ENDPOINTS		12
  #define NUM_USB_BUFFERS	32
  #define NUM_INTERFACE		7

  #define CDC_IAD_DESCRIPTOR	1	// Serial
  #define CDC_STATUS_INTERFACE	0
  #define CDC_DATA_INTERFACE	1
  #define CDC_ACM_ENDPOINT	2
  #define CDC_RX_ENDPOINT	3
  #define CDC_TX_ENDPOINT	4
  #define CDC_ACM_SIZE		16
  #define CDC_RX_SIZE		64
  #define CDC_TX_SIZE		64

  #define CDC2_STATUS_INTERFACE	2	// SerialUSB1
  #define CDC2_DATA_INTERFACE	3
  #define CDC2_ACM_ENDPOINT	5
  #define CDC2_RX_ENDPOINT	6
  #define CDC2_TX_ENDPOINT	7
  #define CDC2_ACM_SIZE		16
  #define CDC2_RX_SIZE		64
  #define CDC2_TX_SIZE		64

  #define CDC3_STATUS_INTERFACE	4	// SerialUSB2
  #define CDC3_DATA_INTERFACE	5
  #define CDC3_ACM_ENDPOINT	8
  #define CDC3_RX_ENDPOINT	9
  #define CDC3_TX_ENDPOINT	10
  #define CDC3_ACM_SIZE		16
  #define CDC3_RX_SIZE		64
  #define CDC3_TX_SIZE		64

  #define RAWHID_INTERFACE      6	// RawHID
  #define RAWHID_TX_ENDPOINT    11
  #define RAWHID_TX_SIZE        64
  #define RAWHID_TX_INTERVAL    1
  #define RAWHID_RX_ENDPOINT    12
  #define RAWHID_RX_SIZE        64
  #define RAWHID_RX_INTERVAL    1

  #define ENDPOINT2_CONFIG	ENDPOINT_TRANSMIT_ONLY
  #define ENDPOINT3_CONFIG	ENDPOINT_RECEIVE_ONLY
  #define ENDPOINT4_CONFIG	ENDPOINT_TRANSMIT_ONLY

  #define ENDPOINT5_CONFIG	ENDPOINT_TRANSMIT_ONLY
  #define ENDPOINT6_CONFIG	ENDPOINT_RECEIVE_ONLY
  #define ENDPOINT7_CONFIG	ENDPOINT_TRANSMIT_ONLY

  #define ENDPOINT8_CONFIG	ENDPOINT_TRANSMIT_ONLY
  #define ENDPOINT9_CONFIG	ENDPOINT_RECEIVE_ONLY
  #define ENDPOINT10_CONFIG	ENDPOINT_TRANSMIT_ONLY

  #define ENDPOINT11_CONFIG	ENDPOINT_TRANSMIT_ONLY
  #define ENDPOINT12_CONFIG	ENDPOINT_RECEIVE_ONLY



yeld.cpp 
--------------------------------------
need to add USB_RAWHID_TRIPLESERIAL wherever USB_TRIPLE_SERIAL is. 
defined(USB_TRIPLE_SERIAL) || defined(USB_RAWHID_TRIPLESERIAL)


usb_inst.cpp
---------------------------------------
Add defined(USB_RAWHID_TRIPLESERIAL) to 
defined(USB_SERIAL) || defined(USB_DUAL_SERIAL) ||....

./platforms/teensy/builder/frameworks/arduino.py
---------------------------------------
Add USB_RAWHID_TRIPLESERIAL

to the section 
BUILTIN_USB_FLAGS = (



= Modifications required for teensy 4.1
* For this to work you need to modify the teensy source code to set the RAWHID iInterface field to 2 to use the product string
--------------------------------------
Around line 1191 in ~/.platformio/packages/framework-arduinoteensy/cores/teensy4/usb_desc.c
#ifdef RAWHID_INTERFACE
        // configuration for 480 Mbit/sec speed
        // interface descriptor, USB spec 9.6.5, page 267-269, Table 9-12
        9,                                      // bLength
        4,                                      // bDescriptorType
        RAWHID_INTERFACE,                       // bInterfaceNumber
        0,                                      // bAlternateSetting
        2,                                      // bNumEndpoints
        0x03,                                   // bInterfaceClass (0x03 = HID)
        0x00,                                   // bInterfaceSubClass
        0x00,                                   // bInterfaceProtocol
        2,                                      // iInterface

--------------------------------------
usb_desc.h 

#elif defined(USB_RAWHID_TRIPLESERIAL)
  #define VENDOR_ID             0x16C0
  #define PRODUCT_ID            0x048C
  #define RAWHID_USAGE_PAGE     0xFFAB  // recommended: 0xFF00 to 0xFFFF
  #define RAWHID_USAGE          0x0200  // recommended: 0x0100 to 0xFFFF
  #define MANUFACTURER_NAME     {'T','e','e','n','s','y','d','u','i','n','o'}
  #define MANUFACTURER_NAME_LEN 11
  #define PRODUCT_NAME          {'T','r','i','p','l','e',' ','S','e','r','i','a','l'}
  #define PRODUCT_NAME_LEN      13
  #define EP0_SIZE              64
  #define NUM_ENDPOINTS         9
  #define NUM_INTERFACE         7

  #define CDC_IAD_DESCRIPTOR    1       // Serial
  #define CDC_STATUS_INTERFACE  0
  #define CDC_DATA_INTERFACE    1
  #define CDC_ACM_ENDPOINT      2
  #define CDC_RX_ENDPOINT       3
  #define CDC_TX_ENDPOINT       3
  #define CDC_ACM_SIZE          16
  #define CDC_RX_SIZE_480       512
  #define CDC_TX_SIZE_480       512
  #define CDC_RX_SIZE_12        64
  #define CDC_TX_SIZE_12        64
  #define SEREMU_TX_SIZE        64

  #define CDC2_STATUS_INTERFACE 2       // SerialUSB1
  #define CDC2_DATA_INTERFACE   3
  #define CDC2_ACM_ENDPOINT     4
  #define CDC2_RX_ENDPOINT      5
  #define CDC2_TX_ENDPOINT      5

  #define CDC3_STATUS_INTERFACE 4       // SerialUSB2
  #define CDC3_DATA_INTERFACE   5
  #define CDC3_ACM_ENDPOINT     6
  #define CDC3_RX_ENDPOINT      7
  #define CDC3_TX_ENDPOINT      7

  #define RAWHID_INTERFACE      6       // RawHID
  #define RAWHID_TX_ENDPOINT    8
  #define RAWHID_TX_SIZE        64
  #define RAWHID_TX_INTERVAL    1        // TODO: is this ok for 480 Mbit speed
  #define RAWHID_RX_ENDPOINT    9
  #define RAWHID_RX_SIZE        64
  #define RAWHID_RX_INTERVAL    1        // TODO: is this ok for 480 Mbit speed

  #define ENDPOINT2_CONFIG      ENDPOINT_RECEIVE_UNUSED + ENDPOINT_TRANSMIT_INTERRUPT
  #define ENDPOINT3_CONFIG      ENDPOINT_RECEIVE_BULK + ENDPOINT_TRANSMIT_BULK
  #define ENDPOINT4_CONFIG      ENDPOINT_RECEIVE_UNUSED + ENDPOINT_TRANSMIT_INTERRUPT
  #define ENDPOINT5_CONFIG      ENDPOINT_RECEIVE_BULK + ENDPOINT_TRANSMIT_BULK
  #define ENDPOINT6_CONFIG      ENDPOINT_RECEIVE_UNUSED + ENDPOINT_TRANSMIT_INTERRUPT
  #define ENDPOINT7_CONFIG      ENDPOINT_RECEIVE_BULK + ENDPOINT_TRANSMIT_BULK
/* for raw hid */
  #define ENDPOINT8_CONFIG      ENDPOINT_RECEIVE_UNUSED + ENDPOINT_TRANSMIT_INTERRUPT
  #define ENDPOINT9_CONFIG      ENDPOINT_RECEIVE_INTERRUPT + ENDPOINT_TRANSMIT_UNUSED

---------------------------------------
./platforms/teensy/builder/frameworks/arduino.py
---------------------------------------
Add USB_RAWHID_TRIPLESERIAL

to the section 
BUILTIN_USB_FLAGS = (