"""In-memory background GCS -> local dataset downloads with observable progress.

A download of several GB outlives any single HTTP request, so the transfer runs in
a daemon thread and clients poll a snapshot instead of holding the connection. State
lives in the API process only: a restart forgets finished operations, and a download
interrupted by a restart is re-run by the client (matching audios are skipped).
"""
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from app.services.dataset_comparison import download_content_check
from app.services.ingestion import IngestionDatasetUnavailable, IngestionValidationError

logger = logging.getLogger(__name__)

_RETAINED_FINISHED = 20
# A transfer phase that reports nothing for this long is presumed hung (for example a socket
# left half-open by a network cut). Its datasets are released so the download can be retried.
# Local preprocessing reports no per-file progress, so it is not watched.
_STALL_SECONDS = 300
_WATCHED_PHASES = {"files", "database"}
_STALLED_ERROR = "La descarga dejó de avanzar durante 5 minutos; vuelve a intentarlo."


class DownloadInProgress(Exception):
    """A requested dataset already has a running download."""

    def __init__(self, operation_id: str):
        super().__init__("A download is already running for this dataset")
        self.operation_id = operation_id


def summarize_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate per-dataset sync results; shared by the synchronous and background paths."""
    total_dl = sum(item.get("downloaded", 0) for item in results)
    total_skip = sum(item.get("skipped", 0) for item in results)
    total_fail = sum(item.get("failed", 0) for item in results)
    total_prep = sum(item.get("preprocessed", 0) for item in results)
    has_errors = total_fail > 0 or any(
        item.get("db_error") or (item.get("preprocess_info") or {}).get("failed", 0) > 0
        for item in results
    )
    status = ("partial" if total_dl + total_skip + total_prep > 0 else "failed") if has_errors else "completed"
    return {
        "status": status,
        "results": results,
        "total_downloaded": total_dl,
        "total_skipped": total_skip,
        "total_failed": total_fail,
        "total_preprocessed": total_prep,
    }


def _error_message(error: Exception) -> str:
    if isinstance(error, IngestionDatasetUnavailable):
        return "El dataset no contiene audios descargables en el bucket actual."
    if isinstance(error, IngestionValidationError):
        return "Destino de dataset inválido."
    return "La descarga terminó con un error inesperado; revisa el registro del servidor."


class _Operation:
    def __init__(self, datasets: List[str], preprocess: bool):
        self.id = uuid.uuid4().hex
        self.datasets = datasets
        self.preprocess = preprocess
        self.state = "running"
        self.current: Optional[str] = None
        self.phase = "files"
        self.counts: Dict[str, Dict[str, int]] = {}
        self.results: List[Dict[str, Any]] = []
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.finished_at: Optional[str] = None
        self.last_progress = 0.0

    def snapshot(self) -> Dict[str, Any]:
        def total(key):
            return sum(item[key] for item in self.counts.values())
        downloaded, skipped, failed = total("downloaded"), total("skipped"), total("failed")
        return {
            "operation_id": self.id,
            "state": self.state,
            "datasets": list(self.datasets),
            "current_dataset": self.current if self.state == "running" else None,
            "downloaded": downloaded,
            "skipped": skipped,
            "failed": failed,
            "phase": self.phase,
            "processed": downloaded + skipped + failed,
            "total": total("total"),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "result": self.result,
        }


class DatasetDownloads:
    """Registry of download operations; at most one running operation per dataset."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._lock = threading.Lock()
        self._operations: Dict[str, _Operation] = {}
        self._clock = clock

    def start(self, service: Any, datasets: List[str], *, preprocess: bool,
              session_factory: Callable[[], Any]) -> Dict[str, Any]:
        """Start a background download and return its first snapshot.

        Raises DownloadInProgress when any dataset is already downloading.
        """
        operation = _Operation(list(datasets), preprocess)
        operation.last_progress = self._clock()
        with self._lock:
            self._expire_stalled()
            for running in self._operations.values():
                if running.state == "running" and set(running.datasets) & set(datasets):
                    raise DownloadInProgress(running.id)
            self._operations[operation.id] = operation
            self._prune()
            first = operation.snapshot()
        try:
            threading.Thread(target=self._run, args=(operation, service, session_factory),
                             name=f"dataset-download-{operation.id[:8]}", daemon=True).start()
        except Exception as error:
            # Without a worker nobody would ever finish it: release the datasets now.
            self._finish(operation, "failed", error=_error_message(error))
            raise
        return first

    def snapshot(self, operation_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._expire_stalled()
            operation = self._operations.get(operation_id)
            return operation.snapshot() if operation else None

    def active(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._expire_stalled()
            return [item.snapshot() for item in self._operations.values() if item.state == "running"]

    def _expire_stalled(self):
        """Fail running operations whose watched phase stopped advancing. Caller holds the lock."""
        now = self._clock()
        for operation in self._operations.values():
            if (operation.state == "running" and operation.phase in _WATCHED_PHASES
                    and now - operation.last_progress > _STALL_SECONDS):
                logger.warning("Dataset download %s stalled in phase %s", operation.id, operation.phase)
                operation.state = "failed"
                operation.error = _STALLED_ERROR
                operation.finished_at = datetime.now(timezone.utc).isoformat()

    def _prune(self):
        finished = [key for key, item in self._operations.items() if item.state != "running"]
        for key in finished[:max(0, len(finished) - _RETAINED_FINISHED)]:
            del self._operations[key]

    def _run(self, operation: _Operation, service: Any, session_factory: Callable[[], Any]):
        try:
            for name in operation.datasets:
                with self._lock:
                    operation.current = name
                    operation.phase = "files"
                    operation.last_progress = self._clock()
                    operation.counts.setdefault(name, {"total": 0, "downloaded": 0, "skipped": 0, "failed": 0})

                def report(counts, name=name):
                    with self._lock:
                        operation.counts[name].update({key: int(counts.get(key, 0)) for key in operation.counts[name]})
                        operation.phase = str(counts.get("phase", operation.phase))
                        operation.last_progress = self._clock()

                with session_factory() as db:
                    result = service.sync_dataset_to_local(
                        name, preprocess=operation.preprocess, db=db, progress=report)
                result["content_check"] = download_content_check(result)
                with self._lock:
                    operation.results.append(result)
                    operation.counts[name].update(
                        {key: int(result.get(key, 0)) for key in ("downloaded", "skipped", "failed")})
            summary = summarize_results(operation.results)
            self._finish(operation, summary["status"], result=summary)
        except Exception as error:
            logger.exception("Dataset download %s ended with an error", operation.id)
            summary = summarize_results(operation.results) if operation.results else None
            self._finish(operation, "failed", result=summary, error=_error_message(error))
        finally:
            # A worker can never leave the operation running, nor its datasets locked.
            self._finish(operation, "failed", error=_error_message(RuntimeError()))

    def _finish(self, operation: _Operation, state: str, *, result=None, error=None):
        with self._lock:
            if operation.state != "running":
                return
            operation.state = state
            operation.result = result
            operation.error = error
            operation.finished_at = datetime.now(timezone.utc).isoformat()
