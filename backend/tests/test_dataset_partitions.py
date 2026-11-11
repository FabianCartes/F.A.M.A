"""Versioned partitions through authenticated HTTP; real files, temporary SQL, no ML/GCS."""
import hashlib
from pathlib import Path
from unittest.mock import Mock

import pytest

from tests.training_admission import DeferredTrainingProcess
from app import main
from app.models.dataset import ConjuntoDatos, Audio
from app.models.dataset_access import AsignacionDataset
from app.models.feedback_sync import FeedbackSync
from app.models.feedback import Retroalimentacion
from app.models.prediction import Prediccion
from app.services import training
from training import paths
from tests.test_web_sessions import web, login, ORIGIN
from tests.test_ingestion_upload_integrity import synthetic_wav


@pytest.fixture
def partition_http(web, tmp_path, monkeypatch):
    client, sessions = web
    from app.routes.partitions import router
    client.app.include_router(router)
    monkeypatch.setattr(paths, "get_raw_data_dir", lambda name=None: tmp_path / "raw" / (name or ""))
    monkeypatch.setattr(paths, "get_processed_data_dir", lambda name=None: tmp_path / "processed" / (name or ""))
    monkeypatch.setattr(training, "SessionLocal", sessions)
    monkeypatch.setattr(main, "training_service", training.TrainingService(tmp_path / "checkpoints", process_factory=DeferredTrainingProcess))
    monkeypatch.setattr(training.threading, "Thread", Mock())
    for route in main.app.routes:
        if getattr(route, "path", "") in {"/api/training/start", "/api/training/progress"}:
            client.app.add_api_route(route.path, route.endpoint, methods=list(route.methods), dependencies=route.dependencies)
    raw = tmp_path / "raw" / "Sample"
    raw.mkdir(parents=True)
    with sessions() as db:
        db.add(ConjuntoDatos(id_conjunto_datos=10, nombre="Sample", ruta_gcp="gs://fixture/datasets/Sample/"))
        db.add(AsignacionDataset(id_usuario=2, id_conjunto_datos=10))
        for index in range(10):
            label = "Chucao" if index < 5 else "Canastero"
            filename = f"{label}/{index}.wav"
            content = synthetic_wav(frames=800)[:-2] + (index + 1).to_bytes(2, "little")
            path = raw / filename
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(content)
            db.add(Audio(id_conjunto_datos=10, nombre_archivo=path.name, clase=label,
                         ruta_gcp=f"gs://fixture/datasets/Sample/{filename}", tamano_bytes=len(content),
                         hash_archivo=hashlib.sha256(content).hexdigest()))
        db.commit()
    assert login(client).status_code == 200
    yield client, sessions, raw


BASE = "/api/training/datasets/Sample/partitions"
POLICY = {"validation_percent": 20, "seed": 42}


def test_researcher_previews_then_saves_an_immutable_version_without_replacing_legacy_csv(partition_http):
    client, _, raw = partition_http
    for split in ("train", "val"):
        (raw / f"{split}.csv").write_text("existing historical partition", encoding="utf-8")

    response = client.post(BASE + "/preview", headers={"Origin": ORIGIN}, json=POLICY)
    assert response.status_code == 200
    preview = response.json()
    assert preview["counts"] == {"train": 6, "val": 2, "test": 2}
    assert len(preview["version"]) == 64
    assert preview["warnings"] == []  # Unknown recordists no longer produce a warning.
    assert client.get(BASE).json()["versions"] == []
    saved = client.post(BASE, headers={"Origin": ORIGIN}, json={
        **POLICY, "preview_version": preview["version"], "acknowledge_warnings": True})
    assert saved.status_code == 200
    version = client.get(BASE + "/" + preview["version"]).json()
    assert version["version"] == preview["version"]
    assert version["created_by"] == 2
    assert version["counts"] == {"train": 6, "val": 2, "test": 2}
    assert len({entry["file_path"] for entry in version["entries"]}) == 10
    assert all(entry["file_stage"] == "raw" and len(entry["hash_sha256"]) == 64 for entry in version["entries"])
    assert {entry["clase"] for entry in version["entries"] if entry["split"] == "val"} == {"Chucao", "Canastero"}
    assert len(client.get(BASE).json()["versions"]) == 1
    for split in ("train", "val"):
        assert (raw / f"{split}.csv").read_text(encoding="utf-8") == "existing historical partition"


