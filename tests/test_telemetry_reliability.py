"""Bounded logging and reconnect regression checks using no hardware."""
import tempfile
import time
import unittest
from pathlib import Path
from pixellink.telemetry import SerialReader, TelemetryState

STATUS = b'{"type":"status","role":"rx","state":"unconfigured","frequency_mhz":0}\n'


class ReliabilityTests(unittest.TestCase):
    def test_size_limit_stops_log_not_reader_state(self):
        state = TelemetryState()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'raw.jsonl'
            reader = SerialReader(state, '/fake', serial_factory=lambda **kw: None,
                                  log_path=path, max_log_bytes=1024)
            for _ in range(30):
                state.ingest(STATUS)
                reader._record(STATUS)
            reader.stop()
            snapshot = state.snapshot()
            self.assertEqual(snapshot['log']['state'], 'size-limit-reached')
            self.assertLessEqual(path.stat().st_size, 1024)
            self.assertEqual(path.stat().st_size, snapshot['log']['bytes'])
            self.assertEqual(snapshot['receiver']['state'], 'unconfigured')
            self.assertIsNone(snapshot['latest'])
            self.assertTrue(all(raw == STATUS for raw in path.read_bytes().splitlines(keepends=True)))

    def test_reconnect_same_explicit_port_and_clean_stop(self):
        opened = []
        class Fake:
            def __init__(self, **kw):
                self.index = len(opened)
                self.reads = 0
            def open(self):
                opened.append(self.port)
            def read(self, size):
                self.reads += 1
                if self.reads == 1:
                    return STATUS
                if self.index == 0:
                    raise OSError('USB unplugged')
                time.sleep(.01)
                return b''
            def close(self):
                pass
        state = TelemetryState()
        reader = SerialReader(state, '/only-this-port', Fake)
        reader.start()
        deadline = time.monotonic()+3
        while state.snapshot()['counts']['reconnects'] < 1 and time.monotonic() < deadline:
            time.sleep(.01)
        reader.stop()
        self.assertFalse(reader.thread.is_alive())
        self.assertEqual(opened, ['/only-this-port', '/only-this-port'])
        self.assertEqual(state.snapshot()['counts']['reconnects'], 1)
        self.assertEqual(state.snapshot()['counts']['serial_errors'], 1)
        self.assertIsNone(state.snapshot()['latest'])
        self.assertIsNone(state.snapshot()['receiver'])


if __name__ == '__main__':
    unittest.main()
