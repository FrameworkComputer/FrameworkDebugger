#!/usr/bin/env python3
"""Bus Pirate 5 control tool using BPIO2 binmode.

Uses BPIO (CDC 1) for GPIO control and creates a Python PTY bridge so
external tools (uartupdatetool, tio) can talk through BPIO's UART.
No bridge mode, no USB reset, no button press needed.

The BP5 binmode port (CDC 1) is a single serial device — only one
process can use it at a time. To control GPIO while a PTY bridge is
running, use signals (see below) or combinable flags.

Wiring:
  BP5 IO4 (TX) --> EC CR_SIN1           (UART RX)
  BP5 IO5 (RX) <-- EC CR_SOUT1         (UART TX)
  BP5 IO6      --[4.7-10K R]--> EC CR_SOUT1/FLPRG1  (flash mode strap)
  BP5 IO7      --> EC VCC1_RST          (reset, active low)
  BP5 GND      --- EC GND

Usage:
  ./buspirate_ctrl.py --reset                          # Toggle EC reset
  ./buspirate_ctrl.py --reset-hold                     # Hold EC in reset
  ./buspirate_ctrl.py --log                            # Print EC UART output (Ctrl+C to stop)
  ./buspirate_ctrl.py --log --reset                    # Reset EC, print boot log
  ./buspirate_ctrl.py --pty-bridge                     # PTY bridge (Ctrl+C to stop)
  ./buspirate_ctrl.py --pty-bridge --reset             # Bridge, then reset (captures boot log)
  ./buspirate_ctrl.py --pty-bridge --enter-flash-mode  # Bridge + enter flash mode
  ./buspirate_ctrl.py --flash ./result/                # Full flash workflow
  ./buspirate_ctrl.py --flash ./result/ --no-reset     # Flash without reboot
  ./buspirate_ctrl.py --flash ./result/ --log          # Flash, reset, print boot log

Signal control (while --pty-bridge is running):
  kill -USR1 <pid>    # Toggle EC reset
  kill -USR2 <pid>    # Enter EC flash mode
"""

import argparse
import collections
import errno
import fcntl
import os
import select
import signal
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import serial.tools.list_ports

# Add upstream pybpio library to path
sys.path.insert(0, str(Path(__file__).parent / "BusPirate-BPIO2-flatbuffer-interface" / "python"))
from pybpio.bpio_client import BPIOClient


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IO_RST = 7
IO_FLPRG = 6

BP5_USB_VID = 0x1209
BP5_USB_PID = 0x7331

PTY_OVERFLOW_MAXLEN = 1024 * 1024  # 1MB max buffered data


# ---------------------------------------------------------------------------
# Port detection
# ---------------------------------------------------------------------------

def find_bp5_binport():
    """Find Bus Pirate 5 binmode (CDC 1) serial port.

    Matches USB VID:PID 1209:7331, then selects the port with
    interface string "Bus Pirate BIN". Falls back to sorted port
    list index 1 if interface strings are unavailable.
    """
    env_port = os.environ.get("BP5_BINPORT")
    if env_port:
        return env_port

    bp5_ports = [p for p in serial.tools.list_ports.comports()
                 if p.vid == BP5_USB_VID and p.pid == BP5_USB_PID]

    if not bp5_ports:
        return None

    for p in bp5_ports:
        iface = (p.interface or "").lower()
        if "bin" in iface:
            return p.device

    if len(bp5_ports) >= 2:
        return sorted(p.device for p in bp5_ports)[1]

    return None


# ---------------------------------------------------------------------------
# PTY Bridge
# ---------------------------------------------------------------------------

TIOCPKT = 0x5420