def test_exact_duplicates_and_known_source_groups_never_cross_partitions(partition_http):
    client, sessions, raw = partition_http
    # Five copies of the same recording form one indivisible source group.
    content = (raw / "Chucao/0.wav").read_bytes()
    with sessions() as db:
        for index in range(1, 5):
            (raw / f"Chucao/{index}.wav").write_bytes(content)
            row = db.query(Audio).filter_by(ruta_gcp=f"gs://fixture/datasets/Sample/Chucao/{index}.wav").one()
            row.hash_archivo = hashlib.sha256(content).hexdigest()
        db.commit()
    (raw / "metadata.csv").write_text(
        "file_path,file_stage,clase,source_group,recordist\n"
        "Canastero/5.wav,raw,Canastero,source-a,\n"
        "Canastero/6.wav,raw,Canastero,source-a,\n", encoding="utf-8")

    response = client.post(BASE + "/preview", headers={"Origin": ORIGIN}, json=POLICY)

    assert response.status_code == 200
    entries = response.json()["entries"]
    assert {entry["split"] for entry in entries if entry["clase"] == "Chucao"} == {"train"}
    assert len({entry["split"] for entry in entries if entry["file_path"] in {"Canastero/5.wav", "Canastero/6.wav"}}) == 1


def add_feedback(sessions, raw, feedback_id, prediction_id, path, label):
    content = (raw / path).read_bytes()
    with sessions() as db:
        if db.get(Prediccion, prediction_id) is None:
            db.add(Prediccion(id_prediccion=prediction_id, ruta_audio_prueba=f"raw_audios/{prediction_id}.wav",
                              etiqueta_predicha=label, confianza=0.7))
            db.flush()
        db.add(Retroalimentacion(id_retroalimentacion=feedback_id, id_prediccion=prediction_id, id_usuario=2,
                                 fue_correcta=True, procesado=True))
        db.flush()
        db.add(FeedbackSync(id_retroalimentacion=feedback_id, dataset_name="Sample", storage_class=label, class_label=label,
                            object_key=f"datasets/Sample/{path}", local_relative_path=f"Sample/{path}",
                            sha256=hashlib.sha256(content).hexdigest()))
        db.commit()


@pytest.mark.parametrize("placeholder", ["", "unknown", "human_feedback"])
def test_feedback_enters_with_its_prediction_as_origin_and_recordists_stay_together(partition_http, placeholder):
    client, sessions, raw = partition_http
    add_feedback(sessions, raw, 1, 1, "Canastero/9.wav", "Canastero")
    (raw / "metadata.csv").write_text(
        "file_path,file_stage,clase,recordist,source_group\n"
        "Chucao/0.wav,raw,Chucao,Recorder A,\n"
        "Chucao/1.wav,raw,Chucao,Recorder A,\n"
        f"Canastero/9.wav,raw,Canastero,human_feedback,{placeholder}\n", encoding="utf-8")

    response = client.post(BASE + "/preview", headers={"Origin": ORIGIN}, json=POLICY)

    assert response.status_code == 200
    assert response.json()["excluded"] == []
    assert not any("corrección" in warning for warning in response.json()["warnings"])
    entries = response.json()["entries"]
    assert len(entries) == 10
    feedback, = [entry for entry in entries if entry["file_path"] == "Canastero/9.wav"]
    assert feedback["origin"] == "prediction:1"
    assert len({entry["split"] for entry in entries if entry["recordist"] == "Recorder A"}) == 1


def test_each_feedback_takes_the_origin_of_its_own_prediction(partition_http):
    client, sessions, raw = partition_http
    add_feedback(sessions, raw, 1, 1, "Canastero/5.wav", "Canastero")
    add_feedback(sessions, raw, 2, 7, "Canastero/6.wav", "Canastero")
    response = client.post(BASE + "/preview", headers={"Origin": ORIGIN}, json=POLICY)
    assert response.status_code == 200, response.text
    origins = {entry["file_path"]: entry.get("origin") for entry in response.json()["entries"]}
    assert (origins["Canastero/5.wav"], origins["Canastero/6.wav"]) == ("prediction:1", "prediction:7")
    assert origins["Canastero/7.wav"] is None


