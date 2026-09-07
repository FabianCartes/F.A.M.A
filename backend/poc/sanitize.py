import os
import sys
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional
from concurrent.futures import ProcessPoolExecutor
import numpy as np
import soundfile as sf
import librosa
from tqdm import tqdm


def sanitize_audio_file(
    src: Path,
    dst: Path,
    target_sr: int = 22050,
    min_duration_sec: float = 0.1,
) -> bool:
    """
    Decodifica un archivo de audio crudo (MP3/WAV) y lo re-codifica a formato WAV estándar
    (PCM_16, mono, target_sr).
    - Silencia y aísla advertencias de bajo nivel de libmpg123 en C.
    - Valida que el archivo no esté vacío o corrupto más allá de su recuperación.
    - Crea directorios de destino si no existen.
    """
    src = Path(src)
    dst = Path(dst)

    if not src.exists() or src.stat().st_size == 0:
        return False

    # Redirigir temporalmente fd 2 (stderr en C) para aislar advertencias de libmpg123
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8", errors="ignore") as tmp:
        old_stderr = os.dup(2)
        os.dup2(tmp.fileno(), 2)
        try:
            y, sr = librosa.load(str(src), sr=target_sr, mono=True)
        except Exception:
            y = None
        finally:
            os.dup2(old_stderr, 2)
            os.close(old_stderr)

    if y is None or len(y) == 0:
        return False

    duration = len(y) / target_sr
    if duration < min_duration_sec:
        return False

    # Asegurar rango dinámico en [-1.0, 1.0] para evitar clipping en PCM_16
    peak = np.max(np.abs(y))
    if peak > 1.0:
        y = y / peak

    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        sf.write(str(dst), y, target_sr, subtype="PCM_16")
        return True
    except Exception:
        if dst.exists():
            dst.unlink()
        return False


def _sanitize_worker_task(args):
    src_str, dst_str, target_sr = args
    success = sanitize_audio_file(Path(src_str), Path(dst_str), target_sr=target_sr)
    return success


def sanitize_dataset(
    raw_dir: Path,
    output_dir: Path,
    target_sr: int = 22050,
    num_workers: int = 4,
    show_progress: bool = False,
) -> Dict[str, Any]:
    """
    Sanea por lotes concurrentes todos los archivos de audio en raw_dir,
    replicando la estructura jerárquica de especies en output_dir como archivos WAV PCM_16.
    """
    raw_dir = Path(raw_dir)
    output_dir = Path(output_dir)

    all_files = sorted([
        p for p in raw_dir.glob("**/*")
        if p.is_file() and p.suffix.lower() in [".mp3", ".wav", ".ogg", ".flac"]
    ])

    tasks = []
    for src in all_files:
        rel_path = src.relative_to(raw_dir)
        dst = output_dir / rel_path.with_suffix(".wav")
        tasks.append((str(src), str(dst), target_sr))

    total = len(tasks)
    converted = 0
    failed = 0

    if total == 0:
        return {
            "total": 0,
            "converted": 0,
            "failed": 0,
            "output_dir": str(output_dir),
        }

    if num_workers > 1 and total > 1:
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            iterator = executor.map(_sanitize_worker_task, tasks)
            if show_progress:
                iterator = tqdm(iterator, total=total, desc="Saneando dataset a WAV")
            for success in iterator:
                if success:
                    converted += 1
                else:
                    failed += 1
    else:
        iterator = tasks
        if show_progress:
            iterator = tqdm(tasks, desc="Saneando dataset a WAV")
        for t in iterator:
            if _sanitize_worker_task(t):
                converted += 1
            else:
                failed += 1

    return {
        "total": total,
        "converted": converted,
        "failed": failed,
        "output_dir": str(output_dir),
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Sanitizar dataset MP3 a WAV PCM_16 estándar")
    parser.add_argument("--raw-dir", type=str, default="data/raw", help="Directorio de audios crudos")
    parser.add_argument("--output-dir", type=str, default="data/processed_wav", help="Directorio de destino WAV")
    parser.add_argument("--sr", type=int, default=22050, help="Frecuencia de muestreo")
    parser.add_argument("--workers", type=int, default=4, help="Número de workers concurrentes")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    raw_path = project_root / args.raw_dir
    out_path = project_root / args.output_dir

    print(f"Iniciando saneamiento de {raw_path} -> {out_path}...")
    stats = sanitize_dataset(raw_path, out_path, target_sr=args.sr, num_workers=args.workers, show_progress=True)
    print("\n=======================================================")
    print("RESUMEN DE SANEAMIENTO DE AUDIO")
    print("=======================================================")
    print(f"Total analizados:   {stats['total']}")
    print(f"Exitosos (.wav):    {stats['converted']}")
    print(f"Fallidos:           {stats['failed']}")
    print(f"Destino:            {stats['output_dir']}")
    print("=======================================================")
