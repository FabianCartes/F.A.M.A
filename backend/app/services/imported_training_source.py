"""Owner-scoped bridge between immutable imported preparation and training."""

class ImportedSourceError(ValueError):
    def __init__(self, code="source_unavailable", message="Fuente importada no disponible."):
        self.code = code
        super().__init__(message)


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
                datasets = db.query(ImportedDataset).filter_by(owner_id=owner).order_by(ImportedDataset.id).limit(129).all()
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
                        aliases = {"audio_cnn": "AudioCNN", "panns_cnn14": "PANNs-CNN14",
                                   "efficientnet_b0": "EfficientNet-B0", "convnext_nano": "ConvNeXt-Nano",
                                   "resnet34d": "ResNet-34d"}
                        reasons = []
                        try:
                            self.resolve(owner, dataset_id, snapshot_id, version,
                                         architecture=aliases[manifest["profile"]["architecture"]])
                            if not migrated:
                                reasons.append("source_migration_required")
                        except ImportedSourceError as error:
                            reasons.append(error.code)
                        entry["preparations"].append({"snapshot_id": snapshot_id, "prepared_version": version,
                            "eligible": not reasons, "reasons": reasons, "profile": manifest["profile"],
                            "warnings": manifest["warnings"]})
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
