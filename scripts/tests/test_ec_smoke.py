"""EC smoke tests: flash, boot, console, repeated reboot.

Run from the scripts dir, e.g.:
  pytest tests --ec-build ~/clone/ec/result
"""

import re

import pytest

BOOT_DONE = r"Inits done"
BOOT_TIMEOUT = 10
# Things that must never appear in a clean boot log
BAD_BOOT_RE = re.compile(
    r"panic|fatal|assert|watchdog|exception|stack overflow", re.IGNORECASE)


def parse_version(out):
    """Parse `version` console output into {'RO': ..., 'RW': ...}."""
    return dict(re.findall(r"^(RO|RW|Build):\s*(\S+)", out, re.MULTILINE))


def test_flash(ec, ec_build):
    if not ec_build:
        pytest.skip("no --ec-build given")
    ec.flash(ec_build["path"])
    ec.boot(BOOT_DONE, BOOT_TIMEOUT)


def test_boot(ec):
    log = ec.boot(BOOT_DONE, BOOT_TIMEOUT)
    assert "Booting Zephyr" in log
    assert re.search(r"Reset cause: .*reset-pin", log), log
    bad = BAD_BOOT_RE.search(log)
    assert not bad, f"boot log contains {bad.group(0)!r}:\n{log}"


def test_version(ec, ec_build):
    ec.wait_quiet(1.0, timeout=10)
    v = parse_version(ec.command("version"))
    assert v.get("RO") and v.get("RW"), v
    assert v["RO"] == v["RW"]
    if ec_build:
        assert ec_build["version"], "no version string found in ec.bin"
        assert v["RO"] == ec_build["version"]


def test_console_responsive(ec):
    out = ec.command("chan")
    assert "command" in out


@pytest.mark.parametrize("n", range(5))
def test_reboot(ec, n):
    log = ec.boot(BOOT_DONE, BOOT_TIMEOUT)
    bad = BAD_BOOT_RE.search(log)
    assert not bad, f"boot {n} log contains {bad.group(0)!r}:\n{log}"
