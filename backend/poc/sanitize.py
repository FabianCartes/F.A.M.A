import os
import sys
import tempfile
import io
import stat
import unicodedata
from pathlib import Path
from typing import Dict, Any, Optional
from concurrent.futures import ProcessPoolExecutor
import numpy as np
import pandas as pd
import soundfile as sf
import librosa
from tqdm import tqdm

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from training.paths import get_dataset_roots
from dataset_references import resolve_reference, reference_from_path


def _physical_path(value: Path) -> Path:
    """Validate future paths without erasing symlink/ancestor evidence."""
    text = str(value)
    if (not text.startswith("/") or "\\" in text or ":" in text
            or any(unicodedata.category(c) == "Cc" for c in text)
            or any(p in ("", ".", "..") for p in text[1:].split("/"))):
        raise ValueError("path must be canonical absolute POSIX text")
    path = Path(value)
    for entry in (path, *path.parents):
        try:
            mode = entry.lstat().st_mode
        except FileNotFoundError:
            continue
        except OSError:
            raise ValueError("path ancestors cannot be physically verified") from None
        if stat.S_ISLNK(mode) or (entry != path and not stat.S_ISDIR(mode)):
            raise ValueError("path ancestors must be physical directories without symlinks")
    return path


def sanitize_audio_file(
    src: Path,
    dst: Path,
    target_sr: int = 22050,
    min_duration_sec: float = 0.1,
) -> bool:
    """Decode MP3/WAV to mono PCM_16 WAV; exclusively create the destination.

    Empty/corrupt/short audio returns False. Existing destinations raise ValueError,
    including a file appearing during decoding. A failed write can leave a partial
    file for offline recovery; this utility never removes or adopts existing bytes.
    """
    src = Path(src)
    dst = _physical_path(dst)
    if dst.exists():
        raise ValueError("processed destination already exists")
    if not src.exists() or src.stat().st_size == 0:
        return False

    # Isolate low-level libmpg123 warnings while restoring the original descriptor.
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
    if y is None or len(y) == 0 or len(y) / target_sr < min_duration_sec:
        return False
    peak = np.max(np.abs(y))
    if peak > 1.0:
        y = y / peak
    try:
        encoded = io.BytesIO()
        sf.write(encoded, y, target_sr, format="WAV", subtype="PCM_16")
    except Exception:
        return False
    _physical_path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    # No check-then-truncate: exclusive creation protects late-arriving files too.
    try:
        with dst.open("xb") as output:
            output.write(encoded.getvalue())
        return True
    except FileExistsError:
        raise ValueError("processed destination already exists") from None
    except OSError:
        return False


def _sanitize_worker_task(args):
    src_str, dst_str, target_sr = args
    return sanitize_audio_file(Path(src_str), Path(dst_str), target_sr=target_sr)


