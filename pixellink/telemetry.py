"""Read-only hardware telemetry. No simulator imports or synthetic samples.

Logs contain original accepted USB JSON lines (including status/error), not
normalized state. Malformed input is counted but never logged as telemetry.
"""
import json
import math
import re
import struct
import threading
import time
import zlib
from collections import Counter, OrderedDict, deque

FRAME = struct.Struct('<4sBBHIIIHHI')
MAX_LINE = 1024
MAX_SESSIONS = 128
MAX_FORWARD_GAP = 1000000


class CRCError(ValueError):
    pass


def decode_frame(raw):
    if not isinstance(raw, bytes) or len(raw) != FRAME.size:
        raise ValueError('Frame must contain exactly 28 bytes')
    magic, version, flags, node, boot, seq, uptime, adc, reserved, crc = FRAME.unpack(raw)
    if magic != b'PXLT' or version != 1 or flags & ~1 or not node or reserved:
        raise ValueError('Invalid frame header')
    if (flags & 1 and adc > 4095) or (not flags & 1 and adc != 65535):
        raise ValueError('Invalid ADC encoding')
    if zlib.crc32(raw[:24]) != crc:
        raise CRCError('Application CRC mismatch')
    return dict(node_id=node, boot_id=boot, sequence=seq, uptime_ms=uptime,
                adc_valid=bool(flags & 1), adc_raw=adc if flags & 1 else None)


