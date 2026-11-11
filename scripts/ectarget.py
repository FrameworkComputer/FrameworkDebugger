"""Library for driving an EC through a Bus Pirate 5 (BPIO2 binmode).

Meant for automated testing: every operation raises on failure, every
wait has a timeout, and all EC console output is captured (optionally
to a timestamped log file) for as long as the target is open.

Wiring:
  BP5 IO3      --> EC VCC1_RST          (reset, active low)
  BP5 IO4 (TX) --> EC CR_SIN1           (UART RX)
  BP5 IO5 (RX) <-- EC CR_SOUT1          (UART TX)
  BP5 IO7      --[4.7-10K R]--> EC CR_SOUT1/FLPRG1  (flash mode strap)
  BP5 GND      --- EC GND

Example:
    from ectarget import EcTarget

    with EcTarget(logfile="ec.log") as ec:
        ec.flash("result/")
        ec.reset()
        ec.expect(r"Inits done", timeout=10)
        print(ec.command("version"))
"""

import collections
import contextlib
import errno
import fcntl
import io
import os
import re
import select
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import serial
import serial.tools.list_ports

sys.path.insert(0, str(Path(__file__).resolve().parent
                       / "BusPirate-BPIO2-flatbuffer-interface" / "python"))
from pybpio.bpio_client import BPIOClient  # noqa: E402


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IO_RST = 3
IO_FLPRG = 7

BP5_USB_VID = 0x1209
BP5_USB_PID = 0x7331
BP5_DEFAULT_BINPORT = "/dev/serial/by-id/usb-Bus_Pirate_Bus_Pirate_5_5buspirate-if02"

SCRIPT_DIR = Path(__file__).resolve().parent
UARTUPDATETOOL = SCRIPT_DIR / "uartupdatetool"
MONITOR_LOAD_ADDR = "0x200c3020"

DEFAULT_PROMPT = "ec:~> "

PTY_BUF_MAX_BYTES = 1024 * 1024
TIOCPKT = 0x5420

# ANSI CSI sequences (cursor moves, erase) the Zephyr shell emits when
# it redraws the prompt around log lines.
_ANSI_RE = re.compile(rb"\x1b\[[0-9;?]*[ -/]*[@-~]")
# A trailing, possibly incomplete escape sequence split across chunks.
_ANSI_PARTIAL_RE = re.compile(rb"\x1b(\[[0-9;?]*[ -/]*)?$")
# Zephyr EC version string as embedded in ec.bin, e.g. lilac-0.0.0-9709bdd
_VERSION_RE = re.compile(rb"([a-z][a-z0-9_]*-\d+\.\d+\.\d+-[0-9a-f]{7,})")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class EcTargetError(Exception):
    """Base class for all errors raised by this module."""


class BpioError(EcTargetError):
    """A BPIO request to the Bus Pirate failed."""


class ExpectTimeout(EcTargetError):
    """expect() did not see the pattern before the timeout."""

    def __init__(self, pattern, timeout, recent):
        self.pattern = pattern
        self.timeout = timeout
        self.recent = recent
        super().__init__(
            f"Timed out after {timeout}s waiting for {pattern!r}. "
            f"Last output:\n{recent}")


