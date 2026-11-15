#!/usr/bin/env python3
"""Bus Pirate 5 control tool using BPIO2 binmode.

Thin CLI around ectarget.py. Uses BPIO (CDC 1) for GPIO control and a
Python PTY bridge so external tools (uartupdatetool, tio) can talk
through BPIO's UART. No bridge mode, no USB reset, no button press.

The BP5 binmode port (CDC 1) is a single serial device - only one
process can use it at a time. To control GPIO while a PTY bridge is
running, use signals (see below) or combinable flags. For test code,
import ectarget.EcTarget instead of shelling out to this script.

Wiring:
  BP5 IO3      --> EC VCC1_RST          (reset, active low)
  BP5 IO4 (TX) --> EC CR_SIN1           (UART RX)
  BP5 IO5 (RX) <-- EC CR_SOUT1         (UART TX)
  BP5 IO7      --[4.7-10K R]--> EC CR_SOUT1/FLPRG1  (flash mode strap)
  BP5 GND      --- EC GND

Usage:
  ./buspirate_ctrl.py --reset                          # Toggle EC reset
  ./buspirate_ctrl.py --reset-hold                     # Hold EC in reset (until next invocation)
  ./buspirate_ctrl.py --log                            # Print EC UART output (Ctrl+C to stop)
  ./buspirate_ctrl.py --log --reset                    # Reset EC, print boot log
  ./buspirate_ctrl.py --log --reset --timeout 5        # ... for 5 seconds
  ./buspirate_ctrl.py --pty-bridge                     # PTY bridge (Ctrl+C to stop)
  ./buspirate_ctrl.py --pty-bridge --reset             # Bridge, then reset (captures boot log)
  ./buspirate_ctrl.py --pty-bridge --enter-flash-mode  # Bridge + enter flash mode
  ./buspirate_ctrl.py --backup original-ec.bin         # Two matching full reads, then reset
  ./buspirate_ctrl.py --flash ./result/                # Program + checked readback, then reset
  ./buspirate_ctrl.py --flash ~/Downloads/ec.bin       # Flash single ec.bin (monitor from script dir)
  ./buspirate_ctrl.py --flash ./result/ --no-reset     # Flash without reboot
  ./buspirate_ctrl.py --flash ./result/ --log          # Flash, reset, print boot log

Scripting (exit code 0 = success, 1 = failure/timeout):
  ./buspirate_ctrl.py --reset --expect 'Inits done' --timeout 10
  ./buspirate_ctrl.py --send version                   # Run console command, print output
  ./buspirate_ctrl.py --reset --expect 'Inits done' --send version --send 'gpioget'
  ./buspirate_ctrl.py --flash ./result/ --expect 'Inits done' --logfile ec.log

Bus Pirate itself (not the EC):
  ./buspirate_ctrl.py --buspirate-reset                # Reboot the BP5
  ./buspirate_ctrl.py --buspirate-bootloader           # Reboot BP5 into RP2 bootloader

Signal control (while --pty-bridge is running):
  kill -USR1 <pid>    # Toggle EC reset
  kill -USR2 <pid>    # Enter EC flash mode

Status messages go to stderr; stdout carries only EC output.
"""

import argparse
import contextlib
import io
import json
import os
import signal
import sys
import time

from ectarget import EcTarget, EcTargetError, ExpectTimeout


def status(msg):
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def bpio_fire_and_forget(ec, **kwargs):
    """Send a configuration request the BP5 will never answer.

    hardware_reset / hardware_bootloader take the MCU down inside the
    request handler, before the ConfigurationResponse is built, so the
    USB device just disappears instead of acking.
    """
    bp = ec.bp
    prev_timeout = bp.timeout
    bp.timeout = 0.5
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            bp.configuration_request(**kwargs)
    except Exception:
        pass  # Device dropped off the bus mid-write - expected
    finally:
        bp.timeout = prev_timeout