class PtyBridge:
    """Bidirectional bridge between BPIO UART and a PTY.

    All BPIO data is buffered in a Python deque. Nothing is written to
    the PTY master until a reader (tio, uartupdatetool) connects.

    TIOCPKT (packet mode) on the master generates status bytes when the
    slave's termios changes, which is how we detect a reader connecting.
    We delay 200ms after detection so tio's tcflush completes before
    we flush, preventing data loss.
    """

    def __init__(self, bp, debug=False):
        self.bp = bp
        self.debug = debug
        self._shutdown = threading.Event()
        self._slave_ready = threading.Event()
        self._buf = collections.deque(maxlen=PTY_OVERFLOW_MAXLEN)

        # Create PTY pair
        self._master_fd, self._slave_fd = os.openpty()
        os.set_blocking(self._master_fd, False)
        self.pty_path = os.ttyname(self._slave_fd)

        # Enable packet mode — reads from master get a status byte prefix.
        # Slave termios changes (tio connecting) produce status events.
        # Writes to master are unaffected by TIOCPKT.
        fcntl.ioctl(self._master_fd, TIOCPKT, struct.pack('i', 1))

        # Start worker threads
        self._reader_thread = threading.Thread(
            target=self._pty_reader_loop, daemon=True, name="pty-reader")
        self._async_thread = threading.Thread(
            target=self._bpio_async_loop, daemon=True, name="bpio-async")
        self._reader_thread.start()
        self._async_thread.start()

    def _flush_buf(self):
        """Try to flush Python buffer to PTY master."""
        while self._buf:
            chunk = self._buf[0]
            try:
                os.write(self._master_fd, chunk)
                self._buf.popleft()
            except OSError as e:
                if e.errno == errno.EAGAIN:
                    return  # Kernel buffer full, retry later
                raise

    def _write_to_master(self, data):
        """Buffer data. Only flush to PTY if a reader is connected."""
        if not data:
            return
        self._buf.append(bytes(data))
        if self._slave_ready.is_set():
            self._flush_buf()

    def _bpio_async_loop(self):
        """Poll BPIO for async UART data and buffer/forward to PTY."""
        while not self._shutdown.is_set():
            try:
                if self._slave_ready.is_set():
                    self._flush_buf()

                pkt = self.bp.check_async_data(timeout=0.05)
                if pkt and pkt.get('data_read'):
                    data = bytes(pkt['data_read'])
                    if self.debug:
                        printable = ''.join(
                            chr(b) if 0x20 <= b < 0x7f else '.'
                            for b in data)
                        print(f"[bpio→pty] {len(data)}B: {printable}",
                              file=sys.stderr)
                    self._write_to_master(data)
            except Exception as e:
                if not self._shutdown.is_set():
                    print(f"bpio-async error: {e}", file=sys.stderr)
                break

    def _pty_reader_loop(self):
        """Read from PTY master (TIOCPKT mode) and forward to BPIO."""
        poll = select.poll()
        poll.register(self._master_fd, select.POLLIN)

        while not self._shutdown.is_set():
            try:
                events = poll.poll(100)  # 100ms timeout
                if not events:
                    continue
                for fd, event in events:
                    if event & select.POLLIN:
                        data = os.read(self._master_fd, 4096)
                        if not data:
                            continue
                        # TIOCPKT: first byte is status, rest is payload
                        status = data[0]
                        if status == 0:
                            # Real data from reader (user typed in tio)
                            payload = data[1:]
                            if payload:
                                if self.debug:
                                    printable = ''.join(
                                        chr(b) if 0x20 <= b < 0x7f else '.'
                                        for b in payload)
                                    print(f"[pty→bpio] {len(payload)}B: "
                                          f"{printable}", file=sys.stderr)
                                self.bp.data_request(
                                    data_write=payload, bytes_read=0)
                        else:
                            # Status change — reader connected (termios set)
                            if not self._slave_ready.is_set():
                                # Wait for tio init (tcflush) to finish
                                time.sleep(0.2)
                                self._slave_ready.set()
                                buflen = sum(len(c) for c in self._buf)
                                print(f"Reader connected, flushing "
                                      f"{buflen} buffered bytes")
                    if event & (select.POLLHUP | select.POLLERR):
                        time.sleep(0.1)
            except OSError as e:
                if e.errno == errno.EIO:
                    time.sleep(0.1)
                    continue
                if not self._shutdown.is_set():
                    print(f"pty-reader error: {e}", file=sys.stderr)
                return

    def stop(self):
        """Shut down the bridge."""
        self._shutdown.set()
        self._reader_thread.join(timeout=2)
        self._async_thread.join(timeout=2)
        os.close(self._master_fd)
        os.close(self._slave_fd)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()


