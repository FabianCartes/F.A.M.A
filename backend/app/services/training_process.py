"""Isolated training execution with bounded progress transport and cooperative stop."""
from multiprocessing import get_context
from pathlib import Path
from time import time
from traceback import format_exc


def run_training_worker(config, checkpoints_dir, publish, stop_event):
    from app.services.training import TrainingService

    service = TrainingService(Path(checkpoints_dir))
    service.status = "training"
    service.current_job_id = config["job_id"]
    service.seed = config["seed"]
    service.is_tri_model = config["is_tri_model"]
    service.models_config = config["models"]
    service.total_models = len(config["models"])
    service.current_model_index = 1
    service.current_architecture = config["models"][0]["architecture"]
    service.total_epochs = config["epochs"]
    service.start_timestamp = time()
    service._progress_callback = publish
    service._stop_event = stop_event
    service._run_training_worker(config)
    publish(service.get_progress())


def _run_child(target, args, seed, events, stop_event):
    import random
    import numpy as np
    import torch

    def publish(snapshot):
        events.put({"type": "progress", "snapshot": snapshot})

    try:
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        target(*args, publish, stop_event)
    except BaseException as exc:
        events.put({"type": "crashed", "error": f"{type(exc).__name__}: {exc}",
                    "traceback": format_exc()})
        raise
    else:
        events.put({"type": "finished"})


class TrainingProcess:
    """One spawn child; its owner must drain events while it is alive, before join."""

    def __init__(self, target, *, args, seed):
        context = get_context("spawn")
        self._events = context.Queue(maxsize=8)
        self._stop_event = context.Event()
        self._process = context.Process(
            target=_run_child, args=(target, args, seed, self._events, self._stop_event),
            name="FamaTrainingProcess", daemon=True,
        )

    def start(self):
        self._process.start()

    def request_stop(self):
        self._stop_event.set()

    def receive(self, timeout=None):
        return self._events.get(timeout=timeout)

    def is_alive(self):
        return self._process.is_alive()

    def join(self, timeout=None):
        self._process.join(timeout)

    @property
    def exitcode(self):
        return self._process.exitcode

    def close(self):
        self._events.close()
        self._events.join_thread()
        self._process.close()

    def abort_start(self):
        """Rollback a failed parent handoff; no training owner remains to drain IPC."""
        self.request_stop()
        if self._process.is_alive():
            self._process.terminate()
            self._process.join()
        self.close()