def test_curated_correction_stays_with_the_recording_it_corrects(partition_http):
    client, sessions, raw = partition_http
    add_feedback(sessions, raw, 1, 1, "Chucao/1.wav", "Chucao")
    (raw / "metadata.csv").write_text(
        "file_path,file_stage,clase,xc_id,recordist,curation_source_id\n"
        "Chucao/0.wav,raw,Chucao,XC1,Recorder A,\n"
        "Chucao/1.wav,raw,Chucao,feedback_1,human_feedback,XC1\n", encoding="utf-8")
    for seed in range(8):
        response = client.post(BASE + "/preview", headers={"Origin": ORIGIN}, json={**POLICY, "seed": seed})
        assert response.status_code == 200, response.text
        entries = {entry["file_path"]: entry for entry in response.json()["entries"]}
        assert entries["Chucao/1.wav"]["split"] == entries["Chucao/0.wav"]["split"]
        assert entries["Chucao/0.wav"]["origin"] == entries["Chucao/1.wav"]["origin"] == "recording:XC1"


def test_same_recording_with_conflicting_labels_requires_review(partition_http):
    client, sessions, raw = partition_http
    content = (raw / "Chucao/0.wav").read_bytes()
    (raw / "Canastero/5.wav").write_bytes(content)
    with sessions() as db:
        db.query(Audio).filter_by(ruta_gcp="gs://fixture/datasets/Sample/Canastero/5.wav").one().hash_archivo = hashlib.sha256(content).hexdigest()
        db.commit()

    response = client.post(BASE + "/preview", headers={"Origin": ORIGIN}, json=POLICY)

    assert response.status_code == 409
    assert "clases distintas" in response.json()["detail"]
    assert client.get(BASE).json()["versions"] == []


def save_version(client):
    preview = client.post(BASE + "/preview", headers={"Origin": ORIGIN}, json=POLICY).json()
    response = client.post(BASE, headers={"Origin": ORIGIN}, json={
        **POLICY, "preview_version": preview["version"], "acknowledge_warnings": True})
    assert response.status_code == 200
    return response.json()


def test_training_explicitly_uses_saved_version_without_needing_legacy_csv(partition_http):
    client, _, _ = partition_http
    saved = save_version(client)

    response = client.post("/api/training/start", headers={"Origin": ORIGIN}, json={
        "dataset_name": "Sample", "partition_version": saved["version"], "epochs": 1})

    assert response.status_code == 200, response.text
    assert response.json()["partition_version"] == saved["version"]
    assert client.get("/api/training/progress").json()["status"] == "training"


def test_stale_preview_is_not_saved_and_repeated_save_keeps_original_author_and_time(partition_http):
    client, sessions, _ = partition_http
    saved = save_version(client)
    repeated = client.post(BASE, headers={"Origin": ORIGIN}, json={
        **POLICY, "preview_version": saved["version"], "acknowledge_warnings": True})
    assert repeated.status_code == 200
    assert repeated.json() == saved
    with sessions() as db:
        db.add(Audio(id_conjunto_datos=10, nombre_archivo="later.wav", clase="Chucao",
                     ruta_gcp="gs://fixture/datasets/Sample/Chucao/later.wav"))
        db.commit()
    stale = client.post(BASE, headers={"Origin": ORIGIN}, json={
        **POLICY, "preview_version": saved["version"], "acknowledge_warnings": True})
    assert stale.status_code == 409
    assert "cambiaron" in stale.json()["detail"]
    assert client.get(BASE + "/" + saved["version"]).json() == saved
    training = client.post("/api/training/start", headers={"Origin": ORIGIN}, json={
        "dataset_name": "Sample", "partition_version": saved["version"]})
    assert training.status_code == 200


def test_versioned_training_rejects_changed_bytes_instead_of_falling_back_to_csv(partition_http):
    client, _, raw = partition_http
    saved = save_version(client)
    (raw / "Chucao/0.wav").write_bytes(b"modified recording")
    response = client.post("/api/training/start", headers={"Origin": ORIGIN}, json={
        "dataset_name": "Sample", "partition_version": saved["version"]})
    assert response.status_code == 400
    assert "contenido local" in response.json()["detail"]
    assert client.get("/api/training/progress").json()["status"] == "failed"


