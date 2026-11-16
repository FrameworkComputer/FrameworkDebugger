"""Independent UART consoles through one Bus Pirate 5 (BPIO 2.3 UART channels).

One process owns the BPIO port and multiplexes the hardware UARTs:

  channel 0 (UART0): BP TX IO4 --> target RX, BP RX IO5 <-- target TX  (EC)
  channel 1 (UART1): BP TX IO0 --> target RX, BP RX IO1 <-- target TX  (SoC)

Nothing here touches the Bus Pirate PSU or pull-ups: the target is expected
to be powered externally and to supply the IO reference voltage. Every
channel starts receive-only; TX must be enabled explicitly.

Library example:
    from bpconsoles import BusPirateConsoles

    with BusPirateConsoles(soc_tx=True) as bp:
        bp.soc.send("")                      # newline
        bp.soc.expect(r"login:", timeout=5)
        print(bp.ec.output)                  # whatever the EC printed

Command line (PTYs for interactive use):
    python3 bpconsoles.py --soc-tx --ec-link /tmp/bp-ec-console \\
                          --soc-link /tmp/bp-soc-console --log-dir /tmp/bp-logs
"""

import argparse
import contextlib
import io
import os
import re
import sys
import threading
import time
from pathlib import Path

import serial

from ectarget import (BpioError, EcTargetError, ExpectTimeout, _PtyBridge,
                      find_bp5_binport, find_port_users)
from pybpio.bpio_client import BPIOClient

EC_CHANNEL = 0
SOC_CHANNEL = 1

