# Framework Light Debug Tool

A tool to connect to the computer debug interfaces was developed. It can either be used in a open case or closed case configuration. It's in an expansion card form factor, so it can be docked inside a DUT.

It's based around an FT4232 for ease of development and broad software tool support.













\# FTDI Channel usages:


Channel 1 is for:

JDB11, SPI interface



Channel 2 is for:

JSPI, SPI interface



Channel 3 is for:

JECDB, EC uart pins

CCD (either EC or AP, depending on which type-C port the user plugged it in)



Channel 4 is for:

JECDB, AP uart pins`

