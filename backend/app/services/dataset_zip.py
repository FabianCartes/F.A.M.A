"""Bounded WAV ZIP validation. Archive paths are metadata, never extraction paths."""
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import time
import unicodedata
import zipfile

import soundfile as sf


@dataclass(frozen=True)
class ImportLimits:
    received_bytes: int = 64 * 1024**2
    expanded_bytes: int = 256 * 1024**2
    entries: int = 2000
    depth: int = 12
    path_bytes: int = 240
    audio_bytes: int = 32 * 1024**2
    audio_seconds: int = 600
    validation_seconds: int = 60
    free_bytes: int = 512 * 1024**2
    ttl_seconds: int = 86400
    concurrent_imports: int = 4

    def public(self):
        return asdict(self)

    @classmethod
    def from_environment(cls):
        values = {name: int(os.environ.get("FAMA_IMPORT_" + name.upper(), default))
                  for name, default in asdict(cls()).items()}
        if any(v <= 0 for v in values.values()):
            raise ValueError("Import limits must be positive integers")
        return cls(**values)


def fingerprint(files):
    pairs = sorted({(f["class_name"], f["sha256"]) for f in files})
    payload = json.dumps(["wav-collection-v1", pairs], ensure_ascii=False, separators=(",", ":"))
    return "v1:" + hashlib.sha256(payload.encode()).hexdigest()


def _parts(text, limits):
    parts = text.split("/")
    if (not text or any(p in ("", ".", "..") for p in parts)
            or "\\" in text or ":" in text
            or any(unicodedata.category(c).startswith("C") for c in text)
            or len(text.encode("utf-8")) > limits.path_bytes or len(parts) > limits.depth):
        raise ValueError("unsafe_path")
    return parts


def _check_directory(source, limits):
    # Bound central-directory construction before ZipFile allocates ZipInfo objects.
    with source.open("rb") as stream:
        stream.seek(max(0, source.stat().st_size - 65557))
        tail = stream.read(65557)
    offset = tail.rfind(b"PK\x05\x06")
    if offset < 0 or len(tail) - offset < 22:
        raise ValueError("corrupt_zip")
    disk, directory_disk, disk_count, count, size, _, comment = struct.unpack_from("<4H2IH", tail, offset + 4)
    if (disk or directory_disk or disk_count != count or count == 65535
            or count > limits.entries or size > limits.entries * (limits.path_bytes + 128)
            or offset + 22 + comment != len(tail)):
        raise ValueError("archive_limits")


def _check_wav_container(path, size, budget):
    """Check declared chunk boundaries; libsndfile can accept truncated data."""
    with path.open("rb") as stream:
        header = stream.read(12)
        if len(header) != 12 or header[8:] != b"WAVE" or header[:4] not in (b"RIFF", b"RIFX", b"RF64"):
            raise ValueError("invalid_wav")
        endian = ">" if header[:4] == b"RIFX" else "<"
        riff_size = struct.unpack(endian + "I", header[4:8])[0]
        data_size = None
        position = 12
        while position < size:
            budget()
            stream.seek(position)
            chunk = stream.read(8)
            if len(chunk) != 8:
                raise ValueError("truncated_wav")
            length = struct.unpack(endian + "I", chunk[4:])[0]
            if chunk[:4] == b"ds64" and header[:4] == b"RF64":
                payload = stream.read(28)
                if length < 28 or len(payload) != 28:
                    raise ValueError("invalid_wav")
                riff_size, data_size = struct.unpack_from("<QQ", payload)
            if length == 0xFFFFFFFF:
                if chunk[:4] != b"data" or data_size is None:
                    raise ValueError("invalid_wav")
                length = data_size
            position += 8 + length + (length % 2)
            if position > size:
                raise ValueError("truncated_wav")
        if riff_size + 8 != size:
            raise ValueError("truncated_wav")


