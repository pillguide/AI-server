"""Run with one worker: uvicorn app.main:app --host 127.0.0.1 --port 8000."""
import asyncio
from contextlib import asynccontextmanager
from io import BytesIO
import logging
import secrets
import warnings

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from .config import Settings
from .contract import PredictionResponse, load_item_sequences, public_predictions
from .engine import InferenceEngine

LOG = logging.getLogger('pillguide')


class RequestGuard:
    """Authenticate before parsing and cap the full multipart body, including chunked uploads."""
    def __init__(self, app, api_key, max_bytes):
        self.app, self.api_key, self.max_bytes = app, api_key, max_bytes

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = dict(scope['headers'])
        supplied = headers.get(b'x-api-key', b'')
        if not self.api_key or not secrets.compare_digest(supplied, self.api_key.encode('utf-8')):
            return await JSONResponse({'detail': 'Invalid or missing X-API-Key'}, status_code=401)(scope, receive, send)
        if scope['method'] == 'POST':
            raw_length = headers.get(b'content-length')
            if raw_length is not None:
                try:
                    length = int(raw_length)
                except ValueError:
                    length = -1
                if length < 0:
                    return await JSONResponse({'detail': 'Invalid Content-Length'}, status_code=400)(scope, receive, send)
                if length > self.max_bytes:
                    return await JSONResponse({'detail': 'Request body too large'}, status_code=413)(scope, receive, send)
            body = bytearray()
            while True:
                message = await receive()
                if message['type'] == 'http.disconnect':
                    return
                body.extend(message.get('body', b''))
                if len(body) > self.max_bytes:
                    return await JSONResponse({'detail': 'Request body too large'}, status_code=413)(scope, receive, send)
                if not message.get('more_body', False):
                    break
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
                return await receive()

            return await self.app(scope, replay, send)
        return await self.app(scope, receive, send)


def decode_image(data, max_pixels):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format not in ('JPEG', 'PNG'):
                    raise HTTPException(415, 'Only JPEG and PNG images are supported')
                if getattr(source, 'n_frames', 1) != 1:
                    raise HTTPException(415, 'Animated images are not supported')
                if source.width * source.height > max_pixels:
                    raise HTTPException(413, 'Image exceeds the pixel limit')
                source.load()
                return ImageOps.exif_transpose(source).convert('RGB')
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(413, 'Image exceeds the pixel limit') from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise HTTPException(415, 'Invalid or corrupted image') from None


def create_app(settings=None, engine_factory=InferenceEngine):
    settings = settings or Settings()
    limits = settings.inference

    @asynccontextmanager
    async def lifespan(application):
        settings.validate_key()
        application.state.item_sequences = load_item_sequences(settings)
        application.state.gate = asyncio.Lock()
        application.state.engine = await run_in_threadpool(engine_factory, settings)
        try:
            yield
        finally:
            application.state.engine = None

    application = FastAPI(title='PillGuide Model H', version='2.0.0', lifespan=lifespan,
                          docs_url=None, redoc_url=None, openapi_url=None)
    application.add_middleware(RequestGuard, api_key=settings.api_key,
                               max_bytes=limits['max_request_bytes'])

    @application.get('/health')
    async def health(request: Request):
        if not getattr(request.app.state, 'engine', None):
            raise HTTPException(503, 'Model is not ready')
        engine = request.app.state.engine
        return {'status': 'ready', 'model': 'H', 'device': settings.device, 'class_count': 150,
                'model_sha256': engine.model_sha256, 'mapping_sha256': engine.mapping_sha256}

    @application.post('/predict', response_model=PredictionResponse)
    async def predict(request: Request, file: UploadFile = File(...)):
        try:
            if file.content_type not in ('image/jpeg', 'image/png', 'application/octet-stream'):
                raise HTTPException(415, 'Upload a JPEG or PNG image')
            data = await file.read(limits['max_upload_bytes'] + 1)
        finally:
            await file.close()
        if not data:
            raise HTTPException(400, 'Empty image upload')
        if len(data) > limits['max_upload_bytes']:
            raise HTTPException(413, 'Image file exceeds 10 MiB')
        gate = request.app.state.gate
        if gate.locked():
            raise HTTPException(503, 'Inference is busy; retry shortly', headers={'Retry-After': '1'})
        async with gate:
            image = await run_in_threadpool(decode_image, data, limits['max_image_pixels'])
            try:
                predictions = await run_in_threadpool(request.app.state.engine.predict, image)
                engine = request.app.state.engine
                return {'model': 'H', 'model_sha256': engine.model_sha256,
                        'mapping_sha256': engine.mapping_sha256,
                        'image': {'width': image.width, 'height': image.height},
                        'predictions': public_predictions(predictions, request.app.state.item_sequences)}
            except HTTPException:
                raise
            except Exception:
                LOG.exception('Model H inference failed')
                raise HTTPException(500, 'Inference failed; check server logs') from None
            finally:
                image.close()

    return application


app = create_app()
