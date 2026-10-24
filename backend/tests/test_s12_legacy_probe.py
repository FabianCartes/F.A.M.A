import json
from tests.test_dataset_import_layout import layout_api
from tests.s12_probe_support import *

def test_legacy_transcript(layout_api, tmp_path):
    request, worker, engine = layout_api
    source, body = new(request, tmp_path, layout=None, entries=[("wrap/bird/session/a.wav", wav_bytes())])
    trace = [state(request, source)]
    job, operation = admit(request, source, root="wrap")
    assert worker.run_once()
    ready = state(request, source)
    assert ready["status"] == "ready" and ready["dataset_id"] is None
    assert "auto_import" not in ready["preview"]
    trace.append(ready)
    reject_unchanged(engine, lambda: request("POST", f"{B}/{source}/confirm", body={"request_key": "wrong", "preview_token": "0"*64}), 409, "La vista previa cambió o no está lista para confirmar.")
    confirmation, _ = admit(request, source, "confirm", preview_token=ready["preview_token"])
    assert worker.run_once()
    imported = state(request, source)
    assert imported["status"] == "imported" and imported["sync_status"] == "pending"
    trace.append(imported)
    trace.append(request("GET", B + "/datasets").json())
    files = request("GET", f"{B}/datasets/{imported["dataset_id"]}/files").json()
    trace.append(files)
    assert request("GET", f"{B}/datasets/{imported["dataset_id"]}/files/{files["files"][0]["sha256"]}").content == wav_bytes()
    assert request("POST", B, body=body).json() == imported
    mapping = {source: "IMPORT", imported["dataset_id"]: "DATASET", ready["preview_token"]: "TOKEN", job["id"]: "PREVIEW_JOB", confirmation["id"]: "CONFIRM_JOB"}
    def ids(value):
        if isinstance(value, dict):
            for key, val in value.items():
                if key == "id" and isinstance(val, str) and val not in mapping: mapping[val] = "RECORD_" + str(len(mapping))
                ids(val)
        elif isinstance(value, list):
            for val in value: ids(val)
    ids(trace)
    text = json.dumps(trace, sort_keys=True, ensure_ascii=False)
    for old, replacement in mapping.items(): text = text.replace(old, replacement)
    print("LEGACY_TRANSCRIPT " + text)
