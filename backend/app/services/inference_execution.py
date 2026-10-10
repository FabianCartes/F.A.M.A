"""Non-queued process admission; request and real worker share one lease."""
import asyncio
from contextlib import contextmanager, nullcontext
import json
import logging
from time import perf_counter
from uuid import uuid4
from pathlib import Path
import tempfile
from threading import Lock


_LOGGER = logging.getLogger(__name__)
_STAGES = {"ingress", "read", "validation", "upload", "predict", "persist", "total"}


class InferenceExecution:
    """One slot across event loops. No queue, deadline, or hard thread cancellation."""

    def __init__(self):
        self._slot = Lock()

    def acquire(self):
        if not self._slot.acquire(blocking=False):
            return None
        return _Lease(self._slot)


class _Lease:
    def __init__(self, slot):
        self._slot = slot
        self._id = uuid4().hex
        self._references = 1
        self._lock = Lock()

    def release(self):
        with self._lock:
            self._references -= 1
            if self._references == 0:
                self._slot.release()

    def record(self, stage, started, outcome, *, worker_finished=False):
        if stage not in _STAGES or outcome not in {"ok", "error", "cancelled", "timeout"}:
            raise ValueError("Invalid inference timing category")
        if _LOGGER.isEnabledFor(logging.INFO):
            _LOGGER.info(json.dumps({"event": "inference_stage", "id": self._id, "stage": stage,
                                     "duration_ms": round(max(0, perf_counter() - started) * 1000, 3),
                                     "outcome": outcome, "worker_finished": worker_finished}))

    @contextmanager
    def stage(self, name, *, worker_finished=False):
        started, outcome = perf_counter(), "ok"
        try:
            yield
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except BaseException:
            outcome = "error"
            raise
        finally:
            self.record(name, started, outcome, worker_finished=worker_finished)

    async def run(self, function, *args, stage=None, **kwargs):
        # Retain before submission, including time spent waiting for an executor thread.
        with self._lock:
            self._references += 1

        def work():
            try:
                timing = self.stage(stage, worker_finished=True) if stage else nullcontext()
                with timing:
                    return True, function(*args, **kwargs)
            except BaseException as error:
                # Python 3.14 shield logs late future exceptions even when observed.
                # Carry the error as a value; only an active waiter may re-raise it.
                return False, error
            finally:
                self.release()

        try:
            future = asyncio.get_running_loop().run_in_executor(None, work)
        except BaseException:
            self.release()
            raise
        # Observe executor failures; work errors travel as values, not future exceptions.
        future.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        success, value = await asyncio.shield(future)
        if not success:
            raise value
        return value

    async def predict(self, predictor, audio_bytes):
        def work():
            path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as audio:
                    path = Path(audio.name)
                    audio.write(audio_bytes)
                return predictor.predict(path)
            finally:
                if path is not None:
                    path.unlink()

        return await self.run(work, stage="predict")
