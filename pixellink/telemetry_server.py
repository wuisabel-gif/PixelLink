"""Allowlisted localhost, read-only dashboard for real USB observations."""
from http.server import HTTPServer
from pathlib import Path
from .server import Handler as BaseHandler
from .telemetry import SerialReader, TelemetryState

ASSETS = Path(__file__).parent / 'telemetry_static'


class Handler(BaseHandler):
    def guard(self, write=False):
        if len(self.headers.get_all('Host', [])) != 1 or len(self.headers.get_all('Origin', [])) > 1:
            self.respond(403, {'error': 'Ambiguous host/origin'})
            return False
        return super().guard(False)

    def do_GET(self):
        if not self.guard():
            return
        if self.path == '/api/state':
            return self.respond(200, self.server.state.snapshot())
        paths = {'/': ('index.html', 'text/html; charset=utf-8'),
                 '/telemetry.js': ('telemetry.js', 'text/javascript; charset=utf-8'),
                 '/telemetry.css': ('telemetry.css', 'text/css; charset=utf-8')}
        if self.path not in paths:
            return self.respond(404, {'error': 'Not found'})
        name, mime = paths[self.path]
        self.respond(200, (ASSETS / name).read_bytes(), mime)

    def do_POST(self):
        if self.guard():
            self.respond(405, {'error': 'Read-only telemetry; no serial control'})

    do_PUT = do_POST
    do_DELETE = do_POST
    do_PATCH = do_POST
    do_OPTIONS = do_POST


class Server(HTTPServer):
    def get_request(self):
        sock, address = super().get_request()
        sock.settimeout(2)
        return sock, address


def make_server(state, port=0):
    server = Server(('127.0.0.1', port), Handler)
    server.state = state
    return server


def serve(port=8000, serial_port=None, log_path=None):
    if log_path and not serial_port:
        raise ValueError('--log requires --serial-port')
    state = TelemetryState()
    reader = None
    server = make_server(state, port)
    try:
        if serial_port:
            reader = SerialReader(state, serial_port, log_path=log_path)
            reader.start()
        print(f'PixelLink hardware-live: http://127.0.0.1:{server.server_port}', flush=True)
        print('USB read-only; no transmit/configuration commands. ' +
              ('Connecting to ' + serial_port if serial_port else 'Waiting: choose an explicit --serial-port; no simulated samples.'), flush=True)
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        if reader:
            reader.stop()
        server.server_close()


def list_ports():
    try:
        from serial.tools.list_ports import comports
    except ImportError as exc:
        raise RuntimeError('Install hardware support: pip install ".[hardware]"') from exc
    return [dict(device=p.device, description=p.description, hwid=p.hwid)
            for p in sorted(comports(), key=lambda p: p.device)]