# CSI (colours, cursor) and OSC (window title) escape sequences.
_ANSI_RE = re.compile(rb"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
# An escape sequence that may continue in the next received chunk.
_ANSI_PARTIAL_RE = re.compile(rb"\x1b(?:\[[0-9;?]*[ -/]*|\][^\x07\x1b]*)?$")


class ChannelError(EcTargetError):
    """A UART channel request failed or the channel reported a fault."""


class UartChannel:
    """One hardware UART on the Bus Pirate. Created by BusPirateConsoles."""

    CONFIG_KEYS = ("speed", "data_bits", "parity", "stop_bits",
                   "signal_inversion", "tx_enable")

    def __init__(self, bus, name, channel, *, speed=115200, data_bits=8,
                 parity=False, stop_bits=1, signal_inversion=False,
                 tx_enable=False, log_dir=None, on_data=None):
        self.bus = bus
        self.name = name
        self.channel = channel
        self.config = dict(speed=speed, data_bits=data_bits, parity=parity,
                           stop_bits=stop_bits,
                           signal_inversion=signal_inversion,
                           tx_enable=tx_enable)
        self.on_data = on_data
        self.faults = []                  # recent firmware fault strings (capped)
        self._recover_at = None           # monotonic time of a pending recovery
        self._last_recover = 0.0
        self._last_report = (None, 0.0)   # (fault text, time) last printed
        self._suppressed = 0
        self._cond = threading.Condition()
        self._raw = bytearray()           # unread raw bytes for read()
        self._text = ""                   # cleaned text for expect()
        self._cursor = 0
        self._partial = b""               # incomplete escape sequence
        self._pty = None
        self._pty_link = None
        self._log = None
        if log_dir:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            self._log = open(Path(log_dir) / f"{name}.raw", "ab")

    # -- configuration -----------------------------------------------------

    def _wire_config(self):
        return dict(channel=self.channel, enable=True, **self.config)

    def configure(self, **changes):
        """Reconfigure this channel only (e.g. speed=, tx_enable=).

        Also clears a latched RX fault. The other channel is not touched.
        """
        unknown = set(changes) - set(self.CONFIG_KEYS)
        if unknown:
            raise ValueError(f"unknown UART settings: {sorted(unknown)}")
        new = dict(self.config, **changes)
        self.bus._configure_channels([dict(channel=self.channel, enable=True, **new)])
        self.config = new

    def enable_tx(self):
        self.configure(tx_enable=True)

    def disable_tx(self):
        self.configure(tx_enable=False)

    # -- data ----------------------------------------------------------------

    def write(self, data):
        """Transmit raw bytes. Requires TX to be enabled."""
        if not self.config["tx_enable"]:
            raise ChannelError(f"{self.name}: TX is disabled (enable_tx() first)")
        self.bus._write(self.channel, bytes(data))

    def send(self, text, eol="\r"):
        self.write((text + eol).encode())

    def read(self, size=None, timeout=0):
        """Return up to `size` unread raw bytes (all if None), waiting up to `timeout` s for any."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while not self._raw:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return b""
                self._cond.wait(remaining)
            n = len(self._raw) if size is None else min(size, len(self._raw))
            data = bytes(self._raw[:n])
            del self._raw[:n]
            return data

    @property
    def output(self):
        """All cleaned (ANSI/CR/NUL stripped) text received so far."""
        with self._cond:
            return self._text

    def mark(self):
        """Make expect() only match output received after this call."""
        with self._cond:
            self._cursor = len(self._text)

    def expect(self, pattern, timeout=10):
        """Wait for regex `pattern` in output after the cursor; return the match."""
        rx = re.compile(pattern)
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                m = rx.search(self._text, self._cursor)
                if m:
                    self._cursor = m.end()
                    return m
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ExpectTimeout(pattern, timeout, self._text[-500:])
                self._cond.wait(remaining)

    # -- PTY -----------------------------------------------------------------

    def start_pty(self, link=None):
        """Expose this channel as a PTY (optionally symlinked at `link`)."""
        if self._pty:
            return self._pty.pty_path
        self._pty = _PtyBridge(self._pty_write, debug=self.bus.debug)
        if link:
            link = Path(link)
            if link.is_symlink():
                link.unlink()
            link.symlink_to(self._pty.pty_path)
            self._pty_link = link
        return self._pty.pty_path

    def stop_pty(self):
        if self._pty:
            self._pty.stop()
            self._pty = None
        if self._pty_link and self._pty_link.is_symlink():
            self._pty_link.unlink()
        self._pty_link = None

    def _pty_write(self, data):
        if not self.config["tx_enable"]:
            return  # receive-only console: drop keystrokes
        try:
            self.write(data)
        except ChannelError as e:
            print(f"{self.name}: {e}", file=sys.stderr)

    # -- receive path (called from the bus reader thread) ------------------

    def _feed(self, data):
        if self._log:
            self._log.write(data)
            self._log.flush()
        if self.on_data:
            self.on_data(data)
        pty = self._pty
        if pty:
            pty.feed(data)
        raw = self._partial + data
        m = _ANSI_PARTIAL_RE.search(raw)
        if m and len(raw) - m.start() < 256:
            self._partial, raw = raw[m.start():], raw[:m.start()]
        else:
            self._partial = b""
        text = _ANSI_RE.sub(b"", raw).replace(b"\r", b"").replace(b"\0", b"")
        with self._cond:
            self._raw += data
            if len(self._raw) > 1 << 20:
                del self._raw[:len(self._raw) - (1 << 20)]
            self._text += text.decode("utf-8", errors="replace")
            self._cond.notify_all()

    def _fault(self, error):
        self.faults.append(error)
        del self.faults[:-100]
        # A powered-down target can fault on every recovery; report a
        # repeated fault at most every 10 s, with a count.
        last, when = self._last_report
        now = time.monotonic()
        if error == last and now - when < 10:
            self._suppressed += 1
            return
        repeats = f" (+{self._suppressed} repeats)" if self._suppressed else ""
        self._suppressed = 0
        self._last_report = (error, now)
        print(f"{self.name}: {error}{repeats}", file=sys.stderr)
        if self._log:
            self._log.write(f"\n[bpconsoles: {error}{repeats}]\n".encode())
            self._log.flush()

    def close(self):
        self.stop_pty()
        if self._log:
            self._log.close()
            self._log = None


class BusPirateConsoles:
    """EC (channel 0) and SoC (channel 1) consoles on one Bus Pirate 5.

    ec_tx/soc_tx enable each TX explicitly; both default to receive-only.
    auto_recover reconfigures a channel after an RX fault (for example a
    break while the target powers down) so its console keeps working; the
    fault is still recorded in channel.faults.
    """

    def __init__(self, port=None, *, ec_baud=115200, soc_baud=115200,
                 ec_tx=False, soc_tx=False, log_dir=None, auto_recover=True,
                 debug=False):
        self.port = port or find_bp5_binport()
        if not self.port:
            raise EcTargetError("BP5 binmode port not found. Set BP5_BINPORT or pass port=")
        users = find_port_users(self.port)
        if users:
            procs = ", ".join(f"{n} (pid {p})" for p, n in users)
            raise EcTargetError(f"{self.port} is already open by: {procs}")
        self.debug = debug
        self.auto_recover = auto_recover
        self._lock = threading.RLock()   # serializes BPIO requests
        self._shutdown = threading.Event()
        self._reader = None

        self.ec = UartChannel(self, "ec", EC_CHANNEL, speed=ec_baud,
                              tx_enable=ec_tx, log_dir=log_dir)
        self.soc = UartChannel(self, "soc", SOC_CHANNEL, speed=soc_baud,
                               tx_enable=soc_tx, log_dir=log_dir)
        self.channels = {c.channel: c for c in (self.ec, self.soc)}

        self.bp = BPIOClient(self.port, timeout=3, debug=debug)
        try:
            self.bp.serial_port.write_timeout = 2
            self.bp.serial_port.reset_input_buffer()
            time.sleep(0.1)
            self.status = self._handshake()
            count = self.status.get("uart_channel_count") or 0
            if count < 2:
                raise BpioError(
                    "Bus Pirate firmware does not support UART channels "
                    f"(uart_channel_count={count}, git {self.status.get('version_firmware_git_hash')})")
            self._max_write = self.status.get("mode_max_write") or 512
            # UART mode entry and both channels in one request. Channel 0's
            # entry also decides whether mode entry drives IO4 at all.
            self._config(mode="UART",
                         mode_configuration={"speed": self.ec.config["speed"]},
                         uart_channels=[c._wire_config() for c in self.channels.values()])
            self.bp.clear_async_queue()
            self._reader = threading.Thread(target=self._reader_loop, daemon=True,
                                            name="bp-consoles")
            self._reader.start()
        except Exception:
            self._close_port()
            raise

    # -- BPIO primitives ---------------------------------------------------

    @contextlib.contextmanager
    def _quiet(self):
        if self.debug:
            yield
        else:
            with contextlib.redirect_stdout(io.StringIO()):
                yield

    def _handshake(self):
        for _ in range(3):
            try:
                with self._lock, self._quiet():
                    st = self.bp.status_request()
            except serial.SerialTimeoutException:
                st = None
            if st:
                return st
            time.sleep(0.5)
        raise BpioError("BPIO2 status check failed (is binmode set to BPIO2?)")

    def _config(self, **kwargs):
        with self._lock, self._quiet():
            self.bp.last_error = None
            ok = self.bp.configuration_request(**kwargs)
        if not ok:
            raise BpioError(f"configuration failed: {self.bp.last_error or 'no response'}")

    def _configure_channels(self, entries):
        self._config(uart_channels=entries)

    def _write(self, channel, data):
        for i in range(0, len(data), self._max_write):
            chunk = data[i:i + self._max_write]
            with self._lock, self._quiet():
                try:
                    self.bp.data_request(data_write=chunk, bytes_read=0,
                                         channel=channel, raise_errors=True)
                except IOError as e:
                    raise ChannelError(f"channel {channel}: {e}") from e

    def status_request(self):
        with self._lock, self._quiet():
            return self.bp.status_request()

    # -- receive dispatch ----------------------------------------------------

    RECOVER_INTERVAL = 1.0  # seconds between recoveries of one channel

    def _recover_due(self):
        now = time.monotonic()
        for ch in self.channels.values():
            if ch._recover_at is not None and now >= ch._recover_at:
                ch._recover_at = None
                ch._last_recover = now
                try:
                    ch.configure()
                except EcTargetError as e:
                    print(f"{ch.name}: recovery failed: {e}", file=sys.stderr)
                    ch._recover_at = now + self.RECOVER_INTERVAL

    def _reader_loop(self):
        while not self._shutdown.is_set():
            self._recover_due()
            try:
                pkt = self.bp.check_async_data(timeout=0.05)
            except Exception as e:  # pragma: no cover - port vanished
                print(f"bp-consoles: {e}", file=sys.stderr)
                return
            if not pkt:
                continue
            ch = self.channels.get(pkt.get("channel", 0))
            if ch is None:
                print(f"bp-consoles: data for unknown channel {pkt.get('channel')}", file=sys.stderr)
                continue
            data = bytes(pkt.get("data_read") or b"")
            if data:
                ch._feed(data)
            if pkt.get("error"):
                ch._fault(pkt["error"])
                if self.auto_recover and ch._recover_at is None:
                    # Reconfiguring clears the latched fault; never spin on it.
                    ch._recover_at = max(time.monotonic(), ch._last_recover + self.RECOVER_INTERVAL)

    # -- lifecycle -----------------------------------------------------------

    def close(self, teardown=True):
        """Stop PTYs and return the Bus Pirate to HiZ (releases both UARTs).

        PSU and pull-ups are left exactly as they were.
        """
        self._shutdown.set()
        for ch in self.channels.values():
            ch.stop_pty()
        if self._reader:
            self._reader.join(timeout=2)
        if teardown:
            with contextlib.suppress(EcTargetError):
                self._config(mode="HiZ", mode_configuration={"speed": 0})
        self._close_port()

    def _close_port(self):
        with contextlib.suppress(Exception):
            self.bp.close()
        for ch in self.channels.values():
            ch.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port")
    ap.add_argument("--ec-baud", type=int, default=115200)
    ap.add_argument("--soc-baud", type=int, default=115200)
    ap.add_argument("--ec-tx", action="store_true", help="enable EC TX (IO4)")
    ap.add_argument("--soc-tx", action="store_true", help="enable SoC TX (IO0)")
    ap.add_argument("--ec-link", default="/tmp/bp-ec-console")
    ap.add_argument("--soc-link", default="/tmp/bp-soc-console")
    ap.add_argument("--log-dir", help="append raw received bytes to <dir>/ec.raw and soc.raw")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    with BusPirateConsoles(args.port, ec_baud=args.ec_baud, soc_baud=args.soc_baud,
                           ec_tx=args.ec_tx, soc_tx=args.soc_tx,
                           log_dir=args.log_dir, debug=args.debug) as bp:
        st = bp.status_request() or {}
        print(f"firmware {st.get('version_firmware_git_hash')}, "
              f"psu_enabled={st.get('psu_enabled')}, pullup_enabled={st.get('pullup_enabled')}, "
              f"vref={st.get('psu_measured_mv')} mV", flush=True)
        adc = st.get("adc_mv") or []
        if len(adc) >= 6:
            # Idle UART lines sit at the target's IO voltage.
            print(f"idle line levels: IO1 (SoC TX) {adc[1]} mV, IO5 (EC TX) {adc[5]} mV", flush=True)
        for ch, link in ((bp.ec, args.ec_link), (bp.soc, args.soc_link)):
            path = ch.start_pty(link)
            mode = "TX enabled" if ch.config["tx_enable"] else "receive only"
            print(f"{ch.name}: channel {ch.channel}, {ch.config['speed']} baud, {mode}: "
                  f"{link} -> {path}", flush=True)
        print("READY (Ctrl-C to stop)", flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
