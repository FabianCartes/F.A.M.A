"""S3d/S12: exact capacity and one-byte excess with integral aggregates."""
import hashlib
from dataclasses import replace

import pytest
from sqlalchemy import Numeric, event, type_coerce
from sqlalchemy.sql import visitors
from sqlalchemy.sql.functions import FunctionElement

from tests.test_dataset_import_automatic import create, run
from tests.test_dataset_import_layout import layout_api
from tests.test_dataset_zip_validation import wav_bytes

BASE = "/api/ingestion/imports"


@pytest.mark.parametrize("shortfall", [0, 1])
def test_decimal_target_quota_boundary(layout_api, tmp_path, shortfall):
    request, worker, engine = layout_api
    original, addition = wav_bytes(), wav_bytes(2)
    first, _ = create(request, tmp_path, [("bird/a.wav", original)])
    published, _, _ = run(request, worker, first)
    target = published["dataset_id"]
    files_url = f"{BASE}/datasets/{target}/files"
    catalog = request("GET", BASE + "/datasets").json()
    files = request("GET", files_url).json()

    def numeric_results(conn, statement, multiparams, params, options):
        def adapt(node):
            if not isinstance(node, FunctionElement):
                return None
            name = node.name.lower()
            wraps_sum = name == "coalesce" and any(
                isinstance(c, FunctionElement) and c.name.lower() == "sum"
                for c in node.clauses)
            if name == "sum" or wraps_sum:
                return type_coerce(node, Numeric(precision=30, scale=0))
        return visitors.replacement_traverse(statement, {}, adapt), multiparams, params

    def database_hash(catalog_only=False):
        with engine.connect() as connection:
            lines = list(connection.connection.driver_connection.iterdump())
        if catalog_only:
            tables = ("imported_dataset", "imported_dataset_member", "imported_dataset_summary")
            lines = [line for line in lines if any(
                line.startswith(f'INSERT INTO "{table}" ') for table in tables)]
        return hashlib.sha256("\n".join(lines).encode()).hexdigest()

    stored_catalog = database_hash(catalog_only=True)
    worker.service.limits = replace(worker.service.limits,
        dataset_bytes=len(original) + len(addition) - shortfall)
    event.listen(engine, "before_execute", numeric_results, retval=True)
    try:
        source, _ = create(request, tmp_path, [("bird/b.wav", addition)], target=target)
        result, _, _ = run(request, worker, source)
        quota = result["preview"]["quota"]
        assert quota["current_bytes"] == len(original)
        assert quota["new_bytes"] == len(addition)
        assert quota["projected_bytes"] == len(original) + len(addition)
        assert all(type(value) is int for value in quota.values())
        if shortfall == 0:
            assert result["status"] == "imported"
            assert result["added_count"] == 1 and result["dataset_id"] == target
            final_files = request("GET", files_url).json()["files"]
            assert len(final_files) == 2
            downloaded = [request("GET", f'{files_url}/{file["sha256"]}').content
                          for file in final_files]
            assert sorted(downloaded) == sorted([original, addition])
        else:
            assert result["status"] == "needs_correction"
            assert result["dataset_id"] is None and result["added_count"] == 0
            issues = request("GET", f"{BASE}/{source}/issues").json()["issues"]
            errors = [i for i in issues if i["severity"] == "error"]
            assert [(i["code"], i["action"]) for i in errors] == [(
                "dataset_size_limit",
                "Reduce el contenido nuevo: supera la cuota de bytes del dataset.")]
            assert request("GET", BASE + "/datasets").json() == catalog
            assert request("GET", files_url).json() == files
            assert database_hash(catalog_only=True) == stored_catalog
            before = database_hash()
            rejected = request("POST", f"{BASE}/{source}/confirm", body={
                "request_key": "rejected-quota-confirm",
                "preview_token": result["preview_token"]})
            assert rejected.status_code == 409
            assert rejected.json() == {"detail": "La vista previa cambió o no está lista para confirmar."}
            assert database_hash() == before
            original_file = files["files"][0]
            downloaded = request("GET", f'{files_url}/{original_file["sha256"]}')
            assert downloaded.status_code == 200 and downloaded.content == original
    finally:
        event.remove(engine, "before_execute", numeric_results)
