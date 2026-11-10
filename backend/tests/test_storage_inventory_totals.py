"""Global storage totals through the public ingestion interface."""
from types import SimpleNamespace


def test_global_totals_include_objects_after_the_first_two_thousand(tmp_path, monkeypatch):
    from google.cloud import storage
    from app.services.ingestion import IngestionService

    class CloudClient:
        def list_blobs(self, bucket, max_results=None):
            objects = (SimpleNamespace(size=7) for _ in range(2003))
            if max_results is None:
                return objects
            from itertools import islice
            return islice(objects, max_results)

    monkeypatch.setattr(storage, "Client", CloudClient)
    service = IngestionService(bucket_name="synthetic-bucket", local_base_dir=tmp_path / "raw",
                               local_processed_dir=tmp_path / "processed")
    observed = service.get_storage_status()
    assert observed["connected"] is True
    assert observed["total_objects"] == 2003
    assert observed["total_bytes"] == 14021
