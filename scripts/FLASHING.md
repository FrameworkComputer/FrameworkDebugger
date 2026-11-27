# Checked NPCX backup and flashing via Bus Pirate 5

Initialize the BPIO dependency with `git submodule update --init --recursive`,
then use `nix-shell` in this directory (or install pyserial, flatbuffers, cobs,
numpy and pytest). Select BPIO2 on the BP and use its stable BIN serial path.
Only one process may own that serial port. Wiring is in `ectarget.py`.
The library enables the BP IO supply at 3.3 V; verify target voltage/common
ground and do not connect BP VOUT to a mainboard power rail.

## Back up first

```sh
python buspirate_ctrl.py --port /dev/serial/by-id/usb-Bus_Pirate_Bus_Pirate_5_5buspirate-if02 \
  --backup original-ec.bin --logfile backup.log
```

Backup enters ROM ISP, loads the bundled RAM monitor, detects physical flash
size, performs two CRC-checked full reads and requires exact equality before
saving. It refuses to overwrite an existing file. Keep this complete dump,
including settings, in persistent storage. `--monitor FILE` selects a different
RAM monitor for backup. Both reads share `--backup-timeout` (default 1200 s).
The CLI resets into the application only after success; `--no-reset` leaves ISP.

## Program and independently verify

```sh
python buspirate_ctrl.py --flash /path/to/lilac-build/ \
  --expect 'Inits done' --send version --logfile flash.log
# A standalone image prefers its sibling npcx_monitor.bin, then the bundled one:
python buspirate_ctrl.py --flash /path/to/lilac-build/ec.bin --no-reset
```

Flash probes supported chip geometry before programming, rejects empty and
oversized images, then uses uartupdatetool to program. Before reporting success
or resetting, it reads all physical flash through the independent CRC-checked
reader and compares the programmed range. A full-size image verifies every
byte; a short image verifies its prefix only (it does not erase or verify the
rest as erased). Supplying a full image replaces its entire settings layout;
there is no automatic settings merge. Back up first.

`--flash-timeout` is the total monitor/program/readback budget (default 900 s).
Failed writes are not retried automatically. Timeout, unknown geometry or
readback mismatch exits nonzero without an application reset. Interruption
exits 130. GPIO/PSU teardown still occurs on failure: `--no-reset`/ISP is not a
hardware interlock. Diagnose logs before another write; recover using the
preserved full stock image and a fresh ROM entry when appropriate.

## Python API

```python
from ectarget import EcTarget

with EcTarget(logfile='ec.log') as ec:
    report = ec.backup('original-ec.bin')  # two matching reads, exclusive output
    print(report)                        # physical size, SHA-256, retry counts
    ec.boot()                            # check the original app after ISP
    report = ec.flash('/path/to/build/')  # verified before return, no app reset
    ec.boot()
    print(ec.command('version'))
```

`read_flash()` returns one checked whole-flash read; `last_flash_read` records
size, SHA-256 and retries. `backup()`/`flash()` return verification reports and
raise `FlashError` for ROM/verification failures. All enter ISP and leave it
there until explicit reset/boot; backup uploads RAM only. Binary traffic is
routed exclusively to the reader/PTY, not console text cleanup or `on_data`.
Do not run a bridge or another UART operation concurrently with these APIs.

## Why the checked reader is necessary

On Lilac with BP5 firmware `8ba3618-dirty`, UART responses occasionally lost
bytes. The bundled uartupdatetool `--read-flash` continued on short reads; its
exit code alone is not reliable backup/readback evidence. PTY reads with
smaller packets also lost data. The issue was observed on this path; it has
not been localized conclusively to BP firmware, host library or the bridge.

The new reader bypasses PTY, uses 128-byte ROM read requests and requires exact
response length, command byte and CRC-16 (0xa001, initial zero). Read errors
trigger bounded retries and resynchronization to discard delayed responses.
Only reads/sync are retried. The total deadline covers all blocks and retries;
UART disconnect errors propagate. The ROM protocol/geometry table follows
Chromium EC `util/uut`; the NPCX993 Lilac path is hardware-tested. Other table
entries require their own hardware validation. This does not make ordinary
console output lossless or establish packet trace completeness.

Run `pytest unit_tests` for host-only tests. `pytest tests` is the existing
hardware suite; with `--ec-build` it programs firmware and now verifies readback.

## Hardware validation — 2026-11-15

Tested the APIs from `/home/zoid/clone/frameworkdebugger-library` on Lilac
revision 4, NPCX993 (chip/device 09/25), with BP5 firmware `8ba3618-dirty`:

- `backup()` produced two matching 524288-byte reads, each with 114 retried
  responses, and saved the complete backup without overwriting a file.
- The existing stock EC booted again after leaving ISP.
- `flash()` programmed the same requested stock build and independently
  verified all 524288 bytes (111 read retries) before returning success.
- Reset/boot reached `Inits done`; RO and RW both report
  `lilac-0.0.0-6bcd05a`, executing RO in G3, with responsive ISL9241.

Image and all successful dump/readback SHA-256:
`afc124b7c6e2a348a515f05a5a446287e3d96db727ae8c18d155b6ed45855198`.
Image was `/nix/store/r7pndvw9qqrshivcz9517ibc8ac7mc2d-lilac/ec.bin` with its
sibling monitor. The first post-flash charger query lost its tail/prompt and
correctly raised a timeout; explicit repeat of read-only version/state/charger
queries passed. Ordinary console capture remains lossy on this setup.
No intentional interrupted-write test or AP/BIOS boot was performed in this
library test. The original pre-upgrade stock backup was preserved separately.

Raw evidence is retained locally under
`/home/zoid/clone/daniel-vibe-playground/circuitpython/ec/logs/lilac-stock-flash-20261115/library-test/`
(`backup.json`, `flash.json`, `boot.json`, `console.log`, `boot-recheck.log`).
All 28 host-only tests passed from this checkout before hardware testing.
