"""Independent hardware-path acceptance checks. PTYs are test fixtures, not RF.

Frames here are packed independently from the implementation; golden vectors
also serve the C++ firmware tests. Nothing connects to a physical serial port.
"""
import http.client
import importlib.util
import json
import os
from pathlib import Path
import select
import struct
import tempfile
import threading
import time
import unittest
import zlib

from pixellink.telemetry import MAX_SESSIONS, SerialReader, TelemetryState, decode_frame, parse_line
from pixellink.telemetry_server import make_server


def packet(sequence=0, boot=17, node=1, adc=None):
    body = struct.pack('<4sBBHIIIHH', b'PXLT', 1, int(adc is not None), node,
                       boot, sequence, (sequence * 1000) & 0xffffffff,
                       65535 if adc is None else adc, 0)
    return body + struct.pack('<I', zlib.crc32(body))


def envelope(sequence=0, boot=17, node=1, adc=None):
    return (json.dumps({'type': 'packet', 'frame': packet(sequence, boot, node, adc).hex(),
                        'rssi_dbm': -65.5, 'lqi': 37}) + '\n').encode()


def wait_for(predicate, seconds=4):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError('Condition not reached before deadline')


class WireAcceptanceTests(unittest.TestCase):
    def test_shared_golden_vectors_decode(self):
        vectors = json.loads((Path(__file__).parent / 'fixtures/telemetry_vectors.json').read_text())
        for vector in vectors:
            with self.subTest(name=vector['name']):
                decoded = decode_frame(bytes.fromhex(vector['frame_hex']))
                for field in ('node_id', 'boot_id', 'sequence', 'uptime_ms'):
                    self.assertEqual(decoded[field], vector[field])
                self.assertEqual(decoded['adc_valid'], bool(vector['flags'] & 1))
                self.assertEqual(decoded['adc_raw'], vector['adc_raw'] if vector['flags'] else None)

    def test_every_single_bit_corruption_is_rejected(self):
        original = packet(19, adc=2031)
        for byte in range(len(original)):
            for bit in range(8):
                damaged = bytearray(original)
                damaged[byte] ^= 1 << bit
                with self.subTest(byte=byte, bit=bit), self.assertRaises(ValueError):
                    decode_frame(bytes(damaged))

    def test_fresh_live_state_has_no_invented_measurements(self):
        snapshot = TelemetryState().snapshot()
        self.assertEqual(snapshot['mode'], 'hardware-live')
        self.assertFalse(snapshot['serial']['connected'])
        self.assertIsNone(snapshot['latest'])
        self.assertIsNone(snapshot['last_packet_age_s'])
        self.assertEqual(snapshot['history'], [])
        self.assertEqual(snapshot['counts']['validated_packets'], 0)
        for field in ('snr', 'ber', 'exact', 'tx', 'rx'):
            self.assertNotIn(field, snapshot)

    def test_wrap_duplicate_out_of_order_and_reboot_accounting(self):
        state = TelemetryState()
        for sequence in (0xfffffffe, 0xffffffff, 0, 2, 2, 1, 3):
            self.assertTrue(state.ingest(envelope(sequence)))
        counts = state.snapshot()['counts']
        self.assertEqual(counts['observed_gaps'], 1)
        self.assertEqual(counts['duplicates'], 1)
        self.assertEqual(counts['out_of_order'], 1)
        self.assertEqual(counts['sequence_discontinuities'], 0)
        state.ingest(envelope(0, boot=18))
        state.ingest(envelope(10, boot=18, node=2))
        snapshot = state.snapshot()
        self.assertEqual(snapshot['counts']['observed_gaps'], 1)
        self.assertEqual(snapshot['counts']['session_starts'], 3)

    def test_large_forward_jump_does_not_manufacture_billions_of_losses(self):
        state = TelemetryState()
        state.ingest(envelope(0))
        state.ingest(envelope(0x40000000))
        counts = state.snapshot()['counts']
        self.assertEqual(counts['observed_gaps'], 0)
        self.assertEqual(counts['sequence_discontinuities'], 1)

    def test_history_and_sessions_are_bounded(self):
        state = TelemetryState()
        for node in range(1, MAX_SESSIONS + 15):
            state.ingest(envelope(0, node=node))
        for sequence in range(300):
            state.ingest(envelope(sequence, node=65535))
        snapshot = state.snapshot()
        self.assertLessEqual(snapshot['sessions_tracked'], MAX_SESSIONS)
        self.assertLessEqual(len(snapshot['history']), 240)

    def test_malformed_numeric_envelopes_do_not_escape_validation(self):
        good = json.loads(envelope())
        for field, value in [('rssi_dbm', 10**400), ('rssi_dbm', float('nan')),
                             ('rssi_dbm', True), ('lqi', 128), ('lqi', 0.5)]:
            with self.subTest(field=field, value=str(value)[:30]):
                data = dict(good, **{field: value})
                with self.assertRaises(ValueError):
                    parse_line(json.dumps(data).encode())
        with self.assertRaises(ValueError):
            parse_line(b'{"type":"status","role":"rx","state":"ready","frequency_mhz":' + b'9'*400 + b'}')


@unittest.skipUnless(os.name == 'posix' and importlib.util.find_spec('serial'),
                     'Requires POSIX pseudo-terminals and optional pyserial')
class VirtualUSBTests(unittest.TestCase):
    def test_real_serial_reader_and_http_with_fragmented_input(self):
        import pty
        master, slave = pty.openpty()
        port = os.ttyname(slave)
        state = TelemetryState()
        server = make_server(state, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / 'received.jsonl'
            reader = SerialReader(state, port, log_path=log)
            try:
                reader.start()
                wait_for(lambda: state.snapshot()['serial']['connected'])
                status = b'{"type":"status","role":"rx","state":"receiving","frequency_mhz":433.5}\n'
                os.write(master, b'ESP32 ROM boot chatter\n')
                os.write(master, b'x' * 2048 + b'\n')
                os.write(master, status)
                first = envelope(4, adc=2048)
                os.write(master, first[:13])
                time.sleep(0.03)
                os.write(master, first[13:])
                os.write(master, envelope(6, adc=2049))
                wait_for(lambda: state.snapshot()['counts']['validated_packets'] == 2)
                client = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                try:
                    client.request('GET', '/api/state')
                    response = client.getresponse()
                    self.assertEqual(response.status, 200)
                    snapshot = json.loads(response.read())
                finally:
                    client.close()
                self.assertEqual(snapshot['latest']['sequence'], 6)
                self.assertEqual(snapshot['latest']['adc_raw'], 2049)
                self.assertEqual(snapshot['counts']['observed_gaps'], 1)
                self.assertEqual(snapshot['counts']['oversized_lines'], 1)
                self.assertEqual(snapshot['counts']['malformed_lines'], 2)
                self.assertEqual(snapshot['receiver']['state'], 'receiving')
                # A receive-only host must never send commands to the attached node.
                self.assertFalse(select.select([master], [], [], 0.05)[0])
            finally:
                reader.stop()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                os.close(master)
                os.close(slave)
            self.assertFalse(reader.thread.is_alive())
            self.assertFalse(state.snapshot()['serial']['connected'])
            recorded = [json.loads(line) for line in log.read_bytes().splitlines()]
            self.assertEqual(len(recorded), 3)
            self.assertEqual([row['type'] for row in recorded], ['status', 'packet', 'packet'])


if __name__ == '__main__':
    unittest.main()
