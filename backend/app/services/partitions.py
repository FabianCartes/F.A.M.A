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
from app.models.feedback import Retroalimentacion
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
    def _split(entries, validation_percent, seed, test_percent, inherited=None):
        """Assign whole groups to splits; ``inherited`` (audio_id -> split) pins groups of a base version."""
        inherited = inherited or {}
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
            for kind in ("hash_sha256", "source_group", "recordist", "origin"):
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
        candidates, assigned = [], {}
        for group in groups.values():
            identity = min(entry["hash_sha256"] for entry in group)
            for entry in group:
                entry["source_group_id"] = identity
            key = hashlib.sha256(f"{seed}:{identity}".encode()).hexdigest()
            pinned = {inherited[entry["audio_id"]] for entry in group if entry["audio_id"] in inherited}
            if len(pinned) > 1:
                raise PartitionError("Los audios nuevos unen grupos que estaban en distintos repartos; "
                                     "prepara una versión desde cero.")
            if pinned:
                assigned[key] = pinned.pop()
            else:
                candidates.append((key, group))
        candidates.sort()
        totals = Counter(entry["clase"] for entry in entries)
        remaining = totals.copy()
        pinned_counts = {split: Counter() for split in ("train", "val", "test")}
        for group in groups.values():
            split = assigned.get(hashlib.sha256(f"{seed}:{group[0]['source_group_id']}".encode()).hexdigest())
            if split:
                pinned_counts[split].update(entry["clase"] for entry in group)
        remaining.subtract(pinned_counts["val"] + pinned_counts["test"])
        for split, percent in (("test", test_percent), ("val", validation_percent)):
            targets = {label: max(1, round(count * percent / 100)) for label, count in totals.items()}
            selected = pinned_counts[split].copy()
            while candidates:
                options = []
                for key, group in candidates:
                    counts = Counter(entry["clase"] for entry in group)
                    if any(remaining[label] <= count for label, count in counts.items()):
                        continue
                    missing = sum(selected[label] == 0 for label in counts)
                    gain = sum(abs(targets[label] - selected[label]) - abs(targets[label] - selected[label] - count)
                               for label, count in counts.items())
                    if missing or gain > 0:
                        options.append((-missing, -gain, key, group, counts))
                if not options:
                    break
                _, _, key, group, counts = min(options, key=lambda item: item[:3])
                assigned[key] = split
                selected.update(counts)
                remaining.subtract(counts)
                candidates = [(candidate, rows) for candidate, rows in candidates if candidate != key]
        for group in groups.values():
            key = hashlib.sha256(f"{seed}:{group[0]['source_group_id']}".encode()).hexdigest()
            for entry in group:
                entry["split"] = assigned.get(key, "train")

    def preview(self, validation_percent=20, seed=42, test_percent=20, base_version=None):
        if not (10 <= validation_percent <= 40 and 10 <= test_percent <= 40 and validation_percent + test_percent <= 60):
            raise PartitionError("Validación y prueba deben dejar al menos 40 % para entrenamiento.")
        base = self.read(base_version) if base_version else None
        if base is not None:
            policy = base.get("policy", {})
            if base.get("format") != 2 or (policy.get("validation_percent"), policy.get("test_percent"), policy.get("seed")) != (
                    validation_percent, test_percent, seed):
                raise PartitionError("La versión actualizada conserva la semilla y los porcentajes de una versión base "
                                     "con prueba independiente.")
        self._safe_directory()
        if not self.raw.is_dir():
            raise PartitionError("Descarga los audios del dataset antes de preparar particiones.")
        prefix = self.dataset.ruta_gcp.rstrip("/") + "/"
        rows = self.db.query(Audio).filter_by(id_conjunto_datos=self.dataset.id_conjunto_datos).order_by(Audio.ruta_gcp).limit(10001).all()
        if len(rows) > 10000:
            raise PartitionError("Esta preparación admite hasta 10000 audios registrados por dataset.")
        entries, excluded = [], []
        provenance = self._provenance()
        # Accepted feedback carries no recordist; its origin comes from the database:
        # the prediction it came from, or the dataset recording it corrects (ADR 0080).
        feedback_origins = {sync.local_relative_path.removeprefix(self.dataset.nombre + "/"): feedback.id_prediccion
                            for sync, feedback in self.db.query(FeedbackSync, Retroalimentacion)
                            .join(Retroalimentacion, Retroalimentacion.id_retroalimentacion == FeedbackSync.id_retroalimentacion)
                            .filter(FeedbackSync.dataset_name == self.dataset.nombre).all()}
        corrected = {_identity(row.get("curation_source_id")) for path, row in provenance.items()
                     if path in feedback_origins} - {""}
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
            origin = ""
            if relative in feedback_origins:
                source = _identity(observed.get("curation_source_id"))
                origin = f"recording:{source}" if source else (
                    f"prediction:{feedback_origins[relative]}" if feedback_origins[relative] else "")
                if not origin and not _identity(observed.get("source_group")):
                    excluded.append({"file_path": relative, "reason": "feedback_without_source_group"})
                    continue
            elif _identity(observed.get("xc_id")) in corrected:
                origin = f"recording:{_identity(observed.get('xc_id'))}"
            entries.append({"audio_id": row.id_audio, "file_path": relative, "file_stage": "raw", "clase": row.clase,
                            "hash_sha256": digest, "size_bytes": path.stat().st_size})
            if observed.get("clase") and observed["clase"] != row.clase:
                raise PartitionError("La clase de los metadatos no coincide con el registro del audio.")
            for field in ("source_group", "recordist"):
                entries[-1][field] = _identity(observed.get(field))
            if origin:
                entries[-1]["origin"] = origin
        inherited = {}
        if base is not None:
            current = {(entry["audio_id"], entry["hash_sha256"], entry["clase"]) for entry in entries}
            inherited = {entry["audio_id"]: entry["split"] for entry in base["entries"]
                         if (entry["audio_id"], entry["hash_sha256"], entry["clase"]) in current}
        self._split(entries, validation_percent, seed, test_percent, inherited)
        warnings = []
        if base is not None and len(inherited) < len(base["entries"]):
            warnings.append(f"{len(base['entries']) - len(inherited)} audios de la versión base cambiaron o ya no están "
                            "disponibles y no se incluyen.")
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
        counts = {split: sum(entry["split"] == split for entry in entries) for split in ("train", "val", "test")}
        if not all(counts.values()):
            raise PartitionError("Se necesitan audios suficientes para entrenamiento, validación y prueba sin compartir grupos.")
        spec = {"format": 2, "dataset": self.dataset.nombre, "dataset_id": self.dataset.id_conjunto_datos,
                "storage_uri": prefix,
                "policy": {"algorithm": "grouped-hash-v2", "validation_percent": validation_percent, "test_percent": test_percent, "seed": seed,
                           **({"algorithm": "grouped-incremental-v1", "base_version": base_version} if base is not None else {})},
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

    def review(self):
        """Read-only summary before partitioning (thresholds: decision 3 of the partitions plan)."""
        from statistics import median
        self._safe_directory()
        prefix = self.dataset.ruta_gcp.rstrip("/") + "/"
        rows = self.db.query(Audio).filter_by(id_conjunto_datos=self.dataset.id_conjunto_datos).order_by(Audio.ruta_gcp).all()
        relative = {row.id_audio: row.ruta_gcp.removeprefix(prefix) for row in rows}
        classes = Counter(row.clase for row in rows)
        missing = [relative[row.id_audio] for row in rows if not (self.raw / relative[row.id_audio]).is_file()]
        by_hash = defaultdict(list)
        for row in rows:
            if row.hash_archivo:
                by_hash[row.hash_archivo].append(relative[row.id_audio])
        duplicates = sorted(sorted(paths) for paths in by_hash.values() if len(paths) > 1)
        durations = defaultdict(list)
        for row in rows:
            if row.duracion_segundos:
                durations[row.clase].append(row.duracion_segundos)
        medians = {label: median(values) for label, values in durations.items()}
        atypical = [{"file_path": relative[row.id_audio], "clase": row.clase, "duration_seconds": row.duracion_segundos,
                     "class_median_seconds": medians[row.clase]}
                    for row in rows if row.duracion_segundos and not
                    0.5 * medians[row.clase] <= row.duracion_segundos <= 3 * medians[row.clase]]
        limit = 50
        return {"total": len(rows), "classes": dict(sorted(classes.items())),
                "not_local": {"count": len(missing), "files": missing[:limit]},
                "duplicates": {"count": len(duplicates), "groups": duplicates[:limit]},
                "small_classes": [{"clase": label, "count": count} for label, count in sorted(classes.items()) if count < 10],
                "atypical_durations": {"count": len(atypical), "files": atypical[:limit]},
                "unknown_durations": sum(not row.duracion_segundos for row in rows)}

    def versions(self):
        self._safe_directory()
        paths = sorted(self.directory.glob("*.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True)[:50]
        if not paths:
            return []
        prefix = self.dataset.ruta_gcp.rstrip("/") + "/"
        registered = {row.id_audio: (row.hash_archivo, row.clase, row.ruta_gcp.removeprefix(prefix))
                      for row in self.db.query(Audio).filter_by(id_conjunto_datos=self.dataset.id_conjunto_datos).all()}
        listed = []
        for path in paths:
            manifest = self.read(path.stem)
            included = {entry["audio_id"] for entry in manifest["entries"]}
            excluded = {entry["file_path"] for entry in manifest.get("excluded", [])}
            changed = sum(entry["audio_id"] not in registered or registered[entry["audio_id"]][1] != entry["clase"]
                          or bool(registered[entry["audio_id"]][0]) and registered[entry["audio_id"]][0] != entry["hash_sha256"]
                          for entry in manifest["entries"])
            new = sum(audio_id not in included and relative not in excluded
                      for audio_id, (_, _, relative) in registered.items())
            listed.append({**{key: value for key, value in manifest.items() if key not in {"entries", "excluded"}},
                           "freshness": {"new": new, "changed": changed}})
        return listed

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
        if manifest.get("format") != 2:
            raise PartitionError("Versión histórica 80/20: consérvala para consulta y crea una versión con prueba independiente para entrenar.")
        from app.services.recording_evaluator import LabelledRecording, validate_recording_splits
        import soundfile as sf
        recordings = {}
        for split in ("train", "val", "test"):
            records = []
            for entry in manifest["entries"]:
                if entry["split"] != split: continue
                path = resolve_reference(entry["file_path"], entry["file_stage"], self.roots)
                try:
                    info = sf.info(path)
                    if info.frames <= 0 or info.samplerate <= 0 or info.channels <= 0: raise ValueError()
                except Exception:
                    raise PartitionError("Hay audios no decodificables en esta versión.") from None
                records.append(LabelledRecording(str(entry["audio_id"]), entry["clase"], path,
                    entry["file_path"], entry["file_stage"], entry["source_group_id"]))
            recordings[split] = tuple(records)
        validate_recording_splits(recordings)
        frame = pd.DataFrame(manifest["entries"])
        return {"raw_dir": self.raw, "roots": self.roots, "train_df": frame[frame["split"] == "train"].copy(),
                "val_df": frame[frame["split"] == "val"].copy(),
                "test_df": frame[frame["split"] == "test"].copy(), "recordings": recordings,
                "partition_manifest": manifest}

    def save(self, validation_percent, seed, preview_version, acknowledge_warnings, actor_id, test_percent=20,
             base_version=None):
        manifest = self.preview(validation_percent, seed, test_percent, base_version)
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
