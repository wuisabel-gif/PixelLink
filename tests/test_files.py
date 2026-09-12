import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from pixellink.files import read_regular
from pixellink.offline import export_iq, import_iq
from pixellink.core import Transfer
from PIL import Image


class FileSafetyTests(unittest.TestCase):
    def test_bounded_regular_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'data'; p.write_bytes(b'1234')
            self.assertEqual(read_regular(p,4), b'1234')
            with self.assertRaises(ValueError): read_regular(p,3)
            with self.assertRaises(ValueError): read_regular(d,20)

    @unittest.skipUnless(Path('/dev/zero').exists(), 'POSIX device required')
    def test_device_and_cli_fail_promptly(self):
        with self.assertRaises(ValueError): read_regular('/dev/zero',100)
        result = subprocess.run([sys.executable,'-m','pixellink','demo','--image','/dev/zero'], capture_output=True, timeout=5)
        self.assertEqual(result.returncode,2)
        self.assertIn(b'regular file',result.stderr)

    @unittest.skipUnless(hasattr(os,'mkfifo') and hasattr(os,'O_NONBLOCK'), 'POSIX FIFO required')
    def test_fifo_does_not_wait_for_writer(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'fifo'; os.mkfifo(p)
            result = subprocess.run([sys.executable,'-m','pixellink','demo','--image',str(p)], capture_output=True, timeout=5)
            self.assertEqual(result.returncode,2)
            self.assertIn(b'regular file',result.stderr)

    @unittest.skipUnless(Path('/dev/zero').exists(), 'POSIX device required')
    def test_offline_devices_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'capture.iq'
            export_iq(Transfer(Image.new('L',(2,2))),p)
            p.unlink(); p.symlink_to('/dev/zero')
            with self.assertRaises(ValueError): import_iq(p)
            metadata=Path(str(p)+'.json'); metadata.unlink(); metadata.symlink_to('/dev/zero')
            with self.assertRaises(ValueError): import_iq(p)


if __name__ == '__main__': unittest.main()
