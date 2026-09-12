import io
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from PIL import Image
from pixellink.core import (Transfer, Receiver, demo_image, load_image, frame, parse_frame,
                            modulate, demodulate, awgn, HEADER, MAX_UPLOAD)
from pixellink.offline import export_iq, import_iq


class ModemTests(unittest.TestCase):
    def test_all_byte_values(self):
        raw = bytes(range(256))
        iq = modulate(raw)
        self.assertEqual(iq.dtype, np.complex64)
        self.assertEqual(demodulate(iq), raw)

    def test_noisy_seed_and_recovery(self):
        a, b = Transfer(demo_image(), 3), Transfer(demo_image(), 3)
        ra, rb = a.transmit(0), b.transmit(0)
        self.assertEqual(ra, rb)
        self.assertGreater(ra['missing'], 0)
        sent = ra['sent']
        recovered = a.transmit(20)
        self.assertTrue(recovered['exact'])
        self.assertEqual(recovered['sent']-sent, ra['missing'])
        self.assertEqual(a.transmit(20)['events'], [])

    def test_limits(self):
        for snr in (float('nan'), float('inf'), -19, 21, True, '3'):
            with self.assertRaises(ValueError): Transfer(demo_image()).transmit(snr)
        for retry in (-1, 9, True, 1.5):
            with self.assertRaises(ValueError): Transfer(demo_image()).transmit(0, retry)
        for iq in (np.ones(13), np.array([complex('nan')]*128), np.ones((128,1))):
            with self.assertRaises(ValueError): demodulate(iq)
        t = Transfer(Image.new('L',(1,1)))
        for _ in range(4): t.transmit(-18,7)
        with self.assertRaises(ValueError): t.transmit(0)


class FrameTests(unittest.TestCase):
    def setUp(self): self.raw = frame(b'12345678', 0, 4, 2, b'abcd')

    def test_roundtrip(self):
        self.assertEqual(parse_frame(self.raw), (b'12345678',0,4,2,b'abcd'))

    def test_malformed(self):
        for raw in (b'', self.raw[:-1], self.raw+b'x', b'BAD!'+self.raw[4:]):
            with self.assertRaises(ValueError): parse_frame(raw)
        for offset in range(len(self.raw)):
            corrupt = bytearray(self.raw); corrupt[offset] ^= 1
            with self.assertRaises(ValueError): parse_frame(corrupt)

    def test_wrong_transfer(self):
        r = Receiver(b'87654321',4,2)
        with self.assertRaises(ValueError): r.accept(self.raw)
        self.assertFalse(r.rows)


class ImageTests(unittest.TestCase):
    def test_normalization(self):
        out=io.BytesIO(); Image.new('RGB',(600,300),(20,90,100)).save(out,format='PNG')
        im=load_image(out.getvalue())
        self.assertEqual(im.mode,'L'); self.assertEqual(im.size,(192,96))

    def test_reject(self):
        for data in (b'', b'not an image', b'x'*(MAX_UPLOAD+1)):
            with self.assertRaises(ValueError): load_image(data)
        out=io.BytesIO(); Image.new('L',(1,1)).save(out,format='GIF')
        with self.assertRaises(ValueError): load_image(out.getvalue())


class OfflineTests(unittest.TestCase):
    def test_clean_roundtrip_and_damage(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'test.iq'; t=Transfer(Image.new('L',(12,9),127))
            export_iq(t,p)
            receiver, stats=import_iq(p)
            self.assertTrue(stats['complete']); self.assertEqual(receiver.image().tobytes(),t.image.tobytes())
            raw=bytearray(p.read_bytes()); raw[0]^=1; p.write_bytes(raw)
            with self.assertRaises(ValueError): import_iq(p)

    def test_metadata_bounds(self):
        for key,value in [('width',193),('sample_rate',1),('packet_samples',[1]),('identity','bad')]:
            with tempfile.TemporaryDirectory() as d:
                p=Path(d)/'test.iq'; export_iq(Transfer(Image.new('L',(2,2))),p)
                m=Path(str(p)+'.json'); meta=json.loads(m.read_text()); meta[key]=value; m.write_text(json.dumps(meta))
                with self.assertRaises(ValueError): import_iq(p)

    def test_collision_preserves_files(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'test.iq'; m=Path(str(p)+'.json'); m.write_text('existing')
            with self.assertRaises(FileExistsError): export_iq(Transfer(Image.new('L',(2,2))),p)
            self.assertFalse(p.exists()); self.assertEqual(m.read_text(),'existing')


if __name__ == '__main__': unittest.main()