def cmd_pty_bridge(ec, reset_after_start=False):
    """Run PTY bridge until Ctrl+C.

    SIGUSR1 -> toggle EC reset
    SIGUSR2 -> enter flash mode
    """
    with ec.pty_bridge() as pty:
        pid = os.getpid()
        status(f"PTY bridge active: {pty}")
        status(f"PID: {pid}")
        status(f"Connect with:  tio {pty}")
        status(f"Reset EC:      kill -USR1 {pid}")
        status(f"Flash mode:    kill -USR2 {pid}")
        status("Press Ctrl+C to stop.")

        if reset_after_start:
            status("Resetting EC...")
            ec.reset()
            status("Reset complete. Boot log is being captured.")

        def on_usr1(signum, frame):
            status("[SIGUSR1] Resetting EC...")
            ec.reset()
            status("[SIGUSR1] Reset complete.")

        def on_usr2(signum, frame):
            status("[SIGUSR2] Entering flash mode...")
            ec.enter_flash_mode()
            status("[SIGUSR2] Flash mode entry complete.")

        signal.signal(signal.SIGUSR1, on_usr1)
        signal.signal(signal.SIGUSR2, on_usr2)

        try:
            while True:
                signal.pause()
        except KeyboardInterrupt:
            pass
    status("PTY bridge stopped.")


def run_console(ec, args, stream, reset):
    """Reset / expect / send / log, in that order.

    Returns the process exit code.
    """
    timeout = args.timeout
    ec.mark()
    if args.log:
        stream.enabled = True
    if reset:
        status("Resetting EC...")
        ec.reset()

    if args.expect:
        m = ec.expect(args.expect, timeout=timeout or 30)
        status(f"Matched: {m.group(0)!r}")

    if args.send:
        if reset and not args.expect:
            # Let the boot log settle before typing into the console
            ec.wait_quiet(1.0, timeout=timeout or 30)
        for cmd in args.send:
            out = ec.command(cmd, timeout=timeout or 10)
            if not args.log:  # with --log it's already on stdout
                print(out, flush=True)

    if args.log and not (args.expect or args.send):
        if timeout:
            status(f"Logging EC output for {timeout}s...")
            time.sleep(timeout)
        else:
            status("Logging EC output (Ctrl+C to stop)...")
            while True:
                time.sleep(1)
    return 0


