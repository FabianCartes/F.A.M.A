import sys
import time
import random
from pathlib import Path

# Asegurar que la raíz del proyecto esté en sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from typing import Dict, List, Tuple, Optional, Any, Union
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torchaudio
import timm
from torch.utils.data import Dataset, DataLoader
from tqdm import tqdm

from poc.preprocess import (
    load_and_fix_length,
    extract_mel_spectrogram,
    extract_active_windows,
    compute_rms,
    GPUAudioFrontEnd,
    GPUSpecAugment,
    GeM,
    TARGET_SR,
    DURATION_SECONDS,
)
from poc.split import grouped_stratified_split



def seed_worker(worker_id: int) -> None:
    """
    Inicializa generadores pseudoaleatorios en cada worker de PyTorch.
    Garantiza que random y np.random no repitan secuencias entre workers concurrentes,
    y restringe torch.set_num_threads(1) para prevenir contención de CPU.
    """
    worker_seed = torch.initial_seed() % (2**32)
    np.random.seed(worker_seed)
    random.seed(worker_seed)
    torch.set_num_threads(1)


class AudioDataset(Dataset):
    """
    Dataset avanzado para clasificación bioacústica con soporte para:
    1. Ventaneo Múltiple con VAD: Selecciona ventanas activas descartando silencios.
    2. Data Augmentation a nivel de Audio (on-the-fly): Pitch-shift y ruido gaussiano.
    3. Data Augmentation a nivel de Espectrograma: SpecAugment nativo (Frequency & Time Masking).
    4. Aislamiento estricto: Las transformaciones estocásticas operan ÚNICAMENTE cuando
       is_train=True. Con is_train=False (validación y test) el pipeline es 100% determinista.
    """

    def __init__(
        self,
        df: pd.DataFrame,
        raw_dir: Path,
        label_to_idx: Dict[str, int],
        target_sr: int = TARGET_SR,
        duration_seconds: float = DURATION_SECONDS,
        n_mels: int = 64,
        is_train: bool = False,
        time_shift_prob: float = 0.5,
        max_time_shift_seconds: float = 0.5,
        gain_prob: float = 0.5,
        gain_range: Tuple[float, float] = (0.8, 1.2),
        noise_prob: float = 0.5,
        noise_factor_range: Tuple[float, float] = (0.002, 0.010),
        spec_augment_prob: float = 0.5,
        freq_mask_param: int = 8,
        time_mask_param: int = 16,
        windows_cache: Optional[Dict[int, List[np.ndarray]]] = None,
        pitch_shift_prob: float = 0.0,
        pitch_shift_range: Tuple[float, float] = (-1.5, 1.5),
        return_raw_waveform: bool = False,
    ):
        self.df = df.reset_index(drop=True)
        self.raw_dir = Path(raw_dir)
        self.label_to_idx = label_to_idx
        self.target_sr = target_sr
        self.duration_seconds = duration_seconds
        self.n_mels = n_mels
        self.is_train = is_train
        self.return_raw_waveform = return_raw_waveform

        # Parámetros de Data Augmentation seguros en memoria O(1)
        self.time_shift_prob = time_shift_prob
        self.max_time_shift_seconds = max_time_shift_seconds
        self.gain_prob = gain_prob
        self.gain_range = gain_range
        self.noise_prob = noise_prob
        self.noise_factor_range = noise_factor_range
        self.spec_augment_prob = spec_augment_prob
        self.pitch_shift_prob = pitch_shift_prob
        self.pitch_shift_range = pitch_shift_range

        # Transformaciones nativas de SpecAugment
        self.freq_mask = torchaudio.transforms.FrequencyMasking(freq_mask_param=freq_mask_param)
        self.time_mask = torchaudio.transforms.TimeMasking(time_mask_param=time_mask_param)

        # Caché de ventanas activas precalculadas (solo lectura para multiprocesamiento seguro)
        self._windows_cache: Dict[int, List[np.ndarray]] = windows_cache if windows_cache is not None else {}

    def __len__(self) -> int:
        return len(self.df)

    def _resolve_file_path(self, row: pd.Series) -> Path:
        clase = str(row.get("clase", ""))
        species_slug = clase.lower().replace(" ", "_").replace("/", "_")
        filename = str(row.get("nombre_archivo", ""))
        xc_id = str(row.get("xc_id", ""))
        stem = Path(filename).stem

        # Búsqueda con prioridad para archivos saneados (.wav)
        candidates = [
            self.raw_dir / species_slug / f"{stem}.wav",
            self.raw_dir / species_slug / f"{xc_id}.wav",
            self.raw_dir.parent / "processed_wav" / species_slug / f"{stem}.wav",
            self.raw_dir.parent / "processed_wav" / species_slug / f"{xc_id}.wav",
            self.raw_dir / species_slug / filename,
            self.raw_dir / species_slug / f"{xc_id}.mp3",
            self.raw_dir / f"{stem}.wav",
            self.raw_dir / filename,
        ]

        for cand in candidates:
            if cand.exists():
                return cand

        return candidates[4]  # fallback a candidate1 original

    def _get_active_window(self, idx: int, file_path: Path) -> np.ndarray:
        """Obtiene una ventana activa usando VAD con caché en RAM; aleatoria en train, determinista en eval."""
        if idx in self._windows_cache:
            windows = self._windows_cache[idx]
        else:
            if not file_path.exists():
                target_samples = int(self.target_sr * self.duration_seconds)
                windows = [np.zeros(target_samples, dtype=np.float32)]
            else:
                try:
                    windows = extract_active_windows(
                        file_path,
                        target_sr=self.target_sr,
                        duration_seconds=self.duration_seconds,
                        hop_seconds=2.5,
                        top_db=25.0,
                    )
                    if not windows:
                        windows = [load_and_fix_length(file_path, self.target_sr, self.duration_seconds)]
                except Exception:
                    windows = [load_and_fix_length(file_path, self.target_sr, self.duration_seconds)]

        if self.is_train:
            # Muestreo estocástico entre las ventanas activas encontradas
            return random.choice(windows)
        else:
            # Determinista: Seleccionar la ventana con máxima energía acústica
            best_idx = int(np.argmax([compute_rms(w) for w in windows]))
            return windows[best_idx]

    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, torch.Tensor]:
        row = self.df.iloc[idx]
        file_path = self._resolve_file_path(row)

        # 1. Obtener ventana activa con VAD (utiliza caché en RAM si fue provista)
        waveform = self._get_active_window(idx, file_path)

        # 2. Data Augmentation a nivel de Audio (Waveform) - SOLO en entrenamiento
        if self.is_train:
            # 2a. Desplazamiento Temporal (Time Shift con zero-padding para evitar clics de fase)
            if random.random() < self.time_shift_prob:
                max_shift_samples = int(self.target_sr * self.max_time_shift_seconds)
                shift = random.randint(-max_shift_samples, max_shift_samples)
                if shift != 0:
                    shifted = np.zeros_like(waveform)
                    if shift > 0:
                        shifted[shift:] = waveform[:-shift]
                    else:
                        shifted[:shift] = waveform[-shift:]
                    waveform = shifted

            # 2b. Ganancia Aleatoria (Random Gain ANTES del ruido para modular SNR real)
            if random.random() < self.gain_prob:
                gain = random.uniform(*self.gain_range)
                waveform = (waveform * gain).astype(np.float32)

            # 2c. Adición de Ruido Blanco / Fondo
            if random.random() < self.noise_prob:
                noise_factor = random.uniform(*self.noise_factor_range)
                noise = np.random.randn(*waveform.shape).astype(np.float32) * noise_factor
                waveform = waveform + noise

        # Si return_raw_waveform está habilitado, omitir extracción de Mel en CPU
        if self.return_raw_waveform:
            label_str = str(row["clase"])
            label_idx = self.label_to_idx.get(label_str, 0)
            label_tensor = torch.tensor(label_idx, dtype=torch.long)
            return torch.from_numpy(np.ascontiguousarray(waveform)).float(), label_tensor

        # 3. Extracción de Espectrograma Mel y Normalización Estándar
        try:
            mel = extract_mel_spectrogram(
                waveform, sr=self.target_sr, n_mels=self.n_mels
            )
            mel_mean = float(np.mean(mel))
            mel_std = float(np.std(mel))
            mel = (mel - mel_mean) / (mel_std + 1e-6)
        except Exception:
            mel = np.zeros((self.n_mels, 216), dtype=np.float32)

        mel_tensor = torch.from_numpy(mel).unsqueeze(0).float()

        # 4. Data Augmentation a nivel de Espectrograma (SpecAugment) - SOLO en entrenamiento
        if self.is_train and random.random() < self.spec_augment_prob:
            mel_tensor = self.freq_mask(mel_tensor)
            mel_tensor = self.time_mask(mel_tensor)

        label_str = str(row["clase"])
        label_idx = self.label_to_idx.get(label_str, 0)
        label_tensor = torch.tensor(label_idx, dtype=torch.long)

        return mel_tensor, label_tensor