def validate_zip(source: Path, staging: Path, *, root: str, limits: ImportLimits):
    """Return safe relative diagnostics and staged content, without publishing anything.

    The caller owns a private staging directory. Work is streaming and uses a
    cooperative deadline, not an OS sandbox for the native audio decoder.
    """
    staging.mkdir(mode=0o700, parents=True, exist_ok=True)
    files, errors, warnings = [], [], []
    deadline = time.monotonic() + limits.validation_seconds
    expanded = 0
    current = ""

    def budget():
        if time.monotonic() >= deadline:
            raise ValueError("validation_timeout")
        if shutil.disk_usage(staging).free < limits.free_bytes:
            raise ValueError("disk_reserve")

    try:
        if source.stat().st_size > limits.received_bytes:
            raise ValueError("received_limit")
        budget()
        _check_directory(source, limits)
        root_parts = _parts(root, limits) if root else []
        seen, kinds, classes, populated, hashes = {}, {}, set(), set(), {}
        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
            if len(infos) > limits.entries:
                raise ValueError("entry_limit")
            for info in infos:
                current = info.filename
                budget()
                name = info.filename[:-1] if info.is_dir() else info.filename
                if info.orig_filename != info.filename:
                    raise ValueError("unsafe_path")
                parts = _parts(name, limits)
                key = unicodedata.normalize("NFC", name).casefold()
                # Normalize every path prefix, including implicit directories.
                for index in range(1, len(parts) + 1):
                    prefix = "/".join(parts[:index])
                    normalized = unicodedata.normalize("NFC", prefix).casefold()
                    if normalized in seen and seen[normalized] != prefix:
                        raise ValueError("normalized_path_collision")
                    seen[normalized] = prefix
                    if index < len(parts) and kinds.get(normalized) == "file":
                        raise ValueError("path_collision")
                if key in kinds:
                    raise ValueError("duplicate_path")
                if not info.is_dir() and any(p.startswith(key + "/") for p in kinds):
                    raise ValueError("path_collision")
                kind = stat.S_IFMT(info.external_attr >> 16)
                if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or (kind == stat.S_IFDIR and not info.is_dir()):
                    raise ValueError("special_entry")
                if info.flag_bits & 1:
                    raise ValueError("encrypted_zip")
                kinds[key] = "directory" if info.is_dir() else "file"
                if info.is_dir() and parts == root_parts[:len(parts)]:
                    continue
                if parts[:len(root_parts)] != root_parts:
                    raise ValueError("outside_selected_root")
                relative = parts[len(root_parts):]
                if relative:
                    relative[0] = unicodedata.normalize("NFC", relative[0])
                if info.is_dir():
                    if relative:
                        classes.add(relative[0])
                    continue
                if len(relative) < 2:
                    raise ValueError("class_folder_required")
                if not relative[-1].lower().endswith(".wav"):
                    raise ValueError("wav_only")
                if info.file_size > limits.audio_bytes:
                    raise ValueError("audio_size_limit")
                temporary = staging / "decoding.part"
                digest, size = hashlib.sha256(), 0
                with archive.open(info) as input_file, temporary.open("wb") as output:
                    while chunk := input_file.read(65536):
                        budget()
                        size += len(chunk)
                        expanded += len(chunk)
                        if size > limits.audio_bytes or expanded > limits.expanded_bytes:
                            raise ValueError("expanded_limit")
                        digest.update(chunk)
                        output.write(chunk)
                _check_wav_container(temporary, size, budget)
                with sf.SoundFile(temporary) as audio:
                    if (audio.format not in ("WAV", "WAVEX", "RF64") or audio.frames <= 0
                            or audio.channels > 64 or audio.samplerate <= 0):
                        raise ValueError("invalid_wav")
                    duration = audio.frames / audio.samplerate
                    if duration > limits.audio_seconds:
                        raise ValueError("audio_duration_limit")
                    decoded = 0
                    for block in audio.blocks(blocksize=8192):
                        budget()
                        decoded += len(block)
                    if decoded != audio.frames:
                        raise ValueError("truncated_wav")
                    sample_rate = audio.samplerate
                hashed = digest.hexdigest()
                duplicate = hashed in hashes
                if duplicate and hashes[hashed] != relative[0]:
                    raise ValueError("label_conflict")
                hashes.setdefault(hashed, relative[0])
                stored_name = hashed + ".wav"
                os.replace(temporary, staging / stored_name)
                populated.add(relative[0])
                files.append({"original_path": info.filename, "class_name": relative[0],
                              "sha256": hashed, "stored_name": stored_name,
                              "duplicate": duplicate,
                              "size_bytes": size, "duration_seconds": duration,
                              "sample_rate": sample_rate})
        if not files:
            raise ValueError("no_valid_wav")
        for label in sorted(classes - populated):
            warnings.append({"path": label, "code": "empty_class"})
        for label in sorted(populated):
            if sum(f["class_name"] == label for f in files) < 2:
                warnings.append({"path": label, "code": "small_class"})
    except (ValueError, zipfile.BadZipFile, RuntimeError, OSError, EOFError, NotImplementedError) as error:
        code = str(error) if type(error) is ValueError else "invalid_archive_or_wav"
        errors.append({"path": current, "code": code,
                       "action": "Corrige la ruta, estructura o contenido y vuelve a subir el ZIP."})
    return {"files": files, "errors": errors, "warnings": warnings,
            "classes": sorted({f["class_name"] for f in files}),
            "unique_count": len({f["sha256"] for f in files}),
            "duplicate_count": sum(f["duplicate"] for f in files),
            "fingerprint": fingerprint(files)}
