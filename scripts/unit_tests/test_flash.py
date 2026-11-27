"""Host-only tests: no EcTarget constructor, serial port, reset or flash write."""
import contextlib
import hashlib
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ectarget import EcTarget, FlashError, resolve_firmware
from npcx_rom import CHIP_ID, DEVICE_ID, FLASH_BASE, RomError, RomReader, crc16


def frame(data, command=0x1c):
    payload = bytes([command]) + data
    return payload + crc16(payload).to_bytes(2, 'big')


class Wire:
    def __init__(self, faults=()):
        self.commands = []
        self.faults = list(faults)
        self.reader = RomReader(self.send, time.monotonic() + 10,
                                response_timeout=0.001)

    def send(self, command):
        self.commands.append(command)
        if command == b'\x55':
            self.reader.feed(b'\x5a')
            return
        assert crc16(command[:-2]) == int.from_bytes(command[-2:], 'big')
        address = int.from_bytes(command[2:6], 'big')
        size = command[1] + 1
        if address == CHIP_ID:
            data = b'\x09'
        elif address == DEVICE_ID:
            data = b'\x25'
        else:
            data = bytes((address + i) & 255 for i in range(size))
        response = frame(data)
        if self.faults:
            response = self.faults.pop(0)(response)
        self.reader.feed(response[:2])
        self.reader.feed(response[2:])


def test_crc_vector():
    assert crc16(bytes.fromhex('1cff6400f600')) == 0xd84e


@pytest.mark.parametrize('fault', [
    lambda r: r[:-1],
    lambda r: r[:-1] + bytes([r[-1] ^ 1]),
    lambda r: frame(r[1:-2], 0xff),
    lambda r: r + b'extra',
])
def test_invalid_responses_retry_and_resync(fault):
    wire = Wire([fault])
    assert wire.reader.read(FLASH_BASE, 4) == bytes(range(4))
    assert wire.commands[1] == b'\x55'
    assert wire.reader.retries == 1
    assert wire.reader.read(FLASH_BASE + 4, 4) == bytes(range(4, 8))


def test_delayed_frame_not_accepted_as_sync():
    wire = Wire()
    original = wire.send
    replies = iter([frame(b'old') + b'\x5a', b'\x5a'])
    def send(command):
        if command == b'\x55':
            wire.reader.feed(next(replies))
        else:
            original(command)
    wire.reader.send = send
    wire.reader.sync()
    assert wire.reader.read(FLASH_BASE, 4) == bytes(range(4))


def test_retry_limit():
    wire = Wire([lambda r: b'wrong'] * 2)
    wire.reader.attempts = 2
    with pytest.raises(RomError, match='failed'):
        wire.reader.read(FLASH_BASE, 4)
    assert wire.reader.retries == 2


def test_deadline_and_invalid_sizes_never_send():
    wire = Wire()
    for size in [0, 129]:
        with pytest.raises(ValueError):
            wire.reader.read(FLASH_BASE, size)
    wire.reader.deadline = time.monotonic() - 1
    with pytest.raises(RomError, match='timed out'):
        wire.reader.read(FLASH_BASE, 4)
    assert not wire.commands


def test_uart_failure_propagates():
    wire = Wire()
    wire.reader.fail(OSError('disconnected'))
    with pytest.raises(RomError, match='disconnected'):
        wire.reader._receive(1, .01)


def test_geometry_and_chunk_boundaries():
    wire = Wire()
    assert wire.reader.flash_size() == 524288
    assert wire.reader.read_flash(129) == bytes(range(129))
    wire.reader.read = lambda address, size: b'\xff'
    with pytest.raises(RomError, match='Unsupported'):
        wire.reader.flash_size()


@pytest.fixture
def target():
    ec = EcTarget.__new__(EcTarget)
    ec.last_flash_read = None
    ec.note = Mock()
    ec.reset = Mock()
    ec._gpio = Mock()
    ec._load_monitor = Mock()
    ec._run_updater = Mock()
    ec._sink = None
    ec._sink_lock = threading.RLock()
    ec._partial = b''
    return ec


def setup_flash(ec, size, actual):
    reader = SimpleNamespace(flash_size=lambda: size,
                             read_flash=lambda size: actual, retries=2)
    @contextlib.contextmanager
    def rom(deadline):
        yield reader
    @contextlib.contextmanager
    def pty():
        yield '/dev/pts/test'
    ec._rom_session = rom
    ec.pty_bridge = pty


def image_dir(tmp_path, data):
    (tmp_path / 'ec.bin').write_bytes(data)
    (tmp_path / 'npcx_monitor.bin').write_bytes(b'monitor')
    return tmp_path


def test_flash_success_is_readback_verified(target, tmp_path):
    setup_flash(target, 4, b'abcd')
    report = target.flash(image_dir(tmp_path, b'abcd'))
    assert report['sha256'] == hashlib.sha256(b'abcd').hexdigest()
    target._run_updater.assert_called_once()
    target.reset.assert_not_called()


def test_flash_readback_mismatch_cannot_report_success(target, tmp_path):
    setup_flash(target, 4, b'abXd')
    with pytest.raises(FlashError, match='offset 0x2'):
        target.flash(image_dir(tmp_path, b'abcd'))
    target.reset.assert_not_called()
    target._gpio.assert_not_called()


def test_flash_oversize_rejected_before_programming(target, tmp_path):
    setup_flash(target, 2, b'ab')
    with pytest.raises(FlashError, match='exceeds'):
        target.flash(image_dir(tmp_path, b'abcd'))
    target._run_updater.assert_not_called()


