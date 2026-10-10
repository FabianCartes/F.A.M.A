"""Count actual ASGI bytes before the multipart parser can spool them."""
import asyncio
from time import perf_counter

from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse


class InferenceLimits:
    def __init__(self, app, execution, body_limit, wait_seconds=lambda: 270):
        self.app = app
        self.execution = execution
        self.body_limit = body_limit
        self.wait_seconds = wait_seconds

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != "/api/predict":
            return await self.app(scope, receive, send)
        lease = self.execution.acquire()
        if lease is None:
            return await JSONResponse({"detail": "Inferencia ocupada. Intente nuevamente más tarde."},
                                      status_code=503, headers={"Retry-After": "5"})(scope, receive, send)
        scope.setdefault("state", {})["inference_lease"] = lease
        total = 0
        exceeded = False
        responded = False
        started = perf_counter()
        ingress_done = False
        response_status = 500
        outcome = "error"
        headers_started = False

        async def bounded_receive():
            nonlocal total, exceeded, ingress_done
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.body_limit():
                    exceeded = True
                    # The parser closes its partial spooled files for this exception.
                    raise MultiPartException("Inference body limit exceeded")
            if message["type"] == "http.request" and not message.get("more_body", False):
                lease.record("ingress", started, "ok")
                ingress_done = True
            return message

        async def bounded_send(message):
            nonlocal responded, response_status, headers_started
            if exceeded:
                if not responded:
                    responded = True
                    response_status = 413
                    headers_started = True
                    # FastAPI may wrap the parser error as 400; expose the real 413.
                    await JSONResponse({"detail": "La solicitud supera el límite de 110 MiB."},
                                       status_code=413)(scope, receive, send)
                return
            if message["type"] == "http.response.start":
                response_status = message["status"]
                headers_started = True
            await send(message)

        budget = asyncio.timeout(self.wait_seconds())
        try:
            async with budget:
                await self.app(scope, bounded_receive, bounded_send)
            outcome = "ok" if response_status < 400 else "error"
        except TimeoutError:
            if not budget.expired():
                raise
            outcome = "timeout"
            if not headers_started:
                await JSONResponse({"detail": "La inferencia excedió el tiempo máximo de espera."},
                                   status_code=504)(scope, receive, send)
            else:
                # Already-started responses cannot be replaced with a second status.
                raise
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        finally:
            scope["state"].pop("inference_lease", None)
            lease.release()
            if not ingress_done:
                lease.record("ingress", started, outcome)
            lease.record("total", started, outcome)
