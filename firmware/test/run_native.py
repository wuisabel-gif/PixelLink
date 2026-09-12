#!/usr/bin/env python3
"""Compile real shared codec and check independent, repository JSON vectors."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

firmware = Path(__file__).resolve().parents[1]
vectors = json.loads((firmware.parent / 'tests/fixtures/telemetry_vectors.json').read_text())
with tempfile.TemporaryDirectory(prefix='pixellink-codec-') as temp:
    exe = str(Path(temp) / 'codec_test')
    subprocess.run([os.environ.get('CXX', 'c++'), '-std=c++11', '-Wall', '-Wextra',
                    '-Werror', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    '-I' + str(firmware / 'include'),
                    str(firmware / 'test/native/codec_test.cpp'), '-o', exe], check=True)
    for vector in vectors:
        args = [str(vector[k]) for k in ('flags', 'node_id', 'boot_id', 'sequence',
                                         'uptime_ms', 'adc_raw', 'frame_hex')]
        subprocess.run([exe, *args], check=True)
        print('PASS:', vector['name'], '(golden bytes, round-trip, bit errors, schema)')
print(f'{len(vectors)} native golden-vector suites passed with ASan/UBSan')
