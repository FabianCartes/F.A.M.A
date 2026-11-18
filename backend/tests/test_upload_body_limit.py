"""Raw-body bound for POST /api/ingestion/upload before multipart spooling."""
import asyncio

from app.middleware.upload_limits import UploadBodyLimit

LIMIT_DETAIL = "La carga supera los límites permitidos."


def run(middleware, scope, chunks):
    messages, consumed = [], []
    queue = list(chunks)

    async def receive():
        body = queue.pop(0) if queue else b""
        return {"type": "http.request", "body": body, "more_body": bool(queue)}

    async def send(message):
        messages.append(message)

    async def scenario():
        await middleware(scope, receive, send)

    middleware.app_consumed = consumed
    asyncio.run(scenario())
    return messages


def reading_app(consumed):
    async def app(scope, receive, send):
        while True:
            message = await receive()
            consumed.append(len(message.get("body", b"")))
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})
    return app


def upload_scope(content_length=None):
    headers = [] if content_length is None else [(b"content-length", str(content_length).encode())]
    return {"type": "http", "method": "POST", "path": "/api/ingestion/upload", "headers": headers}


def status_and_body(messages):
    start = next(m for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return start["status"], body.decode()


def test_streamed_body_over_limit_stops_reading_and_answers_413():
    consumed = []
    middleware = UploadBodyLimit(reading_app(consumed), body_limit=lambda: 100)
    messages = run(middleware, upload_scope(), [b"x" * 60, b"x" * 60, b"x" * 60, b"x" * 60])
    status, body = status_and_body(messages)
    assert status == 413
    assert LIMIT_DETAIL in body
    assert sum(consumed) <= 60


def test_declared_length_over_limit_is_rejected_without_reading_the_body():
    consumed = []
    middleware = UploadBodyLimit(reading_app(consumed), body_limit=lambda: 100)
    messages = run(middleware, upload_scope(content_length=101), [b"x" * 101])
    status, body = status_and_body(messages)
    assert status == 413
    assert LIMIT_DETAIL in body
    assert consumed == []


def test_body_within_limit_reaches_the_route_unchanged():
    consumed = []
    middleware = UploadBodyLimit(reading_app(consumed), body_limit=lambda: 100)
    messages = run(middleware, upload_scope(content_length=100), [b"x" * 50, b"x" * 50])
    assert status_and_body(messages) == (200, "ok")
    assert consumed == [50, 50]


def test_other_routes_are_not_bounded():
    consumed = []
    middleware = UploadBodyLimit(reading_app(consumed), body_limit=lambda: 10)
    scope = {"type": "http", "method": "POST", "path": "/api/predict", "headers": []}
    messages = run(middleware, scope, [b"x" * 50])
    assert status_and_body(messages) == (200, "ok")


def test_invalid_upload_configuration_fails_closed_with_503():
    consumed = []

    def broken_limit():
        from app.services.ingestion import IngestionConfigurationError
        raise IngestionConfigurationError("bad")

    middleware = UploadBodyLimit(reading_app(consumed), body_limit=broken_limit)
    messages = run(middleware, upload_scope(), [b"x"])
    status, body = status_and_body(messages)
    assert status == 503
    assert "Configuración de carga no disponible." in body
    assert consumed == []


def test_application_bounds_upload_body_by_batch_limit_plus_multipart_allowance(monkeypatch):
    from app.main import upload_body_limit, MULTIPART_OVERHEAD_BYTES
    monkeypatch.setenv("FAMA_UPLOAD_MAX_FILE_BYTES", "1000")
    monkeypatch.setenv("FAMA_UPLOAD_MAX_BATCH_BYTES", "5000")
    assert upload_body_limit() == 5000 + MULTIPART_OVERHEAD_BYTES