def test_flash_empty_rejected_before_isp(target, tmp_path):
    with pytest.raises(FlashError, match='empty'):
        target.flash(image_dir(tmp_path, b''))
    target._load_monitor.assert_not_called()


def test_flash_updater_failure_not_retried(target, tmp_path):
    setup_flash(target, 4, b'abcd')
    target._run_updater.side_effect = FlashError('program failed')
    with pytest.raises(FlashError, match='program failed'):
        target.flash(image_dir(tmp_path, b'abcd'))
    target._run_updater.assert_called_once()
    target.reset.assert_not_called()


def fake_reads(ec, values):
    values = iter(values)
    def read(*args):
        ec.last_flash_read = {'retries': 2}
        return next(values)
    ec._read_flash = Mock(side_effect=read)


def test_backup_mismatch_never_publishes_file(target, tmp_path):
    fake_reads(target, [b'abcd', b'abcX'])
    path = tmp_path / 'stock.bin'
    with pytest.raises(FlashError, match='differ'):
        target.backup(path)
    assert not path.exists()
    target.reset.assert_not_called()


def test_backup_exclusive_and_matching(target, tmp_path):
    fake_reads(target, [b'abcd', b'abcd'])
    path = tmp_path / 'stock.bin'
    report = target.backup(path)
    assert report['sha256'] == hashlib.sha256(b'abcd').hexdigest()
    assert path.read_bytes() == b'abcd'
    with pytest.raises(FileExistsError):
        target.backup(path)
    assert target._read_flash.call_count == 2


def test_single_image_prefers_sibling_monitor(tmp_path):
    image_dir(tmp_path, b'abcd')
    assert resolve_firmware(tmp_path / 'ec.bin')[1] == tmp_path / 'npcx_monitor.bin'


def test_binary_session_restores_sink_on_failure(target, monkeypatch):
    fake = SimpleNamespace(sync=Mock(side_effect=RomError('bad sync')))
    monkeypatch.setattr('ectarget.RomReader', lambda *a: fake)
    with pytest.raises(FlashError, match='bad sync'):
        with target._rom_session(time.monotonic() + 1):
            pass
    assert target._sink is None


def test_binary_session_rejects_nested_sink(target):
    target._sink = object()
    with pytest.raises(Exception, match='already has an active'):
        with target._rom_session(time.monotonic() + 1):
            pass


def test_unknown_geometry_blocks_programming(target, tmp_path):
    @contextlib.contextmanager
    def unknown(deadline):
        raise FlashError('Unsupported NPCX device')
        yield
    target._rom_session = unknown
    with pytest.raises(FlashError, match='Unsupported'):
        target.flash(image_dir(tmp_path, b'abcd'))
    target._run_updater.assert_not_called()


@pytest.mark.parametrize('timeout', [-1, 0, float('inf'), float('nan')])
def test_invalid_total_deadline_rejected(target, tmp_path, timeout):
    with pytest.raises(ValueError, match='positive and finite'):
        target.flash(image_dir(tmp_path, b'abcd'), timeout=timeout)
    target._load_monitor.assert_not_called()


@pytest.mark.parametrize('action', ['--flash', '--backup'])
def test_cli_failure_never_resets(monkeypatch, action):
    import buspirate_ctrl
    ec = SimpleNamespace(status={}, port='fake', close=Mock(), reset=Mock(),
                         flash=Mock(side_effect=FlashError('readback mismatch')),
                         backup=Mock(side_effect=FlashError('backups differ')))
    monkeypatch.setattr(buspirate_ctrl, 'EcTarget', lambda *a, **kw: ec)
    monkeypatch.setattr(sys, 'argv', ['buspirate_ctrl.py', action, 'firmware'])
    assert buspirate_ctrl.main() == 1
    ec.reset.assert_not_called()
    ec.close.assert_called_once()


def test_cli_interruption_is_nonzero(monkeypatch):
    import buspirate_ctrl
    ec = SimpleNamespace(status={}, port='fake', close=Mock(), reset=Mock(),
                         backup=Mock(side_effect=KeyboardInterrupt))
    monkeypatch.setattr(buspirate_ctrl, 'EcTarget', lambda *a, **kw: ec)
    monkeypatch.setattr(sys, 'argv', ['buspirate_ctrl.py', '--backup', 'backup'])
    assert buspirate_ctrl.main() == 130
    ec.reset.assert_not_called()
    ec.close.assert_called_once()


def test_isp_strap_break_cleared_before_uart_traffic(monkeypatch):
    ec = object.__new__(EcTarget)
    ec.baud = 57600
    events = []
    ec.note = lambda text: None
    ec._gpio = lambda pin, value: events.append(("gpio", pin, value))
    ec._config = lambda **kw: events.append(("config", kw))
    ec.bp = SimpleNamespace(clear_async_queue=lambda: events.append(("clear",)))
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    ec.enter_flash_mode()
    assert events[:4] == [("gpio", 7, 0), ("gpio", 3, 0), ("gpio", 3, None), ("gpio", 7, 1)]
    cfg = events[4][1]
    assert cfg["mode"] == "UART" and cfg["mode_configuration"]["speed"] == 57600
    assert cfg["io_direction_mask"] == (1 << 3 | 1 << 7)
    assert cfg["io_direction"] == cfg["io_value"] == cfg["io_value_mask"] == 1 << 7
    assert events[-1] == ("clear",)


def test_reset_biases_shared_tx_high(monkeypatch):
    ec = object.__new__(EcTarget)
    events = []
    ec.note = lambda text: None
    ec._gpio = lambda pin, value: events.append((pin, value))
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    ec.reset()
    assert events == [(7, 1), (3, 0), (3, None)]
