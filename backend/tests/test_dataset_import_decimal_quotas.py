"""PostgreSQL-shaped integral aggregates at the public import/worker boundary."""
from sqlalchemy import Numeric, event, type_coerce
from sqlalchemy.sql import visitors
from sqlalchemy.sql.functions import FunctionElement

import pytest

from tests.test_dataset_import_automatic import admit, create, run, state
from tests.test_dataset_import_layout import layout_api
from tests.test_dataset_zip_validation import wav_bytes


@pytest.mark.parametrize("automatic,extend", [(True, False), (False, True)])
def test_integral_decimal_quotas_preserve_duplicate_and_manual_publication(
        layout_api, tmp_path, automatic, extend):
    request, worker, engine = layout_api
    base = "/api/ingestion/imports"
    original = wav_bytes()
    first, _ = create(request, tmp_path, [("bird/a.wav", original)])
    published, _, _ = run(request, worker, first)
    target = published["dataset_id"]
    catalog_before = request("GET", base + "/datasets").json()
    files_before = request("GET", f"{base}/datasets/{target}/files").json()

    def decimal_sums(connection, clause, multiparams, params, options):
        # Model PostgreSQL SUM(bigint)'s numeric result processor without a live DB.
        # The query and its actual SQLite rows remain unchanged.
        def numeric_aggregate(element):
            if isinstance(element, FunctionElement):
                is_sum = element.name.lower() == "sum"
                wraps_sum = element.name.lower() == "coalesce" and any(
                    isinstance(child, FunctionElement) and child.name.lower() == "sum"
                    for child in element.clauses)
                if is_sum or wraps_sum:
                    return type_coerce(element, Numeric(precision=30, scale=0))
        return visitors.replacement_traverse(clause, {}, numeric_aggregate), multiparams, params

    database_errors = []
    def capture_error(context):
        database_errors.append(str(context.original_exception))

    event.listen(engine, "before_execute", decimal_sums, retval=True)
    event.listen(engine, "handle_error", capture_error)
    try:
        content = wav_bytes(2) if extend else original
        source, _ = create(request, tmp_path, [("bird/b.wav", content)],
                           auto=automatic, target=target if extend else None)
        operation, _ = admit(request, source)
        assert worker.run_once()
        execution = request("GET", operation["status_url"]).json()
        assert execution["status"] == "succeeded", (execution, database_errors)
        reviewed = state(request, source)
        quota = reviewed["preview"]["quota"]
        assert quota == {
            "current_bytes": len(original), "current_files": 1,
            "new_bytes": len(content) if extend else 0, "new_files": 1 if extend else 0,
            "projected_bytes": len(original) + (len(content) if extend else 0),
            "projected_files": 2 if extend else 1,
            "limit_bytes": 15 * 1024**3, "limit_files": 50000,
        }
        assert all(type(value) is int for value in quota.values())
        if not automatic:
            assert reviewed["status"] == "ready" and reviewed["dataset_id"] is None
            assert request("GET", base + "/datasets").json() == catalog_before
            assert request("GET", f"{base}/datasets/{target}/files").json() == files_before
            confirmation, _ = admit(request, source, "confirm", preview_token=reviewed["preview_token"])
            assert worker.run_once()
            assert request("GET", confirmation["status_url"]).json()["status"] == "succeeded"
        final = state(request, source)
        assert final["status"] == "imported" and final["dataset_id"] == target
        assert final["added_count"] == (1 if extend else 0)
        assert final["sync_status"] == "pending"
        files = request("GET", f"{base}/datasets/{target}/files").json()["files"]
        assert len(files) == (2 if extend else 1)
        downloaded = [request("GET", f"{base}/datasets/{target}/files/{file['sha256']}").content
                      for file in files]
        assert sorted(downloaded) == sorted([original, content] if extend else [original])
        if not extend:
            assert request("GET", base + "/datasets").json() == catalog_before
            assert request("GET", f"{base}/datasets/{target}/files").json() == files_before
    finally:
        event.remove(engine, "handle_error", capture_error)
        event.remove(engine, "before_execute", decimal_sums)