# ---------------------------------------------------------------------------
# GPIO functions
# ---------------------------------------------------------------------------

def gpio_reset(bp):
    """Assert RST briefly, then release."""
    bp.configuration_request(
        io_direction_mask=(1 << IO_RST),
        io_direction=(1 << IO_RST),
        io_value_mask=(1 << IO_RST),
        io_value=0,
    )
    time.sleep(0.5)
    bp.configuration_request(
        io_direction_mask=(1 << IO_RST),
        io_direction=0,  # input (released)
    )


def gpio_reset_hold(bp):
    """Assert RST and hold it low."""
    bp.configuration_request(
        io_direction_mask=(1 << IO_RST),
        io_direction=(1 << IO_RST),
        io_value_mask=(1 << IO_RST),
        io_value=0,
    )


def gpio_enter_flash_mode(bp, debug=False):
    """Assert FLPRG1 low, reset EC, wait for strap sampling, drive FLPRG1 high."""
    # Set IO_FLPRG (FLPRG1 strap) as output low
    bp.configuration_request(
        io_direction_mask=(1 << IO_FLPRG),
        io_direction=(1 << IO_FLPRG),
        io_value_mask=(1 << IO_FLPRG),
        io_value=0,
    )
    # Hold EC in reset
    bp.configuration_request(
        io_direction_mask=(1 << IO_RST),
        io_direction=(1 << IO_RST),
        io_value_mask=(1 << IO_RST),
        io_value=0,
    )
    time.sleep(0.5)
    # Release RST, keep FLPRG1 low
    bp.configuration_request(
        io_direction_mask=(1 << IO_RST),
        io_direction=0,
    )
    time.sleep(1.0)  # Wait for EC to sample FLPRG1 strap
    # Drive FLPRG1 HIGH (neutralizes the 10K resistor on shared IO5/IO6 line)
    bp.configuration_request(
        io_direction_mask=(1 << IO_FLPRG),
        io_direction=(1 << IO_FLPRG),
        io_value_mask=(1 << IO_FLPRG),
        io_value=(1 << IO_FLPRG),
    )
    time.sleep(0.1)
    if debug:
        print("Flash mode entry complete")


def gpio_release_all(bp):
    """Release all controlled GPIOs to input."""
    bp.configuration_request(
        io_direction_mask=(1 << IO_RST) | (1 << IO_FLPRG),
        io_direction=0,
    )


# ---------------------------------------------------------------------------
# BP5 lifecycle
# ---------------------------------------------------------------------------

def setup_bp5(port, debug=False):
    """Open BPIO client, verify connection, enable PSU and UART."""
    bp = BPIOClient(port, debug=debug)

    # Set write timeout so we don't block forever if BP5 isn't responding
    bp.serial_port.write_timeout = 2

    # Flush any stale data from previous sessions
    bp.serial_port.reset_input_buffer()
    bp.serial_port.reset_output_buffer()
    time.sleep(0.1)

    st = None
    for attempt in range(3):
        try:
            st = bp.status_request()
        except serial.SerialTimeoutException:
            if debug:
                print(f"  Status request attempt {attempt+1}/3: write timeout")
        if st:
            break
        time.sleep(0.5)

    if not st:
        bp.close()
        sys.exit(
            "BPIO2 status check failed.\n\n"
            "The BP5 default binmode is SUMP, not BPIO2.\n"
            "Connect to the BP5 terminal and run:\n"
            "  binmode  ->  select 2 (BPIO2 flatbuffer interface)  ->  save y\n"
            "This only needs to be done once.")

    fw_maj = st.get('version_firmware_major', 0)
    fw_min = st.get('version_firmware_minor', 0)
    print(f"Connected: FW v{fw_maj}.{fw_min}")

    print("Enabling PSU (3.3V for IO buffers)...")
    bp.configuration_request(psu_enable=True, psu_set_mv=3300)
    time.sleep(0.2)

    print("Configuring UART mode (115200 8N1)...")
    bp.configuration_request(mode="UART", mode_configuration={'speed': 115200})

    return bp


