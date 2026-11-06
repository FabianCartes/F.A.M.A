"""Immutable imported preparation, deliberately separate from legacy CSV loaders.

Only server-configured roots and an authorized TrainingSnapshots instance enter
construction. Callers provide identities, annotations and an explicit profile.
Audio stays in T1; these artifacts contain stable references, never client paths.
"""
import csv
import fcntl
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import uuid
import wave

from app.services.training_snapshots import _json, _open, _parts, _root_directory


SPLITS = ("train", "val", "test")
POLICY = {"name": "group-cover-v1", "target": [0.8, 0.1, 0.1],
          "search_nodes": 250000, "group_limit": 200}
INDEPENDENT_PROVENANCE = {"source": "per-wav-independent-assumption-v1"}
INDEPENDENT_POLICY = {"name": "per-wav-stratified-70-15-15-v1", "target": [0.7, 0.15, 0.15]}
FIELDS = ("snapshot_id", "member_id", "class_name", "class_index", "recording_id",
          "group_id", "source_import_id", "stored_name", "original_path",
          "relative_path", "sha256", "size_bytes")


class PreparationError(ValueError):
    """Actionable failure, not a persisted ready preparation or training job."""

    def __init__(self, code, message):
        self.code = code
        self.state = "failed"
        super().__init__(message)


def _text(value):
    return (isinstance(value, str) and 0 < len(value) <= 512 and value == value.strip()
            and all(ord(c) >= 32 and ord(c) != 127 for c in value))


def _mapping(mapping, provenance):
    try:
        if (not isinstance(mapping, list) or not mapping or len(mapping) > 20000
                or not isinstance(provenance, dict) or not provenance
                or not _text(provenance.get("source"))
                or len(json.dumps(provenance, allow_nan=False)) > 65536):
            raise ValueError("mapping/provenance")
        annotations, recordings = {}, {}
        for row in mapping:
            if (not isinstance(row, dict) or set(row) != {"member_id", "recording_id", "group_id"}
                    or not all(_text(v) for v in row.values()) or row["member_id"] in annotations):
                raise ValueError("invalid or duplicate annotation")
            if provenance == INDEPENDENT_PROVENANCE and not (
                    row["member_id"] == row["recording_id"] == row["group_id"]):
                raise ValueError("assumed independence requires one recording/group per member")
            if recordings.setdefault(row["recording_id"], row["group_id"]) != row["group_id"]:
                raise ValueError("recording assigned to multiple groups")
            annotations[row["member_id"]] = dict(row)
        return annotations
    except (ValueError, TypeError) as error:
        raise PreparationError("invalid_mapping", "Se requiere mapa exacto de miembros, grabaciones/grupos y procedencia explícita.") from error


