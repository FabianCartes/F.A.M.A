"""A completed triad training job registers its initial weighted composition."""
import pytest
import torch
from sqlalchemy import event

from app.models.training import Modelo
from app.models.triad_composition import TriadComposition
from tests.test_training_flow import training_env  # noqa: F401  (fixture dependency)
from tests.test_training_persistence import persistence_env, start, history  # noqa: F401


WEIGHTS = (0.5, 0.3, 0.2)


def triad(weights=WEIGHTS):
    return [{"architecture": name, "epochs": 1, "weight": weight}
            for name, weight in zip(("fixture", "fixture2", "fixture3"), weights)]


def compositions(sessions):
    with sessions() as db:
        return db.query(TriadComposition).order_by(TriadComposition.id).all()


def checkpoint_payloads(service, sessions):
    """Checkpoint payloads keyed by the registered model id, in training order."""
    payloads = {}
    for entry in history(service, sessions):
        payload = torch.load(service.checkpoints_dir / entry["filename"], weights_only=False)
        payloads[entry["id"]] = (payload["model_index"], payload, entry)
    return dict(sorted(payloads.items(), key=lambda item: item[1][0]))


def test_completed_triad_creates_version_one_with_the_checkpoint_weights(persistence_env):
    service, sessions, _, dataset_id = persistence_env
    start(service, models=triad())
    assert service.get_progress()["status"] == "completed", service.get_progress()["error_message"]
    payloads = checkpoint_payloads(service, sessions)
    ids = list(payloads)
    composition, = compositions(sessions)
    assert (composition.first_model_id, composition.second_model_id, composition.third_model_id) == tuple(ids)
    assert [composition.first_weight, composition.second_weight, composition.third_weight] == \
        [payload["ensemble_weight"] for _, payload, _ in payloads.values()] == list(WEIGHTS)
    first_payload, first_entry = payloads[ids[0]][1], payloads[ids[0]][2]
    assert composition.job_id == first_payload["job_id"]
    assert (composition.version, composition.previous_id) == (1, None)
    assert composition.dataset_id == dataset_id
    assert composition.partition_version == first_entry["partition_version"]
    assert composition.author_id is None and composition.created_at is not None


def test_failed_triad_creates_no_composition(persistence_env):
    service, sessions, _, _ = persistence_env
    commits = []
    def third_commit_fails(db):
        if any(isinstance(row, Modelo) and row.estado == "standard_eval_pending"
               for row in db.identity_map.values()):
            commits.append(True)
            if len(commits) == 3:
                raise RuntimeError("Third model commit failed")
    event.listen(sessions, "before_commit", third_commit_fails)
    start(service, models=triad())
    assert service.get_progress()["status"] == "failed"
    assert len(history(service, sessions)) == 2
    assert compositions(sessions) == []


def test_stopped_triad_creates_no_composition(persistence_env, request):
    service, sessions, _, _ = persistence_env
    inserted = []
    def stop_after_third(mapper, connection, target):
        inserted.append(target.id_modelo)
        if len(inserted) == 3:
            service._stop_requested = True
    event.listen(Modelo, "after_insert", stop_after_third)
    request.addfinalizer(lambda: event.remove(Modelo, "after_insert", stop_after_third))
    start(service, models=triad())
    assert service.get_progress()["status"] == "stopped"
    assert len(history(service, sessions)) == 3
    assert compositions(sessions) == []


@pytest.mark.parametrize("count", [1, 2])
def test_non_triad_training_creates_no_composition(persistence_env, count):
    service, sessions, _, _ = persistence_env
    start(service, models=[{"architecture": f"fixture{i}", "epochs": 1, "weight": 1 / count}
                           for i in range(count)])
    assert service.get_progress()["status"] == "completed", service.get_progress()["error_message"]
    assert len(history(service, sessions)) == count
    assert compositions(sessions) == []
