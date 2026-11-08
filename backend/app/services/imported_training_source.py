"""Owner-scoped bridge between immutable imported preparation and training."""

class ImportedSourceError(ValueError):
    def __init__(self, code="source_unavailable", message="Fuente importada no disponible."):
        self.code = code
        super().__init__(message)


def validate_imported_checkpoint(payload):
    """Validate the explicit imported identity; never apply legacy name defaults.

    This checks checkpoint self-consistency. Publication must additionally match
    the durable model/source association in its database transaction.
    """
    import re
    from training.imported_dataset_preparation import _profile
    name = payload.get("dataset_name")
    if "imported_source" not in payload and not str(name).startswith("imported:"):
        return None
    try:
        identity = payload["imported_source"]
        if type(identity) is not dict or type(identity.get("owner_id")) is not int or identity["owner_id"] <= 0:
            raise ValueError()
        for key, length in (("dataset_id", 32), ("snapshot_id", 32),
                            ("snapshot_manifest_sha256", 64), ("preparation_version", 64)):
            if type(identity.get(key)) is not str or not re.fullmatch("[0-9a-f]{%d}" % length, identity[key]):
                raise ValueError()
        classes = identity["classes"]
        if (type(classes) is not list or not classes or
                any(type(c) is not str or not c.strip() for c in classes) or
                len(set(classes)) != len(classes) or
                payload.get("classes") != classes or
                identity["class_to_index"] != {c: i for i, c in enumerate(classes)} or
                any(type(v) is not int for v in identity["class_to_index"].values()) or
                type(identity.get("provenance")) is not dict or not identity["provenance"]):
            raise ValueError()
        profile = identity["profile"]
        aliases = {"AudioCNN": "audio_cnn", "PANNs-CNN14": "panns_cnn14",
                   "EfficientNet-B0": "efficientnet_b0", "ConvNeXt-Nano": "convnext_nano",
                   "ResNet-34d": "resnet34d"}
        if (_profile(profile) != profile or payload.get("dataset_id") is not None or
                name != "imported:" + identity["dataset_id"] or
                aliases.get(payload.get("architecture")) != profile["architecture"] or
                payload.get("audio_config") != profile["audio"] or
                payload.get("windowing_config") != {"hop_seconds": profile["window_hop_seconds"],
                    "aggregation_mode": "max", "gem_p": 3.0, "vad_threshold": 0.0}):
            raise ValueError()
        return identity
    except Exception as error:
        raise ImportedSourceError("checkpoint_identity", "Identidad del checkpoint importado inválida.") from error


def configured_sources(sessions):
    """Resolve only explicit server roots, lazily on imported-resource access."""
    import os
    from pathlib import Path
    from app.services.dataset_imports import DatasetImports
    from app.services.training_snapshots import TrainingSnapshots
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    names = ("FAMA_IMPORT_ROOT", "FAMA_TRAINING_SNAPSHOT_ROOT", "FAMA_IMPORTED_PREPARED_ROOT")
    roots = [os.environ.get(name) for name in names]
    if any(not value or not Path(value).is_absolute() for value in roots):
        raise ImportedSourceError()
    snapshots = TrainingSnapshots(sessions, DatasetImports(roots[0]), roots[1])
    return ImportedTrainingSource(ImportedDatasetPreparation(snapshots, roots[2]))


