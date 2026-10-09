"""Explicit preparation and completion barrier; no training/discovery side effects.

Directories become visible before completion. Failed publication leaves its reserved
incomplete directory for offline recovery; no competing destination is adopted or
removed. Audio references are checked at read time, not locked snapshots.
"""
import csv
import hashlib
import io
import json
import os
import stat
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from dataset_references import resolve_reference
from training.paths import get_prepared_data_dir
from training.pipelines.split import grouped_stratified_split_dataset

_MARKER = ".complete"
_SPLITS = ("train", "val", "test")


def _names(dataset_name):
    if dataset_name not in ("AvesChilenas", "engine_diagnostics"):
        raise ValueError("Unsupported dataset naming policy")
    suffix = "_metadata" if dataset_name == "engine_diagnostics" else ""
    return [f"{split}{suffix}.csv" for split in _SPLITS]


@contextmanager
def _directory(path):
    path = Path(path)
    if not path.is_absolute() or any(p in (".", "..") for p in path.parts):
        raise ValueError("Directory must be an absolute physical path")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd
    finally:
        os.close(fd)


def _bytes(fd, name):
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Index must be a regular CSV file")
        return stream.read()


def _parse(data):
    reader = csv.reader(io.StringIO(data.decode("utf-8"), newline=""))
    header = next(reader, [])
    if not header or len(set(header)) != len(header) or any(not c for c in header):
        raise ValueError("Invalid CSV header")
    rows = list(reader)
    if any(len(row) != len(header) for row in rows):
        raise ValueError("Invalid CSV row width")
    return pd.DataFrame(rows, columns=header, dtype=str)


def _validate(frame, roots, dataset_name):
    required = {"file_path", "file_stage", "recordist", "clase"}
    if dataset_name == "AvesChilenas":
        required.add("xc_id")
    if not required.issubset(frame.columns) or frame.empty:
        raise ValueError("Missing required canonical columns or empty index")
    for column in required:
        if frame[column].isna().any() or frame[column].map(lambda x: not str(x).strip()).any():
            raise ValueError(f"Blank required column: {column}")
    paths = [resolve_reference(row.file_path, row.file_stage, roots)
             for row in frame.itertuples(index=False)]
    if len(set(paths)) != len(paths):
        raise ValueError("Duplicate resolved reference")
    # Local importer source IDs are class-scoped filenames; XC IDs are global.
    identity = ["xc_id"] if dataset_name == "AvesChilenas" else ["clase", "source_id"]
    if set(identity).issubset(frame.columns):
        if frame[identity].map(lambda x: not str(x).strip()).any().any():
            raise ValueError("Blank source identity")
        if frame.duplicated(identity).any():
            raise ValueError("Duplicate source identity")


def _validate_trio(parts, roots, dataset_name):
    if any(list(part.columns) != list(parts[0].columns) for part in parts):
        raise ValueError("Inconsistent split columns")
    _validate(pd.concat(parts, ignore_index=True), roots, dataset_name)
    classes = set(pd.concat(parts).clase)
    for i, part in enumerate(parts):
        if part.empty or set(part.clase) != classes:
            raise ValueError("Incomplete class coverage")
        if any(set(part.recordist) & set(other.recordist) for other in parts[:i]):
            raise ValueError("Group leakage")


def _write(fd, name, frame=None, record=None):
    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=fd)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
        os.fchmod(stream.fileno(), 0o644)
        if frame is None:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
        else:
            frame.to_csv(stream, index=False)
        stream.flush()
        os.fsync(stream.fileno())


def prepare_dataset(index_csv, *, roots, dataset_name, output_dir=None,
                    train_ratio=.70, val_ratio=.15, test_ratio=.15, random_state=42):
    """Validate and split an explicit index BEFORE exclusively reserving output.

    Output parent must exist and have no symlink ancestors. Default location is
    data/prepared/<dataset>. Returns counts and actual ratios, not a manifest.
    """
    names = _names(dataset_name)
    index = Path(index_csv)
    with _directory(index.parent) as fd:
        frame = _parse(_bytes(fd, index.name))
    _validate(frame, roots, dataset_name)
    parts = grouped_stratified_split_dataset(frame, train_ratio, val_ratio, test_ratio,
                                             random_state=random_state)
    _validate_trio(parts, roots, dataset_name)
    output = Path(output_dir) if output_dir is not None else get_prepared_data_dir(dataset_name)
    if any(output.is_relative_to(Path(root)) or Path(root).is_relative_to(output)
           for root in roots.values()):
        raise ValueError("Prepared output must be separate from audio roots")
    with _directory(output.parent) as parent:
        os.mkdir(output.name, 0o700, dir_fd=parent)  # Existing targets always fail.
        reserved = os.stat(output.name, dir_fd=parent, follow_symlinks=False)
        fd = os.open(output.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (reserved.st_dev, reserved.st_ino):
                raise RuntimeError("Reserved directory was replaced")
            os.fchmod(fd, 0o755)
            for name, part in zip(names, parts):
                _write(fd, name, part)
            data = {name: _bytes(fd, name) for name in names}
            persisted = tuple(_parse(data[name]) for name in names)
            _validate_trio(persisted, roots, dataset_name)
            for expected, actual in zip(parts, persisted):
                if not expected.equals(actual):
                    raise ValueError("Persisted CSV differs from split")
            os.fsync(fd)
            record = {"schema": 1, "dataset": dataset_name,
                      "sha256": {name: hashlib.sha256(data[name]).hexdigest() for name in names}}
            _write(fd, _MARKER, record=record)  # Completion barrier is always last.
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(parent)
    counts = dict(zip(_SPLITS, map(len, parts)))
    return {"counts": counts, "ratios": {key: count / len(frame) for key, count in counts.items()}}


def load_prepared_dataset(output_dir, *, roots, dataset_name):
    """Return train/val/test only with a completion marker AND a valid full trio."""
    names = _names(dataset_name)
    with _directory(output_dir) as fd:
        try:
            record = json.loads(_bytes(fd, _MARKER))
        except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Missing or malformed completion marker") from exc
        if (not isinstance(record, dict) or set(record) != {"schema", "dataset", "sha256"}
                or type(record["schema"]) is not int or record["schema"] != 1
                or record["dataset"] != dataset_name
                or not isinstance(record["sha256"], dict) or set(record["sha256"]) != set(names)):
            raise ValueError("Unsupported completion marker schema or dataset layout")
        if set(os.listdir(fd)) != {*names, _MARKER}:
            raise ValueError("Unsupported prepared dataset layout")
        data = {name: _bytes(fd, name) for name in names}
        if any(record["sha256"][name] != hashlib.sha256(data[name]).hexdigest() for name in names):
            raise ValueError("Prepared CSV integrity mismatch")
        parts = tuple(_parse(data[name]) for name in names)
    _validate_trio(parts, roots, dataset_name)
    return parts
