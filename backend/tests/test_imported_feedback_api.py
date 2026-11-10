"""Public HTTP identity checks for the imported feedback review lifecycle."""
import pytest
from tests.http_security import cookie_headers, cookie_security

from tests.test_api_feedback import client as legacy_client, test_db, fake_gcs
# Register the complete additive source schema before the shared fixture creates it.
from app.models.training_snapshot import TrainingSnapshot
from app.models.imported_training_source import ImportedModelSource


@pytest.fixture
def client(legacy_client):
    from tests.http_security import COOKIE_ORIGIN
    legacy_client.headers["Origin"] = COOKIE_ORIGIN
    return legacy_client


@pytest.fixture
def private_prediction(test_db):
    from app.models.prediction import Prediccion
    prediction = Prediccion(
        ruta_audio_prueba="raw_audios/0123456789abcdef0123456789abcdef.wav",
        etiqueta_predicha="Synthetic class", confianza=0.9,
        modelo_id="301", dataset_name="imported:" + "a" * 32,
    )
    test_db.add(prediction)
    test_db.commit()
    return prediction.id_prediccion


@pytest.mark.parametrize("action", ["record", "approve", "reject"])
def test_imported_feedback_requires_session_before_mutation(client, test_db, private_prediction, action):
    from app.models.feedback import Retroalimentacion
    if action == "record":
        response = client.post("/api/feedback", json={
            "id_prediccion": private_prediction, "fue_correcta": True,
        })
    else:
        row = Retroalimentacion(id_prediccion=private_prediction, id_usuario=1,
                                fue_correcta=True, procesado=False)
        test_db.add(row)
        test_db.commit()
        response = client.post(f"/api/feedback/{row.id_retroalimentacion}/{action}")
    assert response.status_code == 401, response.text
    assert response.json() == {"detail": "Sesión requerida o expirada."}
    # The existing public review list must not expose private feedback anonymously.
    pending = client.get("/api/feedback/pending")
    assert pending.status_code == 200, pending.text
    assert pending.json() == []


@pytest.fixture
def owners(test_db, monkeypatch):
    from app.models.user import Usuario
    from app.models.training import Modelo
    from app.services import auth
    monkeypatch.setattr(auth, "SECRET_KEY", "synthetic-feedback-growth-session-key-2026-only")
    test_db.add_all([Usuario(id=identity, email=f"owner{identity}@example.test",
                            nombre_completo=f"Owner {identity}", password_hash="unused",
                            rol="investigador", activo=True) for identity in (1, 2)])
    test_db.add(TrainingSnapshot(id="b" * 32, owner_id=1, dataset_id="a" * 32,
                                dataset_revision=1, name="Synthetic", description="",
                                state="ready", file_count=1, total_size_bytes=44, classes=["Synthetic class"]))
    test_db.add(Modelo(id_modelo=301, arquitectura="AudioCNN", epocas=1,
                      tasa_aprendizaje=0.001, tamano_lote=1, ruta_binario_gcp="local.pt"))
    test_db.flush()
    test_db.add(ImportedModelSource(model_id=301, owner_id=1, dataset_id="a" * 32,
                                   snapshot_id="b" * 32, identity={"owner_id": 1, "dataset_id": "a" * 32}))
    test_db.commit()
    from sqlalchemy.orm import sessionmaker
    sessions = sessionmaker(bind=test_db.get_bind())
    return {identity: cookie_headers(sessions, identity) for identity in (1, 2)}


def test_imported_feedback_uses_session_identity_and_preserves_pending_after_foreign_review(
        client, private_prediction, owners):
    body = {"id_prediccion": private_prediction, "fue_correcta": True, "id_usuario": 2}
    foreign = client.post("/api/feedback", json=body, headers=owners[2])
    assert foreign.status_code == 404, foreign.text
    created = client.post("/api/feedback", json=body, headers=owners[1])
    assert created.status_code == 201, created.text
    assert created.json()["id_usuario"] == 1
    feedback_id = created.json()["id_retroalimentacion"]
    for action in ("approve", "reject"):
        rejected = client.post(f"/api/feedback/{feedback_id}/{action}", headers=owners[2])
        assert rejected.status_code == 404, rejected.text
        assert rejected.json() == {"detail": "Retroalimentación no disponible."}
    assert client.get("/api/feedback/pending", headers=owners[2]).json() == []
    pending = client.get("/api/feedback/pending", headers=owners[1])
    assert pending.status_code == 200, pending.text
    assert [(item["id_retroalimentacion"], item["procesado"]) for item in pending.json()] == [(feedback_id, False)]


def test_feedback_stats_hide_private_labels_without_the_owner_session(client, private_prediction, owners):
    created = client.post('/api/feedback', headers=owners[1], json={
        'id_prediccion': private_prediction, 'fue_correcta': False,
        'etiqueta_corregida': 'Private corrected class',
    })
    assert created.status_code == 201, created.text
    for headers in ({}, owners[2]):
        response = client.get('/api/feedback/stats', headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()['total_validated'] == 0
        assert response.json()['corrections_breakdown'] == []
        assert 'Private corrected class' not in response.text
    response = client.get('/api/feedback/stats', headers=owners[1])
    assert response.status_code == 200, response.text
    assert response.json()['total_validated'] == 1
    assert response.json()['corrections_breakdown'] == [{'species': 'Private corrected class', 'count': 1}]


def test_pending_limit_applies_after_owner_visibility(client, test_db, private_prediction, owners):
    from app.models.prediction import Prediccion
    from app.models.feedback import Retroalimentacion
    from app.models.training import Modelo
    created = client.post('/api/feedback', headers=owners[1], json={
        'id_prediccion': private_prediction, 'fue_correcta': True,
    })
    assert created.status_code == 201, created.text
    test_db.add(Modelo(id_modelo=302, arquitectura='AudioCNN', epocas=1,
                      tasa_aprendizaje=.001, tamano_lote=1, ruta_binario_gcp='foreign-local.pt'))
    test_db.add(ImportedModelSource(model_id=302, owner_id=2, dataset_id='c' * 32,
                                   snapshot_id='b' * 32, identity={'owner_id': 2}))
    pred = Prediccion(modelo_id='302', dataset_name='imported:' + 'c' * 32,
                      etiqueta_predicha='Foreign class', confianza=.9, ruta_audio_prueba='foreign.wav')
    test_db.add(pred)
    test_db.flush()
    from datetime import datetime, timezone
    test_db.add(Retroalimentacion(id_prediccion=pred.id_prediccion, id_usuario=2,
                                 fue_correcta=True, procesado=False,
                                 fecha_retroalimentacion=datetime(2099, 1, 1, tzinfo=timezone.utc)))
    test_db.commit()
    response = client.get('/api/feedback/pending?limit=1', headers=owners[1])
    assert response.status_code == 200, response.text
    assert [row['id_retroalimentacion'] for row in response.json()] == [created.json()['id_retroalimentacion']]


def test_imported_pending_feedback_is_not_exposed_without_a_session(client, test_db, private_prediction):
    from app.models.feedback import Retroalimentacion
    test_db.add(Retroalimentacion(id_prediccion=private_prediction, id_usuario=1,
                                 fue_correcta=True, procesado=False))
    test_db.commit()
    response = client.get("/api/feedback/pending")
    assert response.status_code == 200, response.text
    assert response.json() == []
