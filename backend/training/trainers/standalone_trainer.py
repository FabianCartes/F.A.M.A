"""
backend/training/trainers/standalone_trainer.py
Entrenador desacoplado y parametrizado por TrainingConfig.
Ejecuta el ciclo de entrenamiento, optimización, cálculo de métricas y exportación a Model Bundle.
"""
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional
import time
import yaml
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
import pandas as pd
import numpy as np
from sklearn.metrics import accuracy_score, precision_recall_fscore_support

from training.schemas.config import TrainingConfig
from training.pipelines.dataset import GenericAudioDataset
from training.exporters.bundle_exporter import BundleExporter
from poc.preprocess import GPUAudioFrontEnd, GPUSpecAugment
from poc.train import BioacousticModel, FocalLoss, apply_mixup, seed_worker


class GenericModelTrainer:
    """
    Entrenador desacoplado para arquitecturas bioacústicas / acústicas generales.
    """

    def __init__(self, config: TrainingConfig, project_root: Optional[Path] = None):
        self.config = config
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self.device = torch.device(
            config.device if config.device and torch.cuda.is_available() else "cpu"
        )

    def train_and_export(
        self,
        train_df: pd.DataFrame,
        val_df: pd.DataFrame,
        test_df: pd.DataFrame,
        output_checkpoints_dir: Path,
        verbose: bool = True,
    ) -> Tuple[Path, Dict[str, Any]]:
        """
        Ejecuta el ciclo completo de entrenamiento y exporta el Model Bundle.
        """
        classes = sorted(train_df["clase"].unique().tolist())
        num_classes = len(classes)
        label_to_idx = {c: i for i, c in enumerate(classes)}

        # Mitigación opcional de desbalance severo mediante sub-muestreo controlado
        if self.config.dataset.max_samples_per_class is not None:
            max_c = self.config.dataset.max_samples_per_class
            balanced_dfs = []
            for _, group in train_df.groupby("clase"):
                if len(group) > max_c:
                    balanced_dfs.append(group.sample(n=max_c, random_state=self.config.seed))
                else:
                    balanced_dfs.append(group)
            train_df = pd.concat(balanced_dfs, ignore_index=True)
            if verbose:
                print(f"[Trainer] Dataset balanceado a max {max_c} muestras/clase (total train: {len(train_df)})")

        # 1. Instanciar Datasets y DataLoaders
        train_dataset = GenericAudioDataset(
            df=train_df,
            audio_config=self.config.audio,
            label_to_idx=label_to_idx,
            augmentation_config=self.config.augmentation,
            is_train=True,
            return_raw_waveform=True,
        )
        val_dataset = GenericAudioDataset(
            df=val_df,
            audio_config=self.config.audio,
            label_to_idx=label_to_idx,
            is_train=False,
            return_raw_waveform=True,
        )
        test_dataset = GenericAudioDataset(
            df=test_df,
            audio_config=self.config.audio,
            label_to_idx=label_to_idx,
            is_train=False,
            return_raw_waveform=True,
        )

        train_loader = DataLoader(
            train_dataset,
            batch_size=self.config.batch_size,
            shuffle=True,
            num_workers=self.config.dataset.num_workers,
            pin_memory=self.config.dataset.pin_memory and self.device.type == "cuda",
            worker_init_fn=seed_worker,
        )
        val_loader = DataLoader(
            val_dataset,
            batch_size=self.config.batch_size,
            shuffle=False,
            num_workers=self.config.dataset.num_workers,
            pin_memory=self.config.dataset.pin_memory and self.device.type == "cuda",
        )
        test_loader = DataLoader(
            test_dataset,
            batch_size=self.config.batch_size,
            shuffle=False,
            num_workers=self.config.dataset.num_workers,
            pin_memory=self.config.dataset.pin_memory and self.device.type == "cuda",
        )

        # 2. Construir Frontend y Modelo en GPU/CPU
        frontend = GPUAudioFrontEnd(
            sample_rate=self.config.audio.target_sr,
            n_fft=self.config.audio.n_fft,
            hop_length=self.config.audio.hop_length,
            n_mels=self.config.audio.n_mels,
            f_min=self.config.audio.f_min,
            f_max=self.config.audio.f_max,
        ).to(self.device)

        spec_augment = GPUSpecAugment(
            freq_mask_param=self.config.augmentation.freq_mask_param,
            time_mask_param=self.config.augmentation.time_mask_param,
            prob=self.config.augmentation.spec_augment_prob,
        ).to(self.device)

        model = BioacousticModel(
            model_name=self.config.architecture.type,
            num_classes=num_classes,
            pretrained=self.config.architecture.pretrained,
            in_chans=self.config.architecture.in_chans,
            drop_rate=self.config.architecture.drop_rate,
            pool_type=self.config.architecture.pool_type,
            use_gpu_frontend=False,  # Manejado externamente en el loop
        ).to(self.device)

        # 3. Función de Coste y Optimizador con Ponderación de Clases
        class_counts = train_df["clase"].value_counts()
        total_samples = len(train_df)
        weights = [total_samples / (num_classes * max(1, class_counts.get(c, 1))) for c in classes]
        alpha_tensor = torch.tensor(weights, dtype=torch.float32, device=self.device)
        alpha_tensor = alpha_tensor / alpha_tensor.mean()

        if self.config.loss.name.value == "focal":
            criterion = FocalLoss(gamma=self.config.loss.gamma, alpha=alpha_tensor)
        else:
            criterion = nn.CrossEntropyLoss(weight=alpha_tensor)

        optimizer = torch.optim.AdamW(
            model.parameters(),
            lr=self.config.optimizer.lr,
            weight_decay=self.config.optimizer.weight_decay,
        )
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
            optimizer, T_max=self.config.epochs, eta_min=1e-6
        )

        best_val_f1 = -1.0
        best_state_dict = None

        if verbose:
            print(f"[Trainer] Iniciando entrenamiento de '{self.config.model_name}' ({self.config.architecture.type})")
            print(f"[Trainer] Dispositivo: {self.device} | Clases: {num_classes} | Épocas: {self.config.epochs}")

        # 4. Ciclo de Entrenamiento
        for epoch in range(1, self.config.epochs + 1):
            t_epoch_start = time.time()
            model.train()
            train_loss = 0.0
            train_correct = 0
            train_samples = 0

            for x_batch, y_batch in train_loader:
                x_batch = x_batch.to(self.device, non_blocking=True)
                y_batch = y_batch.to(self.device, non_blocking=True)

                # Frontend & Augment
                mel_batch = frontend(x_batch)
                mel_batch = spec_augment(mel_batch)

                optimizer.zero_grad()

                if self.config.augmentation.mixup_prob > 0.0:
                    mel_batch, y_a, y_b, lam = apply_mixup(
                        mel_batch,
                        y_batch,
                        alpha=self.config.augmentation.mixup_alpha,
                        prob=self.config.augmentation.mixup_prob,
                    )
                    logits = model(mel_batch)
                    loss = lam * criterion(logits, y_a) + (1.0 - lam) * criterion(logits, y_b)
                    preds = torch.argmax(logits, dim=-1)
                    train_correct += int(torch.sum(preds == y_a).item())
                else:
                    logits = model(mel_batch)
                    loss = criterion(logits, y_batch)
                    preds = torch.argmax(logits, dim=-1)
                    train_correct += int(torch.sum(preds == y_batch).item())

                loss.backward()
                optimizer.step()

                bsz = x_batch.size(0)
                train_loss += float(loss.item()) * bsz
                train_samples += bsz

            scheduler.step()
            train_loss_avg = train_loss / max(1, train_samples)
            train_acc = train_correct / max(1, train_samples)

            # Validación
            val_loss, val_acc, val_f1 = self._evaluate_split(model, val_loader, frontend, criterion)
            epoch_duration = time.time() - t_epoch_start

            if verbose:
                print(
                    f"Época [{epoch:02d}/{self.config.epochs:02d}] ({epoch_duration:.1f}s) | "
                    f"Train Loss: {train_loss_avg:.4f} Acc: {train_acc*100:.1f}% | "
                    f"Val Loss: {val_loss:.4f} Acc: {val_acc*100:.1f}% F1: {val_f1:.4f}"
                )

            if val_f1 > best_val_f1:
                best_val_f1 = val_f1
                best_state_dict = {k: v.cpu() for k, v in model.state_dict().items()}

        # 5. Evaluación Final en Test Set con el Mejor Modelo
        if best_state_dict is not None:
            model.load_state_dict({k: v.to(self.device) for k, v in best_state_dict.items()})

        test_loss, test_acc, test_f1 = self._evaluate_split(model, test_loader, frontend, criterion)
        if verbose:
            print(f"\n[Trainer] Evaluación Test Final: Loss={test_loss:.4f}, Acc={test_acc*100:.2f}%, F1-Macro={test_f1:.4f}")

        metrics = {
            "test_accuracy": round(float(test_acc), 4),
            "test_f1_macro": round(float(test_f1), 4),
            "test_loss": round(float(test_loss), 4),
            "best_val_f1_macro": round(float(best_val_f1), 4),
            "classes_count": num_classes,
        }

        # 6. Exportar Model Bundle
        bundle_path = BundleExporter.export(
            output_dir=output_checkpoints_dir,
            model=model,
            config=self.config,
            classes=classes,
            metrics=metrics,
        )
        if verbose:
            print(f"[Trainer] Model Bundle exportado exitosamente en: {bundle_path}")

        return bundle_path, metrics

    def _evaluate_split(
        self,
        model: nn.Module,
        loader: DataLoader,
        frontend: nn.Module,
        criterion: nn.Module,
    ) -> Tuple[float, float, float]:
        model.eval()
        total_loss = 0.0
        total_samples = 0
        all_preds = []
        all_targets = []

        with torch.no_grad():
            for x_batch, y_batch in loader:
                x_batch = x_batch.to(self.device, non_blocking=True)
                y_batch = y_batch.to(self.device, non_blocking=True)

                mel = frontend(x_batch)
                logits = model(mel)
                loss = criterion(logits, y_batch)

                bsz = x_batch.size(0)
                total_loss += float(loss.item()) * bsz
                total_samples += bsz

                preds = torch.argmax(logits, dim=-1).cpu().numpy()
                targets = y_batch.cpu().numpy()

                all_preds.extend(preds)
                all_targets.extend(targets)

        avg_loss = total_loss / max(1, total_samples)
        acc = float(accuracy_score(all_targets, all_preds))
        _, _, f1_macro, _ = precision_recall_fscore_support(
            all_targets, all_preds, average="macro", zero_division=0
        )
        return avg_loss, acc, float(f1_macro)
