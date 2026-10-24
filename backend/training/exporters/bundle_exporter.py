"""
backend/training/exporters/bundle_exporter.py
Empaquetador de Model Bundles estandarizados para serving desacoplado.
"""
from pathlib import Path
from typing import Dict, Any, List, Optional
import hashlib
import os
import re
from datetime import datetime, timezone
import json
import torch
import torch.nn as nn
import yaml

from training.schemas.config import TrainingConfig
from training.schemas.manifest import (
    ModelManifest,
    ManifestAudioSpecs,
    ManifestModelSpecs,
    ManifestDiagnostics,
    FinalEvaluations,
)


class BundleExporter:
    """
    Exporta un modelo entrenado a una carpeta autocontenida (Model Bundle)
    con weights.pt puro y manifest.json.
    """

    @classmethod
    def export(
        cls,
        output_dir: Path,
        model: nn.Module,
        config: TrainingConfig,
        classes: List[str],
        metrics: Optional[Dict[str, Any]] = None,
    ) -> Path:
        output_dir = Path(output_dir)
        bundle_dir = output_dir / config.model_id
        bundle_dir.mkdir(parents=True, exist_ok=True)

        # 1. Guardar pesos limpios (state_dict puro)
        weights_file = bundle_dir / "weights.pt"
        torch.save(model.state_dict(), weights_file)

        # 2. Construir manifest.json
        manifest = ModelManifest(
            model_id=config.model_id,
            name=config.model_name,
            description=config.description,
            created_at=datetime.now(timezone.utc).isoformat(),
            is_default=False,
            classes=classes,
            audio_specs=ManifestAudioSpecs(
                target_sr=config.audio.target_sr,
                duration_seconds=config.audio.duration_seconds,
                n_mels=config.audio.n_mels,
                n_fft=config.audio.n_fft,
                hop_length=config.audio.hop_length,
                f_min=config.audio.f_min,
                f_max=config.audio.f_max,
                use_gpu_frontend=config.audio.use_gpu_frontend,
            ),
            model_specs=ManifestModelSpecs(
                architecture_family="audio_cnn" if "cnn" in config.architecture.type else "timm_bioacoustic",
                backbone=config.architecture.type,
                in_channels=config.architecture.in_chans,
                pool_type=config.architecture.pool_type,
                weights_file="weights.pt",
            ),
            diagnostics=ManifestDiagnostics(),
            metrics=metrics or {},
            dataset_name=config.dataset_name,
        )

        manifest_file = bundle_dir / "manifest.json"
        manifest_file.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

        # 3. Guardar copia de la receta original para auditoría de linaje
        recipe_file = bundle_dir / "training_recipe.yaml"
        with open(recipe_file, "w", encoding="utf-8") as f:
            yaml.dump(config.model_dump(mode="json"), f, default_flow_style=False)

        return bundle_dir

    @classmethod
    def publish_official(cls, provisional_bundle: Path, final_evaluations: Dict[str, Any]) -> Path:
        """Validate reports against staged weights, then publish without overwrite."""
        provisional_bundle = Path(provisional_bundle)
        if provisional_bundle.is_symlink() or not provisional_bundle.is_dir():
            raise ValueError("Official publication requires a real provisional bundle directory")
        manifest_path = provisional_bundle / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError("Official bundle manifest must be a regular local file")
        manifest = ModelManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        if not re.fullmatch(r"[a-z0-9_-]+", manifest.model_id):
            raise ValueError("Official bundle model_id must be a single safe slug")
        if not provisional_bundle.parent.name.startswith(f".{manifest.model_id}.provisional-"):
            raise ValueError("Official publication requires a model-bound provisional directory")
        publication_root = provisional_bundle.parent.parent
        if (provisional_bundle.parent.is_symlink() or publication_root.is_symlink() or
                not publication_root.is_dir()):
            raise ValueError("Official publication path must use real directories")
        weights_name = manifest.model_specs.weights_file
        if Path(weights_name).name != weights_name or weights_name in (".", ".."):
            raise ValueError("Official bundle weights_file must be a single relative filename")
        weights_path = provisional_bundle / weights_name
        if weights_path.is_symlink() or not weights_path.is_file():
            raise ValueError("Official bundle weights must be a regular local file")
        digest = hashlib.sha256(weights_path.read_bytes()).hexdigest()
        evaluations = FinalEvaluations.model_validate({
            "weights_sha256": digest,
            "reports": final_evaluations,
        })
        manifest_data = manifest.model_dump(mode="python")
        manifest_data["final_evaluations"] = evaluations
        # Re-run the complete manifest contract; assignment validation alone would
        # skip the root-level bundle/provenance binding validator.
        validated_manifest = ModelManifest.model_validate(manifest_data)
        destination = publication_root / manifest.model_id
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"Official bundle already exists: {destination}")
        manifest_path.write_text(validated_manifest.model_dump_json(indent=2), encoding="utf-8")
        os.rename(provisional_bundle, destination)
        return destination
