"""Immutable local partition manifests; no cloud writes or legacy CSV replacement."""
import hashlib
import csv
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from collections import Counter, defaultdict

from app.models.dataset import Audio
from app.models.feedback_sync import FeedbackSync
from dataset_references import resolve_reference
from training.paths import get_dataset_roots


class PartitionError(ValueError):
    """An actionable, safe-to-display partition conflict."""


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _identity(value):
    text = (value or "").strip()
    return text if text.casefold() not in {"", "unknown", "desconocido", "nan", "none", "human_feedback", "-"} else ""


def verify_partition_files(manifest, roots):
    """A manifest freezes identities, not copies of the recording bytes."""
    try:
        for entry in manifest["entries"]:
            path = resolve_reference(entry["file_path"], entry["file_stage"], roots)
            if path.stat().st_size != entry["size_bytes"] or _digest(path) != entry["hash_sha256"]:
                raise ValueError()
    except (ValueError, KeyError, TypeError, OSError):
        raise PartitionError("El contenido local cambió o falta un audio de esta versión; restaura la copia correcta o crea otra versión.") from None


class DatasetPartitions:
    def __init__(self, dataset, db):
        self.dataset, self.db = dataset, db
        self.roots = get_dataset_roots(dataset.nombre)
        self.raw = self.roots["raw"]
        self.directory = self.raw / ".partitions"

    def _safe_directory(self):
        for path in (self.directory, *self.directory.parents):
            if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                raise PartitionError("La fuente de particiones debe ser un directorio físico del dataset.")
        if self.directory.resolve() != self.directory.absolute():
            raise PartitionError("La fuente de particiones debe conservar su ruta física.")

    def _provenance(self):
        metadata = self.raw / "metadata.csv"
        if not metadata.exists():
            return {}
        try:
            path = resolve_reference("metadata.csv", "raw", self.roots)
            if path.stat().st_size > 16 * 1024 * 1024:
                raise ValueError()
            with path.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                if not {"file_path", "file_stage"}.issubset(reader.fieldnames or []):
                    raise ValueError()
                result = {}
                for index, row in enumerate(reader):
                    if index >= 100000:
                        raise ValueError()
                    if row["file_stage"] != "raw":
                        continue
                    if row["file_path"] in result and result[row["file_path"]] != row:
                        raise ValueError()
                    result[row["file_path"]] = row
                return result
        except (ValueError, UnicodeError, csv.Error):
            raise PartitionError("Los metadatos de procedencia deben ser canónicos y no ambiguos.") from None

    @staticmethod
    def _split(entries, validation_percent, seed):
        parents = list(range(len(entries)))
        labels_by_hash = defaultdict(set)
        for entry in entries:
            labels_by_hash[entry["hash_sha256"]].add(entry["clase"])
        if any(len(labels) > 1 for labels in labels_by_hash.values()):
            raise PartitionError("Una misma grabación tiene clases distintas; revisa sus etiquetas antes de preparar particiones.")

        def root(index):
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        identities = {}
        for index, entry in enumerate(entries):
            for kind in ("hash_sha256", "source_group", "recordist"):
                identity = entry.get(kind)
                if not identity:
                    continue
                key = (kind, identity)
                if key in identities:
                    parents[root(index)] = root(identities[key])
                else:
                    identities[key] = index
        groups = defaultdict(list)
        for index, entry in enumerate(entries):
            groups[root(index)].append(entry)
        candidates = []
        for group in groups.values():
            identity = min(entry["hash_sha256"] for entry in group)
            for entry in group:
                entry["source_group_id"] = identity
            candidates.append((hashlib.sha256(f"{seed}:{identity}".encode()).hexdigest(), group))
        candidates.sort()
        remaining = Counter(entry["clase"] for entry in entries)
        targets = {label: max(1, round(count * validation_percent / 100)) for label, count in remaining.items()}
        validation = Counter()
        chosen = set()
        while candidates:
            options = []
            for key, group in candidates:
                counts = Counter(entry["clase"] for entry in group)
                if any(remaining[label] <= count for label, count in counts.items()):
                    continue
                missing = sum(validation[label] == 0 for label in counts)
                gain = sum(abs(targets[label] - validation[label]) - abs(targets[label] - validation[label] - count)
                           for label, count in counts.items())
                if missing or gain > 0:
                    options.append((-missing, -gain, key, group, counts))
            if not options:
                break
            _, _, key, group, counts = min(options, key=lambda item: item[:3])
            chosen.add(key)
            validation.update(counts)
            remaining.subtract(counts)
            candidates = [(candidate, rows) for candidate, rows in candidates if candidate != key]
        for group in groups.values():
            key = hashlib.sha256(f"{seed}:{group[0]['source_group_id']}".encode()).hexdigest()
            for entry in group:
                entry["split"] = "val" if key in chosen else "train"

    def preview(self, validation_percent=20, seed=42):
        self._safe_directory()
        if not self.raw.is_dir():
            raise PartitionError("Descarga los audios del dataset antes de preparar particiones.")
        prefix = self.dataset.ruta_gcp.rstrip("/") + "/"
        rows = self.db.query(Audio).filter_by(id_conjunto_datos=self.dataset.id_conjunto_datos).order_by(Audio.ruta_gcp).limit(10001).all()
        if len(rows) > 10000:
            raise PartitionError("Esta preparación admite hasta 10000 audios registrados por dataset.")
        entries, excluded = [], []
        provenance = self._provenance()
        feedback_paths = {row.local_relative_path.removeprefix(self.dataset.nombre + "/")
                          for row in self.db.query(FeedbackSync).filter_by(dataset_name=self.dataset.nombre).all()}
        for row in rows:
            if not row.ruta_gcp.startswith(prefix):
                raise PartitionError("Hay audios cuya ruta no coincide con el dataset registrado.")
            relative = row.ruta_gcp[len(prefix):]
            candidate = self.raw / relative
            if not candidate.exists():
                excluded.append({"file_path": relative, "reason": "not_local"})
                continue
            try:
                path = resolve_reference(relative, "raw", self.roots)
            except ValueError:
                raise PartitionError("Hay una referencia local inválida en el dataset.") from None
            digest = _digest(path)
            if (not path.stat().st_size or path.suffix.lower() not in {".wav", ".mp3", ".flac", ".ogg"}
                    or row.hash_archivo and row.hash_archivo != digest):
                raise PartitionError("Un audio local no coincide con su registro; vuelve a sincronizarlo.")
            observed = provenance.get(relative, {})
            if relative in feedback_paths and not _identity(observed.get("source_group")):
                excluded.append({"file_path": relative, "reason": "feedback_without_source_group"})
                continue
            entries.append({"audio_id": row.id_audio, "file_path": relative, "file_stage": "raw", "clase": row.clase,
                            "hash_sha256": digest, "size_bytes": path.stat().st_size})
            if observed.get("clase") and observed["clase"] != row.clase:
                raise PartitionError("La clase de los metadatos no coincide con el registro del audio.")
            for field in ("source_group", "recordist"):
                entries[-1][field] = _identity(observed.get(field))
        self._split(entries, validation_percent, seed)
        warnings = []
        if any(not entry["recordist"] for entry in entries):
            warnings.append("Falta procedencia de grabador; no se garantiza independencia entre grabadores o derivados sin relación registrada.")
        reasons = Counter(entry["reason"] for entry in excluded)
        if reasons["not_local"]:
            warnings.append(f"Se excluyen {reasons['not_local']} audios sin copia local.")
        if reasons["feedback_without_source_group"]:
            warnings.append(f"Se excluyen {reasons['feedback_without_source_group']} aportes de corrección sin grupo de origen trazable.")
        for label in sorted({entry["clase"] for entry in entries}):
            if not any(entry["clase"] == label and entry["split"] == "val" for entry in entries):
                warnings.append(f"La clase {label} solo tiene representación en entrenamiento.")
        counts = {split: sum(entry["split"] == split for entry in entries) for split in ("train", "val")}
        if not all(counts.values()):
            raise PartitionError("Se necesitan audios suficientes para entrenamiento y validación sin compartir grupos.")
        spec = {"format": 1, "dataset": self.dataset.nombre, "dataset_id": self.dataset.id_conjunto_datos,
                "storage_uri": prefix,
                "policy": {"algorithm": "grouped-hash-v1", "validation_percent": validation_percent, "seed": seed},
                "counts": counts, "entries": entries, "excluded": excluded, "warnings": warnings}
        return {**spec, "version": hashlib.sha256(_encoded(spec)).hexdigest()}

    def read(self, version):
        self._safe_directory()
        if not re.fullmatch(r"[0-9a-f]{64}", version):
            raise PartitionError("Identificador de versión inválido.")
        path = self.directory / f"{version}.json"
        if not path.exists():
            raise PartitionError("La versión seleccionada no está disponible en este equipo.")
        try:
            safe = resolve_reference(f".partitions/{version}.json", "raw", self.roots)
            manifest = json.loads(safe.read_text(encoding="utf-8"))
            spec = {key: value for key, value in manifest.items() if key not in {"version", "created_at", "created_by"}}
            if (hashlib.sha256(_encoded(spec)).hexdigest() != version or manifest["version"] != version
                    or manifest["dataset_id"] != self.dataset.id_conjunto_datos or manifest["dataset"] != self.dataset.nombre
                    or manifest["storage_uri"] != self.dataset.ruta_gcp.rstrip("/") + "/"):
                raise ValueError()
            return manifest
        except (ValueError, KeyError, TypeError, AttributeError):
            raise PartitionError("La versión de particiones está dañada o pertenece a otro dataset.") from None

    def versions(self):
        self._safe_directory()
        paths = sorted(self.directory.glob("*.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True)[:50]
        return [{key: value for key, value in self.read(path.stem).items() if key not in {"entries", "excluded"}}
                for path in paths]

    def training_source(self, version):
        import pandas as pd

        manifest = self.read(version)
        verify_partition_files(manifest, self.roots)
        registered = {row.id_audio: row for row in self.db.query(Audio).filter_by(id_conjunto_datos=self.dataset.id_conjunto_datos).all()}
        prefix = self.dataset.ruta_gcp.rstrip("/") + "/"
        for entry in manifest["entries"]:
            row = registered.get(entry["audio_id"])
            if (row is None or row.clase != entry["clase"] or row.ruta_gcp != prefix + entry["file_path"]
                    or row.hash_archivo and row.hash_archivo != entry["hash_sha256"]):
                raise PartitionError("El registro de un audio cambió desde esta versión; revisa la selección.")
        frame = pd.DataFrame(manifest["entries"])
        return {"raw_dir": self.raw, "roots": self.roots, "train_df": frame[frame["split"] == "train"].copy(),
                "val_df": frame[frame["split"] == "val"].copy(), "partition_manifest": manifest}

    def save(self, validation_percent, seed, preview_version, acknowledge_warnings, actor_id):
        manifest = self.preview(validation_percent, seed)
        if manifest["version"] != preview_version:
            raise PartitionError("Los audios o metadatos cambiaron. Genera otra vista previa antes de guardar.")
        if manifest["warnings"] and not acknowledge_warnings:
            raise PartitionError("Revisa y acepta las advertencias de procedencia antes de guardar.")
        manifest.update(created_by=actor_id, created_at=datetime.now(timezone.utc).isoformat())
        self.directory.mkdir(exist_ok=True)
        destination = self.directory / f"{manifest['version']}.json"
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.directory, prefix=".pending-", delete=False) as stream:
                temporary = stream.name
                stream.write(_encoded(manifest))
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, destination)
            except FileExistsError:
                return self.read(manifest["version"])
            if hasattr(os, "O_DIRECTORY"):
                descriptor = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            return manifest
        finally:
            if temporary is not None:
                os.unlink(temporary)
