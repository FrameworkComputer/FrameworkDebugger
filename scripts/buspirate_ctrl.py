#!/usr/bin/env python3
"""Bus Pirate 5 control tool using BPIO2 binmode.

Uses BPIO (CDC 1) for GPIO control and creates a Python PTY bridge so
external tools (uartupdatetool, tio) can talk through BPIO's UART.
No bridge mode, no USB reset, no button press needed.

The BP5 binmode port (CDC 1) is a single serial device — only one
process can use it at a time. To control GPIO while a PTY bridge is
running, use signals (see below) or combinable flags.

Wiring:
  BP5 IO3      --> EC VCC1_RST          (reset, active low)
  BP5 IO4 (TX) --> EC CR_SIN1           (UART RX)
  BP5 IO5 (RX) <-- EC CR_SOUT1         (UART TX)
  BP5 IO7      --[4.7-10K R]--> EC CR_SOUT1/FLPRG1  (flash mode strap)
  BP5 GND      --- EC GND

Usage:
  ./buspirate_ctrl.py --reset                          # Toggle EC reset
  ./buspirate_ctrl.py --reset-hold                     # Hold EC in reset
  ./buspirate_ctrl.py --log                            # Print EC UART output (Ctrl+C to stop)
  ./buspirate_ctrl.py --log --reset                    # Reset EC, print boot log
  ./buspirate_ctrl.py --pty-bridge                     # PTY bridge (Ctrl+C to stop)
  ./buspirate_ctrl.py --pty-bridge --reset             # Bridge, then reset (captures boot log)
  ./buspirate_ctrl.py --pty-bridge --enter-flash-mode  # Bridge + enter flash mode
  ./buspirate_ctrl.py --flash ./result/                # Full flash workflow (RO+RW)
  ./buspirate_ctrl.py --flash ./result/ --section rw   # Flash only the RW section
  ./buspirate_ctrl.py --flash ./result/ --section ro   # Flash only the RO section
  ./buspirate_ctrl.py --flash ./result/ --no-reset     # Flash without reboot
  ./buspirate_ctrl.py --flash ./result/ --log          # Flash, reset, print boot log
  ./buspirate_ctrl.py --dump flash.bin                 # Dump EC's current flash to a file
  ./buspirate_ctrl.py --fmap ./result/                 # Print ec.bin FMAP layout (no hardware)

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
import tempfile
import threading
import time
from pathlib import Path

# NOTE: pyserial and pybpio are imported lazily inside the functions that
# talk to hardware, so offline commands (e.g. --fmap) work without them.


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IO_RST = 3
IO_FLPRG = 7

BP5_USB_VID = 0x1209
BP5_USB_PID = 0x7331

PTY_OVERFLOW_MAXLEN = 1024 * 1024  # 1MB max buffered data

SCRIPT_DIR = Path(__file__).parent.resolve()
UARTUPDATETOOL = str(SCRIPT_DIR / "uartupdatetool")
# npcx_monitor.bin is the flash-service stub loaded into EC SRAM. It is
# chip-level (npcx9), identical across boards, so a copy is bundled here
# and used when a firmware dir doesn't provide one.
BUNDLED_MONITOR = SCRIPT_DIR / "npcx_monitor.bin"

# The NPCX bootrom loads the monitor to this SRAM address and executes it.
MONITOR_LOAD_ADDR = "0x200c3020"


# ---------------------------------------------------------------------------
# Port detection
# ---------------------------------------------------------------------------

def find_bp5_binport():
    """Find Bus Pirate 5 binmode (CDC 1) serial port.

    Matches USB VID:PID 1209:7331, then selects the port with
    interface string "Bus Pirate BIN". Falls back to sorted port
    list index 1 if interface strings are unavailable.
    """
    import serial.tools.list_ports

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

    def __init__(self, bp, debug=False, stats=False):
        self.bp = bp
        self.debug = debug
        self.stats = stats
        self._shutdown = threading.Event()
        self._slave_ready = threading.Event()
        self._buf = collections.deque(maxlen=PTY_OVERFLOW_MAXLEN)

        # Lightweight throughput counters (see print_stats). Maintained
        # cheaply on the hot path; _buf_bytes mirrors bytes queued in _buf.
        self._buf_bytes = 0
        self._s = {
            'bpio_bytes': 0,    # bytes received from BPIO async UART
            'bpio_chunks': 0,   # async DataResponse chunks received
            'pty_bytes': 0,     # bytes written out to the PTY master
            'eagain': 0,        # PTY-full events (consumer too slow)
            'max_buf_bytes': 0,  # peak backlog queued toward the PTY
            'max_gap_ms': 0.0,  # longest gap between async chunks
            'max_qdepth': 0,    # peak depth of pybpio's async_queue
        }
        self._last_rx = None
        self._last_report = None

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

    def _async_qsize(self):
        """Depth of pybpio's async queue (0 if the internal API is absent)."""
        try:
            return self.bp._async_queue.qsize()
        except Exception:
            return 0

    def _flush_buf(self):
        """Try to flush Python buffer to PTY master."""
        while self._buf:
            chunk = self._buf[0]
            try:
                os.write(self._master_fd, chunk)
                self._buf.popleft()
                self._buf_bytes -= len(chunk)
                self._s['pty_bytes'] += len(chunk)
            except OSError as e:
                if e.errno == errno.EAGAIN:
                    self._s['eagain'] += 1
                    return  # Kernel buffer full, retry later
                raise

    def _write_to_master(self, data):
        """Buffer data. Only flush to PTY if a reader is connected."""
        if not data:
            return
        self._buf.append(bytes(data))
        self._buf_bytes += len(data)
        if self._buf_bytes > self._s['max_buf_bytes']:
            self._s['max_buf_bytes'] = self._buf_bytes
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
                    if self.stats:
                        now = time.monotonic()
                        self._s['bpio_bytes'] += len(data)
                        self._s['bpio_chunks'] += 1
                        if self._last_rx is not None:
                            gap = (now - self._last_rx) * 1000.0
                            if gap > self._s['max_gap_ms']:
                                self._s['max_gap_ms'] = gap
                        self._last_rx = now
                        qd = self._async_qsize()
                        if qd > self._s['max_qdepth']:
                            self._s['max_qdepth'] = qd
                        if self._last_report is None or now - self._last_report > 2.0:
                            self._last_report = now
                            print(f"[dump] rx {self._s['bpio_bytes']}B "
                                  f"in {self._s['bpio_chunks']} chunks "
                                  f"({self._s['bpio_bytes'] / max(1, self._s['bpio_chunks']):.1f} B/chunk), "
                                  f"buf {self._buf_bytes}B, "
                                  f"eagain {self._s['eagain']}, "
                                  f"asyncq {qd}", file=sys.stderr)
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
                                print(f"Reader connected, flushing "
                                      f"{self._buf_bytes} buffered bytes")
                    if event & (select.POLLHUP | select.POLLERR):
                        time.sleep(0.1)
            except OSError as e:
                if e.errno == errno.EIO:
                    time.sleep(0.1)
                    continue
                if not self._shutdown.is_set():
                    print(f"pty-reader error: {e}", file=sys.stderr)
                return

    def print_stats(self, expected=None):
        """Print throughput counters gathered during the session.

        expected is the payload size we hoped to receive from the EC; if
        bpio_bytes falls short of it, bytes were lost at/before the BP5
        (device or USB) rather than in our host-side bridge.
        """
        s = self._s
        print("--- bridge stats ---", file=sys.stderr)
        print(f"  bytes from BPIO (UART RX): {s['bpio_bytes']} "
              f"in {s['bpio_chunks']} chunks", file=sys.stderr)
        print(f"  bytes written to PTY:      {s['pty_bytes']}", file=sys.stderr)
        print(f"  still queued in bridge:    {self._buf_bytes}", file=sys.stderr)
        print(f"  peak bridge backlog:       {s['max_buf_bytes']} bytes",
              file=sys.stderr)
        print(f"  PTY-full (EAGAIN) events:  {s['eagain']}", file=sys.stderr)
        print(f"  avg chunk size:            "
              f"{s['bpio_bytes'] / max(1, s['bpio_chunks']):.1f} bytes",
              file=sys.stderr)
        print(f"  max gap between chunks:    {s['max_gap_ms']:.1f} ms",
              file=sys.stderr)
        print(f"  peak async-queue depth:    {s['max_qdepth']}", file=sys.stderr)
        if expected is not None:
            delta = s['bpio_bytes'] - expected
            note = ("device/USB-side loss (BP5 delivered fewer bytes than the "
                    "EC sent)" if delta < 0 else
                    "BP5 delivered the full payload; any corruption is "
                    "host-side (bridge/uartupdatetool timing)")
            print(f"  vs expected {expected}: {delta:+d} bytes -> {note}",
                  file=sys.stderr)

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
    # Drive FLPRG1 HIGH (neutralizes the 10K resistor on shared EC TX/FLPRG1 line)
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
    import serial
    sys.path.insert(0, str(
        Path(__file__).parent / "BusPirate-BPIO2-flatbuffer-interface" / "python"))
    from pybpio.bpio_client import BPIOClient

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
    fw_hash = st.get('version_firmware_git_hash')
    fw_date = st.get('version_firmware_date')
    extra = f" ({fw_hash} {fw_date})" if (fw_hash or fw_date) else ""
    print(f"Connected: FW v{fw_maj}.{fw_min}{extra}")

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
# Firmware image / flash section layout
# ---------------------------------------------------------------------------