class AudioCNN(nn.Module):
    """
    Arquitectura CNN baseline (3 bloques convolucionales) para clasificación bioacústica.
    Compacta, diseñada para ejecución rápida en nodos locales y CPU.
    """

    def __init__(self, num_classes: int, in_channels: int = 1):
        super().__init__()

        self.features = nn.Sequential(
            # Bloque 1
            nn.Conv2d(in_channels, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=2, stride=2),
            # Bloque 2
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=2, stride=2),
            # Bloque 3
            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((4, 4)),
        )

        self.classifier = nn.Sequential(
            nn.Dropout(0.3),
            nn.Linear(128 * 4 * 4, 128),
            nn.ReLU(inplace=True),
            nn.Linear(128, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.features(x)
        x = torch.flatten(x, 1)
        x = self.classifier(x)
        return x


class FocalLoss(nn.Module):
    """
    Focal Loss para clasificación multiclase.
    FL(p_t) = -alpha_t * (1 - p_t)^gamma * log(p_t)
    Donde gamma modula la pérdida para penalizar fuertemente ejemplos confusos/difíciles
    y atenuar el gradiente en clases ya resueltas con alta confianza.
    """

    def __init__(
        self,
        gamma: float = 2.0,
        alpha: Optional[Union[float, torch.Tensor]] = None,
        reduction: str = "mean",
    ):
        super().__init__()
        self.gamma = gamma
        self.alpha = alpha
        self.reduction = reduction

    def forward(self, inputs: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        ce_loss = nn.functional.cross_entropy(inputs, targets, reduction="none")
        pt = torch.exp(-ce_loss)
        focal_loss = ((1.0 - pt) ** self.gamma) * ce_loss

        if self.alpha is not None:
            if isinstance(self.alpha, (float, int)):
                focal_loss = self.alpha * focal_loss
            elif isinstance(self.alpha, torch.Tensor):
                alpha_t = self.alpha.to(inputs.device)[targets]
                focal_loss = alpha_t * focal_loss

        if self.reduction == "mean":
            return focal_loss.mean()
        elif self.reduction == "sum":
            return focal_loss.sum()
        return focal_loss


class BioacousticModel(nn.Module):
    """
    Arquitectura de clasificación bioacústica profunda basada en timm (EfficientNet, ConvNeXt, etc.).
    Soporta opcionalmente extracción directa de espectrogramas Mel en GPU si se reciben
    formas de onda crudas [B, T], o procesa directamente tensores Mel [B, 1, Mels, T].
    """

    def __init__(
        self,
        model_name: str = "efficientnet_b0",
        num_classes: int = 15,
        pretrained: bool = True,
        in_chans: int = 1,
        drop_rate: float = 0.3,
        use_gpu_frontend: bool = False,
        pool_type: str = "gem",
    ):
        super().__init__()
        self.model_name = model_name
        self.num_classes = num_classes
        self.use_gpu_frontend = use_gpu_frontend
        self.pool_type = pool_type.lower() if pool_type else "avg"

        if use_gpu_frontend:
            self.frontend = GPUAudioFrontEnd(n_mels=128, f_min=800.0, f_max=10000.0)
        else:
            self.frontend = None

        self.backbone = timm.create_model(
            model_name,
            pretrained=pretrained,
            in_chans=in_chans,
            drop_rate=drop_rate,
            num_classes=num_classes,
        )

        if self.pool_type == "gem":
            if hasattr(self.backbone, "global_pool") and getattr(self.backbone, "global_pool") is not None:
                self.backbone.global_pool = GeM(p=3.0, flatten=True)
            elif hasattr(self.backbone, "head") and hasattr(self.backbone.head, "global_pool"):
                self.backbone.head.global_pool = GeM(p=3.0, flatten=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if x.ndim in (1, 2) or (x.ndim == 3 and x.shape[1] == 1):
            if self.frontend is None:
                self.frontend = GPUAudioFrontEnd(n_mels=128, f_min=800.0, f_max=10000.0).to(x.device)
            x = self.frontend(x)
        return self.backbone(x)

    def freeze_backbone(self) -> None:
        """Congela los parámetros del extractor convolucional para la fase de Warmup."""
        for param in self.backbone.parameters():
            param.requires_grad = False
        classifier = self.backbone.get_classifier() if hasattr(self.backbone, "get_classifier") else None
        if isinstance(classifier, nn.Module):
            for param in classifier.parameters():
                param.requires_grad = True
        elif hasattr(self.backbone, "head") and hasattr(self.backbone.head, "fc"):
            for param in self.backbone.head.fc.parameters():
                param.requires_grad = True
        elif hasattr(self.backbone, "classifier"):
            for param in self.backbone.classifier.parameters():
                param.requires_grad = True
        elif hasattr(self.backbone, "fc"):
            for param in self.backbone.fc.parameters():
                param.requires_grad = True

    def unfreeze_backbone(self) -> None:
        """Descongela todos los parámetros del backbone para la fase de Fine-Tuning."""
        for param in self.backbone.parameters():
            param.requires_grad = True


# Alias para retrocompatibilidad 100% con pipelines existentes
BioacousticEfficientNet = BioacousticModel



def apply_mixup(
    x: torch.Tensor,
    y: torch.Tensor,
    alpha: float = 0.2,
    prob: float = 0.5,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, float]:
    """
    Aplica Mixup Aditivo Espectral en GPU.
    Combina convexamente pares de espectrogramas y sus etiquetas:
        x_mix = lam * x + (1 - lam) * x[perm]
    Aplica simetrización lam = max(lam, 1.0 - lam) asegurando que lam >= 0.5,
    garantizando que la etiqueta principal y_a mantenga la mayor ponderación.
    Respeta prob=0.0 o alpha <= 0.0 devolviendo lam=1.0 y tensores intactos.
    """
    if prob <= 0.0 or alpha <= 0.0 or random.random() > prob or x.size(0) <= 1:
        return x, y, y, 1.0

    lam = float(np.random.beta(alpha, alpha))
    lam = max(lam, 1.0 - lam)

    batch_size = x.size(0)
    perm = torch.randperm(batch_size, device=x.device)

    x_mix = lam * x + (1.0 - lam) * x[perm]
    y_a = y
    y_b = y[perm.to(y.device)]

    return x_mix, y_a, y_b, lam


def train_one_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
    epoch: Optional[int] = None,
    total_epochs: Optional[int] = None,
    show_progress: bool = True,
    mixup_alpha: float = 0.0,
    mixup_prob: float = 0.0,
    frontend: Optional[nn.Module] = None,
    spec_augment: Optional[nn.Module] = None,
) -> Tuple[float, float]:
    """Entrena una época completa y retorna (loss_promedio, accuracy)."""
    model.train()
    total_loss = 0.0
    correct = 0
    total_samples = 0

    if show_progress:
        desc = (
            f"Época [{epoch:02d}/{total_epochs:02d}]"
            if epoch is not None and total_epochs is not None
            else "Entrenando"
        )
        iterator = tqdm(loader, desc=desc, leave=False)
    else:
        iterator = loader

    for x_batch, y_batch in iterator:
        x_batch = x_batch.to(device, non_blocking=True)
        y_batch = y_batch.to(device, non_blocking=True)

        if frontend is not None and (x_batch.ndim <= 2 or (x_batch.ndim == 3 and x_batch.shape[1] == 1)):
            x_batch = frontend(x_batch)

        if spec_augment is not None:
            x_batch = spec_augment(x_batch)

        optimizer.zero_grad()

        if mixup_alpha > 0.0 and mixup_prob > 0.0:
            x_batch, y_a, y_b, lam = apply_mixup(
                x_batch, y_batch, alpha=mixup_alpha, prob=mixup_prob
            )
            outputs = model(x_batch)
            if lam < 1.0:
                loss = lam * criterion(outputs, y_a) + (1.0 - lam) * criterion(outputs, y_b)
            else:
                loss = criterion(outputs, y_a)
            _, preds = torch.max(outputs, 1)
            batch_correct = torch.sum(preds == y_a).item()
        else:
            outputs = model(x_batch)
            loss = criterion(outputs, y_batch)
            _, preds = torch.max(outputs, 1)
            batch_correct = torch.sum(preds == y_batch).item()

        loss.backward()
        optimizer.step()

        batch_size = x_batch.size(0)
        total_loss += loss.item() * batch_size
        correct += batch_correct
        total_samples += batch_size

        if show_progress and hasattr(iterator, "set_postfix"):
            iterator.set_postfix({
                "loss": f"{loss.item():.4f}",
                "acc": f"{(batch_correct / max(1, batch_size)) * 100:.1f}%",
            })

    avg_loss = total_loss / max(1, total_samples)
    accuracy = correct / max(1, total_samples)
    return avg_loss, accuracy


def evaluate_loss_acc(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
    frontend: Optional[nn.Module] = None,
) -> Tuple[float, float]:
    """Evalúa un conjunto (val o test) y retorna (loss_promedio, accuracy)."""
    model.eval()
    total_loss = 0.0
    correct = 0
    total_samples = 0

    with torch.no_grad():
        for x_batch, y_batch in loader:
            x_batch = x_batch.to(device, non_blocking=True)
            y_batch = y_batch.to(device, non_blocking=True)

            if frontend is not None and (x_batch.ndim <= 2 or (x_batch.ndim == 3 and x_batch.shape[1] == 1)):
                x_batch = frontend(x_batch)

            outputs = model(x_batch)
            loss = criterion(outputs, y_batch)

            batch_size = x_batch.size(0)
            total_loss += loss.item() * batch_size
            _, preds = torch.max(outputs, 1)
            correct += torch.sum(preds == y_batch).item()
            total_samples += batch_size

    avg_loss = total_loss / max(1, total_samples)
    accuracy = correct / max(1, total_samples)
    return avg_loss, accuracy


def build_dataloaders(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    raw_dir: Path,
    label_to_idx: Dict[str, int],
    batch_size: int = 16,
    num_workers: int = 4,
    pin_memory: Optional[bool] = None,
    device: Optional[torch.device] = None,
    train_windows_cache: Optional[Dict[int, List[np.ndarray]]] = None,
    val_windows_cache: Optional[Dict[int, List[np.ndarray]]] = None,
    n_mels: int = 64,
    return_raw_waveform: bool = False,
) -> Tuple[DataLoader, DataLoader]:
    """
    Factoría desacoplada para construir DataLoaders concurrentes y seguros para multiprocesamiento.
    - Aplica worker_init_fn para evitar duplicación de semillas de data augmentation en workers forked.
    - Configura pin_memory dinámicamente según la presencia de aceleración CUDA.
    - Habilita persistent_workers cuando num_workers > 0 para eliminar la latencia de re-creación de procesos.
    """
    if pin_memory is None:
        if device is not None:
            pin_memory = (device.type == "cuda")
        else:
            pin_memory = torch.cuda.is_available()

    train_ds = AudioDataset(
        train_df,
        raw_dir,
        label_to_idx,
        n_mels=n_mels,
        is_train=True,
        windows_cache=train_windows_cache,
        return_raw_waveform=return_raw_waveform,
    )
    val_ds = AudioDataset(
        val_df,
        raw_dir,
        label_to_idx,
        n_mels=n_mels,
        is_train=False,
        windows_cache=val_windows_cache,
        return_raw_waveform=return_raw_waveform,
    )

    generator = torch.Generator()
    generator.manual_seed(42)

    train_loader = DataLoader(
        train_ds,
        batch_size=batch_size,
        shuffle=True,
        drop_last=False,
        num_workers=num_workers,
        pin_memory=pin_memory,
        worker_init_fn=seed_worker if num_workers > 0 else None,
        generator=generator,
        persistent_workers=(num_workers > 0),
    )

    val_loader = DataLoader(
        val_ds,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        pin_memory=pin_memory,
        worker_init_fn=seed_worker if num_workers > 0 else None,
        persistent_workers=(num_workers > 0),
    )

    return train_loader, val_loader


def train_pipeline(
    metadata_csv: Path,
    raw_dir: Path,
    checkpoint_dir: Path,
    epochs: int = 15,
    batch_size: int = 16,
    lr: float = 1e-3,
    num_workers: int = 4,
    device: Optional[str] = None,
    checkpoint_name: str = "augmented_best.pt",
    seed: Optional[int] = None,
    model_type: str = "efficientnet_b0",
    loss_type: str = "focal",
    focal_gamma: float = 2.0,
    warmup_epochs: int = 3,
    n_mels: int = 128,
    mixup_alpha: float = 0.2,
    mixup_prob: float = 0.5,
    pitch_shift_bins: int = 2,
    pitch_shift_prob: float = 0.3,
    pool_type: str = "gem",
) -> Dict[str, Any]:
    """
    Ejecuta el ciclo de entrenamiento completo:
    1. Carga particiones o genera split agrupado y estratificado.
    2. Configura AudioDataset con Data Augmentation en Train y Determinismo en Val.
    3. Construye DataLoaders concurrentes con multiprocesamiento y memoria fijada.
    4. Entrena el modelo (EfficientNet o AudioCNN) registrando loss y accuracy por época con Mixup opcional.
    5. Guarda el mejor checkpoint en checkpoints/<checkpoint_name>.
    """
    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)

    if device is None:
        device_obj = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        device_obj = torch.device(device)

    print(f"\nIniciando entrenamiento en dispositivo: {device_obj}")

    data_dir = metadata_csv.parent
    train_file = data_dir / "train.csv"
    val_file = data_dir / "val.csv"
    test_file = data_dir / "test.csv"

    if train_file.exists() and val_file.exists() and test_file.exists():
        print("Cargando particiones existentes (train.csv, val.csv, test.csv)...")
        train_df = pd.read_csv(train_file)
        val_df = pd.read_csv(val_file)
        test_df = pd.read_csv(test_file)
    else:
        df = pd.read_csv(metadata_csv)
        def _exists(row):
            sp_slug = str(row["clase"]).lower().replace(" ", "_").replace("/", "_")
            f1 = raw_dir / sp_slug / str(row["nombre_archivo"])
            f2 = raw_dir / sp_slug / f"{row['xc_id']}.mp3"
            return f1.exists() or f2.exists()

        df = df[df.apply(_exists, axis=1)].reset_index(drop=True)
        train_df, val_df, test_df = grouped_stratified_split(df)
        train_df.to_csv(train_file, index=False)
        val_df.to_csv(val_file, index=False)
        test_df.to_csv(test_file, index=False)

    print(f"Split cargado -> Train: {len(train_df)}, Val: {len(val_df)}, Test: {len(test_df)}")

    classes = sorted(train_df["clase"].unique())
    label_to_idx = {c: i for i, c in enumerate(classes)}
    idx_to_label = {i: c for c, i in label_to_idx.items()}

    # Construcción concurrente y segura de DataLoaders (Productor-Consumidor)
    train_loader, val_loader = build_dataloaders(
        train_df=train_df,
        val_df=val_df,
        raw_dir=raw_dir,
        label_to_idx=label_to_idx,
        batch_size=batch_size,
        num_workers=num_workers,
        device=device_obj,
        n_mels=n_mels,
        return_raw_waveform=True,
    )

    frontend = GPUAudioFrontEnd(n_mels=n_mels, normalize=True).to(device_obj)
    spec_augment = GPUSpecAugment(
        freq_mask_param=8,
        time_mask_param=16,
        prob=0.5,
        pitch_shift_max_bins=pitch_shift_bins,
        pitch_shift_prob=pitch_shift_prob,
    ).to(device_obj)

    is_cnn = model_type.lower() in ("audiocnn", "cnn")
    if is_cnn:
        model = AudioCNN(num_classes=len(classes)).to(device_obj)
        optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    else:
        model = BioacousticModel(
            model_name=model_type,
            num_classes=len(classes),
            pretrained=True,
            pool_type=pool_type,
        ).to(device_obj)

        if warmup_epochs > 0:
            print(f"Configurando Warmup: backbone congelado durante las primeras {warmup_epochs} épocas...")
            model.freeze_backbone()
            optimizer = torch.optim.Adam(
                filter(lambda p: p.requires_grad, model.parameters()),
                lr=lr,
            )
        else:
            optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-2)

    if loss_type.lower() == "focal":
        criterion = FocalLoss(gamma=focal_gamma)
    else:
        criterion = nn.CrossEntropyLoss()

    checkpoint_dir = Path(checkpoint_dir)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    best_checkpoint_path = checkpoint_dir / checkpoint_name

    history: Dict[str, List[float]] = {
        "train_loss": [],
        "train_acc": [],
        "val_loss": [],
        "val_acc": [],
    }

    best_val_acc = -1.0

    print(f"\nIniciando entrenamiento con {model.__class__.__name__} ({model_type}) | Loss: {criterion.__class__.__name__} | Mels: {n_mels} | Mixup: alpha={mixup_alpha}, prob={mixup_prob}...", flush=True)
    for epoch in range(1, epochs + 1):
        if not is_cnn and warmup_epochs > 0 and epoch == warmup_epochs + 1:
            print("\n>>> [Warmup finalizado] Descongelando backbone para Fine-Tuning con AdamW...", flush=True)
            model.unfreeze_backbone()
            optimizer = torch.optim.AdamW(model.parameters(), lr=lr * 0.1, weight_decay=1e-2)

        t_epoch_start = time.time()
        tr_loss, tr_acc = train_one_epoch(
            model,
            train_loader,
            criterion,
            optimizer,
            device_obj,
            epoch=epoch,
            total_epochs=epochs,
            show_progress=True,
            mixup_alpha=mixup_alpha,
            mixup_prob=mixup_prob,
            frontend=frontend,
            spec_augment=spec_augment,
        )
        v_loss, v_acc = evaluate_loss_acc(
            model,
            val_loader,
            criterion,
            device_obj,
            frontend=frontend,
        )
        epoch_sec = time.time() - t_epoch_start

        history["train_loss"].append(tr_loss)
        history["train_acc"].append(tr_acc)
        history["val_loss"].append(v_loss)
        history["val_acc"].append(v_acc)

        print(
            f"Época [{epoch:02d}/{epochs:02d}] ({epoch_sec:.2f}s) "
            f"Train Loss: {tr_loss:.4f} | Train Acc: {tr_acc * 100:.2f}% "
            f"|| Val Loss: {v_loss:.4f} | Val Acc: {v_acc * 100:.2f}%",
            flush=True,
        )

        if v_acc > best_val_acc:
            best_val_acc = v_acc
            torch.save(
                {
                    "epoch": epoch,
                    "model_type": model_type,
                    "pool_type": pool_type,
                    "n_mels": n_mels,
                    "mixup_alpha": mixup_alpha,
                    "mixup_prob": mixup_prob,
                    "pitch_shift_bins": pitch_shift_bins,
                    "pitch_shift_prob": pitch_shift_prob,
                    "model_state_dict": model.state_dict(),
                    "optimizer_state_dict": optimizer.state_dict(),
                    "val_acc": v_acc,
                    "val_loss": v_loss,
                    "classes": classes,
                    "label_to_idx": label_to_idx,
                    "idx_to_label": idx_to_label,
                },
                best_checkpoint_path,
            )
            print(f"  -> Nuevo mejor modelo guardado en {best_checkpoint_path} (Val Acc: {v_acc * 100:.2f}%)", flush=True)

    return {
        "history": history,
        "classes": classes,
        "label_to_idx": label_to_idx,
        "idx_to_label": idx_to_label,
        "best_checkpoint_path": str(best_checkpoint_path),
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Entrenar modelo bioacústico F.A.M.A.")
    parser.add_argument("--epochs", type=int, default=15, help="Número de épocas de entrenamiento")
    parser.add_argument("--batch-size", type=int, default=16, help="Tamaño del lote")
    parser.add_argument("--lr", type=float, default=1e-3, help="Learning rate")
    parser.add_argument("--workers", type=int, default=4, help="Workers concurrentes para DataLoader")
    parser.add_argument("--device", type=str, default=None, help="Dispositivo (cuda o cpu)")
    parser.add_argument("--checkpoint-name", type=str, default="augmented_best.pt", help="Nombre del checkpoint de salida")
    parser.add_argument("--model-type", type=str, default="efficientnet_b0", help="Arquitectura del modelo (efficientnet_b0 o audiocnn)")
    parser.add_argument("--pool-type", type=str, default="gem", choices=["gem", "avg"], help="Tipo de pooling global para EfficientNet (gem o avg)")
    parser.add_argument("--loss-type", type=str, default="focal", help="Función de pérdida (focal o ce)")
    parser.add_argument("--gamma", type=float, default=2.0, help="Parámetro gamma de Focal Loss")
    parser.add_argument("--warmup-epochs", type=int, default=3, help="Épocas de warmup con backbone congelado")
    parser.add_argument("--n-mels", type=int, default=128, help="Cantidad de bandas Mel")
    parser.add_argument("--mixup-alpha", type=float, default=0.2, help="Parámetro alpha para distribución Beta en Mixup")
    parser.add_argument("--mixup-prob", type=float, default=0.5, help="Probabilidad de aplicar Mixup por batch en entrenamiento")
    parser.add_argument("--pitch-shift-bins", type=int, default=2, help="Cantidad máxima de bins Mel para Pitch Shift espectral")
    parser.add_argument("--pitch-shift-prob", type=float, default=0.3, help="Probabilidad de aplicar Pitch Shift espectral por muestra")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    repo_root = project_root if (project_root / "data").exists() else project_root.parent
    train_pipeline(
        metadata_csv=repo_root / "data" / "metadata.csv",
        raw_dir=repo_root / "data" / "raw",
        checkpoint_dir=repo_root / "checkpoints",
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        num_workers=args.workers,
        device=args.device,
        checkpoint_name=args.checkpoint_name,
        model_type=args.model_type,
        pool_type=args.pool_type,
        loss_type=args.loss_type,
        focal_gamma=args.gamma,
        warmup_epochs=args.warmup_epochs,
        n_mels=args.n_mels,
        mixup_alpha=args.mixup_alpha,
        mixup_prob=args.mixup_prob,
        pitch_shift_bins=args.pitch_shift_bins,
        pitch_shift_prob=args.pitch_shift_prob,
    )

