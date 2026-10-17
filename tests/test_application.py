import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import unittest

import httpx
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app
from app.middleware import RequestGuard


class FakeEngine:
    def __init__(self, settings):
        self.model_sha256 = settings.inference['model_sha256']
        self.mapping_sha256 = settings.inference['mapping_sha256']
        self.calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.block = False
        self.fail = False
        self.images = []

    def predict(self, image):
        self.calls += 1
        self.images.append(image)
        self.entered.set()
        try:
            if self.block and not self.release.wait(5):
                raise RuntimeError('Test timed out')
            if self.fail:
                raise RuntimeError('private engine detail')
            return [{'class_id': 0, 'confidence': 0.95,
                     'bbox_xyxy': [0.1, 0.2, 0.8, 0.9], 'needs_review': False}]
        finally:
            self.finished.set()


class ApplicationFixture:
    def __init__(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / 'model').mkdir()
        (self.root / 'config').mkdir()
        rows = [{'class_id': index, 'product_code': f'synthetic-{index}',
                 'item_seq': f'{index:09d}'} for index in range(150)]
        mapping = json.dumps(rows).encode()
        (self.root / 'model/classes.json').write_bytes(mapping)
        template = Path(__file__).resolve().parents[1] / 'config/inference.example.json'
        self.options = json.loads(template.read_text(encoding='utf-8'))
        self.options['model_sha256'] = '0' * 64
        self.options['mapping_sha256'] = hashlib.sha256(mapping).hexdigest()
        self.save_options()
        self.key = secrets.token_urlsafe(32)
        self.settings = Settings(root=self.root, api_key=self.key, device='cpu')
        self.engines = []
        self.app = create_app(self.settings, self.engine_factory)

    def save_options(self):
        (self.root / 'config/inference.json').write_text(json.dumps(self.options), encoding='utf-8')

    def engine_factory(self, settings):
        engine = FakeEngine(settings)
        self.engines.append(engine)
        return engine

    @property
    def headers(self):
        return {'X-API-Key': self.key}

    def files(self):
        with Image.new('RGB', (32, 24), 'white') as image:
            output = BytesIO()
            image.save(output, format='PNG')
        return {'file': ('synthetic.png', output.getvalue(), 'image/png')}

    def close(self):
        self.temporary.cleanup()


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ApplicationFixture()
        self.addCleanup(self.fixture.close)

    def test_lifespan_loads_once_and_public_contract_is_unchanged(self):
        fixture = self.fixture
        self.assertEqual(fixture.engines, [])
        with TestClient(fixture.app) as client:
            for request_index in range(2):
                response = client.post('/predict', headers=fixture.headers, files=fixture.files())
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {
                    'model': 'H', 'model_sha256': '0' * 64,
                    'mapping_sha256': fixture.options['mapping_sha256'],
                    'image': {'width': 32, 'height': 24},
                    'predictions': [{'detection_id': 1, 'class_id': 0, 'item_seq': '000000000',
                                     'confidence': 0.95, 'bbox_xyxy': [0.1, 0.2, 0.8, 0.9],
                                     'recognition_may_be_degraded': False}],
                })
                self.assertEqual(fixture.engines[0].calls, request_index + 1)
            self.assertEqual(len(fixture.engines), 1)
            self.assertEqual(client.get('/health', headers=fixture.headers).status_code, 200)
        self.assertEqual(client.get('/health', headers=fixture.headers).status_code, 503)

    def test_invalid_inputs_and_authentication_never_reach_engine(self):
        fixture = self.fixture
        with TestClient(fixture.app) as client:
            self.assertEqual(client.get('/health').status_code, 401)
            self.assertEqual(client.post('/predict', content=b'not multipart').status_code, 401)
            self.assertEqual(client.post('/predict', headers=fixture.headers).status_code, 422)
            for content, mime, expected in [(b'', 'image/png', 400),
                                            (b'broken', 'image/png', 415),
                                            (b'broken', 'text/plain', 415)]:
                response = client.post('/predict', headers=fixture.headers,
                                       files={'file': ('image.png', content, mime)})
                self.assertEqual(response.status_code, expected)
            for path in ['/docs', '/redoc', '/openapi.json']:
                self.assertEqual(client.get(path, headers=fixture.headers).status_code, 404)
            self.assertEqual(fixture.engines[0].calls, 0)

    def test_busy_does_not_block_health_or_overlap_model_calls(self):
        fixture = self.fixture
        with TestClient(fixture.app) as client, ThreadPoolExecutor(max_workers=1) as pool:
            engine = fixture.engines[0]
            engine.block = True
            first = pool.submit(client.post, '/predict', headers=fixture.headers, files=fixture.files())
            try:
                self.assertTrue(engine.entered.wait(3))
                self.assertEqual(client.get('/health', headers=fixture.headers).status_code, 200)
                busy = client.post('/predict', headers=fixture.headers, files=fixture.files())
                self.assertEqual(busy.status_code, 503)
                self.assertEqual(busy.headers['retry-after'], '1')
                self.assertEqual(engine.calls, 1)
            finally:
                engine.release.set()
            self.assertEqual(first.result(timeout=3).status_code, 200)

    def test_engine_failure_hides_detail_closes_image_and_releases_capacity(self):
        fixture = self.fixture
        with TestClient(fixture.app) as client:
            engine = fixture.engines[0]
            engine.fail = True
            with self.assertLogs('pillguide', level='ERROR'):
                failed = client.post('/predict', headers=fixture.headers, files=fixture.files())
            self.assertEqual(failed.status_code, 500)
            self.assertNotIn('private engine detail', failed.text)
            with self.assertRaises(ValueError):
                engine.images[0].getpixel((0, 0))
            engine.fail = False
            self.assertEqual(client.post('/predict', headers=fixture.headers,
                                         files=fixture.files()).status_code, 200)

    def test_configuration_is_loaded_once_and_secret_is_not_in_repr(self):
        fixture = self.fixture
        with TestClient(fixture.app) as client:
            fixture.options['max_request_bytes'] = 1
            fixture.save_options()
            self.assertNotIn(fixture.key, repr(fixture.settings))
            self.assertNotEqual(fixture.settings.inference['max_request_bytes'], 1)
            self.assertEqual(client.post('/predict', headers=fixture.headers,
                                         files=fixture.files()).status_code, 200)

    def test_import_does_not_read_private_configuration(self):
        script = (
            'from unittest.mock import patch\n'
            'from pathlib import Path\n'
            'import sys\n'
            'original = Path.read_text\n'
            'def guarded(path, *args, **kwargs):\n'
            '    if path.name == "inference.json":\n'
            '        raise AssertionError("private configuration read at import")\n'
            '    return original(path, *args, **kwargs)\n'
            'with patch.object(Path, "read_text", guarded):\n'
            '    import app.main\n'
            'assert "torch" not in sys.modules\n'
        )
        environment = dict(os.environ, PILLGUIDE_API_KEY='', PILLGUIDE_DEVICE='cpu')
        result = subprocess.run([sys.executable, '-B', '-c', script],
                                cwd=Path(__file__).resolve().parents[1], env=environment,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_limits_and_missing_key_fail_before_model_load(self):
        fixture = self.fixture
        for value in [0, -1, True, '20000000']:
            with self.subTest(value=value):
                fixture.options['max_image_pixels'] = value
                fixture.save_options()
                settings = Settings(root=fixture.root, api_key=fixture.key, device='cpu')
                with self.assertRaises(ValueError):
                    with TestClient(create_app(settings, fixture.engine_factory)):
                        pass
        fixture.options['max_image_pixels'] = 20_000_000
        fixture.save_options()
        with self.assertRaises(ValueError):
            with TestClient(create_app(Settings(root=fixture.root, api_key='', device='cpu'),
                                       fixture.engine_factory)):
                pass
        self.assertEqual(fixture.engines, [])

    def test_pixel_limit_and_exif_orientation(self):
        fixture = self.fixture
        fixture.options['max_image_pixels'] = 100
        fixture.save_options()
        with TestClient(fixture.app) as client:
            self.assertEqual(client.post('/predict', headers=fixture.headers,
                                         files=fixture.files()).status_code, 413)
            self.assertEqual(fixture.engines[0].calls, 0)
            with Image.new('RGB', (8, 4)) as image:
                exif = image.getexif()
                exif[274] = 6
                buffer = BytesIO()
                image.save(buffer, format='JPEG', exif=exif)
            response = client.post('/predict', headers=fixture.headers,
                                   files={'file': ('oriented.jpg', buffer.getvalue(), 'image/jpeg')})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['image'], {'width': 4, 'height': 8})

    def test_request_and_file_limits_remain_distinct(self):
        fixture = self.fixture
        fixture.options['max_upload_bytes'] = 128
        fixture.options['max_request_bytes'] = 1024
        fixture.save_options()
        with TestClient(fixture.app) as client:
            response = client.post('/predict', headers=fixture.headers,
                                   files={'file': ('large.png', b'x' * 129, 'image/png')})
            self.assertEqual(response.status_code, 413)
            response = client.post('/predict', headers=fixture.headers, content=b'x' * 1025)
            self.assertEqual(response.status_code, 413)
            self.assertEqual(response.json(), {'detail': 'Request body too large'})
            self.assertEqual(fixture.engines[0].calls, 0)


class CancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_request_retains_capacity_until_worker_finishes(self):
        fixture = ApplicationFixture()
        self.addCleanup(fixture.close)
        async with fixture.app.router.lifespan_context(fixture.app):
            transport = httpx.ASGITransport(app=fixture.app)
            async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
                engine = fixture.engines[0]
                engine.block = True
                first = asyncio.create_task(client.post('/predict', headers=fixture.headers,
                                                         files=fixture.files()))
                try:
                    self.assertTrue(await asyncio.to_thread(engine.entered.wait, 3))
                    first.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await first
                    busy = await client.post('/predict', headers=fixture.headers, files=fixture.files())
                    self.assertEqual(busy.status_code, 503)
                    self.assertEqual(busy.headers['retry-after'], '1')
                    self.assertEqual(engine.calls, 1)
                finally:
                    engine.release.set()
                    self.assertTrue(await asyncio.to_thread(engine.finished.wait, 3))
                    if not first.done():
                        await first


class RequestGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_authentication_precedes_body_read_and_limit_validation(self):
        fixture = ApplicationFixture()
        self.addCleanup(fixture.close)
        messages = []

        async def downstream(scope, receive, send):
            self.fail('Unauthenticated request reached application')

        async def receive():
            self.fail('Unauthenticated body was read')

        async def send(message):
            messages.append(message)

        scope = {'type': 'http', 'method': 'POST', 'headers': [(b'content-length', b'invalid')]}
        await RequestGuard(downstream, fixture.settings)(scope, receive, send)
        self.assertEqual(messages[0]['status'], 401)

    async def test_content_length_rejection_does_not_read_body(self):
        fixture = ApplicationFixture()
        self.addCleanup(fixture.close)
        for length, status in [(b'-1', 400), (b'invalid', 400), (b'999999999', 413)]:
            with self.subTest(length=length):
                messages = []

                async def downstream(scope, receive, send):
                    self.fail('Rejected request reached application')

                async def receive():
                    self.fail('Rejected body was read')

                async def send(message):
                    messages.append(message)

                scope = {'type': 'http', 'method': 'POST',
                         'headers': [(b'x-api-key', fixture.key.encode()), (b'content-length', length)]}
                await RequestGuard(downstream, fixture.settings)(scope, receive, send)
                self.assertEqual(messages[0]['status'], status)

    async def test_chunked_body_cap_and_replay(self):
        fixture = ApplicationFixture()
        self.addCleanup(fixture.close)
        fixture.options.update(max_upload_bytes=5, max_request_bytes=5)
        fixture.save_options()
        for last_chunk, accepted in [(b'45', True), (b'456', False)]:
            with self.subTest(accepted=accepted):
                forwarded, messages = [], []
                chunks = iter([
                    {'type': 'http.request', 'body': b'123', 'more_body': True},
                    {'type': 'http.request', 'body': last_chunk, 'more_body': False},
                ])

                async def downstream(scope, receive, send):
                    forwarded.append(await receive())

                async def receive():
                    return next(chunks)

                async def send(message):
                    messages.append(message)

                scope = {'type': 'http', 'method': 'POST',
                         'headers': [(b'x-api-key', fixture.key.encode())]}
                await RequestGuard(downstream, fixture.settings)(scope, receive, send)
                if accepted:
                    self.assertEqual(forwarded, [
                        {'type': 'http.request', 'body': b'12345', 'more_body': False}])
                else:
                    self.assertEqual(forwarded, [])
                    self.assertEqual(messages[0]['status'], 413)


if __name__ == '__main__':
    unittest.main()
