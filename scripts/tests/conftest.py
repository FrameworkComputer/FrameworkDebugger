"""pytest fixtures for EC hardware-in-the-loop tests via Bus Pirate 5.

Options:
  --ec-build PATH   build dir (ec.bin + npcx_monitor.bin) or ec.bin to
                    flash before the tests; without it, flash tests are
                    skipped and the image already on the EC is tested
  --ec-port PATH    BP5 binmode port (default: auto-detect)
  --ec-log PATH     timestamped console log (default: ec-console.log)
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ectarget import EcTarget, image_version, resolve_firmware  # noqa: E402


def pytest_addoption(parser):
    parser.addoption("--ec-build", default=None,
                     help="EC build dir or ec.bin to flash and test")
    parser.addoption("--ec-port", default=None,
                     help="BP5 binmode port (default: auto-detect)")
    parser.addoption("--ec-log", default="ec-console.log",
                     help="Timestamped EC console log file")


@pytest.fixture(scope="session")
def ec_build(request):
    path = request.config.getoption("--ec-build")
    if not path:
        return None
    ec_bin, _ = resolve_firmware(path)
    return {"path": path, "ec_bin": ec_bin, "version": image_version(ec_bin)}


@pytest.fixture(scope="session")
def ec(request):
    with EcTarget(request.config.getoption("--ec-port"),
                  logfile=request.config.getoption("--ec-log")) as target:
        yield target


@pytest.fixture(autouse=True)
def _mark_test_in_log(ec, request):
    ec.note(f"test {request.node.nodeid}")
    yield