def test_unassigned_and_anonymous_accounts_cannot_discover_or_modify_versions(partition_http):
    client, sessions, _ = partition_http
    saved = save_version(client)
    with sessions() as db:
        db.query(AsignacionDataset).filter_by(id_usuario=2).delete()
        db.commit()
    for method, suffix, body in [("get", "", None), ("get", "/" + saved["version"], None),
                                 ("post", "/preview", POLICY), ("post", "", {**POLICY, "preview_version": saved["version"]})]:
        kwargs = {"headers": {"Origin": ORIGIN}}
        if body is not None:
            kwargs["json"] = body
        assert getattr(client, method)(BASE + suffix, **kwargs).status_code == 404
    client.cookies.clear()
    assert client.get(BASE).status_code == 401


@pytest.mark.parametrize("policy", [{"validation_percent": 0}, {"validation_percent": 50}, {"seed": -1},
                                  {"validation_percent": True}, {"seed": "42"}])
def test_invalid_policy_cannot_create_a_version(partition_http, policy):
    client, _, _ = partition_http
    assert client.post(BASE + "/preview", headers={"Origin": ORIGIN}, json=policy).status_code == 422
    assert client.get(BASE).json()["versions"] == []


def test_partition_cannot_be_reused_after_switching_dataset_storage_identity(partition_http):
    client, sessions, _ = partition_http
    saved = save_version(client)
    with sessions() as db:
        db.get(ConjuntoDatos, 10).ruta_gcp = "gs://another-bucket/datasets/Sample/"
        for row in db.query(Audio).filter_by(id_conjunto_datos=10):
            row.ruta_gcp = row.ruta_gcp.replace("gs://fixture/", "gs://another-bucket/")
        db.commit()

    assert client.get(BASE + "/" + saved["version"]).status_code == 409
    assert client.post("/api/training/start", headers={"Origin": ORIGIN}, json={
        "dataset_name": "Sample", "partition_version": saved["version"]}).status_code == 400


@pytest.mark.parametrize("broken", ["[]", "{}", "{not json"])
def test_damaged_manifest_is_reported_as_unavailable_without_fallback(partition_http, broken):
    client, _, raw = partition_http
    saved = save_version(client)
    (raw / ".partitions" / f"{saved['version']}.json").write_text(broken, encoding="utf-8")
    response = client.get(BASE + "/" + saved["version"])
    assert response.status_code == 409
    assert "dañada" in response.json()["detail"]


def test_unreviewed_warnings_and_foreign_origin_cannot_publish(partition_http):
    client, _, raw = partition_http
    (raw / "Chucao/4.wav").unlink()  # A real warning: one audio without a local copy.
    preview = client.post(BASE + "/preview", headers={"Origin": ORIGIN}, json=POLICY).json()
    body = {**POLICY, "preview_version": preview["version"]}
    assert client.post(BASE, headers={"Origin": ORIGIN}, json=body).status_code == 409
    assert client.post(BASE, headers={"Origin": "https://foreign.example.test"}, json={
        **body, "acknowledge_warnings": True}).status_code == 403
    assert client.get(BASE).json()["versions"] == []


def test_new_partitions_have_independent_test_groups_and_legacy_versions_stay_readable(partition_http):
    import json
    from app.services.partitions import _encoded
    client, _, raw = partition_http
    version = save_version(client)
    assert version["format"] == 2
    groups = [{entry["source_group_id"] for entry in version["entries"] if entry["split"] == split}
              for split in ("train", "val", "test")]
    assert all(groups)
    assert not (groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2])
    legacy = {key: value for key, value in version.items() if key not in {"version", "created_at", "created_by"}}
    legacy["format"] = 1
    legacy["policy"].pop("test_percent")
    for entry in legacy["entries"]:
        if entry["split"] == "test": entry["split"] = "train"
    legacy["counts"] = {"train": 8, "val": 2}
    identity = hashlib.sha256(_encoded(legacy)).hexdigest()
    (raw/".partitions"/f"{identity}.json").write_bytes(_encoded(dict(legacy, version=identity)))
    assert client.get(BASE+"/"+identity).status_code == 200
    response = client.post("/api/training/start", headers={"Origin": ORIGIN}, json={
        "dataset_name": "Sample", "partition_version": identity})
    assert response.status_code == 400
    assert "histórica" in response.json()["detail"]


