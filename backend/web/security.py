"""HTTP limits and browser protections, including early error responses."""
import os
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from backend.core.config import LOCAL_HOSTS, public_origin
from backend.core.rate_limit import RateLimiter

limiter = RateLimiter()
MAX_BODY_BYTES = 256 * 1024
API_LIMIT = 240
LOGIN_LIMIT = 10
SECURITY_HEADERS = {
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'no-referrer',
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
    'Content-Security-Policy': (
        "default-src 'self'; script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; "
        "connect-src 'self'; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'self'"
    ),
}


class SecurityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        path, method = scope['path'], scope['method']
        origin = public_origin()

        async def protected_send(message):
            if message['type'] == 'http.response.start':
                outgoing = MutableHeaders(scope=message)
                outgoing.update(SECURITY_HEADERS)
                if path.startswith('/api/'):
                    outgoing['Cache-Control'] = 'no-store'
                if origin.scheme == 'https':
                    outgoing['Strict-Transport-Security'] = 'max-age=31536000'
            await send(message)

        async def reject(status, detail, extra=None):
            await JSONResponse({'detail': detail}, status_code=status, headers=extra)(scope, receive, protected_send)

        if origin.hostname not in LOCAL_HOSTS and headers.get('host', '').lower() != origin.netloc.lower():
            return await reject(400, 'Request host is not allowed.')
        if method not in ('GET', 'HEAD', 'OPTIONS'):
            if headers.get('origin') != os.getenv('APP_ORIGIN', 'http://localhost:8000'):
                return await reject(403, 'Request origin is not allowed.')
        if path.startswith('/api/'):
            # Uvicorn supplies this value. Never trust arbitrary forwarding
            # headers here; configure only the known reverse proxy at deployment.
            address = scope.get('client') or ('unknown', 0)
            if not limiter.allow(('api', address[0]), API_LIMIT):
                return await reject(429, 'Too many requests. Try again in a minute.', {'Retry-After': '60'})
            if method == 'POST' and path in ('/api/auth/telegram', '/api/auth/bot/start'):
                if not limiter.allow(('login', address[0]), LOGIN_LIMIT):
                    return await reject(429, 'Too many login attempts. Try again in a minute.', {'Retry-After': '60'})
        if 'content-length' in headers:
            try:
                size = int(headers['content-length'])
                if size < 0:
                    raise ValueError()
            except ValueError:
                return await reject(400, 'Invalid request length.')
            if size > MAX_BODY_BYTES:
                return await reject(413, 'Request body is too large.')
        # Bound actual bytes as well as Content-Length, including chunked bodies.
        chunks, size = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            size += len(chunk)
            if size > MAX_BODY_BYTES:
                return await reject(413, 'Request body is too large.')
            chunks.append(chunk)
            if not message.get('more_body'):
                break
        delivered = False

        async def limited_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': b''.join(chunks), 'more_body': False}
            return await receive()

        await self.app(scope, limited_receive, protected_send)