class ImportedTrainingSource:
    def __init__(self, preparations):
        self.preparations = preparations

    def catalog(self, owner):
        import os
        import re
        from scripts.migrate_imported_training_source import validate_imported_sources
        from app.models.dataset_import import ImportedDataset
        from app.models.training_snapshot import TrainingSnapshot
        from app.services.training_snapshots import _root_directory
        if type(owner) is not int or owner <= 0:
            raise ImportedSourceError()
        try:
            with self.preparations.snapshots.sessions() as db:
                from app.services.dataset_import_archive import require_schema
                require_schema(db)
                datasets = db.query(ImportedDataset).filter_by(owner_id=owner, archived=False).order_by(ImportedDataset.id).limit(129).all()
                snapshots = db.query(TrainingSnapshot).filter_by(owner_id=owner, state="ready").order_by(TrainingSnapshot.id).limit(129).all()
                try:
                    validate_imported_sources(db.get_bind())
                    migrated = True
                except RuntimeError:
                    migrated = False
                entries = [{"source_type": "imported", "id": d.id, "name": d.name,
                            "eligible": False, "reasons": ["preparation_required"], "preparations": []}
                           for d in datasets]
                snapshot_choices = [(s.id, s.dataset_id) for s in snapshots]
            if len(datasets) > 128 or len(snapshot_choices) > 128:
                raise ImportedSourceError("catalog_budget", "Catálogo importado excede el límite de consulta.")
            with _root_directory(self.preparations.root) as fd:
                versions = sorted(name for name in os.listdir(fd) if re.fullmatch("[0-9a-f]{64}", name))
            if len(versions) > 512:
                raise ImportedSourceError("catalog_budget", "Catálogo importado excede el límite de consulta.")
            for entry in entries:
                for snapshot_id, dataset_id in snapshot_choices:
                    if dataset_id != entry["id"]:
                        continue
                    for version in versions:
                        try:
                            manifest = self.preparations.get(owner, snapshot_id, version)
                        except Exception:
                            continue  # Never disclose another owner's preparation.
                        reasons = []
                        try:
                            # Catalog eligibility covers metadata only. Training admission
                            # still exhausts verified audio and validates split semantics.
                            from training.imported_dataset_preparation import _profile
                            snapshot = self.preparations.snapshots.get(owner, snapshot_id)
                            with self.preparations.snapshots.sessions() as db:
                                dataset = db.get(ImportedDataset, dataset_id)
                                if (dataset is None or dataset.owner_id != owner
                                        or snapshot["dataset_id"] != dataset.id):
                                    raise ImportedSourceError()
                                if snapshot["dataset_revision"] != dataset.revision:
                                    raise ImportedSourceError("preparation_stale")
                            if _profile(manifest["profile"]) != manifest["profile"]:
                                raise ImportedSourceError()
                            if not migrated:
                                reasons.append("source_migration_required")
                        except ImportedSourceError as error:
                            reasons.append(error.code)
                        except Exception:
                            reasons.append("source_unavailable")
                        entry["preparations"].append({"snapshot_id": snapshot_id, "prepared_version": version,
                            "eligible": not reasons, "reasons": reasons, "profile": manifest["profile"],
                            "warnings": manifest["warnings"], "seed": manifest["seed"],
                            "policy": manifest["policy"], "provenance": manifest["provenance"]})
                entry["eligible"] = any(p["eligible"] for p in entry["preparations"])
                if entry["preparations"]:
                    entry["reasons"] = [] if entry["eligible"] else sorted({r for p in entry["preparations"] for r in p["reasons"]})
            return entries
        except ImportedSourceError:
            raise
        except Exception as error:
            raise ImportedSourceError() from error

    def model_source(self, owner, model_id):
        from app.models.imported_training_source import ImportedModelSource
        if type(owner) is not int or owner <= 0:
            raise ImportedSourceError()
        try:
            with self.preparations.snapshots.sessions() as db:
                row = db.get(ImportedModelSource, model_id)
                if row is None or row.owner_id != owner:
                    raise ImportedSourceError()
                return dict(row.identity)
        except Exception as error:
            raise ImportedSourceError() from error

    def resolve_for_training(self, owner, dataset_id, snapshot_id, version, **options):
        """Admit the current source under the shared archive gate.

        The successful active/revision check is the admission linearization point,
        not process start. After this transaction commits, archival may proceed
        while verified source capture and the already-admitted start continue.
        Historical resolve deliberately does not repeat the admission check.
        """
        from app.models.dataset_import import ImportedDataset
        if type(owner) is not int or owner <= 0:
            raise ImportedSourceError()
        try:
            snapshot = self.preparations.snapshots.get(owner, snapshot_id)
            with self.preparations.snapshots.sessions.begin() as db:
                from app.services.dataset_import_jobs import _gate
                from app.services.dataset_import_archive import require_active
                _gate(db)
                dataset = db.get(ImportedDataset, dataset_id)
                if (dataset is None or dataset.owner_id != owner
                        or snapshot["dataset_id"] != dataset.id):
                    raise ImportedSourceError()
                require_active(db, dataset)
                if snapshot["dataset_revision"] != dataset.revision:
                    raise ImportedSourceError("preparation_stale",
                        "La preparación corresponde a una revisión anterior del dataset. Cree un nuevo "
                        "snapshot, complete la procedencia de todos los audios y vuelva a preparar las particiones.")
            return self.resolve(owner, dataset_id, snapshot_id, version, **options)
        except ImportedSourceError:
            raise
        except Exception as error:
            from fastapi import HTTPException
            if isinstance(error, HTTPException) and error.status_code == 503:
                raise
            raise ImportedSourceError() from error

    def resolve(self, owner, dataset_id, snapshot_id, version, *, architecture,
                audio_config=None, windowing_config=None):
        if type(owner) is not int or owner <= 0:
            raise ImportedSourceError()
        try:
            snapshot = self.preparations.snapshots.get(owner, snapshot_id)
            if snapshot["dataset_id"] != dataset_id:
                raise ImportedSourceError()
            manifest = self.preparations.get(owner, snapshot_id, version)
            profile = manifest["profile"]
            from training.imported_dataset_preparation import _profile
            if _profile(profile) != profile:
                raise ImportedSourceError()
            aliases = {"AudioCNN": "audio_cnn", "PANNs-CNN14": "panns_cnn14",
                       "EfficientNet-B0": "efficientnet_b0", "ConvNeXt-Nano": "convnext_nano",
                       "ResNet-34d": "resnet34d"}
            if aliases.get(architecture) != profile["architecture"]:
                raise ImportedSourceError("profile_conflict", "La arquitectura no coincide con el perfil preparado.")
            if audio_config is not None and any(profile["audio"].get(k) != v for k, v in audio_config.items()):
                raise ImportedSourceError("profile_conflict", "El audio solicitado no coincide con el perfil preparado.")
            if windowing_config is not None and windowing_config != {
                    "hop_seconds": profile["window_hop_seconds"], "aggregation_mode": "max",
                    "gem_p": 3.0, "vad_threshold": 0.0}:
                raise ImportedSourceError("profile_conflict", "Las ventanas no coinciden con el perfil preparado.")
            members = {}
            # Exhaustion is required: T1 verifies bytes, final counts and manifest.
            for member, chunk in self.preparations.snapshots.iter_verified(owner, snapshot_id):
                members[member["member_id"]] = member
            if len(members) != snapshot["file_count"]:
                raise ImportedSourceError()
            class_map = manifest["class_to_index"]
            classes = sorted(class_map, key=class_map.get)
            if ([class_map[c] for c in classes] != list(range(len(classes)))
                    or set(classes) != set(snapshot["classes"])):
                raise ImportedSourceError()
            mapping = {r["member_id"]: r for r in manifest["mapping"]}
            if len(mapping) != len(members) or set(mapping) != set(members):
                raise ImportedSourceError()
            splits, seen, groups, recordings = {}, set(), set(), set()
            for split in ("train", "val", "test"):
                rows = self.preparations.read_split(owner, snapshot_id, version, split)
                split_groups, split_recordings = set(), set()
                if {r["class_name"] for r in rows} != set(classes):
                    raise ImportedSourceError()
                for row in rows:
                    member_id = row["member_id"]
                    member = members[member_id]
                    annotation = mapping[member_id]
                    if (member_id in seen or row["snapshot_id"] != snapshot_id
                            or int(row["class_index"]) != class_map[row["class_name"]]
                            or any(row[k] != str(member[k]) for k in (
                                "class_name", "source_import_id", "stored_name", "original_path",
                                "relative_path", "sha256", "size_bytes"))
                            or any(row[k] != annotation[k] for k in ("recording_id", "group_id"))):
                        raise ImportedSourceError()
                    seen.add(member_id)
                    split_groups.add(row["group_id"])
                    split_recordings.add(row["recording_id"])
                if groups & split_groups or recordings & split_recordings:
                    raise ImportedSourceError()
                groups.update(split_groups)
                recordings.update(split_recordings)
                splits[split] = rows
            if seen != set(members):
                raise ImportedSourceError()
            return {"kind": "imported", "classes": classes, "splits": splits,
                    "snapshot_root": str(self.preparations.snapshots.root),
                    "identity": {"owner_id": owner, "dataset_id": dataset_id,
                        "snapshot_id": snapshot_id, "snapshot_manifest_sha256": snapshot["manifest_sha256"],
                        "preparation_version": version, "profile": profile, "classes": classes,
                        "class_to_index": class_map, "provenance": manifest["provenance"]},
                    "preparation": {"manifest": manifest}}
        except ImportedSourceError:
            raise
        except Exception as error:
            raise ImportedSourceError() from error


