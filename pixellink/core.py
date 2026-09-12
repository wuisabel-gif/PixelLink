"""Bounded grayscale row transport over simulated complex-baseband binary FSK."""
from __future__ import annotations
import base64
import hashlib
import io
import struct
import zlib
from dataclasses import dataclass
import numpy as np
from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

MAX_SIDE = 192
MAX_UPLOAD = 4 * 1024 * 1024
MAX_SOURCE_PIXELS = 16_000_000
FS = 48000
SPS = 16
TONES = (-3000, 3000)
HEADER = struct.Struct('!4sB8sHHHHH')
MAGIC = b'PXLK'


def integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name} must be an integer from {low} to {high}')
    return value


def demo_image():
    im = Image.new('L', (160, 120))
    a = np.asarray(im).copy()
    y, x = np.indices(a.shape)
    a[:] = ((x * 1.1 + y * .5) % 220).astype('uint8')
    im = Image.fromarray(a)
    d = ImageDraw.Draw(im)
    d.ellipse((42, 15, 117, 90), fill=235)
    d.ellipse((58, 30, 109, 81), fill=65)
    d.polygon([(0, 119), (45, 66), (78, 107), (119, 60), (159, 119)], fill=30)
    d.text((9, 9), 'PIXEL / LINK', fill=255)
    return im


def load_image(data):
    if not data or len(data) > MAX_UPLOAD:
        raise ValueError('Image must be 1 byte to 4 MiB')
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format not in ('PNG', 'JPEG', 'WEBP', 'BMP'):
                raise ValueError('Use PNG, JPEG, WebP or BMP')
            if im.width * im.height > MAX_SOURCE_PIXELS:
                raise ValueError('Source image exceeds 16 million pixels')
            im = ImageOps.exif_transpose(im)
            im.thumbnail((MAX_SIDE, MAX_SIDE))
            return im.convert('L').copy()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('Invalid or oversized image') from exc


def png(im):
    out = io.BytesIO()
    im.save(out, format='PNG')
    return out.getvalue()


def data_url(im):
    return 'data:image/png;base64,' + base64.b64encode(png(im)).decode()


def identity(im):
    return hashlib.sha256(struct.pack('!HH', *im.size) + im.tobytes()).digest()[:8]


def frame(tid, seq, width, height, payload):
    if len(tid) != 8 or not 1 <= width <= MAX_SIDE or not 1 <= height <= MAX_SIDE:
        raise ValueError('Invalid frame geometry or identity')
    if not 0 <= seq < height or len(payload) != width:
        raise ValueError('Invalid row')
    head = HEADER.pack(MAGIC, 1, tid, seq, height, width, height, len(payload))
    body = head + payload
    return body + struct.pack('!I', zlib.crc32(body))


def parse_frame(raw):
    if not HEADER.size + 5 <= len(raw) <= HEADER.size + MAX_SIDE + 4:
        raise ValueError('Frame size out of range')
    magic, version, tid, seq, total, width, height, length = HEADER.unpack(raw[:HEADER.size])
    if magic != MAGIC or version != 1:
        raise ValueError('Invalid magic/version')
    if not 1 <= width <= MAX_SIDE or not 1 <= height <= MAX_SIDE or total != height or seq >= total:
        raise ValueError('Invalid geometry/sequence')
    if length != width or len(raw) != HEADER.size + length + 4:
        raise ValueError('Invalid payload length')
    if zlib.crc32(raw[:-4]) != struct.unpack('!I', raw[-4:])[0]:
        raise ValueError('CRC mismatch')
    return tid, seq, width, height, raw[HEADER.size:-4]


def bits(raw):
    return np.unpackbits(np.frombuffer(raw, dtype=np.uint8))


def modulate(raw):
    """Orthogonal tones, integer cycles/symbol; phase returns to zero each symbol."""
    b = bits(raw)
    n = np.arange(SPS)
    table = np.exp(2j * np.pi * np.asarray(TONES)[:, None] * n / FS)
    return table[b].reshape(-1).astype(np.complex64)


def demodulate(iq):
    iq = np.asarray(iq)
    if iq.ndim != 1 or not len(iq) or len(iq) % (8 * SPS) or not np.isfinite(iq).all():
        raise ValueError('IQ must contain finite whole-byte symbol blocks')
    n = np.arange(SPS)
    refs = np.exp(-2j * np.pi * np.asarray(TONES)[:, None] * n / FS)
    energy = np.abs(iq.reshape(-1, SPS) @ refs.T) ** 2
    return np.packbits((energy[:, 1] > energy[:, 0]).astype(np.uint8)).tobytes()


