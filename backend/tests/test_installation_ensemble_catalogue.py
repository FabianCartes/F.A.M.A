"""Installation catalogue with real configuration, SQLite and checkpoint metadata."""
import json
import os
from pathlib import Path
import subprocess
import sys


def test_declared_catalogue_survives_restart_and_persisted_activation(tmp_path):
    from app.configuration import InstallationStore

    store = InstallationStore(tmp_path / "installation")
    store.save({
        "DATABASE_URL_FILE": str(tmp_path / "database.secret"),
        "GCS_BUCKET_NAME": "synthetic-bucket",
        "FAMA_RUNTIME_DIR": str(tmp_path / "runtime"),
        "FAMA_ENSEMBLES_JSON": json.dumps({
            "version": 1, "enabled": ["chilean-birds-ensemble"],
            "default": "chilean-birds-ensemble",
        }),
    })
    (tmp_path / "database.secret").write_text("sqlite:///" + (tmp_path / "catalogue.db").as_posix())
    program = r'''
import json, sys
from pathlib import Path
from app.configuration import activate_configuration, load_configuration
configuration = load_configuration({"FAMA_CONFIG_DIR": sys.argv[1]})
activate_configuration(configuration, replace_environment=True)
from app.database import Base, engine, SessionLocal
import app.models
from app.models.training import Modelo
from app.services.registry import build_default_registry
from training.paths import get_checkpoints_dir
if sys.argv[2] == "prepare":
    import torch, hashlib
    from poc.train import AudioCNN
    Base.metadata.create_all(engine)
    root = get_checkpoints_dir()
    root.mkdir(parents=True)
    checkpoint = root / "persisted.pt"
    torch.save({"model_state_dict": AudioCNN(num_classes=2).state_dict(),
                "classes": ["A", "B"], "architecture": "AudioCNN"}, checkpoint)
    with SessionLocal() as db:
        db.add(Modelo(arquitectura="AudioCNN", epocas=1, tasa_aprendizaje=.001,
                      tamano_lote=2, ruta_binario_gcp=checkpoint.as_uri(), activo=False,
                      hash_binario=hashlib.sha256(checkpoint.read_bytes()).hexdigest(), tamano_bytes=checkpoint.stat().st_size))
        db.commit()
registry = build_default_registry()
models = registry.list_models()
assert {m.id for m in models} == {"chilean-birds-ensemble", "fama_trained_model_1"}
assert registry.get_default_model_id() == "chilean-birds-ensemble"
assert not registry.get("chilean-birds-ensemble").has_weights
assert registry.get("1").has_weights
with SessionLocal() as db:
    db.get(Modelo, 1).activo = True
    db.commit()
activated = build_default_registry()
assert activated.get_default_model_id() == "fama_trained_model_1"
with SessionLocal() as db:
    db.get(Modelo, 1).activo = False
    db.commit()
print("catalogue_verified")
'''
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("FAMA_") and key not in {
                       "DATABASE_URL", "DATABASE_URL_FILE", "GCS_BUCKET_NAME", "JWT_SECRET_KEY",
                       "JWT_SECRET_KEY_FILE", "GCP_KEY_PATH", "GOOGLE_APPLICATION_CREDENTIALS",
                   }}
    for mode in ("prepare", "restart"):
        result = subprocess.run([sys.executable, "-c", program, str(store.directory), mode],
                                cwd=Path(__file__).resolve().parents[1], env=environment,
                                capture_output=True, text=True, timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "catalogue_verified" in result.stdout