def _pairs(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError('Duplicate JSON key')
        obj[key] = value
    return obj


def parse_line(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_LINE:
        raise ValueError('Invalid serial line length')
    try:
        obj = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                         parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    except (UnicodeError, RecursionError) as exc:
        raise ValueError('Invalid USB JSON') from exc
    if not isinstance(obj, dict):
        raise ValueError('USB envelope must be an object')
    kind = obj.get('type')
    if kind == 'packet':
        text = obj.get('frame')
        rssi, lqi = obj.get('rssi_dbm'), obj.get('lqi')
        if not isinstance(text, str) or not re.fullmatch('[0-9a-fA-F]{56}', text):
            raise ValueError('Invalid frame hex')
        # Bounds precede float conversion: JSON may contain a 400-digit int.
        if type(rssi) not in (int, float) or not -140 <= rssi <= 20 or not math.isfinite(rssi):
            raise ValueError('Invalid RSSI')
        if type(lqi) is not int or not 0 <= lqi <= 127:
            raise ValueError('Invalid LQI')
        return dict(type=kind, **decode_frame(bytes.fromhex(text)), rssi_dbm=rssi, lqi=lqi)
    if kind == 'status':
        if obj.get('role') not in ('rx', 'tx') or obj.get('state') not in (
                'unconfigured', 'ready', 'receiving', 'armed', 'disarmed', 'error'):
            raise ValueError('Invalid receiver status')
        frequency = obj.get('frequency_mhz')
        if frequency is not None and (type(frequency) not in (int, float) or
                                     not 0 <= frequency <= 1000 or not math.isfinite(frequency)):
            raise ValueError('Invalid frequency')
        return {k: obj[k] for k in ('type', 'role', 'state', 'frequency_mhz') if k in obj}
    if kind == 'error':
        if type(obj.get('code')) is not int or not -(2**31) <= obj['code'] < 2**31:
            raise ValueError('Invalid receiver error code')
        if not isinstance(obj.get('message'), str) or len(obj['message']) > 256:
            raise ValueError('Invalid receiver error message')
        return {k: obj[k] for k in ('type', 'code', 'message')}
    raise ValueError('Unknown USB envelope')


class TelemetryState:
    def __init__(self):
        self.lock = threading.RLock()
        self.started = time.monotonic()
        self.counts = Counter(validated_packets=0, duplicates=0, out_of_order=0,
                              observed_gaps=0, sequence_discontinuities=0, session_starts=0,
                              malformed_lines=0, crc_failures=0, oversized_lines=0,
                              serial_errors=0, receiver_errors=0, reconnects=0)
        self.sessions = OrderedDict()
        self.history = deque(maxlen=240)
        self.latest = None
        self.last_rx = None
        self.receiver = None
        self.receiver_time = None
        self.serial = dict(connected=False, port=None, state='waiting', error=None)
        self.log = dict(state='disabled', bytes=0, error=None)

    def serial_status(self, **values):
        with self.lock:
            self.serial.update(values)
            if not self.serial['connected']:
                self.receiver = None
                self.receiver_time = None

    def ingest(self, raw):
        try:
            event = parse_line(raw)
        except ValueError as exc:
            with self.lock:
                self.counts['crc_failures' if isinstance(exc, CRCError) else 'malformed_lines'] += 1
            return False
        now = time.monotonic()
        with self.lock:
            if event['type'] == 'status':
                self.receiver = event
                self.receiver_time = now
            elif event['type'] == 'error':
                self.counts['receiver_errors'] += 1
                self.serial['receiver_error'] = event
            else:
                self.counts['validated_packets'] += 1
                key = (event['node_id'], event['boot_id'])
                seq = event['sequence']
                session = self.sessions.get(key)
                classification = 'first'
                if session is None:
                    self.counts['session_starts'] += 1
                    session = {'high': seq, 'seen': deque(maxlen=256)}
                    self.sessions[key] = session
                    if len(self.sessions) > MAX_SESSIONS:
                        self.sessions.popitem(last=False)
                elif seq in session['seen'] or seq == session['high']:
                    self.counts['duplicates'] += 1
                    classification = 'duplicate'
                else:
                    delta = (seq - session['high']) & 0xffffffff
                    if 0 < delta < 0x80000000:
                        if delta - 1 <= MAX_FORWARD_GAP:
                            self.counts['observed_gaps'] += delta - 1
                            classification = 'forward'
                        else:
                            self.counts['sequence_discontinuities'] += 1
                            classification = 'discontinuity'
                        session['high'] = seq
                    else:
                        self.counts['out_of_order'] += 1
                        classification = 'out_of_order'
                if seq not in session['seen']:
                    session['seen'].append(seq)
                self.sessions.move_to_end(key)
                event['classification'] = classification
                self.latest = event
                self.last_rx = now
                self.history.append(dict(elapsed_s=now-self.started, rssi_dbm=event['rssi_dbm']))
        return True

    def snapshot(self):
        with self.lock:
            now = time.monotonic()
            return dict(mode='hardware-live', host_uptime_s=now-self.started,
                        serial=dict(self.serial), receiver=dict(self.receiver) if self.receiver else None,
                        receiver_age_s=None if self.receiver_time is None else now-self.receiver_time,
                        latest=dict(self.latest) if self.latest else None,
                        last_packet_age_s=None if self.last_rx is None else now-self.last_rx,
                        counts=dict(self.counts), history=list(self.history), sessions_tracked=len(self.sessions),
                        log=dict(self.log), gap_note='Observed sequence gaps can include RF, TX, USB, or disconnected time; not RF loss alone.')


class SerialReader:
    def __init__(self, state, port, serial_factory=None, log_path=None, max_log_bytes=64*1024*1024):
        if not isinstance(port, str) or not port:
            raise ValueError('Explicit serial port required')
        if max_log_bytes < MAX_LINE:
            raise ValueError('Log limit must be at least 1024 bytes')
        if serial_factory is None:
            try:
                import serial
            except ImportError as exc:
                raise RuntimeError('Install hardware support: pip install ".[hardware]"') from exc
            serial_factory = serial.Serial
        self.factory = serial_factory
        self.state, self.port = state, port
        self.halt = threading.Event()
        self.thread = None
        self.device = None
        self.logfile = open(log_path, 'xb') if log_path else None
        self.max_log_bytes = max_log_bytes
        if self.logfile:
            state.log['state'] = 'recording-original-usb-jsonl'
        state.serial_status(port=port, state='disconnected')

    def start(self):
        if self.thread is not None:
            raise RuntimeError('Reader already started')
        self.thread = threading.Thread(target=self._run, name='pixellink-usb', daemon=True)
        self.thread.start()

    def _record(self, raw):
        if self.logfile is None:
            return
        with self.state.lock:
            if self.state.log['bytes'] + len(raw) > self.max_log_bytes:
                self.logfile.close()
                self.logfile = None
                self.state.log['state'] = 'size-limit-reached'
                return
            try:
                self.logfile.write(raw)
                self.logfile.flush()
                self.state.log['bytes'] += len(raw)
            except OSError as exc:
                self.state.log.update(state='error', error=str(exc))
                try:
                    self.logfile.close()
                except OSError:
                    pass
                self.logfile = None

    def _run(self):
        connected_once = False
        while not self.halt.is_set():
            device = None
            try:
                device = self.factory(port=None, baudrate=115200, timeout=0.25)
                self.device = device
                # Set lines before opening. OS/USB drivers may still pulse at open.
                device.dtr = False
                device.rts = False
                device.port = self.port
                device.open()
                with self.state.lock:
                    if connected_once:
                        self.state.counts['reconnects'] += 1
                connected_once = True
                self.state.serial_status(connected=True, state='connected', error=None)
                pending = bytearray()
                dropping = False
                while not self.halt.is_set():
                    chunk = device.read(256)
                    for byte in chunk:
                        if dropping:
                            if byte == 10:
                                dropping = False
                            continue
                        pending.append(byte)
                        if len(pending) > MAX_LINE:
                            pending.clear()
                            dropping = byte != 10
                            with self.state.lock:
                                self.state.counts['oversized_lines'] += 1
                                self.state.counts['malformed_lines'] += 1
                        elif byte == 10:
                            raw = bytes(pending)
                            pending.clear()
                            if self.state.ingest(raw):
                                self._record(raw)
            except Exception as exc:
                if not self.halt.is_set():
                    with self.state.lock:
                        self.state.counts['serial_errors'] += 1
                    self.state.serial_status(connected=False, state='error',
                                             error=f'{type(exc).__name__}: {exc}')
            finally:
                if device is not None:
                    try:
                        device.close()
                    except Exception:
                        pass
                self.device = None
            self.halt.wait(1)
        self.state.serial_status(connected=False, state='stopped')

    def stop(self):
        self.halt.set()
        if self.thread is not None:
            self.thread.join(timeout=3)
        if self.logfile is not None:
            try:
                self.logfile.close()
                self.state.log['state'] = 'closed'
            except OSError as exc:
                self.state.log.update(state='error', error=str(exc))
            self.logfile = None
