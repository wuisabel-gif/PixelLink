"""Loopback-only, single-request-at-a-time dashboard server. No filesystem uploads."""
import base64
import binascii
import json
import secrets
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from .core import MAX_UPLOAD, Transfer, demo_image, load_image, integer

STATIC = Path(__file__).parent / 'static'
MAX_BODY = 6 * 1024 * 1024


class Server(HTTPServer):
    def __init__(self, address):
        if address[0] != '127.0.0.1':
            raise ValueError('PixelLink binds only to 127.0.0.1')
        super().__init__(address, Handler)
        self.token = secrets.token_urlsafe(32)
        self.sessions = {}

    def get_request(self):
        sock, addr = super().get_request()
        sock.settimeout(10)
        return sock, addr


class Handler(BaseHTTPRequestHandler):
    server_version = 'PixelLink/1'

    def log_message(self, fmt, *args):
        pass

    def respond(self, status, data, content_type='application/json'):
        if isinstance(data, dict):
            data = json.dumps(data, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True

    def guard(self, write=False):
        port = self.server.server_port
        hosts = (f'127.0.0.1:{port}', f'localhost:{port}')
        if self.headers.get('Host') not in hosts:
            self.respond(403, {'error': 'Invalid Host'})
            return False
        origin = self.headers.get('Origin')
        if origin is not None and origin not in tuple('http://' + h for h in hosts):
            self.respond(403, {'error': 'Cross-origin requests are forbidden'})
            return False
        if write and not secrets.compare_digest(self.headers.get('X-PixelLink-Token', '').encode('utf-8'), self.server.token.encode('ascii')):
            self.respond(403, {'error': 'Invalid request token'})
            return False
        return True

    def do_GET(self):
        if not self.guard():
            return
        if self.path == '/api/config':
            return self.respond(200, {'token': self.server.token, 'maxUpload': MAX_UPLOAD, 'maxSide': 192})
        paths = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if self.path not in paths:
            return self.respond(404, {'error': 'Not found'})
        name, mime = paths[self.path]
        self.respond(200, (STATIC / name).read_bytes(), mime)

    def do_POST(self):
        if not self.guard(write=True):
            return
        if self.path not in ('/api/transfer', '/api/retry'):
            return self.respond(404, {'error': 'Not found'})
        if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
            return self.respond(400, {'error': 'One Content-Length required; chunking unsupported'})
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.respond(415, {'error': 'application/json required'})
        try:
            length = int(self.headers.get('Content-Length', ''))
            if not 1 <= length <= MAX_BODY:
                return self.respond(413, {'error': 'Request body exceeds limit'})
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError('Incomplete request')
            obj = json.loads(raw)
            if not isinstance(obj, dict):
                raise ValueError('Expected JSON object')
            snr = obj.get('snr', 0)
            retries = obj.get('retries', 0)
            now = time.monotonic()
            self.server.sessions = {k: v for k, v in self.server.sessions.items() if now-v[0] < 1800}
            if self.path == '/api/transfer':
                seed = integer(obj.get('seed', 7), 0, 2**32-1, 'seed')
                encoded = obj.get('image')
                if encoded is None:
                    image = demo_image()
                else:
                    if not isinstance(encoded, str) or len(encoded) > 4*((MAX_UPLOAD+2)//3):
                        raise ValueError('Invalid image upload')
                    image = load_image(base64.b64decode(encoded, validate=True))
                transfer = Transfer(image, seed)
                result = transfer.transmit(snr, retries)
                if len(self.server.sessions) >= 8:
                    oldest = min(self.server.sessions, key=lambda k: self.server.sessions[k][0])
                    del self.server.sessions[oldest]
                sid = secrets.token_urlsafe(18)
            else:
                sid = obj.get('session')
                if not isinstance(sid, str) or sid not in self.server.sessions:
                    return self.respond(404, {'error': 'Session expired; start a new transfer'})
                transfer = self.server.sessions[sid][1]
                result = transfer.transmit(snr, retries)
            self.server.sessions[sid] = (now, transfer)
            result['session'] = sid
            self.respond(200, result)
        except (ValueError, TypeError, binascii.Error, UnicodeError, RecursionError) as exc:
            self.respond(400, {'error': str(exc)[:200]})
        except TimeoutError:
            self.respond(408, {'error': 'Request timed out'})


def serve(port=8000):
    with Server(('127.0.0.1', port)) as server:
        print(f'PixelLink simulation: http://127.0.0.1:{server.server_port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