class ImportedAudioDataset:
    """Verify the exact admitted bytes before decoding each sample; never zero-fill errors.

    No DB/session/file descriptor crosses spawn. T1's confined opener rejects
    symlink replacements. The bounded spool prevents a hash/read TOCTOU gap.
    """
    def __init__(self, source, split):
        self.source = source
        self.rows = source["splits"][split]

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        import hashlib
        import tempfile
        import torch
        from app.services.training_snapshots import _open
        from training.pipelines.dataset import load_and_resample
        row = self.rows[index]
        identity = self.source["identity"]
        profile = identity["profile"]
        try:
            digest, size = hashlib.sha256(), 0
            with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as verified:
                with _open(self.source["snapshot_root"], identity["snapshot_id"] + "/" + row["member_id"]) as stream:
                    while chunk := stream.read(1024 * 1024):
                        size += len(chunk)
                        if size > min(int(row["size_bytes"]), 512 * 1024**2):
                            raise ImportedSourceError()
                        digest.update(chunk)
                        verified.write(chunk)
                if size != int(row["size_bytes"]) or digest.hexdigest() != row["sha256"]:
                    raise ImportedSourceError()
                verified.seek(0)
                waveform = load_and_resample(verified, profile["audio"]["target_sr"],
                    profile["audio"]["duration_seconds"], hop_seconds=profile["window_hop_seconds"], strict=True)
            return torch.from_numpy(waveform).float(), torch.tensor(int(row["class_index"]), dtype=torch.long)
        except Exception as error:
            raise ImportedSourceError() from error
