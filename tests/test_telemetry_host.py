import http.client
import json
import struct
import tempfile
import threading
import time
import unittest
import zlib
from pathlib import Path

from pixellink.telemetry import CRCError, SerialReader, TelemetryState, decode_frame, parse_line
from pixellink.telemetry_server import make_server


def frame(seq=0, boot=1, node=1, flags=0, adc=65535, reserved=0):
    raw = struct.pack('<4sBBHIIIHH', b'PXLT', 1, flags, node, boot, seq, 1234, adc, reserved)
    return raw + struct.pack('<I', zlib.crc32(raw))


def line(seq=0, boot=1, **kw):
    return (json.dumps(dict(type='packet', frame=frame(seq, boot, **kw).hex(), rssi_dbm=-63.5, lqi=42))+'\n').encode()


class CodecTests(unittest.TestCase):
    def test_frame_validation(self):
        self.assertEqual(decode_frame(frame())['uptime_ms'], 1234)
        self.assertIsNone(decode_frame(frame())['adc_raw'])
        self.assertEqual(decode_frame(frame(flags=1, adc=4095))['adc_raw'], 4095)
        for raw in [frame()[:-1], frame()+b'0', frame(flags=2), frame(node=0),
                    frame(reserved=1), frame(adc=0), frame(flags=1, adc=4096)]:
            with self.assertRaises(ValueError):
                decode_frame(raw)
        raw = bytearray(frame()); raw[16] ^= 1
        with self.assertRaises(CRCError):
            decode_frame(bytes(raw))

    def test_bad_envelopes(self):
        obj = json.loads(line())
        for key, values in [('rssi_dbm', [True, None, -141, 21, float('nan'), float('inf'), 10**400]),
                            ('lqi', [True, -1, 128, 1.0]), ('frame', ['00', 'z'*56])]:
            for value in values:
                bad = dict(obj); bad[key] = value
                with self.assertRaises(ValueError, msg=(key, value)):
                    parse_line(json.dumps(bad).encode())
        for raw in [b'booting\n', b'[]', b'\xff', b'{"type":"status","type":"error"}', b'x'*1025,
                    json.dumps(dict(type='status',role='rx',state='ready',frequency_mhz=10**400)).encode()]:
            with self.assertRaises(ValueError):
                parse_line(raw)

    def test_metrics_wrap_restart_order_and_bounds(self):
        s = TelemetryState()
        for seq in [0xfffffffe, 0xffffffff, 0, 0, 3, 2, 4]:
            self.assertTrue(s.ingest(line(seq)))
        s.ingest(line(0, boot=2))
        counts = s.snapshot()['counts']
        self.assertEqual(counts['duplicates'], 1)
        self.assertEqual(counts['out_of_order'], 1)
        self.assertEqual(counts['observed_gaps'], 2)
        self.assertEqual(counts['session_starts'], 2)
        s.ingest(line(2000000, boot=2))
        self.assertEqual(s.snapshot()['counts']['sequence_discontinuities'], 1)
        self.assertEqual(s.snapshot()['counts']['observed_gaps'], 2)
        for boot in range(300):
            s.ingest(line(1, boot=boot))
        self.assertEqual(len(s.sessions), 128)
        self.assertEqual(len(s.history), 240)

    def test_error_status_do_not_create_samples(self):
        s = TelemetryState()
        self.assertTrue(s.ingest(b'{"type":"status","role":"rx","state":"unconfigured","frequency_mhz":0}\n'))
        self.assertTrue(s.ingest(b'{"type":"error","code":-7,"message":"radio unavailable"}\n'))
        snapshot = s.snapshot()
        self.assertIsNone(snapshot['latest'])
        self.assertEqual(snapshot['history'], [])
        self.assertEqual(snapshot['receiver']['state'], 'unconfigured')
        self.assertEqual(snapshot['counts']['receiver_errors'], 1)
        s.serial_status(connected=False)
        self.assertIsNone(s.snapshot()['receiver'])


class ReaderTests(unittest.TestCase):
    def test_thread_read_only_framing_logging_shutdown(self):
        chunks = [b'boot\n', b'x'*1025+b'\n', line(4)[:8], line(4)[8:]]
        class Fake:
            def __init__(self, **kw):
                self.kw = kw
                self.closed = False
            def open(self):
                assert self.dtr is False and self.rts is False
                assert self.kw == dict(port=None, baudrate=115200, timeout=0.25)
            def read(self, n):
                if chunks:
                    return chunks.pop(0)
                time.sleep(.005)
                return b''
            def close(self):
                self.closed = True
            def write(self, data):
                raise AssertionError('Host must never write')
        s = TelemetryState()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'usb.jsonl'
            reader = SerialReader(s, '/fake', Fake, path)
            reader.start()
            deadline = time.monotonic()+2
            while s.snapshot()['latest'] is None and time.monotonic()<deadline:
                time.sleep(.01)
            reader.stop()
            self.assertFalse(reader.thread.is_alive())
            self.assertEqual(path.read_bytes(), line(4))
            self.assertEqual(s.snapshot()['counts']['malformed_lines'], 2)
            self.assertEqual(s.snapshot()['log']['state'], 'closed')
            self.assertEqual(s.snapshot()['serial']['state'], 'stopped')
            with self.assertRaises(FileExistsError):
                SerialReader(s, '/fake', Fake, path)

    def test_serial_error_no_fallback(self):
        def fail(**kw):
            raise OSError('No such port')
        s = TelemetryState(); reader = SerialReader(s, '/missing', fail)
        reader.start()
        deadline = time.monotonic()+1
        while not s.snapshot()['counts']['serial_errors'] and time.monotonic()<deadline:
            time.sleep(.01)
        reader.stop()
        self.assertIsNone(s.snapshot()['latest'])
        self.assertEqual(s.snapshot()['counts']['serial_errors'], 1)
        self.assertIn('OSError', s.snapshot()['serial']['error'])


class HTTPTests(unittest.TestCase):
    def test_empty_state_and_security(self):
        s = TelemetryState(); server = make_server(s)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        def request(path, method='GET', headers=None):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse(); result = response.status, response.read()
            connection.close(); return result
        try:
            code, body = request('/api/state')
            self.assertEqual(code, 200)
            state = json.loads(body)
            self.assertEqual(state['mode'], 'hardware-live')
            self.assertIsNone(state['latest'])
            self.assertEqual(state['history'], [])
            for headers in [dict(Host='evil.example'), dict(Origin='https://evil.example')]:
                self.assertEqual(request('/api/state', headers=headers)[0], 403)
            self.assertEqual(request('/api/state', method='POST')[0], 405)
            self.assertEqual(request('/../pyproject.toml')[0], 404)
            self.assertEqual(request('/app.js')[0], 404)
            self.assertIn(b'HARDWARE LIVE', request('/')[1])
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    unittest.main()