# FMAP header: signature + ver + base + size + name + nareas
_FMAP_HDR = struct.Struct("<8sBBQI32sH")
# FMAP area: offset + size + name + flags
_FMAP_AREA = struct.Struct("<II32sH")


def parse_fmap(data):
    """Parse the FMAP embedded in an EC image.

    Returns {area_name: (offset, size)} or None if no valid FMAP found.
    Cros/Zephyr EC images embed an FMAP describing WP_RO, EC_RW, etc.
    """
    idx = data.find(b"__FMAP__")
    if idx < 0:
        return None
    try:
        _, _, _, _, _, _, nareas = _FMAP_HDR.unpack_from(data, idx)
        areas = {}
        pos = idx + _FMAP_HDR.size
        for _ in range(nareas):
            off, size, name, _flags = _FMAP_AREA.unpack_from(data, pos)
            areas[name.split(b"\x00")[0].decode("ascii", "replace")] = (off, size)
            pos += _FMAP_AREA.size
        return areas
    except struct.error:
        return None


def print_fmap(path):
    """Parse and print the FMAP of an EC image (a file or a dir with ec.bin)."""
    p = Path(path)
    if p.is_dir():
        p = p / "ec.bin"
    if not p.exists():
        sys.exit(f"Error: {p} not found")

    data = p.read_bytes()
    areas = parse_fmap(data)
    if not areas:
        sys.exit(f"No FMAP found in {p}")

    print(f"FMAP for {p} ({len(data)} bytes):")
    print(f"  {'AREA':<22} {'OFFSET':>10} {'SIZE':>10} {'END':>10}")
    for name, (off, size) in areas.items():
        print(f"  {name:<22} {off:#010x} {size:#010x} {off + size:#010x}")