def test_triad_training_uses_the_saved_partition_version(partition_http):
    client, _, _ = partition_http
    saved = save_version(client)

    response = client.post("/api/training/start", headers={"Origin": ORIGIN}, json={
        "dataset_name": "Sample", "partition_version": saved["version"], "is_tri_model": True, "epochs": 1})

    assert response.status_code == 200, response.text
    assert response.json()["partition_version"] == saved["version"]
    progress = client.get("/api/training/progress").json()
    assert (progress["status"], progress["total_models"]) == ("training", 3)


def add_audio(sessions, raw, path, label, content):
    (raw / path).parent.mkdir(exist_ok=True)
    (raw / path).write_bytes(content)
    with sessions() as db:
        db.add(Audio(id_conjunto_datos=10, nombre_archivo=Path(path).name, clase=label,
                     ruta_gcp=f"gs://fixture/datasets/Sample/{path}", tamano_bytes=len(content),
                     hash_archivo=hashlib.sha256(content).hexdigest()))
        db.commit()


def saved_base(client):
    preview = client.post(BASE + "/preview", headers={"Origin": ORIGIN}, json=POLICY).json()
    saved = client.post(BASE, headers={"Origin": ORIGIN}, json={
        **POLICY, "preview_version": preview["version"], "acknowledge_warnings": True})
    assert saved.status_code == 200, saved.text
    return client.get(BASE + "/" + preview["version"]).json()


def test_updated_version_keeps_previous_splits_and_only_assigns_new_audios(partition_http):
    client, sessions, raw = partition_http
    base = saved_base(client)
    for index in range(10, 18):
        label = "Chucao" if index % 2 else "Canastero"
        add_audio(sessions, raw, f"{label}/{index}.wav", label, synthetic_wav(frames=800)[:-2] + index.to_bytes(2, "little"))

    response = client.post(BASE + "/preview", headers={"Origin": ORIGIN}, json={**POLICY, "base_version": base["version"]})

    assert response.status_code == 200, response.text
    update = response.json()
    previous = {entry["file_path"]: entry["split"] for entry in base["entries"]}
    current = {entry["file_path"]: entry["split"] for entry in update["entries"]}
    assert {path: current[path] for path in previous} == previous
    assert len(current) == 18
    assert update["policy"]["base_version"] == base["version"]
    assert update["policy"]["algorithm"] == "grouped-incremental-v1"
    assert sum(update["counts"].values()) == 18
    assert update["version"] != base["version"]
    saved = client.post(BASE, headers={"Origin": ORIGIN}, json={
        **POLICY, "base_version": base["version"], "preview_version": update["version"], "acknowledge_warnings": True})
    assert saved.status_code == 200, saved.text
    assert client.get(BASE + "/" + update["version"]).json()["policy"]["base_version"] == base["version"]


def test_new_exact_duplicate_inherits_the_split_of_its_original(partition_http):
    client, sessions, raw = partition_http
    base = saved_base(client)
    original = next(entry for entry in base["entries"] if entry["split"] != "train")
    add_audio(sessions, raw, f"{original['clase']}/copy.wav", original["clase"], (raw / original["file_path"]).read_bytes())
    update = client.post(BASE + "/preview", headers={"Origin": ORIGIN}, json={**POLICY, "base_version": base["version"]}).json()
    copy, = [entry for entry in update["entries"] if entry["file_path"].endswith("copy.wav")]
    assert copy["split"] == original["split"]


@pytest.mark.parametrize("change", [{"seed": 7}, {"validation_percent": 25}, {"test_percent": 15}])
def test_updated_version_requires_the_base_policy(partition_http, change):
    client, _, _ = partition_http
    base = saved_base(client)
    response = client.post(BASE + "/preview", headers={"Origin": ORIGIN},
                           json={**POLICY, **change, "base_version": base["version"]})
    assert response.status_code == 409
    assert "semilla y los porcentajes" in response.json()["detail"]


