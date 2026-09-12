"""Compile actual firmware control flow against native mock peripherals.

This is not an ESP32 firmware build or a physical radio test. PlatformIO builds
are separate; these tests verify arming, expiry, reset and receiver-only gates.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMPILER = shutil.which('c++') or shutil.which('g++') or shutil.which('clang++')


@unittest.skipUnless(COMPILER, 'Requires a native C++17 compiler')
class FirmwareControlTests(unittest.TestCase):
    def verify_role(self, role, expected):
        with tempfile.TemporaryDirectory() as folder:
            executable = Path(folder) / 'control'
            command = [COMPILER, '-std=c++17', f'-DPIXELLINK_TX={role}',
                       '-I' + str(ROOT / 'tests/firmware_mocks'),
                       '-I' + str(ROOT / 'firmware/include'),
                       str(ROOT / 'tests/firmware_control.cpp'), '-o', str(executable)]
            built = subprocess.run(command, capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            tested = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
            self.assertEqual(tested.returncode, 0, tested.stdout + tested.stderr)
            self.assertIn(expected, tested.stdout)

    def test_transmitter_requires_arm_and_expires_safely(self):
        self.verify_role(1, 'TX control:')

    def test_receiver_never_transmits_and_rejects_corrupt_frames(self):
        self.verify_role(0, 'RX control:')


if __name__ == '__main__':
    unittest.main()
