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
from training.grouping import recording_groups

_MARKER = ".complete"
_SPLITS = ("train", "val", "test")


def _version_id(record):
    payload = {key: value for key, value in record.items() if key != "version_id"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


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
    groups = recording_groups(pd.concat(parts, ignore_index=True), dataset_name)
    seen_groups = set()
    for i, part in enumerate(parts):
        if part.empty or set(part.clase) != classes:
            raise ValueError("Incomplete class coverage")
        selected = {groups[(row.file_stage, row.file_path)] for row in part.itertuples()}
        if selected & seen_groups:
            raise ValueError("Group leakage")
        seen_groups.update(selected)


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
                    train_ratio=.70, val_ratio=.15, test_ratio=.15, random_state=42,
                    versioned=False):
    """Validate and split an explicit index BEFORE exclusively reserving output.

    Output parent must exist and have no symlink ancestors. Default location is
    data/prepared/<dataset>. With versioned=True, output_dir is an existing
    version store and a content-identified child is exclusively published.
    Returns counts, actual ratios, version identity and physical output path.
    """
    names = _names(dataset_name)
    index = Path(index_csv)
    with _directory(index.parent) as fd:
        source_bytes = _bytes(fd, index.name)
        frame = _parse(source_bytes)
    _validate(frame, roots, dataset_name)
    groups = recording_groups(frame, dataset_name)
    group_column = object()
    grouped = frame.copy()
    grouped[group_column] = [groups[(row.file_stage, row.file_path)] for row in frame.itertuples()]
    parts = tuple(part.drop(columns=[group_column]) for part in grouped_stratified_split_dataset(
        grouped, train_ratio, val_ratio, test_ratio, group_col=group_column, random_state=random_state))
    _validate_trio(parts, roots, dataset_name)
    if type(versioned) is not bool or (versioned and output_dir is None):
        raise ValueError("Versioned preparation requires an explicit version store")
    data = {name: part.to_csv(index=False).encode("utf-8") for name, part in zip(names, parts)}
    record = {"schema": 2, "dataset": dataset_name,
              "sha256": {name: hashlib.sha256(data[name]).hexdigest() for name in names},
              "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
              "parameters": {"train_ratio": float(train_ratio), "val_ratio": float(val_ratio),
                             "test_ratio": float(test_ratio), "random_state": int(random_state),
                             "grouping": "curation-source-v1"}}
    record["version_id"] = _version_id(record)
    output = Path(output_dir) if output_dir is not None else get_prepared_data_dir(dataset_name)
    if versioned:
        output = output / record["version_id"]
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
            if any(hashlib.sha256(data[name]).hexdigest() != record["sha256"][name] for name in names):
                raise ValueError("Persisted CSV bytes differ from version identity")
            _write(fd, _MARKER, record=record)  # Completion barrier is always last.
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(parent)
    counts = dict(zip(_SPLITS, map(len, parts)))
    return {"counts": counts, "ratios": {key: count / len(frame) for key, count in counts.items()},
            "version_id": record["version_id"], "output_dir": str(output)}


def load_prepared_dataset(output_dir, *, roots, dataset_name):
    """Read an integrity-checked trio, including legacy schema1, without freshness admission."""
    parts, _ = _load_prepared(output_dir, roots=roots, dataset_name=dataset_name)
    return parts


def _load_prepared(output_dir, *, roots, dataset_name):
    names = _names(dataset_name)
    with _directory(output_dir) as fd:
        try:
            record = json.loads(_bytes(fd, _MARKER))
        except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Missing or malformed completion marker") from exc
        if (not isinstance(record, dict) or type(record.get("schema")) is not int
                or record["schema"] not in (1, 2)
                or not {"schema", "dataset", "sha256"}.issubset(record)
                or record["dataset"] != dataset_name
                or not isinstance(record["sha256"], dict) or set(record["sha256"]) != set(names)):
            raise ValueError("Unsupported completion marker schema or dataset layout")
        keys = {"schema", "dataset", "sha256"}
        if record["schema"] == 2:
            keys |= {"source_sha256", "parameters", "version_id"}
        if set(record) != keys:
            raise ValueError("Unsupported completion marker fields")
        if record["schema"] == 2:
            params = record["parameters"]
            if (not isinstance(params, dict)
                    or set(params) != {"train_ratio", "val_ratio", "test_ratio", "random_state", "grouping"}
                    or params["grouping"] != "curation-source-v1"
                    or not isinstance(record["source_sha256"], str)
                    or len(record["source_sha256"]) != 64):
                raise ValueError("Unsupported completion marker provenance")
            try:
                valid_identity = record["version_id"] == _version_id(record)
            except (TypeError, ValueError):
                valid_identity = False
            if not valid_identity:
                raise ValueError("Prepared version identity mismatch")
        if set(os.listdir(fd)) != {*names, _MARKER}:
            raise ValueError("Unsupported prepared dataset layout")
        data = {name: _bytes(fd, name) for name in names}
        if any(record["sha256"][name] != hashlib.sha256(data[name]).hexdigest() for name in names):
            raise ValueError("Prepared CSV integrity mismatch")
        parts = tuple(_parse(data[name]) for name in names)
    _validate_trio(parts, roots, dataset_name)
    return parts, record


def load_prepared_version(output_dir, *, roots, dataset_name, index_csv,
                          expected_version=None, allow_historical=False):
    """Admit an identified preparation against an explicit current index.

    Historical selection bypasses only freshness, never integrity or grouping.
    Identity covers index bytes and partition bytes, not immutable audio content.
    """
    if type(allow_historical) is not bool:
        raise ValueError("allow_historical must be a boolean")
    if allow_historical and expected_version is None:
        raise ValueError("Historical preparation requires an explicit expected_version")
    parts, record = _load_prepared(output_dir, roots=roots, dataset_name=dataset_name)
    if record["schema"] != 2:
        raise ValueError("Legacy preparation has no source identity; prepare a new version explicitly")
    if expected_version is not None and expected_version != record["version_id"]:
        raise ValueError("Prepared version identity does not match the selected version")
    if not allow_historical:
        index = Path(index_csv)
        with _directory(index.parent) as fd:
            digest = hashlib.sha256(_bytes(fd, index.name)).hexdigest()
        if digest != record["source_sha256"]:
            raise ValueError("Stale prepared dataset: source index changed; prepare a new version explicitly")
    return parts, record
