"""Verified recording inputs for imported evaluation; no registry or activation effects."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import tempfile

from app.services.imported_training_source import ImportedSourceError
from app.services.recording_evaluator import LabelledRecording


@contextmanager
def evaluation_recordings(source):
    """Materialize only admitted val/test bytes in a private, bounded-lived copy.

    The evaluator and predictor both consume this exact copy, not mutable source
    paths or a newly inferred split. T1's confined opener rejects symlinks.
    """
    from app.services.training_snapshots import _open, _root_directory
    identity = source["identity"]
    # Keep the trusted root descriptor alive through copy consumption and cleanup.
    # Global temporary storage may be a small tmpfs, unlike snapshot storage.
    with _root_directory(Path(source["snapshot_root"]).absolute()) as root_fd, tempfile.TemporaryDirectory(
        prefix="imported-evaluation-", dir=f"/proc/self/fd/{root_fd}"
    ) as directory:
        recordings = {}
        for split in ("val", "test"):
            records = []
            for index, row in enumerate(source["splits"][split]):
                reference = identity["snapshot_id"] + "/" + row["member_id"]
                target = Path(directory) / f"{split}-{index}.wav"
                digest, size = hashlib.sha256(), 0
                try:
                    expected_size = int(row["size_bytes"])
                    with _open(source["snapshot_root"], reference) as origin, target.open("xb") as output:
                        while block := origin.read(1024 * 1024):
                            size += len(block)
                            if size > min(expected_size, 512 * 1024**2):
                                raise ImportedSourceError()
                            digest.update(block)
                            output.write(block)
                    if size != expected_size or digest.hexdigest() != row["sha256"]:
                        raise ImportedSourceError()
                    target.chmod(0o400)
                    records.append(LabelledRecording(identity=row["recording_id"], label=row["class_name"],
                        path=target, reference=reference, stage="imported_snapshot", group=row["group_id"]))
                except Exception as error:
                    raise ImportedSourceError() from error
            recordings[split] = tuple(records)
        yield recordings