def sanitize_dataset(
    raw_dir: Path,
    output_dir: Path,
    target_sr: int = 22050,
    num_workers: int = 4,
    show_progress: bool = False,
    *,
    metadata_index: Path,
    roots: Dict[str, Path],
    output_index: Optional[Path] = None,
) -> Dict[str, Any]:
    """Derive processed WAVs from an explicit canonical raw index, never a scan.

    Preflight every reference/collision/existing output before conversion. Preserve
    original fields, including original-byte hash and acoustic metadata; change
    only file_path/file_stage. No raw index or historical split is rewritten.
    Only successfully verified derivatives enter the separate output index.
    Publication is exclusive per file, NOT atomic across the batch: interruption
    can leave unindexed derivatives requiring offline recovery, never adoption.
    """
    if not {"raw", "processed"}.issubset(roots):
        raise ValueError("raw and processed roots must be explicitly declared")
    raw_dir = _physical_path(raw_dir)
    output_dir = _physical_path(output_dir)
    if raw_dir != _physical_path(roots["raw"]) or output_dir != _physical_path(roots["processed"]):
        raise ValueError("directories must match declared physical roots")
    if not raw_dir.is_dir() or (output_dir.exists() and not output_dir.is_dir()):
        raise ValueError("roots must be physical directories")
    if output_dir.is_relative_to(raw_dir) or raw_dir.is_relative_to(output_dir):
        raise ValueError("raw and processed roots must not overlap")
    metadata_index = _physical_path(metadata_index)
    index = _physical_path(output_index if output_index is not None else output_dir / "metadata.csv")
    if index.exists() or index.is_relative_to(raw_dir) or index == metadata_index:
        raise ValueError("output index already exists or overlaps original data")
    if metadata_index.is_relative_to(output_dir):
        raise ValueError("input index must not overlap processed root")
    frame = pd.read_csv(metadata_index, dtype=str, keep_default_na=False)
    if not {"file_path", "file_stage"}.issubset(frame.columns):
        raise ValueError("canonical file_path and file_stage required; convert legacy offline")
    records = frame.to_dict("records")
    tasks = []
    destinations = set()
    for row in records:
        if row["file_stage"] != "raw":
            raise ValueError("sanitization requires raw-stage input rows")
        src = resolve_reference(row["file_path"], row["file_stage"], roots)
        if src.samefile(metadata_index) or src.stat().st_size == 0:
            raise ValueError("source must be nonempty audio, not its index")
        if src.suffix.lower() not in (".mp3", ".wav", ".ogg", ".flac"):
            raise ValueError("unsupported raw audio extension")
        dst = _physical_path(output_dir / Path(row["file_path"]).with_suffix(".wav"))
        if (dst.exists() or dst.is_relative_to(index) or index.is_relative_to(dst)
                or any(dst.is_relative_to(other) or other.is_relative_to(dst) for other in destinations)):
            raise ValueError("processed destination already exists or collides")
        destinations.add(dst)
        tasks.append((str(src), str(dst), target_sr))

    if num_workers > 1 and len(tasks) > 1:
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            successes = list(executor.map(_sanitize_worker_task, tasks))
    else:
        iterator = tqdm(tasks, desc="Saneando dataset a WAV") if show_progress else tasks
        successes = [_sanitize_worker_task(task) for task in iterator]
    derived = []
    for row, task, success in zip(records, tasks, successes):
        if success:
            dst = Path(task[1])
            reference = reference_from_path(dst, "processed", roots)
            if dst.stat().st_size == 0 or sf.info(dst).frames == 0:
                raise ValueError("processed derivative must be nonempty audio")
            derived.append({**row, **reference})
    if derived:
        _physical_path(index)
        index.parent.mkdir(parents=True, exist_ok=True)
        with index.open("x", encoding="utf-8", newline="") as output:
            pd.DataFrame(derived, columns=frame.columns).to_csv(output, index=False)
    return {"total": len(tasks), "converted": len(derived), "failed": len(tasks) - len(derived),
            "output_dir": str(output_dir)}


def main(argv=None):
    """Bind physical Aves roots at the CLI, with independent index overrides."""
    import argparse
    parser = argparse.ArgumentParser(description="Sanitizar índice raw canónico a WAV PCM_16")
    parser.add_argument("--raw-dir", type=Path, help="Raíz física raw")
    parser.add_argument("--output-dir", type=Path, help="Raíz física processed")
    parser.add_argument("--metadata-index", type=Path, help="Índice raw canónico")
    parser.add_argument("--output-index", type=Path, help="Índice derivado nuevo")
    parser.add_argument("--sr", type=int, default=22050)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)
    defaults = get_dataset_roots("AvesChilenas") if args.raw_dir is None or args.output_dir is None else {}
    raw = args.raw_dir if args.raw_dir is not None else defaults["raw"]
    processed = args.output_dir if args.output_dir is not None else defaults["processed"]
    index = args.metadata_index if args.metadata_index is not None else raw / "metadata.csv"
    stats = sanitize_dataset(raw, processed, target_sr=args.sr, num_workers=args.workers,
                             show_progress=True, metadata_index=index,
                             roots={"raw": raw, "processed": processed}, output_index=args.output_index)
    print(f"Total: {stats['total']}; convertidos: {stats['converted']}; fallidos: {stats['failed']}")
    return stats


if __name__ == "__main__":
    main()