def test_updated_version_requires_an_existing_base(partition_http):
    client, _, _ = partition_http
    response = client.post(BASE + "/preview", headers={"Origin": ORIGIN}, json={**POLICY, "base_version": "e" * 64})
    assert response.status_code == 409
    assert "no está disponible" in response.json()["detail"]


def test_versions_report_audios_added_or_changed_since_they_were_saved(partition_http):
    client, sessions, raw = partition_http
    base = saved_base(client)
    listed, = client.get(BASE).json()["versions"]
    assert listed["freshness"] == {"new": 0, "changed": 0}
    for index in range(10, 13):
        add_audio(sessions, raw, f"Chucao/{index}.wav", "Chucao", synthetic_wav(frames=800)[:-2] + index.to_bytes(2, "little"))
    with sessions() as db:
        changed = db.query(Audio).filter_by(ruta_gcp="gs://fixture/datasets/Sample/Canastero/9.wav").one()
        changed.hash_archivo = "f" * 64
        db.commit()
    listed, = client.get(BASE).json()["versions"]
    assert listed["version"] == base["version"]
    assert listed["freshness"] == {"new": 3, "changed": 1}
    assert "entries" not in listed


def test_review_summarizes_missing_duplicates_small_classes_and_atypical_durations(partition_http):
    client, sessions, raw = partition_http
    (raw / "Chucao/4.wav").unlink()
    content = (raw / "Canastero/5.wav").read_bytes()
    (raw / "Canastero/6.wav").write_bytes(content)
    with sessions() as db:
        rows = {row.ruta_gcp.rsplit("Sample/", 1)[1]: row for row in db.query(Audio).filter_by(id_conjunto_datos=10)}
        rows["Canastero/6.wav"].hash_archivo = rows["Canastero/5.wav"].hash_archivo
        for path, row in rows.items():
            row.duracion_segundos = 2.0
        rows["Chucao/0.wav"].duracion_segundos = 0.5
        rows["Canastero/9.wav"].duracion_segundos = 9.0
        rows["Chucao/1.wav"].duracion_segundos = None
        db.commit()

    response = client.get(BASE + "/review")

    assert response.status_code == 200, response.text
    review = response.json()
    assert review["total"] == 10
    assert review["classes"] == {"Canastero": 5, "Chucao": 5}
    assert review["not_local"] == {"count": 1, "files": ["Chucao/4.wav"]}
    assert review["duplicates"] == {"count": 1, "groups": [["Canastero/5.wav", "Canastero/6.wav"]]}
    assert review["small_classes"] == [{"clase": "Canastero", "count": 5}, {"clase": "Chucao", "count": 5}]
    assert review["atypical_durations"] == {"count": 2, "files": [
        {"file_path": "Canastero/9.wav", "clase": "Canastero", "duration_seconds": 9.0, "class_median_seconds": 2.0},
        {"file_path": "Chucao/0.wav", "clase": "Chucao", "duration_seconds": 0.5, "class_median_seconds": 2.0}]}
    assert review["unknown_durations"] == 1


def test_review_requires_a_session(partition_http):
    client, _, _ = partition_http
    client.cookies.clear()
    assert client.get(BASE + "/review").status_code == 401


def test_updated_version_rejects_metadata_that_joins_groups_from_different_splits(partition_http):
    client, _, raw = partition_http
    base = saved_base(client)
    by_split = {}
    for entry in base["entries"]:
        by_split.setdefault(entry["split"], entry)
    first, second = by_split["train"], by_split["val"]
    (raw / "metadata.csv").write_text(
        "file_path,file_stage,clase,source_group\n"
        f"{first['file_path']},raw,{first['clase']},shared-session\n"
        f"{second['file_path']},raw,{second['clase']},shared-session\n", encoding="utf-8")
    response = client.post(BASE + "/preview", headers={"Origin": ORIGIN}, json={**POLICY, "base_version": base["version"]})
    assert response.status_code == 409
    assert "desde cero" in response.json()["detail"]
    assert client.post(BASE + "/preview", headers={"Origin": ORIGIN}, json=POLICY).status_code == 200
