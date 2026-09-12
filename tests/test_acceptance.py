"""Independent transport acceptance tests: real signals, not mocked delivery."""
import unittest

import numpy as np
from PIL import Image

from pixellink.core import (
    Receiver, Transfer, awgn, demodulate, frame, identity, modulate, parse_frame,
)


class AcceptanceTests(unittest.TestCase):
    def test_noncoherent_receiver_handles_unknown_constant_phase(self):
        raw = np.random.default_rng(27).integers(0, 256, 257, dtype=np.uint8).tobytes()
        iq = modulate(raw)
        for phase in (0, 0.3, 1.7, np.pi):
            with self.subTest(phase=phase):
                self.assertEqual(demodulate(iq * np.exp(1j * phase)), raw)

    def test_every_single_bit_frame_corruption_is_rejected(self):
        image = Image.new('L', (19, 3), 127)
        raw = frame(identity(image), 0, 19, 3, bytes(range(19)))
        for offset in range(len(raw)):
            for bit in range(8):
                corrupt = bytearray(raw)
                corrupt[offset] ^= 1 << bit
                with self.subTest(offset=offset, bit=bit):
                    with self.assertRaises(ValueError):
                        parse_frame(bytes(corrupt))

    def test_rows_arrive_out_of_order_and_duplicates_are_idempotent(self):
        pixels = np.random.default_rng(13).integers(0, 256, (11, 17), dtype=np.uint8)
        image = Image.fromarray(pixels)
        transfer = Transfer(image)
        receiver = Receiver(identity(image), *image.size)
        for packet in reversed(transfer.frames):
            receiver.accept(packet)
            receiver.accept(packet)
        self.assertEqual(len(receiver.rows), image.height)
        self.assertEqual(receiver.image().tobytes(), image.tobytes())

    def test_other_transfer_and_conflicting_duplicate_cannot_overwrite_rows(self):
        first = Transfer(Image.new('L', (8, 2), 17))
        other = Transfer(Image.new('L', (8, 2), 18))
        first.receiver.accept(first.frames[0])
        with self.assertRaises(ValueError):
            first.receiver.accept(other.frames[0])
        forged = frame(first.tid, 0, 8, 2, bytes([99]) * 8)
        with self.assertRaises(ValueError):
            first.receiver.accept(forged)
        self.assertEqual(first.receiver.rows[0], bytes([17]) * 8)

    def test_degenerate_image_shapes_roundtrip_exactly(self):
        for width, height in ((1, 1), (1, 192), (192, 1), (37, 41)):
            with self.subTest(width=width, height=height):
                pixels = np.random.default_rng(8).integers(
                    0, 256, (height, width), dtype=np.uint8)
                transfer = Transfer(Image.fromarray(pixels))
                result = transfer.transmit(20)
                self.assertTrue(result['exact'])
                self.assertEqual(result['bitErrors'], 0)
                self.assertEqual(transfer.receiver.image().tobytes(), pixels.tobytes())

    def test_clean_retry_sends_only_missing_rows(self):
        transfer = Transfer(Image.new('L', (32, 64), 128), seed=17)
        initial = transfer.transmit(-2)
        missing = set(range(64)) - set(initial['accepted'])
        self.assertGreater(len(missing), 0)
        self.assertLess(len(missing), 64)
        attempts = list(initial['attempts'])
        recovered = transfer.transmit(20)
        self.assertTrue(recovered['exact'])
        self.assertEqual({e['seq'] for e in recovered['events']}, missing)
        for seq in range(64):
            self.assertEqual(recovered['attempts'][seq], attempts[seq] + (seq in missing))
        self.assertEqual(recovered['sent'] - initial['sent'], len(missing))

    def test_seed_reproduces_actual_noisy_demodulation(self):
        image = Image.new('L', (17, 23), 85)
        first = Transfer(image, seed=482).transmit(-5, retries=1)
        second = Transfer(image, seed=482).transmit(-5, retries=1)
        self.assertEqual(first, second)
        self.assertGreater(first['bitErrors'], 0)

    def test_complex_noise_power_matches_snr_definition(self):
        clean = np.ones(250_000, dtype=np.complex64)
        noisy = awgn(clean, 3.0, np.random.default_rng(61))
        noise = noisy - clean
        measured = 10 * np.log10(1 / np.mean(np.abs(noise) ** 2))
        self.assertAlmostEqual(float(measured), 3.0, delta=0.04)
        self.assertAlmostEqual(float(np.var(noise.real)),
                               float(np.var(noise.imag)), delta=0.004)

    def test_invalid_iq_is_rejected(self):
        for iq in ([], np.zeros(129), np.zeros((8, 16)),
                   np.full(128, np.nan), np.full(128, np.inf)):
            with self.subTest(shape=np.shape(iq)):
                with self.assertRaises(ValueError):
                    demodulate(iq)


if __name__ == '__main__':
    unittest.main()
