#include "usb_names.h"

#define PRODUCT_NAME		{'C','M','S','I','S','-','D','A','P'}
#define PRODUCT_NAME_LEN	9

struct usb_string_descriptor_struct usb_string_product_name = {
  2 + PRODUCT_NAME_LEN * 2,
  3,
  PRODUCT_NAME
};

  #define MANUFACTURER_NAME     {'F','r','a','m','e','w','o','r','k'}
  #define MANUFACTURER_NAME_LEN 9

struct usb_string_descriptor_struct usb_string_manufacturer_name = {
        2 + MANUFACTURER_NAME_LEN * 2,
        3,
        MANUFACTURER_NAME
};