def _profile(profile):
    from training.schemas.config import AudioConfig
    try:
        fields = {"architecture", "channels", "preprocessing", "windowing", "window_hop_seconds", "audio"}
        if not isinstance(profile, dict) or set(profile) != fields:
            raise ValueError("explicit profile required")
        audio = profile["audio"]
        if not isinstance(audio, dict) or set(audio) != set(AudioConfig.model_fields):
            raise ValueError("all audio fields required")
        for name, value in audio.items():
            if name == "use_gpu_frontend":
                if type(value) is not bool:
                    raise ValueError("boolean required")
            elif name == "f_max" and value is None:
                continue  # Explicit None means Nyquist, persisted as an effective number.
            elif type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("finite numeric audio fields required")
        for name in ("target_sr", "n_mels", "n_fft", "hop_length"):
            if type(audio[name]) is not int:
                raise ValueError("integer required")
        effective = AudioConfig(**audio).model_dump()
        if effective["f_max"] is None:
            effective["f_max"] = effective["target_sr"] / 2
        sr, fft = effective["target_sr"], effective["n_fft"]
        samples = int(sr * effective["duration_seconds"])
        hop = profile["window_hop_seconds"]
        architecture = profile["architecture"]
        if (architecture not in ("audio_cnn", "panns_cnn14", "efficientnet_b0", "convnext_nano", "resnet34d")
                or type(profile["channels"]) is not int or profile["channels"] != 1
                or profile["preprocessing"] != "mono_mel" or profile["windowing"] != "energy_peak_pad"
                or type(hop) not in (int, float) or not math.isfinite(hop)
                or not 0 < hop <= effective["duration_seconds"] or int(hop * sr) < 1
                or not 1000 <= sr <= 384000 or not fft <= samples <= 10000000
                or fft > 65536 or fft & (fft - 1)
                or not 0 <= effective["f_min"] < effective["f_max"] <= sr / 2
                or effective["n_mels"] > fft // 2 + 1):
            raise ValueError("incompatible audio physics or preprocessing")
        minimum = 64 if architecture == "panns_cnn14" else 32
        if effective["n_mels"] < minimum or 1 + samples // effective["hop_length"] < minimum:
            raise ValueError("spectrogram too small for architecture")
        return dict(profile, audio=effective)
    except (ValueError, TypeError, OverflowError) as error:
        raise PreparationError("invalid_profile", "Perfil explícito incompatible: revise arquitectura, canales, física y ventanas.") from error


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _audio(stream):
    try:
        stream.seek(0)
        with wave.open(stream, "rb") as audio:
            channels, width, rate, frames = (audio.getnchannels(), audio.getsampwidth(),
                                             audio.getframerate(), audio.getnframes())
            if (audio.getcomptype() != "NONE" or not 1 <= channels <= 8
                    or width not in (1, 2, 3, 4) or not 1 <= rate <= 384000 or frames <= 0):
                raise ValueError("unsupported WAV physics/codec")
            remaining = frames * channels * width
            while remaining:
                chunk = audio.readframes(min(65536, (remaining + channels * width - 1) // (channels * width)))
                if not chunk or len(chunk) > remaining:
                    raise ValueError("truncated PCM frames")
                remaining -= len(chunk)
    except (wave.Error, EOFError, ValueError) as error:
        raise PreparationError("invalid_audio", "WAV PCM ilegible, vacío, truncado o incompatible.") from error


def _members(snapshots, owner, snapshot_id, snapshot):
    if not 0 < snapshot["file_count"] <= 20000 or snapshot["total_size_bytes"] > 16 * 1024**3:
        raise PreparationError("budget_exceeded", "Snapshot fuera del presupuesto de preparación v1.")
    members, total = {}, 0
    current, length = None, 0
    try:
        # T1 already retains a verified member in the global temporary volume.
        # Spill this second copy on private snapshot storage, anchored to the
        # verified directory descriptor rather than following a mutable path.
        with _root_directory(snapshots.root) as root_fd, tempfile.SpooledTemporaryFile(
                max_size=1024 * 1024, dir=f"/proc/self/fd/{root_fd}") as audio:
            def finish():
                if current is not None:
                    if length != current["size_bytes"]:
                        raise PreparationError("source_unavailable", "Tamaño de miembro incoherente.")
                    _audio(audio)
                    members[current["member_id"]] = dict(current)
            for member, chunk in snapshots.iter_verified(owner, snapshot_id):
                if current is None or member["member_id"] != current["member_id"]:
                    finish()
                    if member["member_id"] in members or len(members) >= 20000:
                        raise PreparationError("source_unavailable", "Membresía duplicada o excesiva.")
                    for field in ("original_path", "relative_path", "stored_name", "source_import_id", "member_id"):
                        _parts(member[field])
                    label = member["class_name"]
                    if (not _text(label) or "/" in label or "\\" in label
                            or label in (".", "..", "__unknown__", "__unlabeled__")
                            or not member["original_path"].lower().endswith(".wav")):
                        raise PreparationError("invalid_metadata", "Etiqueta o referencia WAV inválida.")
                    current, length = dict(member), 0
                    audio.seek(0)
                    audio.truncate()
                if member != current or not chunk or len(chunk) > 1024 * 1024:
                    raise PreparationError("source_unavailable", "Flujo de miembros incoherente.")
                length += len(chunk)
                total += len(chunk)
                if length > min(current["size_bytes"], 512 * 1024**2) or total > snapshot["total_size_bytes"]:
                    raise PreparationError("budget_exceeded", "Audio fuera del presupuesto de preparación v1.")
                audio.write(chunk)
            finish()  # Only after successful iterator exhaustion, including late failures.
        if len(members) != snapshot["file_count"] or total != snapshot["total_size_bytes"]:
            raise PreparationError("source_unavailable", "Snapshot incompleto.")
        if sorted({m["class_name"] for m in members.values()}) != snapshot["classes"]:
            raise PreparationError("invalid_metadata", "Clases incoherentes con el snapshot.")
        return members
    except PreparationError:
        raise
    except Exception as error:
        raise PreparationError("source_unavailable", "No se pudo verificar completamente la fuente T1.") from error


def _split(rows, seed):
    # Exact bounded constraint search. A budget exhaustion is NOT an
    # infeasibility proof. Groups may contain several different classes.
    classes = sorted({r["class_name"] for r in rows})
    groups = {}
    for row in rows:
        groups.setdefault(row["group_id"], set()).add(row["class_name"])
    counts = {c: sum(c in labels for labels in groups.values()) for c in classes}
    if min(counts.values()) < 3:
        raise PreparationError("split_impossible", "Cada clase necesita al menos tres grupos independientes.")
    if len(groups) > POLICY["group_limit"]:
        raise PreparationError("split_search_unavailable", "Demasiados grupos para la búsqueda acotada v1.")
    ordered = sorted(groups, key=lambda g: (-len(groups[g]), _hash(_json([seed, g]))))
    suffix = [set() for _ in range(len(ordered) + 1)]
    for i in range(len(ordered) - 1, -1, -1):
        suffix[i] = suffix[i + 1] | groups[ordered[i]]
    covered = [set(), set(), set()]
    assignment = {}
    visits = 0

    def search(i):
        nonlocal visits
        visits += 1
        if visits > POLICY["search_nodes"]:
            raise PreparationError("split_search_unavailable", "Presupuesto de búsqueda agotado; factibilidad no determinada.")
        if all(len(c) == len(classes) for c in covered):
            return True
        if i == len(ordered) or any(set(classes) - c - suffix[i] for c in covered):
            return False
        group = ordered[i]
        seen = set()
        # Prefer coverage before target proportions. Split label symmetry is
        # removed only when the two partial covered sets really are identical.
        for s in sorted(range(3), key=lambda s: (-len(groups[group] - covered[s]), s)):
            signature = frozenset(covered[s])
            if signature in seen:
                continue
            seen.add(signature)
            previous = covered[s]
            covered[s] = previous | groups[group]
            assignment[group] = s
            if search(i + 1):
                return True
            covered[s] = previous
            assignment.pop(group)
        return False

    if not search(0):
        raise PreparationError("split_impossible", "No existe una partición con cobertura de clases sin fuga de grupos.")
    # Fill unneeded groups toward 80/10/10; coverage always takes priority.
    sizes = [sum(s == n for s in assignment.values()) for n in range(3)]
    for group in ordered:
        if group not in assignment:
            s = max(range(3), key=lambda n: POLICY["target"][n] * len(groups) - sizes[n])
            assignment[group] = s
            sizes[s] += 1
    warnings = [dict(code="low_independent_groups", class_name=c, groups=counts[c], recommended=10)
                for c in classes if counts[c] < 10]
    return {name: [r for r in rows if assignment[r["group_id"]] == i]
            for i, name in enumerate(SPLITS)}, warnings


def _independent_split(rows, seed):
    """Class-stratified allocation, O(n log n), only for per-member groups.

    Reserve coverage first, then fill the largest target deficit. Tiny classes
    necessarily deviate from the target; their independence remains an assumption.
    """
    classes = {}
    for row in rows:
        classes.setdefault(row["class_name"], []).append(row)
    partitions = {name: [] for name in SPLITS}
    warnings = []
    for label, entries in sorted(classes.items()):
        count = len(entries)
        if count < 3:
            raise PreparationError("split_impossible", "Cada clase necesita al menos tres WAV independientes asumidos.")
        ordered = sorted(entries, key=lambda row: _hash(_json([seed, row["member_id"]])))
        sizes = [1, 1, 1]
        for _ in range(count - 3):
            split = max(range(3), key=lambda i: INDEPENDENT_POLICY["target"][i] * count - sizes[i])
            sizes[split] += 1
        start = 0
        for name, size in zip(SPLITS, sizes):
            partitions[name].extend(ordered[start:start + size])
            start += size
        if count < 10:
            warnings.append(dict(code="low_independent_groups", class_name=label, groups=count, recommended=10))
    return partitions, warnings


class ImportedDatasetPreparation:
    """create/get/read_split by owner, snapshot ID and exact version ID.

    No implicit reprepare, GC, admission or legacy-loader compatibility. Files
    are immutable by application convention, with hashes rechecked on read.
    """

    def __init__(self, snapshots, root):
        self.snapshots = snapshots
        self.root = Path(root).absolute()

    def create(self, owner, snapshot_id, *, mapping, provenance, seed, profile):
        snapshot = self.snapshots.get(owner, snapshot_id)
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise PreparationError("invalid_seed", "La semilla debe ser un entero uint32, no bool.")
        profile = _profile(profile)
        annotations = _mapping(mapping, provenance)
        members = _members(self.snapshots, owner, snapshot_id, snapshot)
        if set(annotations) != set(members):
            raise PreparationError("invalid_mapping", "El mapa debe cubrir exactamente todos los miembros del snapshot.")
        classes = {c: i for i, c in enumerate(sorted({m["class_name"] for m in members.values()}))}
        rows = []
        for key, member in sorted(members.items()):
            row = {f: member[f] for f in FIELDS if f in member}
            row.update(snapshot_id=snapshot_id, class_index=classes[member["class_name"]],
                       recording_id=annotations[key]["recording_id"], group_id=annotations[key]["group_id"])
            rows.append(row)
        independent = provenance == INDEPENDENT_PROVENANCE
        policy = INDEPENDENT_POLICY if independent else POLICY
        partitions, warnings = (_independent_split if independent else _split)(rows, seed)
        payloads = {}
        for name, entries in partitions.items():
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(entries)
            payloads[name + ".csv"] = stream.getvalue().encode("utf-8")
        manifest = dict(schema_version=1, format="imported-preparation", state="ready",
                        owner_id=owner, snapshot_id=snapshot_id,
                        snapshot_manifest_sha256=snapshot["manifest_sha256"],
                        seed=seed, profile=profile, provenance=provenance,
                        mapping=sorted(mapping, key=lambda r: r["member_id"]),
                        class_to_index=classes, policy=policy, warnings=warnings,
                        file_count=len(rows), files={n: _hash(b) for n, b in payloads.items()})
        version = _hash(_json(manifest))
        manifest["version_id"] = version
        payloads["manifest.json"] = _json(manifest)
        if (len(payloads["manifest.json"]) > 16 * 1024**2
                or any(len(payloads[s + ".csv"]) > 32 * 1024**2 for s in SPLITS)):
            raise PreparationError("budget_exceeded", "Índices exceden el presupuesto de preparación v1.")
        with _root_directory(self.root) as root_fd:
            if shutil.disk_usage(self.root).free < sum(map(len, payloads.values())) + 1024**2:
                raise PreparationError("budget_exceeded", "Espacio insuficiente para publicar índices.")
            staging = ".staging-" + uuid.uuid4().hex
            os.mkdir(staging, mode=0o700, dir_fd=root_fd)
            fd = None
            try:
                fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
                for name, data in payloads.items():
                    out = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400, dir_fd=fd)
                    with os.fdopen(out, "wb") as stream:
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                os.fsync(fd)
                try:
                    fcntl.flock(root_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise PreparationError("publication_busy", "Publicación concurrente; vuelva a seleccionar o solicite preparación explícita.") from error
                try:
                    try:
                        os.stat(version, dir_fd=root_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        os.rename(staging, version, src_dir_fd=root_fd, dst_dir_fd=root_fd)
                        staging = None
                        os.fsync(root_fd)
                    # Every existing entry is retained, even an empty directory
                    # or symlink. Public get below verifies or rejects it.
                finally:
                    fcntl.flock(root_fd, fcntl.LOCK_UN)
            finally:
                if fd is not None:
                    os.close(fd)
                if staging is not None:
                    if fd is None:
                        os.rmdir(staging, dir_fd=root_fd)  # Our exclusive, still-empty directory.
                    else:
                        shutil.rmtree(staging, dir_fd=root_fd)
        return self.get(owner, snapshot_id, version)

    def get(self, owner, snapshot_id, version_id, *, expected_profile=None):
        snapshot = self.snapshots.get(owner, snapshot_id)
        if not isinstance(version_id, str) or len(version_id) != 64 or any(c not in "0123456789abcdef" for c in version_id):
            raise PreparationError("invalid_identity", "Identidad de preparación inválida.")
        try:
            with _open(self.root, version_id + "/manifest.json") as stream:
                raw = stream.read(16 * 1024 * 1024 + 1)
            if len(raw) > 16 * 1024 * 1024:
                raise ValueError("manifest budget")
            manifest = json.loads(raw)
            identity = dict(manifest)
            identity.pop("version_id")
            if (_hash(_json(identity)) != version_id or manifest["version_id"] != version_id
                    or manifest["owner_id"] != owner or manifest["snapshot_id"] != snapshot_id
                    or manifest["snapshot_manifest_sha256"] != snapshot["manifest_sha256"]
                    or manifest["schema_version"] != 1 or manifest["state"] != "ready"
                    or manifest["format"] != "imported-preparation"
                    or set(manifest["files"]) != {s + ".csv" for s in SPLITS}):
                raise ValueError("identity mismatch")
            if manifest["policy"] == INDEPENDENT_POLICY:
                if manifest["provenance"] != INDEPENDENT_PROVENANCE:
                    raise ValueError("independence assumption missing")
                _mapping(manifest["mapping"], manifest["provenance"])
            elif manifest["policy"] != POLICY:
                raise ValueError("unsupported preparation policy")
            for name, digest in manifest["files"].items():
                with _open(self.root, version_id + "/" + name) as stream:
                    data = stream.read(32 * 1024 * 1024 + 1)
                if len(data) > 32 * 1024 * 1024 or _hash(data) != digest:
                    raise ValueError("partition hash mismatch")
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise PreparationError("artifact_unavailable", "Preparación ausente, incompatible o alterada.") from error
        if expected_profile is not None and manifest["profile"] != _profile(expected_profile):
            raise PreparationError("profile_mismatch", "El perfil solicitado no corresponde a esta versión.")
        return manifest

    def read_split(self, owner, snapshot_id, version_id, split):
        manifest = self.get(owner, snapshot_id, version_id)
        if split not in SPLITS:
            raise PreparationError("invalid_split", "Partición desconocida.")
        with _open(self.root, version_id + "/" + split + ".csv") as stream:
            data = stream.read(32 * 1024 * 1024 + 1)
        if _hash(data) != manifest["files"][split + ".csv"]:
            raise PreparationError("artifact_unavailable", "Partición alterada durante lectura.")
        return list(csv.DictReader(io.StringIO(data.decode("utf-8"))))