def cleanup_bp5(bp):
    """Disable PSU, return to HiZ, close."""
    try:
        bp.configuration_request(psu_disable=True)
        bp.configuration_request(mode="HiZ", mode_configuration={'speed': 0})
        bp.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def cmd_reset(bp):
    """Toggle reset: low then release."""
    print("Resetting EC...")
    gpio_reset(bp)
    print("Reset complete.")


def cmd_reset_hold(bp):
    """Hold EC in reset."""
    print("Holding EC in reset (IO7 low)...")
    gpio_reset_hold(bp)
    print("EC held in reset. Run --reset to release.")


def cmd_pty_bridge(bp, debug=False, reset_after_start=False):
    """Run PTY bridge until Ctrl+C. Supports signal-based control.

    SIGUSR1 → toggle EC reset
    SIGUSR2 → enter flash mode
    """
    with PtyBridge(bp, debug=debug) as bridge:
        pid = os.getpid()
        print(f"PTY bridge active: {bridge.pty_path}")
        print(f"PID: {pid}")
        print("Connect with:  tio %s" % bridge.pty_path)
        print("Reset EC:      kill -USR1 %d" % pid)
        print("Flash mode:    kill -USR2 %d" % pid)
        print("Press Ctrl+C to stop.")

        if reset_after_start:
            print("Resetting EC...")
            gpio_reset(bp)
            print("Reset complete. Boot log is being captured.")

        def on_usr1(signum, frame):
            print("\n[SIGUSR1] Resetting EC...")
            gpio_reset(bp)
            print("[SIGUSR1] Reset complete.")

        def on_usr2(signum, frame):
            print("\n[SIGUSR2] Entering flash mode...")
            gpio_enter_flash_mode(bp, debug=debug)
            print("[SIGUSR2] Flash mode entry complete.")

        signal.signal(signal.SIGUSR1, on_usr1)
        signal.signal(signal.SIGUSR2, on_usr2)

        try:
            while True:
                signal.pause()
        except KeyboardInterrupt:
            pass
    print("\nPTY bridge stopped.")


def cmd_log(bp, reset=False, debug=False):
    """Print BPIO async UART data to stdout until Ctrl+C.

    If reset=True, starts collection first then resets so no boot
    log bytes are dropped.
    """
    bp.clear_async_queue()

    if reset:
        print("Resetting EC...", file=sys.stderr)
        gpio_reset(bp)
        print("Reset complete. Logging EC output (Ctrl+C to stop)...",
              file=sys.stderr)
    else:
        print("Logging EC output (Ctrl+C to stop)...", file=sys.stderr)

    try:
        while True:
            pkt = bp.check_async_data(timeout=0.1)
            if pkt and pkt.get('data_read'):
                data = bytes(pkt['data_read'])
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
    except KeyboardInterrupt:
        pass
    print("\nLog stopped.", file=sys.stderr)


