import secrets

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Settings


class RequestGuard:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self._app = app
        self._settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self._app(scope, receive, send)
            return
        headers = dict(scope['headers'])
        supplied = headers.get(b'x-api-key', b'')
        if not self._settings.api_key or not secrets.compare_digest(
            supplied, self._settings.api_key.encode('utf-8'),
        ):
            await JSONResponse({'detail': 'Invalid or missing X-API-Key'}, status_code=401)(
                scope, receive, send,
            )
            return
        if scope['method'] != 'POST':
            await self._app(scope, receive, send)
            return
        max_bytes = self._settings.limits.max_request_bytes
        raw_length = headers.get(b'content-length')
        if raw_length is not None:
            try:
                length = int(raw_length)
            except ValueError:
                length = -1
            if length < 0:
                await JSONResponse({'detail': 'Invalid Content-Length'}, status_code=400)(
                    scope, receive, send,
                )
                return
            if length > max_bytes:
                await JSONResponse({'detail': 'Request body too large'}, status_code=413)(
                    scope, receive, send,
                )
                return
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            if len(body) + len(chunk) > max_bytes:
                await JSONResponse({'detail': 'Request body too large'}, status_code=413)(
                    scope, receive, send,
                )
                return
            body.extend(chunk)
            if not message.get('more_body', False):
                break
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()

        await self._app(scope, replay, send)
