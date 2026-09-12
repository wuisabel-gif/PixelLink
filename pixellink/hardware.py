"""Optional, explicitly invoked Pluto RX capture. Never creates a TX buffer.

This is an acquisition boundary, NOT an over-air PixelLink receiver. Captures
have unknown timing and use a separate format from the simulated IQ importer.
API reference: Analog Devices pyadi-iio Buffers and adi.ad936x.Pluto docs.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
from pathlib import Path

import numpy as np

from .core import integer

MAX_CAPTURE_SAMPLES = 1_048_576


def _open_pluto(uri):
    try:
        import adi
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            'Pluto capture needs optional pyadi-iio and its native libiio dependencies. '
            'See README.md; simulation does not require them.'
        ) from exc
    return adi.Pluto(uri=uri)


def capture_pluto(path, *, uri, frequency, sample_rate=1_000_000,
                  samples=65_536, gain=20):
    """Capture one bounded, unaligned RX block and an exclusive JSON sidecar.

    Frequency/rate/gain validity ultimately depends on the connected device's
    firmware and driver. No frequency is chosen implicitly. Values outside
    these conservative software bounds are rejected before device access.
    """
    if not isinstance(uri, str) or not uri or len(uri) > 256 or any(ord(c) < 32 for c in uri):
        raise ValueError('Supply an explicit Pluto URI, at most 256 printable characters')
    integer(frequency, 1, 6_000_000_000, 'frequency in Hz')
    integer(sample_rate, 521_000, 20_000_000, 'sample rate')
    integer(samples, 128, MAX_CAPTURE_SAMPLES, 'capture sample count')
    if isinstance(gain, bool) or not isinstance(gain, (int, float)) or not np.isfinite(gain) or not 0 <= gain <= 60:
        raise ValueError('Manual RX gain must be finite and between 0 and 60 dB')
    path = Path(path)
    sidecar = Path(str(path) + '.json')
    # Check early for ordinary mistakes; exclusive creation below also handles races.
    if path.exists() or sidecar.exists():
        raise FileExistsError('Capture or JSON sidecar already exists')
    if not path.parent.is_dir():
        raise FileNotFoundError('Capture output directory does not exist')

    radio = None
    try:
        radio = _open_pluto(uri)
        radio.rx_enabled_channels = [0]
        radio.sample_rate = sample_rate
        radio.rx_lo = frequency
        radio.rx_rf_bandwidth = min(sample_rate, 20_000_000)
        radio.gain_control_mode_chan0 = 'manual'
        radio.rx_hardwaregain_chan0 = gain
        radio.rx_buffer_size = samples
        captured = np.asarray(radio.rx())
        if (captured.ndim != 1 or captured.size != samples
                or not np.iscomplexobj(captured) or not np.isfinite(captured).all()):
            raise ValueError('Pluto returned an unexpected, non-complex, or invalid RX block')
        iq = captured.astype('<c8')
        if not np.isfinite(iq).all():
            raise ValueError('RX samples exceed complex64 range')
        data = iq.tobytes()
        metadata = {
            'format': 'pixellink-pluto-rx-v1',
            'dtype': '<c8',
            'samples': samples,
            'sample_rate': int(radio.sample_rate),
            'center_frequency_hz': int(radio.rx_lo),
            'rx_bandwidth_hz': int(radio.rx_rf_bandwidth),
            'gain_mode': 'manual',
            'rx_gain_db': float(radio.rx_hardwaregain_chan0),
            'sample_units': 'raw device ADC units; not unit-amplitude normalized',
            'synchronization': 'unaligned; no packet, symbol, or carrier acquisition',
            'sha256': hashlib.sha256(data).hexdigest(),
        }
    finally:
        if radio is not None:
            with contextlib.suppress(Exception):
                radio.rx_destroy_buffer()

    created = []
    try:
        with path.open('xb') as output:
            created.append(path)
            with sidecar.open('x', encoding='utf-8') as description:
                created.append(sidecar)
                output.write(data)
                json.dump(metadata, description, indent=2, allow_nan=False)
    except BaseException:
        for owned in created:
            owned.unlink(missing_ok=True)
        raise
    return metadata
