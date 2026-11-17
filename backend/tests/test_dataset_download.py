"""Background GCS -> local downloads observed through the public registry interface."""
import threading
import time

import pytest

from app.services.dataset_download import DatasetDownloads, DownloadInProgress, summarize_results


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class FakeService:
    """Stands in for IngestionService.sync_dataset_to_local with gated progress."""

    def __init__(self):
        self.release = threading.Event()
        self.reported = threading.Event()
        self.calls = []
        self.fail_with = None
        self.results = {}

    def sync_dataset_to_local(self, name, preprocess=False, db=None, progress=None):
        self.calls.append((name, preprocess, db))
        if progress:
            progress({"total": 4, "downloaded": 1, "skipped": 0, "failed": 0})
            self.reported.set()
        assert self.release.wait(5)
        if self.fail_with:
            raise self.fail_with
        return self.results.get(name) or {
            "dataset": name, "downloaded": 3, "skipped": 1, "failed": 0, "preprocessed": 0,
            "db_persisted": True, "db_error": None, "hash_conflicts": [],
        }


class Session:
    closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True


def start(downloads, service, datasets=("AvesChilenas",), **kwargs):
    return downloads.start(service, list(datasets), preprocess=False, session_factory=Session, **kwargs)


def test_running_operation_reports_downloaded_and_total_while_it_runs():
    downloads, service = DatasetDownloads(), FakeService()
    operation = start(downloads, service)
    assert service.reported.wait(5)

    snapshot = downloads.snapshot(operation["operation_id"])

    assert snapshot["state"] == "running"
    assert snapshot["datasets"] == ["AvesChilenas"]
    assert (snapshot["downloaded"], snapshot["total"], snapshot["processed"]) == (1, 4, 1)
    assert snapshot["result"] is None
    service.release.set()


def test_completed_operation_keeps_the_sync_result_and_releases_the_dataset():
    downloads, service = DatasetDownloads(), FakeService()
    operation = start(downloads, service)
    service.release.set()
    assert wait_for(lambda: downloads.snapshot(operation["operation_id"])["state"] != "running")

    snapshot = downloads.snapshot(operation["operation_id"])

    assert snapshot["state"] == "completed"
    assert snapshot["error"] is None
    assert snapshot["result"]["status"] == "completed"
    assert snapshot["result"]["total_downloaded"] == 3
    assert snapshot["result"]["results"][0]["hash_conflicts"] == []
    assert (snapshot["downloaded"], snapshot["skipped"], snapshot["failed"]) == (3, 1, 0)
    assert downloads.active() == []
    again = start(downloads, service)
    assert again["operation_id"] != operation["operation_id"]


def test_worker_uses_its_own_session_and_closes_it():
    downloads, service = DatasetDownloads(), FakeService()
    start(downloads, service)
    service.release.set()
    assert wait_for(lambda: service.calls and downloads.active() == [])

    assert isinstance(service.calls[0][2], Session)
    assert service.calls[0][2].closed is True


def test_partial_result_is_reported_as_partial():
    downloads, service = DatasetDownloads(), FakeService()
    service.results["AvesChilenas"] = {"dataset": "AvesChilenas", "downloaded": 2, "skipped": 0, "failed": 1,
                                       "preprocessed": 0, "db_persisted": True, "db_error": None}
    operation = start(downloads, service)
    service.release.set()
    assert wait_for(lambda: downloads.snapshot(operation["operation_id"])["state"] != "running")

    snapshot = downloads.snapshot(operation["operation_id"])
    assert snapshot["state"] == "partial"
    assert snapshot["result"]["total_failed"] == 1


def test_second_start_for_a_running_dataset_is_rejected_and_names_the_operation():
    downloads, service = DatasetDownloads(), FakeService()
    first = start(downloads, service)

    with pytest.raises(DownloadInProgress) as rejected:
        start(downloads, service, datasets=("Other", "AvesChilenas"))

    assert rejected.value.operation_id == first["operation_id"]
    assert len(service.calls) <= 1
    assert start(downloads, service, datasets=("Other",))["state"] == "running"
    service.release.set()


def test_an_exception_ends_in_failed_with_a_generic_error_and_frees_the_dataset():
    downloads, service = DatasetDownloads(), FakeService()
    service.fail_with = RuntimeError("secret /private/path credentials")
    operation = start(downloads, service)
    service.release.set()
    assert wait_for(lambda: downloads.snapshot(operation["operation_id"])["state"] != "running")

    snapshot = downloads.snapshot(operation["operation_id"])

    assert snapshot["state"] == "failed"
    assert snapshot["error"]
    assert "secret" not in snapshot["error"] and "/private" not in snapshot["error"]
    assert downloads.active() == []


def test_unknown_operation_is_none():
    assert DatasetDownloads().snapshot("missing") is None


def test_summary_matches_the_synchronous_endpoint_semantics():
    clean = {"downloaded": 1, "skipped": 1, "failed": 0, "preprocessed": 0}
    assert summarize_results([clean])["status"] == "completed"
    assert summarize_results([{**clean, "db_error": "x"}])["status"] == "partial"
    assert summarize_results([{"downloaded": 0, "skipped": 0, "failed": 2, "preprocessed": 0}])["status"] == "failed"
