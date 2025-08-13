#!/usr/bin/env python3
#requires pyusb 

import usb.core
import usb.util
import argparse
import os
import sys
import tty
import termios
import threading


class Terminal(object):
    def __init__(self, devicepath):

        self.devicepath = devicepath
        #self.rawhid = open(self.devicepath, "r+b")
        self.setup_hid()
        self.fd = sys.stdin.fileno()


        self.run = 1
        self.receiver_thread = threading.Thread(target=self.reader, name='reader')
        self.transmitter_thread = threading.Thread(target=self.writer, name='transmitter')

        self.transmitter_thread.daemon = True
        self.receiver_thread.daemon = True

    def setup_hid(self):
        dev = usb.core.find(idVendor=0x16c0, idProduct=0x0486)
        if dev is None:
            raise ValueError('Device not found')

        # get an endpoint instance
        for interface in dev.get_active_configuration():
            #if interface.bInterfaceNumber in  [1,2]:
            if dev.is_kernel_driver_active(interface.bInterfaceNumber):
                # Detach kernel drivers and claim through libusb
                dev.detach_kernel_driver(interface.bInterfaceNumber)
                usb.util.claim_interface(dev, interface.bInterfaceNumber)

        dev.set_configuration()
        self.dev = dev

    def runterminal(self):
        self.setup_terminal()
        self.receiver_thread.start()

        self.transmitter_thread.start()

        self.receiver_thread.join()
        self.transmitter_thread.join()

        self.restore_terminal()
        print("\r\n")

    def setup_terminal(self):
        self.old_settings = termios.tcgetattr(self.fd)
        tty.setraw(self.fd)

    def restore_terminal(self):
        tty.tcsetattr(self.fd, termios.TCSANOW, self.old_settings)


    def reader(self):
        while self.run:
            data = sys.stdin.buffer.read(1)
            #print ("{:02x}\r\n".format(data[0]))
            if data == b'~':
                self.run = 0
            output = bytearray(64)
            output[0] = data[0]
            self.dev.write(0x02,data)

    def writer(self):
        while self.run:
            data = []
            sret = ""
            try:
                data = self.dev.read(0x81, 64, 1000)
                sret = ''.join([chr(x) for x in data]).strip('\0')
            except:
                pass

            sys.stdout.buffer.write(sret.encode('utf-8', errors='backslashreplace'))
            sys.stdout.buffer.flush()

if __name__ == '__main__':
    t = Terminal(None)

    t.runterminal()
    sys.exit()