class FlashError(EcTargetError):
    """uartupdatetool failed or timed out."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_bp5_binport():
    """Find the Bus Pirate 5 binmode (CDC 1) serial port, or None.

    Uses BP5_BINPORT if set, else BP5_DEFAULT_BINPORT if it exists.
    Otherwise matches USB VID:PID 1209:7331 and picks the interface
    named "Bus Pirate BIN", falling back to the second port by name.
    """
    env_port = os.environ.get("BP5_BINPORT")
    if env_port:
        return env_port

    if os.path.exists(BP5_DEFAULT_BINPORT):
        return BP5_DEFAULT_BINPORT

    bp5_ports = [p for p in serial.tools.list_ports.comports()
                 if p.vid == BP5_USB_VID and p.pid == BP5_USB_PID]
    for p in bp5_ports:
        if "bin" in (p.interface or "").lower():
            return p.device
    if len(bp5_ports) >= 2:
        return sorted(p.device for p in bp5_ports)[1]
    return None


def find_port_users(port):
    """Return [(pid, name)] of other processes holding `port` open.

    Scans /proc/*/fd; only sees processes we're allowed to inspect.
    """
    try:
        target = os.stat(port).st_rdev
    except OSError:
        return []
    users = []
    me = os.getpid()
    for pid in filter(str.isdigit, os.listdir("/proc")):
        if int(pid) == me:
            continue
        fd_dir = f"/proc/{pid}/fd"
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        for fd in fds:
            try:
                st = os.stat(f"{fd_dir}/{fd}")
            except OSError:
                continue
            if st.st_rdev == target and (st.st_mode & 0o170000) == 0o020000:
                try:
                    with open(f"/proc/{pid}/comm") as f:
                        name = f.read().strip()
                except OSError:
                    name = "?"
                users.append((int(pid), name))
                break
    return users


def image_version(ec_bin):
    """Return the version string embedded in an ec.bin, or None."""
    m = _VERSION_RE.search(Path(ec_bin).read_bytes())
    return m.group(1).decode() if m else None


_PROGRESS_RE = re.compile(r"^\[\d+%\] \d+/\d+$")


def _drop_progress(text):
    """Drop uartupdatetool's per-block progress lines, keeping the last."""
    lines = text.splitlines()
    progress = [i for i, ln in enumerate(lines) if _PROGRESS_RE.match(ln)]
    drop = set(progress[:-1])
    return "".join(ln + "\n" for i, ln in enumerate(lines) if i not in drop)


def resolve_firmware(path):
    """Return (ec_bin, monitor_bin) for a build dir or a single ec.bin.

    A build dir must contain ec.bin and npcx_monitor.bin. For a single
    file, npcx_monitor.bin is taken from this script's directory.
    """
    path = Path(path).expanduser()
    if path.is_dir():
        ec_bin = path / "ec.bin"
        monitor_bin = path / "npcx_monitor.bin"
    else:
        ec_bin = path
        monitor_bin = SCRIPT_DIR / "npcx_monitor.bin"
    for f in (ec_bin, monitor_bin):
        if not f.is_file():
            raise FileNotFoundError(f"{f} not found")
    return ec_bin, monitor_bin


# ---------------------------------------------------------------------------
# Log file
# ---------------------------------------------------------------------------

class _TimestampedLog:
    """Writes EC output to a file, prefixing each line with host time."""

    def __init__(self, path):
        self._f = open(path, "a", buffering=1, encoding="utf-8",
                       errors="replace")
        self._t0 = time.monotonic()
        self._at_line_start = True
        self._lock = threading.Lock()

    def note(self, msg):
        """Write a marker line (e.g. '--- reset ---') into the log."""
        with self._lock:
            self._note(msg)

    def _note(self, msg):
        if not self._at_line_start:
            self._f.write("\n")
        self._f.write(f"[{self._stamp()}] ### {msg}\n")
        self._at_line_start = True

    def write(self, text):
        with self._lock:
            self._write(text)

    def _write(self, text):
        for part in text.splitlines(keepends=True):
            if self._at_line_start:
                self._f.write(f"[{self._stamp()}] ")
            self._f.write(part)
            self._at_line_start = part.endswith("\n")

    def _stamp(self):
        return f"{time.monotonic() - self._t0:10.3f}"

    def close(self):
        with self._lock:
            if not self._at_line_start:
                self._f.write("\n")
            self._f.close()


# ---------------------------------------------------------------------------
# EcTarget
# ---------------------------------------------------------------------------

class EcTarget:
    """An EC reachable through a Bus Pirate 5.

    Opening it (constructor or `with`) connects to BPIO, enables the
    PSU for the IO buffers, switches to UART mode and starts capturing
    console output. close() releases the GPIOs and returns to HiZ.

    Console output is cleaned (ANSI escapes, CR and NUL removed) before
    being matched by expect()/command(). Raw bytes can be observed by
    passing on_data, a callable receiving each raw chunk.
    """

    def __init__(self, port=None, *, baud=115200, logfile=None,
                 prompt=DEFAULT_PROMPT, configure=True, on_data=None,
                 debug=False):
        self.port = port or find_bp5_binport()
        if not self.port:
            raise EcTargetError(
                "BP5 binmode port not found. Set BP5_BINPORT or pass port=")
        users = find_port_users(self.port)
        if users:
            procs = ", ".join(f"{n} (pid {p})" for p, n in users)
            raise EcTargetError(f"{self.port} is already open by: {procs}")

        self.prompt = prompt
        self.debug = debug
        self.on_data = on_data

        self._lock = threading.RLock()       # serializes BPIO requests
        self._cond = threading.Condition()   # guards console buffer
        self._console = ""                   # cleaned console text
        self._cursor = 0                     # expect() position
        self._last_rx = time.monotonic()
        self._partial = b""                  # incomplete ANSI escape
        self._sink = None                    # PTY bridge, when active
        self._shutdown = threading.Event()
        self._reader = None
        self._log = _TimestampedLog(logfile) if logfile else None

        self.bp = BPIOClient(self.port, debug=debug)
        if not self.bp.serial_port:
            raise BpioError(f"Could not open {self.port}")
        self.bp.serial_port.write_timeout = 2
        self.bp.serial_port.reset_input_buffer()
        self.bp.serial_port.reset_output_buffer()
        time.sleep(0.1)

        try:
            self.status = self._handshake()
            if configure:
                self._configure(baud)
        except Exception:
            self._close_port()
            raise

    # -- lifecycle ---------------------------------------------------------

    def _handshake(self):
        for _ in range(3):
            try:
                with self._quiet():
                    st = self.bp.status_request()
            except serial.SerialTimeoutException:
                st = None
            if st:
                return st
            time.sleep(0.5)
        raise BpioError(
            "BPIO2 status check failed. The BP5 default binmode is SUMP; "
            "in the BP5 terminal run: binmode -> 2 (BPIO2) -> save y")

    def _configure(self, baud):
        self._config(psu_enable=True, psu_set_mv=3300)
        time.sleep(0.2)
        self._config(mode="UART", mode_configuration={"speed": baud})
        self.bp.clear_async_queue()
        self._reader = threading.Thread(
            target=self._reader_loop, daemon=True, name="ec-console")
        self._reader.start()

    def close(self, teardown=True):
        """Release GPIOs, disable PSU, return to HiZ and close the port.

        teardown=False leaves the BP5 as it is (PSU on, pins driven),
        e.g. to keep the EC held in reset after the process exits.
        """
        self._shutdown.set()
        if self._reader:
            self._reader.join(timeout=2)
        if self._reader and teardown:
            try:
                self.release_all()
                self._config(psu_disable=True)
                self._config(mode="HiZ", mode_configuration={"speed": 0})
            except EcTargetError:
                pass
        self._close_port()

    def _close_port(self):
        with contextlib.suppress(Exception):
            self.bp.close()
        if self._log:
            self._log.close()
            self._log = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- BPIO primitives ---------------------------------------------------

    @contextlib.contextmanager
    def _quiet(self):
        """Hide pybpio's stdout chatter unless debugging."""
        if self.debug:
            yield
        else:
            with contextlib.redirect_stdout(io.StringIO()):
                yield

    def _config(self, **kwargs):
        with self._lock, self._quiet():
            ok = self.bp.configuration_request(**kwargs)
        if not ok:
            raise BpioError(f"configuration_request({kwargs}) failed")

    def _uart_write(self, data):
        with self._lock, self._quiet():
            ok = self.bp.data_request(data_write=bytes(data), bytes_read=0)
        if ok is False:
            raise BpioError(f"UART write of {len(data)} bytes failed")

    def _gpio(self, pin, value):
        """Drive pin low/high, or release it (input) if value is None."""
        if value is None:
            self._config(io_direction_mask=1 << pin, io_direction=0)
        else:
            self._config(io_direction_mask=1 << pin, io_direction=1 << pin,
                         io_value_mask=1 << pin,
                         io_value=(1 << pin) if value else 0)

    def note(self, msg):
        """Add a marker line to the log file (no-op without a log)."""
        if self._log:
            self._log.note(msg)

    # -- GPIO control ------------------------------------------------------

    def reset(self, hold=0.5):
        """Pulse EC reset low for `hold` seconds, then release it."""
        self.note("reset")
        self._gpio(IO_RST, 0)
        time.sleep(hold)
        self._gpio(IO_RST, None)

    def hold_reset(self):
        """Assert EC reset and leave it asserted."""
        self.note("hold reset")
        self._gpio(IO_RST, 0)

    def release_reset(self):
        self.note("release reset")
        self._gpio(IO_RST, None)

    def enter_flash_mode(self):
        """Reset the EC with FLPRG1 strapped low so it boots to UART ISP."""
        self.note("enter flash mode")
        self._gpio(IO_FLPRG, 0)
        self._gpio(IO_RST, 0)
        time.sleep(0.5)
        self._gpio(IO_RST, None)
        time.sleep(1.0)  # EC samples the strap
        # Drive FLPRG1 high so the resistor doesn't load the shared EC TX line
        self._gpio(IO_FLPRG, 1)
        time.sleep(0.1)

    def release_all(self):
        """Release RST and FLPRG1 to inputs."""
        self._config(io_direction_mask=(1 << IO_RST) | (1 << IO_FLPRG),
                     io_direction=0)

    # -- console capture ---------------------------------------------------

    def _reader_loop(self):
        while not self._shutdown.is_set():
            try:
                pkt = self.bp.check_async_data(timeout=0.05)
            except Exception as e:  # pragma: no cover - port vanished
                print(f"ec-console: {e}", file=sys.stderr)
                return
            if not pkt or not pkt.get("data_read"):
                continue
            data = bytes(pkt["data_read"])
            if self.on_data:
                self.on_data(data)
            sink = self._sink
            if sink is not None:
                sink.feed(data)
            else:
                self._ingest(data)

    def _ingest(self, data):
        raw = self._partial + data
        m = _ANSI_PARTIAL_RE.search(raw)
        if m:
            self._partial = raw[m.start():]
            raw = raw[:m.start()]
        else:
            self._partial = b""
        raw = _ANSI_RE.sub(b"", raw).replace(b"\r", b"").replace(b"\0", b"")
        text = raw.decode("utf-8", errors="replace")
        if self._log:
            self._log.write(text)
        with self._cond:
            self._console += text
            self._last_rx = time.monotonic()
            self._cond.notify_all()

    @property
    def output(self):
        """All cleaned console output captured so far."""
        with self._cond:
            return self._console

    def mark(self):
        """Move the expect() cursor to the end of captured output.

        Call before triggering an event (reset, command) so expect()
        only matches output produced after it.
        """
        with self._cond:
            self._cursor = len(self._console)
            return self._cursor

    def expect(self, pattern, timeout=10):
        """Wait for regex `pattern` in output after the cursor.

        Returns the re.Match and advances the cursor past it. Raises
        ExpectTimeout with recent output if not seen in time.
        """
        rx = re.compile(pattern) if isinstance(pattern, str) else pattern
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                m = rx.search(self._console, self._cursor)
                if m:
                    self._cursor = m.end()
                    return m
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    recent = self._console[max(self._cursor,
                                               len(self._console) - 2000):]
                    raise ExpectTimeout(rx.pattern, timeout, recent)
                self._cond.wait(remaining)

    def wait_quiet(self, quiet=0.5, timeout=10):
        """Wait until no console output has arrived for `quiet` seconds."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                now = time.monotonic()
                idle = now - self._last_rx
                if idle >= quiet:
                    return
                if now >= deadline:
                    raise ExpectTimeout(f"<{quiet}s of silence>", timeout,
                                        self._console[-2000:])
                self._cond.wait(min(quiet - idle, deadline - now))

    def boot(self, pattern=r"Inits done", timeout=15):
        """Reset the EC and wait for `pattern` in the boot log.

        Returns the boot log text up to and including the match.
        """
        start = self.mark()
        self.reset()
        m = self.expect(pattern, timeout)
        with self._cond:
            return self._console[start:m.end()]

    # -- console input -----------------------------------------------------

    def send(self, text, eol="\r"):
        """Send a line to the EC console."""
        self._uart_write((text + eol).encode())

    def command(self, cmd, timeout=5, settle=0.2):
        """Run an EC console command and return its output.

        Waits for the echoed command, then for the prompt to come back
        with no further output for `settle` seconds. Asynchronous log
        lines that arrive while the command runs are included.
        """
        self.mark()
        self.send(cmd)
        self.expect(re.escape(cmd) + r"\n", timeout)
        start = self._cursor
        deadline = time.monotonic() + timeout
        prompt_rx = re.compile(re.escape(self.prompt) + r"$")
        with self._cond:
            while True:
                tail = self._console[start:]
                idle = time.monotonic() - self._last_rx
                if prompt_rx.search(tail) and idle >= settle:
                    self._cursor = len(self._console)
                    out = tail[:-len(self.prompt)]
                    # Log lines arrive as "<prompt>[log line]"; drop
                    # the redrawn prompts in front of them.
                    return out.replace(self.prompt, "").rstrip("\n")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ExpectTimeout(f"prompt after {cmd!r}", timeout,
                                        tail[-2000:])
                self._cond.wait(min(remaining, settle))

    # -- PTY bridge --------------------------------------------------------

    @contextlib.contextmanager
    def pty_bridge(self):
        """Expose the EC UART as a PTY for external tools.

        While active, console output goes to the PTY instead of
        expect()/command(). Yields the PTY path (e.g. /dev/pts/5).
        """
        bridge = _PtyBridge(self._uart_write, debug=self.debug)
        self.note(f"pty bridge {bridge.pty_path}")
        self._sink = bridge
        try:
            yield bridge.pty_path
        finally:
            self._sink = None
            bridge.stop()
            self.note("pty bridge closed")

    # -- flashing ----------------------------------------------------------

    def flash(self, firmware, timeout=300, tool=UARTUPDATETOOL):
        """Flash ec.bin via the NPCX UART ISP using uartupdatetool.

        `firmware` is a build dir (ec.bin + npcx_monitor.bin) or an
        ec.bin path. Leaves the EC in flash mode; call reset()/boot()
        afterwards to run the new image.
        """
        ec_bin, monitor_bin = resolve_firmware(firmware)
        self.enter_flash_mode()
        time.sleep(0.5)
        deadline = time.monotonic() + timeout
        with self.pty_bridge() as pty:
            port_arg = pty.removeprefix("/dev/")
            steps = [
                ("monitor", ["--opr", "wr", "--addr", MONITOR_LOAD_ADDR,
                             "--file", str(monitor_bin)]),
                ("ec.bin", ["--opr", "wr", "--auto", "--addr", "0x0000",
                            "--file", str(ec_bin)]),
            ]
            for name, args in steps:
                self.note(f"uartupdatetool: {name}")
                remaining = deadline - time.monotonic()
                try:
                    r = subprocess.run(
                        [str(tool), "--port", port_arg, *args],
                        capture_output=True, text=True,
                        timeout=max(remaining, 1))
                except subprocess.TimeoutExpired as e:
                    raise FlashError(
                        f"uartupdatetool ({name}) timed out after "
                        f"{timeout}s:\n{e.stdout or ''}{e.stderr or ''}")
                if self._log:
                    self._log.write(_drop_progress(r.stdout + r.stderr))
                if r.returncode != 0:
                    raise FlashError(
                        f"uartupdatetool ({name}) failed with exit code "
                        f"{r.returncode}:\n{r.stdout}{r.stderr}")
        self._gpio(IO_FLPRG, None)


# ---------------------------------------------------------------------------
# PTY bridge
# ---------------------------------------------------------------------------

class _PtyBridge:
    """Bidirectional bridge between the BPIO UART and a PTY.

    EC output is buffered until a reader opens the slave: TIOCPKT
    (packet mode) on the master reports the reader's termios changes,
    and we wait 200ms for its initial tcflush before flushing.
    """

    def __init__(self, uart_write, debug=False):
        self._uart_write = uart_write
        self.debug = debug
        self._shutdown = threading.Event()
        self._slave_ready = threading.Event()
        self._buf = collections.deque()
        self._buf_bytes = 0
        self._buf_lock = threading.Lock()

        self._master_fd, self._slave_fd = os.openpty()
        os.set_blocking(self._master_fd, False)
        self.pty_path = os.ttyname(self._slave_fd)
        fcntl.ioctl(self._master_fd, TIOCPKT, struct.pack("i", 1))

        self._thread = threading.Thread(
            target=self._pty_reader_loop, daemon=True, name="pty-reader")
        self._thread.start()

    def feed(self, data):
        """Queue EC output for the PTY; flush if a reader is attached."""
        if self.debug:
            print(f"[uart→pty] {len(data)}B", file=sys.stderr)
        with self._buf_lock:
            self._buf.append(data)
            self._buf_bytes += len(data)
            while self._buf_bytes > PTY_BUF_MAX_BYTES:
                self._buf_bytes -= len(self._buf.popleft())
        if self._slave_ready.is_set():
            self._flush()

    def _flush(self):
        with self._buf_lock:
            while self._buf:
                chunk = self._buf[0]
                try:
                    n = os.write(self._master_fd, chunk)
                except OSError as e:
                    if e.errno == errno.EAGAIN:
                        return
                    raise
                self._buf_bytes -= n
                if n < len(chunk):
                    self._buf[0] = chunk[n:]
                    return
                self._buf.popleft()

    def _pty_reader_loop(self):
        poll = select.poll()
        poll.register(self._master_fd, select.POLLIN)
        while not self._shutdown.is_set():
            try:
                events = poll.poll(100)
                if self._slave_ready.is_set():
                    self._flush()  # retry after EAGAIN
                for _fd, event in events:
                    if event & select.POLLIN:
                        data = os.read(self._master_fd, 4096)
                        if not data:
                            continue
                        if data[0] == 0:  # TIOCPKT_DATA
                            if len(data) > 1:
                                if self.debug:
                                    print(f"[pty→uart] {len(data) - 1}B",
                                          file=sys.stderr)
                                self._uart_write(data[1:])
                        elif not self._slave_ready.is_set():
                            time.sleep(0.2)  # let the reader's tcflush finish
                            self._slave_ready.set()
                            self._flush()
                    if event & (select.POLLHUP | select.POLLERR):
                        time.sleep(0.1)
            except OSError as e:
                if e.errno == errno.EIO:
                    time.sleep(0.1)
                    continue
                if not self._shutdown.is_set():
                    print(f"pty-reader error: {e}", file=sys.stderr)
                return
            except EcTargetError as e:
                print(f"pty-reader: {e}", file=sys.stderr)

    def stop(self):
        self._shutdown.set()
        self._thread.join(timeout=2)
        os.close(self._master_fd)
        os.close(self._slave_fd)
