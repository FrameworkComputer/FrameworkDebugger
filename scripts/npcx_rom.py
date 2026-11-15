"""Checked, read-only NPCX UART ROM protocol (no PTY or text decoding).

Protocol/geometry follow Chromium EC util/uut/{cmd.cc,lib_crc.cc,main.cc}.
Only the Lilac NPCX993 path has been exercised on hardware. A CRC validates
each block; read retries resynchronize because responses have no address/tag.
"""
import queue
import time


FLASH_BASE = 0x64000000
DEVICE_ID = 0x400C1022
CHIP_ID = 0x400C101C
# (device, chip): physical flash capacity, from uartupdatetool's chip table.
FLASH_SIZES = {
    (0x21, 0x06): 1024 * 1024,
    (0x21, 0x07): 1024 * 1024,
    (0x29, 0x07): 512 * 1024,
    (0x20, 0x07): 512 * 1024,
    (0x24, 0x07): 1024 * 1024,
    (0x2C, 0x07): 512 * 1024,
    (0x25, 0x09): 512 * 1024,
    (0x21, 0x09): 512 * 1024,
    (0x22, 0x09): 1024 * 1024,
    (0x2B, 0x09): 1024 * 1024,
    (0x62, 0x09): 512 * 1024,
}


class RomError(RuntimeError):
    """ROM synchronization, read validation or deadline failed."""


def crc16(data):
    """ROM CRC-16: reflected polynomial 0xa001, initial zero."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc


class RomReader:
    """Raw RX sink plus stop-and-wait ROM reader; never writes target memory.

    Install as the exclusive UART RX sink while active. ``send`` transmits
    raw bytes and must raise on transport failure. All operations share the
    caller's monotonic deadline. Only reads/synchronization are retried.
    """

    def __init__(self, send, deadline, *, attempts=10, response_timeout=0.25):
        self.send = send
        self.deadline = deadline
        self.attempts = attempts
        self.response_timeout = response_timeout
        self.retries = 0
        self._rx = queue.Queue()

    def feed(self, data):
        self._rx.put(bytes(data))

    def fail(self, error):
        self._rx.put(error)

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise RomError("NPCX ROM operation timed out")
        return remaining

    def _receive(self, size, timeout):
        data = bytearray()
        deadline = min(self.deadline, time.monotonic() + timeout)
        while len(data) < size:
            remaining = min(self.remaining(), deadline - time.monotonic())
            if remaining <= 0:
                break
            try:
                chunk = self._rx.get(timeout=remaining)
            except queue.Empty:
                break
            if isinstance(chunk, Exception):
                raise RomError(f"UART reader failed: {chunk}") from chunk
            data.extend(chunk)
        return bytes(data)

    def _drain(self):
        # Wait for a quiet interval, rather than just clearing bytes already
        # queued: the remainder of a short response may still be in flight.
        while True:
            try:
                chunk = self._rx.get(timeout=min(0.05, self.remaining()))
            except queue.Empty:
                return
            if isinstance(chunk, Exception):
                raise RomError(f"UART reader failed: {chunk}") from chunk

    def sync(self):
        for _ in range(3):
            self._drain()
            self.send(b'\x55')
            if self._receive(1, 2) == b'\x5a':
                return
        raise RomError("NPCX ROM synchronization failed")

    def read(self, address, size):
        if not 1 <= size <= 128:
            raise ValueError("NPCX read size must be 1..128 bytes")
        command = bytes([0x1C, size - 1]) + address.to_bytes(4, 'big')
        command += crc16(command).to_bytes(2, 'big')
        reason = "no response"
        for _ in range(self.attempts):
            self.remaining()
            self.send(command)
            response = self._receive(size + 3, self.response_timeout)
            if len(response) != size + 3:
                reason = f"short/oversized response ({len(response)}/{size + 3})"
            elif response[0] != 0x1C:
                reason = f"wrong response command {response[0]:#x}"
            elif crc16(response[:-2]) != int.from_bytes(response[-2:], 'big'):
                reason = "CRC mismatch"
            else:
                return response[1:-2]
            self.retries += 1
            # A synchronization reply is ordered after previous read replies;
            # do not mistake a delayed valid old block for the next address.
            self.sync()
        raise RomError(f"NPCX read at {address:#010x} failed: {reason}")

    def flash_size(self):
        device = self.read(DEVICE_ID, 1)[0]
        chip = self.read(CHIP_ID, 1)[0]
        try:
            return FLASH_SIZES[device, chip]
        except KeyError:
            raise RomError(f"Unsupported NPCX device/chip {device:#04x}/{chip:#04x}") from None

    def read_flash(self, size):
        data = bytearray()
        for offset in range(0, size, 128):
            data.extend(self.read(FLASH_BASE + offset, min(128, size - offset)))
        return bytes(data)
