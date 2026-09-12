"""Mock-only receive adapter checks. No connected SDR is required or exercised."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from pixellink.hardware import capture_pluto, _open_pluto
from pixellink.offline import import_iq


class FakePluto:
    def __init__(self, fail=False, invalid=False):
        self.destroyed = False
        self.fail = fail
        self.invalid = invalid
        self.reads = 0

    def __setattr__(self, name, value):
        if name.startswith('tx'):
            raise AssertionError('Receive adapter must never configure TX')
        object.__setattr__(self, name, value)

    def rx(self):
        self.reads += 1
        if self.fail:
            raise RuntimeError('Simulated device disconnection')
        n = self.rx_buffer_size
        if self.invalid:
            return np.ones(n, dtype=np.float32)
        return (np.arange(n) + 1j * np.arange(n)[::-1]).astype(np.complex64)

    def rx_destroy_buffer(self):
        self.destroyed = True

    def tx(self, *args, **kwargs):
        raise AssertionError('Receive adapter must never transmit')


class HardwareTests(unittest.TestCase):
    def test_receive_only_capture_has_distinct_format_and_exact_samples(self):
        radio = FakePluto()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'capture.iq'
            with patch('pixellink.hardware._open_pluto', return_value=radio) as connect:
                metadata = capture_pluto(output, uri='ip:test.invalid', frequency=900_000_000,
                                         samples=128, gain=12)
            connect.assert_called_once_with('ip:test.invalid')
            self.assertTrue(radio.destroyed)
            self.assertEqual(radio.reads, 1)
            self.assertEqual(radio.rx_enabled_channels, [0])
            self.assertEqual(radio.gain_control_mode_chan0, 'manual')
            self.assertEqual(output.stat().st_size, 128 * 8)
            data = output.read_bytes()
            actual = np.frombuffer(data, dtype='<c8')
            np.testing.assert_array_equal(actual.real, np.arange(128))
            np.testing.assert_array_equal(actual.imag, np.arange(128)[::-1])
            self.assertEqual(metadata['format'], 'pixellink-pluto-rx-v1')
            self.assertEqual(metadata['sha256'], hashlib.sha256(data).hexdigest())
            self.assertEqual(metadata, json.loads(Path(str(output) + '.json').read_text()))
            with self.assertRaises(ValueError):
                import_iq(output)

    def test_validation_precedes_device_access(self):
        defaults = {'uri': 'ip:test.invalid', 'frequency': 900_000_000}
        for key, value in [('uri', ''), ('uri', '\ninvalid'), ('frequency', True),
                           ('frequency', -1), ('sample_rate', 48_000),
                           ('sample_rate', 20_000_001), ('samples', 0),
                           ('samples', 1_048_577), ('gain', float('nan')),
                           ('gain', True), ('gain', 61)]:
            with self.subTest(key=key, value=value):
                arguments = dict(defaults, **{key: value})
                with patch('pixellink.hardware._open_pluto') as connect:
                    with self.assertRaises(ValueError):
                        capture_pluto('unused.iq', **arguments)
                    connect.assert_not_called()

    def test_existing_output_is_never_replaced_and_radio_is_not_opened(self):
        for suffix in ('', '.json'):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as folder:
                output = Path(folder) / 'capture.iq'
                existing = Path(str(output) + suffix)
                existing.write_bytes(b'keep this')
                with patch('pixellink.hardware._open_pluto') as connect:
                    with self.assertRaises(FileExistsError):
                        capture_pluto(output, uri='ip:test.invalid', frequency=900_000_000)
                    connect.assert_not_called()
                self.assertEqual(existing.read_bytes(), b'keep this')

    def test_rx_failure_releases_buffer_and_leaves_no_files(self):
        for invalid in (False, True):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as folder:
                output = Path(folder) / 'capture.iq'
                radio = FakePluto(fail=not invalid, invalid=invalid)
                with patch('pixellink.hardware._open_pluto', return_value=radio):
                    with self.assertRaises((ValueError, RuntimeError)):
                        capture_pluto(output, uri='ip:test.invalid', frequency=900_000_000)
                self.assertTrue(radio.destroyed)
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_missing_optional_dependency_has_actionable_error(self):
        with patch.dict('sys.modules', {'adi': None}):
            with self.assertRaisesRegex(RuntimeError, 'pyadi-iio.*libiio'):
                _open_pluto('ip:test.invalid')


if __name__ == '__main__':
    unittest.main()