def cmd_flash(bp, firmware_dir, no_reset=False, log=False, debug=False):
    """Full flash workflow: enter flash mode, PTY bridge, uartupdatetool, reset."""
    fw_dir = Path(firmware_dir)
    ec_bin = fw_dir / "ec.bin"
    monitor_bin = fw_dir / "npcx_monitor.bin"

    if not ec_bin.exists() or not monitor_bin.exists():
        sys.exit(f"Error: ec.bin and/or npcx_monitor.bin not found in {fw_dir}")

    print(f"Firmware: {ec_bin}")

    # Enter flash mode
    print("Entering EC flash mode...")
    gpio_enter_flash_mode(bp, debug=debug)
    time.sleep(0.5)

    # Start PTY bridge
    with PtyBridge(bp, debug=debug) as bridge:
        pty_name = bridge.pty_path
        port_arg = pty_name.removeprefix("/dev/")
        print(f"PTY bridge: {pty_name}")

        script_dir = os.path.dirname(os.path.abspath(__file__))
        tool = os.path.join(script_dir, "uartupdatetool")

        print("Flashing monitor...")
        subprocess.run(
            [tool, "--port", port_arg, "--opr", "wr",
             "--addr", "0x200c3020", "--file", str(monitor_bin)],
            check=True,
        )

        print("Flashing ec.bin...")
        subprocess.run(
            [tool, "--port", port_arg, "--opr", "wr", "--auto",
             "--addr", "0x0000", "--file", str(ec_bin)],
            check=True,
        )

    print("Flash complete.")

    if log:
        # Start collecting before reset so no boot log is dropped
        bp.clear_async_queue()
        if not no_reset:
            print("Rebooting EC...")
            gpio_reset(bp)
        print("Logging EC output (Ctrl+C to stop)...", file=sys.stderr)
        try:
            while True:
                pkt = bp.check_async_data(timeout=0.1)
                if pkt and pkt.get('data_read'):
                    data = bytes(pkt['data_read'])
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
        except KeyboardInterrupt:
            pass
        print("\nLog stopped.", file=sys.stderr)
    else:
        if not no_reset:
            print("Rebooting EC...")
            gpio_reset(bp)
        print("Done.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Bus Pirate 5 control tool (BPIO2 binmode)")

    parser.add_argument("--port", default=None,
                        help="BP5 binmode port (default: auto-detect)")
    parser.add_argument("--debug", action="store_true",
                        help="Enable verbose debug output")

    # Primary action (mutually exclusive)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--reset-hold", action="store_true",
                       help="Hold EC in reset (IO7 low)")
    group.add_argument("--pty-bridge", action="store_true",
                       help="PTY bridge (blocks until Ctrl+C)")
    group.add_argument("--flash", metavar="DIR",
                       help="Full flash workflow with uartupdatetool")

    # Combinable flags
    parser.add_argument("--reset", action="store_true",
                        help="Toggle EC reset (combinable with --pty-bridge, --log)")
    parser.add_argument("--log", action="store_true",
                        help="Print EC UART output to stdout (combinable with --reset, --flash)")
    parser.add_argument("--enter-flash-mode", action="store_true",
                        help="Enter EC flash mode before primary action")
    parser.add_argument("--no-reset", action="store_true",
                        help="Skip reset after --flash")

    args = parser.parse_args()

    if not (args.reset or args.reset_hold or args.pty_bridge or args.flash or args.log):
        parser.error("One of --reset, --reset-hold, --pty-bridge, --flash, or --log is required")

    # Find port
    binmode_port = args.port or find_bp5_binport()
    if not binmode_port:
        sys.exit("Error: BP5 binmode port not found. "
                 "Set BP5_BINPORT or use --port")

    print(f"BP5 binmode: {binmode_port}")

    # Setup
    bp = setup_bp5(binmode_port, debug=args.debug)

    # Install signal handler for clean shutdown
    original_sigint = signal.getsignal(signal.SIGINT)

    def sigint_handler(signum, frame):
        signal.signal(signal.SIGINT, original_sigint)
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, sigint_handler)

    try:
        # Optional: enter flash mode before primary action
        if args.enter_flash_mode:
            print("Entering EC flash mode...")
            gpio_enter_flash_mode(bp, debug=args.debug)

        # Primary action
        if args.pty_bridge:
            cmd_pty_bridge(bp, debug=args.debug, reset_after_start=args.reset)
        elif args.reset_hold:
            cmd_reset_hold(bp)
        elif args.flash:
            cmd_flash(bp, args.flash, no_reset=args.no_reset,
                      log=args.log, debug=args.debug)
        elif args.log:
            cmd_log(bp, reset=args.reset, debug=args.debug)
        elif args.reset:
            cmd_reset(bp)
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        gpio_release_all(bp)
        cleanup_bp5(bp)


if __name__ == "__main__":
    main()
