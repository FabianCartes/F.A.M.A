import tempfile
import torch
import soundfile as sf
import numpy as np
from pathlib import Path

from training.schemas.config import AudioConfig, TrainingConfig
from training.schemas.manifest import ModelManifest
from training.datasets.local_folder import LocalFolderPAMIngestor
from training.pipelines.dataset import GenericAudioDataset
from training.pipelines.split import grouped_stratified_split_dataset
from training.exporters.bundle_exporter import BundleExporter
from app.services.predictors.bundle_predictor import BundleAudioPredictor
from app.services.registry import ModelRegistry, discover_and_register_bundles

def main():
    print("=== 1. Validando Esquemas Pydantic ===")
    audio_cfg = AudioConfig(target_sr=32000, duration_seconds=3.0, n_mels=64, f_max=16000)
    print(f"[OK] AudioConfig generado: SR={audio_cfg.target_sr}, Dur={audio_cfg.duration_seconds}s, Mels={audio_cfg.n_mels}")

    print("\n=== 2. Simulando Ingesta y Dataset con Ingestor Local ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        # Crear estructura de carpetas por especie con audios dummy
        sp1 = tmp_path / "Turdus_falklandii"
        sp2 = tmp_path / "Sephanoides_sephaniodes"
        sp1.mkdir(); sp2.mkdir()
        
        dummy_audio = np.random.uniform(-0.5, 0.5, 32000 * 2).astype(np.float32)
        sf.write(str(sp1 / "audio1.wav"), dummy_audio, 32000)
        sf.write(str(sp2 / "audio2.wav"), dummy_audio, 32000)

        ingestor = LocalFolderPAMIngestor(data_dir=tmp_path)
        records = ingestor.ingest()
        print(f"[OK] Ingestadas {len(records)} grabaciones.")

        train_recs, val_recs, test_recs = grouped_stratified_split_dataset(records, train_ratio=0.5, val_ratio=0.5, test_ratio=0.0)
        print(f"[OK] Split completado: {len(train_recs)} train, {len(val_recs)} val")

        label_to_idx = {rec.clase: i for i, rec in enumerate(records)}
        dataset = GenericAudioDataset(train_recs, audio_cfg, label_to_idx=label_to_idx, is_train=False)
        melspec, label = dataset[0]
        print(f"[OK] Tensor extraído desde GenericAudioDataset: Forma Melspec={melspec.shape}, Label={label}")

        print("\n=== 3. Exportando Model Bundle ===")
        checkpoints_dir = tmp_path / "checkpoints"
        exporter = BundleExporter(output_dir=checkpoints_dir)
        
        manifest = ModelManifest(
            model_id="patagonian-birds-resnet34",
            name="Patagonian Birds ResNet34",
            version="1.0.0",
            architecture="resnet34d",
            labels=["Turdus_falklandii", "Sephanoides_sephaniodes"],
            audio_config=audio_cfg,
            num_classes=2,
        )
        
        # Modelo dummy simple con weights
        dummy_weights = {"dummy_layer.weight": torch.randn(2, 64)}
        bundle_path = exporter.export(manifest, dummy_weights, training_recipe_yaml="dummy: true\n")
        print(f"[OK] Bundle exportado en: {bundle_path}")

        print("\n=== 4. Auto-descubrimiento en ModelRegistry de Serving ===")
        registry = ModelRegistry()
        discovered = discover_and_register_bundles(checkpoints_dir, registry=registry)
        print(f"[OK] Modelos auto-descubiertos e inyectados al catálogo: {discovered}")

        predictor = registry.get("patagonian-birds-resnet34")
        print(f"[OK] Modelo resuelto con éxito desde Registry: {predictor.metadata.nombre} (v{predictor.metadata.version})")

    print("\n>>> ¡TODO EL SUBSISTEMA MODULAR FUNCIONA CORRECTAMENTE! <<<")

if __name__ == "__main__":
    main()
