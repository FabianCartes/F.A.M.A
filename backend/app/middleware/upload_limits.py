"""Bound the raw ingestion upload body before the multipart parser spools it."""
from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse

from app.services.ingestion import IngestionConfigurationError

UPLOAD_PATH = "/api/ingestion/upload"
LIMIT_DETAIL = "La carga supera los límites permitidos."


class UploadBodyLimit:
    """Reject POST /api/ingestion/upload once its raw body exceeds body_limit().

    The route keeps the exact per-file and per-batch checks; this bound only stops
    an oversized request before the parser writes it to temporary files.
    """

    def __init__(self, app, body_limit):
        self.app = app
        self.body_limit = body_limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != UPLOAD_PATH:
            return await self.app(scope, receive, send)
        try:
            limit = self.body_limit()
        except IngestionConfigurationError:
            return await JSONResponse({"detail": "Configuración de carga no disponible."},
                                      status_code=503)(scope, receive, send)
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            return await JSONResponse({"detail": LIMIT_DETAIL}, status_code=413)(scope, receive, send)

        total = 0
        exceeded = False
        responded = False

        async def bounded_receive():
            nonlocal total, exceeded
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > limit:
                    exceeded = True
                    # The parser closes its partial spooled files for this exception.
                    raise MultiPartException("Upload body limit exceeded")
            return message

        async def bounded_send(message):
            nonlocal responded
            if exceeded:
                if not responded:
                    responded = True
                    # FastAPI may wrap the parser error as 400; expose the real 413.
                    await JSONResponse({"detail": LIMIT_DETAIL}, status_code=413)(scope, receive, send)
                return
            await send(message)

        try:
            await self.app(scope, bounded_receive, bounded_send)
        except MultiPartException:
            if not exceeded:
                raise
            if not responded:
                responded = True
                await JSONResponse({"detail": LIMIT_DETAIL}, status_code=413)(scope, receive, send)
