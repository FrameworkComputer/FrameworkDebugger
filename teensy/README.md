# Multi purpose debugger - target controller

Supports:

- CMSIS-DAP
- Multiple serial terminals
- GPIO read/write/port register control.

Right now the backend uses raw hid reports for debug communication, terminal.py will open an interactive terminal to the device.

### Building

Pre-requisites:

- [Install PlatformIO](https://docs.platformio.org/en/latest/core/installation/index.html)

###### Pre-build

Build all of the platforms you need. It will fetch source and dependencies but
will fail! After this first attempt at building, the patches listed below need
to be applied.

```sh
pio run -e teensy41
pio run -e teensy31
pio run -e teensy36
```

###### Patching Arduino Source

Required for all teensy versions.

```sh
patch -d ~/.platformio/ -p0 < diff/arduino.py.diff
```

###### Patching Teensy3 Source

```sh
patch -d ~/.platformio/ -p0 < diff/teensy3/usb_desc.c.diff
patch -d ~/.platformio/ -p0 < diff/teensy3/usb_desc.h.diff
patch -d ~/.platformio/ -p0 < diff/teensy3/usb_inst.cpp.diff
patch -d ~/.platformio/ -p0 < diff/teensy3/yield.cpp.diff
```

###### Patching Teensy4 Source

```sh
patch -d ~/.platformio/ -p0 < diff/arduino.py.diff
patch -d ~/.platformio/ -p0 < diff/teensy4/usb_desc.c.diff
patch -d ~/.platformio/ -p0 < diff/teensy4/usb_desc.h.diff
patch -d ~/.platformio/ -p0 < diff/teensy4/usb_inst.cpp.diff
patch -d ~/.platformio/ -p0 < diff/teensy4/yield.cpp.diff
```

###### Build again

Now all the builds should succeed.

```sh
pio run -e teensy41
pio run -e teensy31
pio run -e teensy36
```

### Flashing to Teensy

Flash to whatever teensy hardware you have attached.

```sh
pio run -e teensy41 --target upload
pio run -e teensy31 --target upload
pio run -e teensy36 --target upload
```

### EC Serial

```sh
# For example with tio
tio /dev/serial/by-id/usb-Framework_CMSIS-DAP_13993040-if04

# Or picocom/minicom/screen
picocom /dev/ttyACM2 -b 115200
```

### Flashing EC firmware

Run the script for your target platform

```sh
./scripts/flash_tgl_ec.sh
./scripts/flash_adl_ec.sh
```

### Teensy Control Serial

Only for advanced usage, you can probably ignore this.

```sh
# For example with tio
tio /dev/serial/by-id/usb-Framework_CMSIS-DAP_13993040-if00

# Or picocom/minicom/screen
picocom /dev/ttyACM0 -b 115200
```
