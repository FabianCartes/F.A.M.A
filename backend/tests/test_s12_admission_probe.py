import os
import pytest
from tests.test_dataset_import_layout import layout_api
from tests.s12_probe_support import *

def test_strict_flag_errors_and_legacy_false_serialization(layout_api):
    request, worker, engine = layout_api
    payload = {"request_key": "legacy", "name": "Legacy"}
    created = request("POST", B, body=payload)
    assert created.status_code == 200
    before = digest(engine)
    assert request("POST", B, body={**payload, "auto_import": False}).json() == created.json()
    assert digest(engine) == before
    for value in ["true", "false", 1, 0, None, [], {}]:
        before = digest(engine)
        rejected = request("POST", B, body={**payload, "request_key": "bad", "auto_import": value})
        assert rejected.status_code == 422
        assert rejected.json() == {"detail": [{"type": "bool_type", "loc": ["body", "auto_import"], "msg": "Input should be a valid boolean", "input": value}]}
        assert digest(engine) == before
    reject_unchanged(engine, lambda: request("POST", B, body={**payload, "auto_import": True}), 409, "La solicitud ya existe con otro destino o contenido.")
    assert not worker.run_once()


def test_recovery_rejections_preserve_whole_database(layout_api, tmp_path, monkeypatch):
    from fastapi import HTTPException
    request, worker, engine = layout_api
    source, _ = new(request, tmp_path, auto=True)
    job, _ = admit(request, source)
    original = os.rename
    def interrupted(a, b):
        original(a, b)
        raise OSError("Independent interruption")
    with monkeypatch.context() as fault:
        fault.setattr(os, "rename", interrupted)
        assert worker.run_once()
    assert state(request, source)["status"] == "committing"
    before = digest(engine)
    with pytest.raises(HTTPException) as foreign:
        worker.queue.admit(2, source, "preview", "foreign", {"root": ""})
    assert (foreign.value.status_code, foreign.value.detail) == (404, "Importación no encontrada.")
    assert digest(engine) == before
    other, _ = new(request, tmp_path, auto=True, name="Other", entries=[("bird/b.wav", wav_bytes(2))])
    occupying, _ = admit(request, other)
    for total, owner in [(1, 2), (4, 1)]:
        monkeypatch.setenv("FAMA_IMPORT_CONCURRENT_IMPORTS", str(total))
        monkeypatch.setenv("FAMA_IMPORT_JOBS_PER_OWNER", str(owner))
        reject_unchanged(engine, lambda: request("POST", job["status_url"] + "/retry", body={"request_key": "capacity"}), 429, "Se alcanzó el límite de trabajos activos.")
    assert request("POST", occupying["status_url"] + "/cancel").status_code == 200
    monkeypatch.setenv("FAMA_IMPORT_CONCURRENT_IMPORTS", "4")
    monkeypatch.setenv("FAMA_IMPORT_JOBS_PER_OWNER", "2")
    assert request("POST", job["status_url"] + "/retry", body={"request_key": "recover"}).status_code == 202
    reject_unchanged(engine, lambda: request("POST", f"{B}/{source}/preview", body={"request_key": "duplicate", "root": ""}), 409, "La importación ya tiene un trabajo activo.")
    assert worker.run_once()
    assert state(request, source)["status"] == "imported"