def section_bounds(data, section):
    """Return (flash_offset, length) of the requested section within data.

    section is "all", "ro", or "rw". RO/RW bounds come from the image's
    FMAP (WP_RO / EC_RW areas); if absent, fall back to a half-image split.
    """
    if section == "all":
        return 0, len(data)

    areas = parse_fmap(data)
    if areas and "WP_RO" in areas and "EC_RW" in areas:
        ro_off, ro_size = areas["WP_RO"]
        rw_off, rw_size = areas["EC_RW"]
    else:
        half = len(data) // 2
        ro_off, ro_size = 0, half
        rw_off, rw_size = half, len(data) - half

    if section == "ro":
        return ro_off, ro_size
    return rw_off, rw_size


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
    print("Holding EC in reset (RST low)...")
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


def cmd_flash(bp, firmware_dir, section="all", no_reset=False, log=False, debug=False):
    """Full flash workflow: enter flash mode, PTY bridge, uartupdatetool, reset.

    section selects which part of ec.bin to program: "all" (default),
    "ro", or "rw". For "ro"/"rw" only that region is erased and written,
    leaving the other region untouched.
    """
    fw_dir = Path(firmware_dir)
    ec_bin = fw_dir / "ec.bin"

    if not ec_bin.exists():
        sys.exit(f"Error: ec.bin not found in {fw_dir}")

    # Prefer the firmware dir's monitor; fall back to the bundled copy.
    monitor_bin = fw_dir / "npcx_monitor.bin"
    if not monitor_bin.exists():
        monitor_bin = BUNDLED_MONITOR

    # Determine which slice of the image to program.
    image = ec_bin.read_bytes()
    flash_off, length = section_bounds(image, section)
    payload = image[flash_off:flash_off + length]

    print(f"Firmware: {ec_bin}")
    print(f"Section:  {section} "
          f"(flash 0x{flash_off:06x}..0x{flash_off + len(payload):06x}, "
          f"{len(payload)} bytes)")

    # Enter flash mode
    print("Entering EC flash mode...")
    gpio_enter_flash_mode(bp, debug=debug)
    time.sleep(0.5)

    # Start PTY bridge
    with PtyBridge(bp, debug=debug) as bridge:
        pty_name = bridge.pty_path
        port_arg = pty_name.removeprefix("/dev/")
        print(f"PTY bridge: {pty_name}")

        print("Flashing monitor...")
        subprocess.run(
            [UARTUPDATETOOL, "--port", port_arg, "--opr", "wr",
             "--addr", MONITOR_LOAD_ADDR, "--file", str(monitor_bin)],
            check=True,
        )

        if section == "all":
            print("Flashing ec.bin...")
            subprocess.run(
                [UARTUPDATETOOL, "--port", port_arg, "--opr", "wr", "--auto",
                 "--addr", "0x0000", "--file", str(ec_bin)],
                check=True,
            )
        else:
            # Write only the selected region at its flash offset. uartupdatetool
            # writes the whole --file, so hand it just the region's bytes.
            with tempfile.NamedTemporaryFile(
                    suffix=f"_{section}.bin", delete=False) as tf:
                tf.write(payload)
                slice_path = tf.name
            try:
                print(f"Flashing {section} section...")
                subprocess.run(
                    [UARTUPDATETOOL, "--port", port_arg, "--opr", "wr", "--auto",
                     "--offset", f"0x{flash_off:x}", "--file", slice_path],
                    check=True,
                )
            finally:
                os.unlink(slice_path)

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


