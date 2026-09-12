"""Black-box HTTP checks against a real ephemeral loopback server."""
import base64
import http.client
import io
import json
import threading
import unittest

from PIL import Image

from pixellink.server import MAX_BODY, Server


class HTTPAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = Server(('127.0.0.1', 0))
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        buf = io.BytesIO()
        Image.new('L', (16, 16), 123).save(buf, 'PNG')
        cls.image = base64.b64encode(buf.getvalue()).decode('ascii')

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            data = response.read()
            return response.status, dict(response.getheaders()), data
        finally:
            connection.close()

    def post(self, obj, path='/api/transfer', headers=None):
        combined = {'Content-Type': 'application/json',
                    'X-PixelLink-Token': self.server.token}
        combined.update(headers or {})
        status, response_headers, data = self.request(
            'POST', path, json.dumps(obj).encode(), combined)
        return status, response_headers, json.loads(data)

    def test_config_and_security_headers(self):
        status, headers, body = self.request('GET', '/api/config')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['token'], self.server.token)
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertNotIn('Access-Control-Allow-Origin', headers)

    def test_static_assets_and_allowlisted_routes(self):
        for path, mime in (('/', 'text/html'), ('/app.js', 'text/javascript'),
                           ('/style.css', 'text/css')):
            with self.subTest(path=path):
                status, headers, body = self.request('GET', path)
                self.assertEqual(status, 200)
                self.assertTrue(headers['Content-Type'].startswith(mime))
                self.assertGreater(len(body), 100)
        for path in ('/../README.md', '/%2e%2e/README.md', '/pixellink/core.py'):
            self.assertEqual(self.request('GET', path)[0], 404)

    def test_host_and_origin_rejected(self):
        for headers in ({'Host': 'attacker.example'},
                        {'Origin': 'https://attacker.example'},
                        {'Origin': 'null'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request('GET', '/api/config', headers=headers)[0], 403)

    def test_tokens_rejected_without_server_exception(self):
        for token in ('', 'wrong', '\xff'):
            with self.subTest(token=token):
                self.assertEqual(self.post({}, headers={'X-PixelLink-Token': token})[0], 403)

    def test_uploaded_image_roundtrip_through_http(self):
        status, _, result = self.post({'image': self.image, 'snr': 20, 'seed': 4})
        self.assertEqual(status, 200)
        self.assertTrue(result['exact'])
        self.assertEqual(result['tx'], result['rx'])
        self.assertEqual(result['received'], 16)
        self.assertEqual(result['bitErrors'], 0)
        status, _, no_op = self.post({'session': result['session'], 'snr': 20}, '/api/retry')
        self.assertEqual(status, 200)
        self.assertEqual(no_op['events'], [])
        self.assertEqual(no_op['sent'], result['sent'])

    def test_bad_channel_then_clean_retry(self):
        status, _, bad = self.post({'image': self.image, 'snr': -18, 'seed': 4})
        self.assertEqual(status, 200)
        self.assertGreater(bad['missing'], 0)
        self.assertFalse(bad['exact'])
        status, _, good = self.post({'session': bad['session'], 'snr': 20}, '/api/retry')
        self.assertEqual(status, 200)
        self.assertTrue(good['exact'])
        self.assertEqual(len(good['events']), bad['missing'])

    def test_invalid_input_does_not_break_next_request(self):
        invalid = [[], {'seed': True}, {'seed': -1}, {'snr': True},
                   {'snr': float('nan')}, {'snr': 21}, {'retries': 9},
                   {'retries': 0.5}, {'image': 'not base64!'},
                   {'image': base64.b64encode(b'not an image').decode()},
                   {'image': {}}, {'image': ''}]
        for obj in invalid:
            with self.subTest(obj=obj):
                self.assertEqual(self.post(obj)[0], 400)
        self.assertEqual(self.request('GET', '/api/config')[0], 200)

    def test_unknown_session_is_not_found(self):
        for sid in ('unknown', [], None):
            self.assertEqual(self.post({'session': sid}, '/api/retry')[0], 404)

    def test_body_size_and_content_type_rejected_before_processing(self):
        self.assertEqual(self.post({}, headers={'Content-Type': 'text/plain'})[0], 415)
        headers = {'Content-Type': 'application/json',
                   'X-PixelLink-Token': self.server.token,
                   'Content-Length': str(MAX_BODY + 1)}
        self.assertEqual(self.request('POST', '/api/transfer', b'', headers)[0], 413)

    def test_malformed_and_deep_json_return_errors(self):
        headers = {'Content-Type': 'application/json',
                   'X-PixelLink-Token': self.server.token}
        for body in (b'{', b'\xff', b'[' * 2000 + b']' * 2000):
            with self.subTest(size=len(body)):
                self.assertEqual(self.request('POST', '/api/transfer', body, headers)[0], 400)

    def test_server_cannot_bind_public_interface(self):
        with self.assertRaises(ValueError):
            Server(('0.0.0.0', 0))


if __name__ == '__main__':
    unittest.main()