class _Stream:
    """Copies raw EC output to stdout once enabled."""

    enabled = False

    def __call__(self, data):
        if self.enabled:
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Bus Pirate 5 control tool (BPIO2 binmode)",
        epilog="Exit code: 0 on success, 1 on error or --expect timeout.")

    parser.add_argument("--port", default=None,
                        help="BP5 binmode port (default: auto-detect)")
    parser.add_argument("--debug", action="store_true",
                        help="Enable verbose debug output")
    parser.add_argument("--logfile", metavar="PATH",
                        help="Append timestamped EC console output to PATH")

    # Primary action (mutually exclusive)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--reset-hold", action="store_true",
                       help="Hold EC in reset (RST low). Stays held after exit "
                            "until the next invocation connects, which "
                            "reconfigures the pins and releases it")
    group.add_argument("--pty-bridge", action="store_true",
                       help="PTY bridge (blocks until Ctrl+C)")
    group.add_argument("--flash", metavar="PATH",
                       help="Full flash workflow with uartupdatetool. "
                            "PATH is a build dir with ec.bin + npcx_monitor.bin, "
                            "or a single ec.bin file (prefer its sibling monitor)")
    group.add_argument("--backup", metavar="FILE",
                       help="Save two matching CRC-checked full flash reads; "
                            "refuse to overwrite FILE, then reset unless --no-reset")
    group.add_argument("--buspirate-reset", action="store_true",
                       help="Hardware reset the Bus Pirate itself (not the EC)")
    group.add_argument("--buspirate-bootloader", action="store_true",
                       help="Reboot the Bus Pirate into its UF2 bootloader")

    # Combinable flags
    parser.add_argument("--reset", action="store_true",
                        help="Toggle EC reset (combinable with --pty-bridge, --log, "
                             "--expect, --send)")
    parser.add_argument("--log", action="store_true",
                        help="Print EC UART output to stdout")
    parser.add_argument("--expect", metavar="REGEX",
                        help="Wait for REGEX in EC output (after --reset/--flash); "
                             "exit 1 if not seen within --timeout (default 30s)")
    parser.add_argument("--send", metavar="CMD", action="append", default=[],
                        help="Run an EC console command and print its output; "
                             "repeatable")
    parser.add_argument("--timeout", type=float, metavar="SECONDS",
                        help="Timeout for --expect/--send; duration for --log")
    parser.add_argument("--flash-timeout", type=float, default=900,
                        metavar="SECONDS", help="Total flash/readback timeout (default 900)")
    parser.add_argument("--backup-timeout", type=float, default=1200,
                        metavar="SECONDS", help="Total two-read backup timeout (default 1200)")
    parser.add_argument("--monitor", metavar="FILE",
                        help="RAM monitor for --backup (default: bundled npcx_monitor.bin)")
    parser.add_argument("--enter-flash-mode", action="store_true",
                        help="Enter EC flash mode before primary action")
    parser.add_argument("--no-reset", action="store_true",
                        help="Skip reset after --flash/--backup")

    args = parser.parse_args()

    bp_reboot = args.buspirate_reset or args.buspirate_bootloader
    console = args.log or args.expect or args.send

    if not (args.reset or args.reset_hold or args.pty_bridge or args.flash or args.backup
            or console or bp_reboot):
        parser.error("One of --reset, --reset-hold, --pty-bridge, --flash, --log, "
                     "--backup, --expect, --send, --buspirate-reset, or "
                     "--buspirate-bootloader is required")
    if bp_reboot and (args.reset or console or args.enter_flash_mode):
        parser.error("--buspirate-reset/--buspirate-bootloader cannot be combined "
                     "with other actions")
    if (args.pty_bridge or args.reset_hold) and console:
        parser.error("--log/--expect/--send cannot be combined with "
                     "--pty-bridge or --reset-hold")

    if args.monitor and not args.backup:
        parser.error("--monitor applies only to --backup; --flash resolves its build monitor")
    if args.flash_timeout <= 0 or args.backup_timeout <= 0:
        parser.error("Flash/backup timeouts must be positive")

    # Background jobs inherit SIGINT as ignored; make both SIGINT and
    # SIGTERM raise KeyboardInterrupt so we always tear down cleanly.
    def interrupt(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGINT, interrupt)
    signal.signal(signal.SIGTERM, interrupt)

    stream = _Stream()
    try:
        ec = EcTarget(args.port, logfile=args.logfile, configure=not bp_reboot,
                      on_data=stream, debug=args.debug)
    except EcTargetError as e:
        sys.exit(f"Error: {e}")
    st = ec.status
    status(f"BP5 binmode: {ec.port}")
    status(f"Connected: FW v{st.get('version_firmware_major', 0)}."
           f"{st.get('version_firmware_minor', 0)}")

    rc = 0
    teardown = True
    try:
        try:
            if args.buspirate_reset:
                status("Resetting Bus Pirate...")
                bpio_fire_and_forget(ec, hardware_reset=True)
                status("Reset sent. The BP5 will re-enumerate over USB in a "
                       "few seconds.")
                return 0
            if args.buspirate_bootloader:
                status("Rebooting Bus Pirate into bootloader...")
                bpio_fire_and_forget(ec, hardware_bootloader=True)
                status("Bootloader entered. The BP5 should appear as an RPI-RP2 "
                       "mass storage device; copy the .uf2 firmware onto it.")
                return 0

            if args.enter_flash_mode:
                status("Entering EC flash mode...")
                ec.enter_flash_mode()

            if args.pty_bridge:
                cmd_pty_bridge(ec, reset_after_start=args.reset)
            elif args.reset_hold:
                status("Holding EC in reset (RST low)...")
                ec.hold_reset()
                teardown = False  # keep RST driven after we exit
                status("EC held in reset. Run --reset to release.")
            elif args.backup:
                status(f"Backing up flash to {args.backup} (two checked reads)...")
                options = {"timeout": args.backup_timeout}
                if args.monitor:
                    options["monitor"] = args.monitor
                report = ec.backup(args.backup, **options)
                status(f"Backup verified: {json.dumps(report)}")
                reset = not args.no_reset
                if console:
                    rc = run_console(ec, args, stream, reset)
                elif reset:
                    status("Rebooting EC...")
                    ec.reset()
            elif args.flash:
                status(f"Flashing {args.flash}...")
                t0 = time.monotonic()
                report = ec.flash(args.flash, timeout=args.flash_timeout)
                status(f"Flash/readback verified in {time.monotonic() - t0:.1f}s: "
                       f"{json.dumps(report)}")
                reset = not args.no_reset
                if console:
                    rc = run_console(ec, args, stream, reset)
                elif reset:
                    status("Rebooting EC...")
                    ec.reset()
            elif console:
                rc = run_console(ec, args, stream, args.reset)
            elif args.reset:
                status("Resetting EC...")
                ec.reset()
                status("Reset complete.")
        except KeyboardInterrupt:
            status("Interrupted.")
            rc = 130
        except ExpectTimeout as e:
            status(f"Error: {e}")
            rc = 1
        except (EcTargetError, OSError, ValueError) as e:
            status(f"Error: {e}")
            rc = 1
    finally:
        ec.close(teardown=teardown)
    return rc


if __name__ == "__main__":
    sys.exit(main())
