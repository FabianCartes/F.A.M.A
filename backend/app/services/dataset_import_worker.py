"""Trusted, bounded callback orchestration; not an untrusted decoder sandbox."""
from pathlib import Path
import os
import stat
import threading

from app.services.dataset_import_jobs import LeaseLost, lease_duration


def _private_root(root):
    root = Path(root)
    if not root.is_absolute() or root != root.resolve(strict=True):
        raise ValueError("Staging root must be an existing physical absolute directory")
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise ValueError("Staging root must not contain links")
    info = root.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Staging root must be private and owned by this process user")
    return root


class ImportJobWorker:
    """Poll durable jobs once; dependencies are supplied, never HTTP dispatch.

    Callbacks receive (attempt, private_path, report). They must be trusted and
    cooperative: timeout revokes database writes, not Python execution or arbitrary
    filesystem effects. No cleanup or final membership publication happens here.
    """

    def __init__(self, queue, staging_root, execute, *, lease_seconds=60,
                 execution_seconds=300, heartbeat_wait=None):
        self.queue, self.root, self.execute = queue, _private_root(staging_root), execute
        self.lease_seconds = lease_duration(lease_seconds)
        self.execution_seconds = lease_duration(execution_seconds)
        self.heartbeat_wait = heartbeat_wait or (lambda stop, interval: stop.wait(interval))
        self._work = None

    def run_once(self):
        # A timed-out cooperative callback may still be unwinding. Do not spawn
        # an unbounded succession of execution threads in this worker instance.
        if self._work is not None and self._work.is_alive():
            return False
        attempt = self.queue.claim(lease_seconds=self.lease_seconds)
        if attempt is None:
            return False
        stop, lost, done = threading.Event(), threading.Event(), threading.Event()
        outcome = {}

        def report(**values):
            if lost.is_set() or stop.is_set():
                raise LeaseLost("Attempt stopped")
            self.queue.progress(attempt, **values)

        def heartbeat():
            while not self.heartbeat_wait(stop, self.lease_seconds / 3):
                if stop.is_set():
                    return
                try:
                    self.queue.heartbeat(attempt, lease_seconds=self.lease_seconds)
                except Exception:
                    lost.set()
                    return

        def execute():
            try:
                outcome["result"] = self.execute(attempt, staging, report)
            except Exception:
                outcome["error"] = "execution_failed"
            finally:
                done.set()

        try:
            _private_root(self.root)
            staging = self.root / f"{attempt['id']}-{attempt['attempt']}-{attempt['token']}"
            # Never adopt an existing attempt directory or follow a link.
            staging.mkdir(mode=0o700)
        except Exception:
            try:
                self.queue.finish(attempt, error="staging_failed")
            except LeaseLost:
                pass
            return True
        pulse = threading.Thread(target=heartbeat, daemon=True)
        work = threading.Thread(target=execute, daemon=True)
        self._work = work
        pulse.start()
        work.start()
        try:
            if not done.wait(self.execution_seconds):
                outcome = {"error": "execution_timeout"}
            if not lost.is_set():
                try:
                    self.queue.finish(attempt, **outcome)
                except LeaseLost:
                    lost.set()
                except Exception:
                    # Invalid callback output is not persisted or interpolated.
                    try:
                        self.queue.finish(attempt, error="execution_failed")
                    except LeaseLost:
                        lost.set()
        finally:
            stop.set()
            pulse.join(timeout=min(self.lease_seconds, 1))
        return True
