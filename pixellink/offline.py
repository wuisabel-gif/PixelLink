"""Portable, bounded complex64 capture with explicit oracle packet boundaries."""
import hashlib
import json
from pathlib import Path
import numpy as np
from .files import read_regular
from .core import FS, SPS, TONES, HEADER, MAX_SIDE, Receiver, awgn, modulate, demodulate, integer, identity

MAX_IQ_BYTES = MAX_SIDE * (HEADER.size + MAX_SIDE + 4) * 8 * SPS * 8


def export_iq(transfer, path, snr_db=20):
    if not np.isfinite(snr_db) or not -18 <= snr_db <= 20:
        raise ValueError('SNR out of range')
    path = Path(path)
    sidecar = Path(str(path) + '.json')
    rng = np.random.default_rng(transfer.seed)
    samples = [awgn(modulate(raw), snr_db, rng) for raw in transfer.frames]
    data = np.concatenate(samples).astype('<c8').tobytes()
    meta = {'format': 'pixellink-iq-v1', 'dtype': '<c8', 'sample_rate': FS,
            'samples_per_symbol': SPS, 'tones': list(TONES), 'identity': transfer.tid.hex(),
            'width': transfer.image.width, 'height': transfer.image.height,
            'packet_samples': [len(x) for x in samples], 'sha256': hashlib.sha256(data).hexdigest(),
            'snr_db': snr_db, 'seed': transfer.seed, 'synchronization': 'known packet and symbol boundaries'}
    created = []
    try:
        with path.open('xb') as f:
            created.append(path)
            with sidecar.open('x') as m:
                created.append(sidecar)
                f.write(data)
                json.dump(meta, m, indent=2)
    except BaseException:
        for owned in created:
            owned.unlink(missing_ok=True)
        raise
    return meta


def import_iq(path):
    path = Path(path)
    metadata = Path(str(path) + '.json')
    try:
        meta = json.loads(read_regular(metadata, 16384))
        if not isinstance(meta, dict):
            raise ValueError('Metadata must be an object')
        if (meta['format'], meta['dtype'], meta['sample_rate'], meta['samples_per_symbol'], meta['tones']) != ('pixellink-iq-v1', '<c8', FS, SPS, list(TONES)):
            raise ValueError('Unsupported modem metadata')
        w = integer(meta['width'], 1, MAX_SIDE, 'width')
        h = integer(meta['height'], 1, MAX_SIDE, 'height')
        tid = bytes.fromhex(meta['identity'])
        if len(tid) != 8:
            raise ValueError('Invalid identity')
        expected = (HEADER.size + w + 4) * 8 * SPS
        sizes = meta['packet_samples']
        if not isinstance(sizes, list) or len(sizes) != h or any(type(n) is not int or n != expected for n in sizes):
            raise ValueError('Invalid packet boundaries')
        data = read_regular(path, min(MAX_IQ_BYTES, expected * h * 8))
        if len(data) != expected * h * 8:
            raise ValueError('IQ length mismatch')
        if hashlib.sha256(data).hexdigest() != meta['sha256']:
            raise ValueError('Capture checksum mismatch')
        iq = np.frombuffer(data, dtype='<c8')
        if not np.isfinite(iq).all():
            raise ValueError('Nonfinite IQ')
    except (KeyError, TypeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('Malformed metadata') from exc
    receiver = Receiver(tid, w, h)
    rejected = 0
    for start in range(0, len(iq), expected):
        try:
            receiver.accept(demodulate(iq[start:start+expected]))
        except ValueError:
            rejected += 1
    complete = len(receiver.rows) == h
    if complete and identity(receiver.image()) != tid:
        raise ValueError('Reconstructed content identity mismatch')
    return receiver, {'received': len(receiver.rows), 'total': h, 'rejected': rejected,
                      'complete': complete, 'identity': tid.hex()}