def cmd_dump(bp, out_file, monitor=None, no_reset=False, debug=False):
    """Dump the EC's current flash contents to a file.

    Reading flash needs npcx_monitor.bin loaded into SRAM first, same as
    writing. Uses the bundled monitor unless one is given.
    """
    monitor_bin = Path(monitor) if monitor else BUNDLED_MONITOR
    if monitor_bin.is_dir():
        monitor_bin = monitor_bin / "npcx_monitor.bin"
    if not monitor_bin.exists():
        sys.exit(f"Error: npcx_monitor.bin not found at {monitor_bin}")
    out = Path(out_file)

    print(f"Monitor: {monitor_bin}")
    print(f"Output:  {out}")

    # Enter flash mode
    print("Entering EC flash mode...")
    gpio_enter_flash_mode(bp, debug=debug)
    time.sleep(0.5)

    with PtyBridge(bp, debug=debug, stats=True) as bridge:
        port_arg = bridge.pty_path.removeprefix("/dev/")
        print(f"PTY bridge: {bridge.pty_path}")

        print("Flashing monitor...")
        subprocess.run(
            [UARTUPDATETOOL, "--port", port_arg, "--opr", "wr",
             "--addr", MONITOR_LOAD_ADDR, "--file", str(monitor_bin)],
            check=True,
        )

        print("Reading flash (this can take a while at 115200)...")
        rc = subprocess.run(
            [UARTUPDATETOOL, "--port", port_arg, "--read-flash",
             "--file", str(out)],
        ).returncode

        out_size = out.stat().st_size if out.exists() else None
        bridge.print_stats(expected=out_size)

    if rc != 0:
        print(f"WARNING: uartupdatetool exited {rc}; dump may be incomplete.",
              file=sys.stderr)
    print(f"Flash dumped to {out} ({out.stat().st_size} bytes)")

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
                       help="Hold EC in reset (RST low)")
    group.add_argument("--pty-bridge", action="store_true",
                       help="PTY bridge (blocks until Ctrl+C)")
    group.add_argument("--flash", metavar="DIR",
                       help="Full flash workflow with uartupdatetool")
    group.add_argument("--dump", metavar="OUTFILE",
                       help="Dump the EC's current flash to OUTFILE")
    group.add_argument("--fmap", metavar="PATH",
                       help="Print the FMAP of an ec.bin (file or dir) and exit")

    # Combinable flags
    parser.add_argument("--reset", action="store_true",
                        help="Toggle EC reset (combinable with --pty-bridge, --log)")
    parser.add_argument("--log", action="store_true",
                        help="Print EC UART output to stdout (combinable with --reset, --flash)")
    parser.add_argument("--enter-flash-mode", action="store_true",
                        help="Enter EC flash mode before primary action")
    parser.add_argument("--no-reset", action="store_true",
                        help="Skip reset after --flash/--dump")
    parser.add_argument("--section", choices=["all", "ro", "rw"], default="all",
                        help="Which ec.bin region to flash (default: all)")
    parser.add_argument("--monitor", metavar="PATH", default=None,
                        help="npcx_monitor.bin file or dir (default: bundled copy)")

    args = parser.parse_args()

    # Offline command: no BP5 hardware needed.
    if args.fmap:
        print_fmap(args.fmap)
        return

    if not (args.reset or args.reset_hold or args.pty_bridge or args.flash
            or args.dump or args.log):
        parser.error("One of --reset, --reset-hold, --pty-bridge, --flash, "
                     "--dump, or --log is required")

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
            cmd_flash(bp, args.flash, section=args.section,
                      no_reset=args.no_reset, log=args.log, debug=args.debug)
        elif args.dump:
            cmd_dump(bp, args.dump, monitor=args.monitor,
                     no_reset=args.no_reset, debug=args.debug)
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
