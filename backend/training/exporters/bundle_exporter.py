"""
backend/training/exporters/bundle_exporter.py
Empaquetador de Model Bundles estandarizados para serving desacoplado.
"""
from pathlib import Path
from typing import Dict, Any, List, Optional
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
        )

        manifest_file = bundle_dir / "manifest.json"
        manifest_file.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

        # 3. Guardar copia de la receta original para auditoría de linaje
        recipe_file = bundle_dir / "training_recipe.yaml"
        with open(recipe_file, "w", encoding="utf-8") as f:
            yaml.dump(config.model_dump(mode="json"), f, default_flow_style=False)

        return bundle_dir