def awgn(iq, snr_db, rng):
    # Unit-power signal; SNR is signal / total complex noise power per sample.
    sigma = np.sqrt(10 ** (-snr_db / 10) / 2)
    return (iq + sigma * (rng.standard_normal(len(iq)) + 1j * rng.standard_normal(len(iq)))).astype(np.complex64)


@dataclass
class Receiver:
    tid: bytes
    width: int
    height: int

    def __post_init__(self):
        self.rows = {}

    def accept(self, raw):
        tid, seq, w, h, payload = parse_frame(raw)
        if (tid, w, h) != (self.tid, self.width, self.height):
            raise ValueError('Wrong transfer identity or dimensions')
        if seq in self.rows and self.rows[seq] != payload:
            raise ValueError('Conflicting duplicate')
        self.rows[seq] = payload
        return seq

    def image(self):
        y, x = np.indices((self.height, self.width))
        a = np.where((x // 8 + y // 8) % 2, 42, 55).astype(np.uint8)
        for seq, payload in self.rows.items():
            a[seq] = np.frombuffer(payload, dtype=np.uint8)
        return Image.fromarray(a)


class Transfer:
    def __init__(self, image, seed=7):
        integer(seed, 0, 2**32 - 1, 'seed')
        if image.mode != 'L' or not all(1 <= v <= MAX_SIDE for v in image.size):
            raise ValueError('Expected bounded grayscale image')
        self.image = image.copy()
        self.tid = identity(image)
        self.receiver = Receiver(self.tid, *image.size)
        w, h = image.size
        self.frames = [frame(self.tid, y, w, h, image.tobytes()[y*w:(y+1)*w]) for y in range(h)]
        self.rng = np.random.default_rng(seed)
        self.seed = seed
        self.attempts = [0] * h
        self.bit_errors = self.bit_count = self.failed = self.sent = 0
        self.trace = None
        self.round = 0

    def transmit(self, snr_db, retries=0):
        if isinstance(snr_db, bool) or not isinstance(snr_db, (int, float)) or not np.isfinite(snr_db) or not -18 <= snr_db <= 20:
            raise ValueError('SNR must be finite and between -18 and 20 dB')
        integer(retries, 0, 8, 'retries')
        if self.round + retries + 1 > 32:
            raise ValueError('32-round session limit; start a new transfer')
        events = []
        for _ in range(retries + 1):
            pending = [i for i in range(len(self.frames)) if i not in self.receiver.rows]
            if not pending:
                break
            self.round += 1
            for seq in pending:
                raw = self.frames[seq]
                tx = modulate(raw)
                rx = awgn(tx, snr_db, self.rng)
                decoded = demodulate(rx)
                errors = int(np.count_nonzero(bits(raw) != bits(decoded)))
                self.bit_errors += errors
                self.bit_count += len(raw) * 8
                self.attempts[seq] += 1
                self.sent += 1
                try:
                    accepted = self.receiver.accept(decoded)
                    ok = True
                except ValueError:
                    accepted = seq
                    ok = False
                    self.failed += 1
                events.append({'seq': accepted, 'ok': ok, 'attempt': self.attempts[seq], 'errors': errors,
                               'row': base64.b64encode(self.receiver.rows[accepted]).decode() if ok else None})
                if self.trace is None or seq == pending[0]:
                    spectrum = 20 * np.log10(np.maximum(np.abs(np.fft.fftshift(np.fft.fft(rx[:2048] * np.hanning(2048)))) / 2048, 1e-8))
                    self.trace = {'i': rx[:256].real.tolist(), 'q': rx[:256].imag.tolist(), 'spectrum': spectrum[::8].tolist()}
        result = self.snapshot()
        result['events'] = events
        return result

    def snapshot(self):
        count = len(self.receiver.rows)
        exact = count == self.image.height and self.receiver.image().tobytes() == self.image.tobytes()
        return {'identity': self.tid.hex(), 'width': self.image.width, 'height': self.image.height,
                'tx': data_url(self.image), 'rx': data_url(self.receiver.image()), 'seed': self.seed,
                'received': count, 'total': self.image.height, 'rounds': self.round,
                'sent': self.sent, 'failed': self.failed, 'bitErrors': self.bit_errors, 'bits': self.bit_count,
                'ber': self.bit_errors / self.bit_count if self.bit_count else 0,
                'packetErrorRate': self.failed / self.sent if self.sent else 0,
                'missing': self.image.height-count, 'exact': exact, 'attempts': self.attempts,
                'accepted': sorted(self.receiver.rows), 'trace': self.trace,
                'rows': {str(seq): base64.b64encode(payload).decode() for seq, payload in self.receiver.rows.items()},
                'signalSeconds': self.bit_count * SPS / FS}
