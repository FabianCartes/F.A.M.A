"""Durable composition identity, NOT model admission or registry publication.

create(owner, components, weights) and get(owner, id) return fresh dictionaries
{id: SHA256, manifest: descriptor}. Components are ordered, already-admitted
references: positive integer model_id, registered checkpoint_sha256 and the FULL
unchanged imported_source schema-1 identity. No paths are accepted as references.

The future DB caller MUST independently bind every model ID/hash/source to its
owner's authoritative ImportedModelSource and available checkpoint, verify the
shared evaluation cohort and evaluate these exact weights before publication.
Self-consistency here proves none of those facts. Weight revisions create new
identities; this module neither updates history nor declares availability.
"""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import uuid

from app.services.imported_training_source import validate_imported_checkpoint
from app.services.training_snapshots import _parts, _root_directory


class ImportedTriadManifestError(ValueError):
    """Uniform private failure: absent, foreign, corrupt and unsafe are identical."""
    code = "composition_unavailable"

    def __init__(self):
        super().__init__("Composición importada no disponible.")


# Bound memory/JSON parsing of untrusted descriptors, not a model-size limit.
_MAX_BYTES = 1024 * 1024
_COMMON = ("owner_id", "dataset_id", "snapshot_id", "snapshot_manifest_sha256",
           "classes", "class_to_index")
_ALIASES = {"audio_cnn": "AudioCNN", "panns_cnn14": "PANNs-CNN14",
            "efficientnet_b0": "EfficientNet-B0", "convnext_nano": "ConvNeXt-Nano",
            "resnet34d": "ResNet-34d"}


def _bytes(value):
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")
    if len(data) > _MAX_BYTES:
        raise ValueError()
    return data


def _sha(value):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError()
    return value


class ImportedTriadManifests:
    """Explicit physical private root. Only opaque SHA IDs reach filesystem IO.

    Publication uses an exclusive same-directory staging file and atomic hard
    link (never overwrite). Staging files are intentionally retained: this small
    store has no deletion/GC interface. Operators may manage them separately.
    All root ancestors are opened without following symlinks using snapshot
    helpers; configured roots must be absolute, non-traversing and private.
    """

    def __init__(self, root):
        try:
            raw = os.fspath(root)
            if type(raw) is not str or not raw.startswith("/"):
                raise ValueError()
            _parts(raw[1:])
            self.root = Path(raw)
            with _root_directory(self.root):
                pass
        except Exception:
            raise ImportedTriadManifestError() from None

    def _validate(self, owner, manifest):
        if type(owner) is not int or owner <= 0:
            raise ValueError()
        if (type(manifest) is not dict or set(manifest) != {
                "type", "schema_version", "components", "weights", "cohort"}
                or manifest["type"] != "imported_triad_composition"
                or type(manifest["schema_version"]) is not int
                or manifest["schema_version"] != 1):
            raise ValueError()
        components, weights = manifest["components"], manifest["weights"]
        if (type(components) is not list or len(components) != 3
                or type(weights) is not list or len(weights) != 3
                or any(type(w) not in (int, float) or not math.isfinite(w) or w < 0 for w in weights)
                or not any(w > 0 for w in weights)
                or not math.isclose(sum(weights), 1, rel_tol=0, abs_tol=1e-9)):
            raise ValueError()
        ids, identities = [], []
        for component in components:
            if type(component) is not dict or set(component) != {
                    "model_id", "checkpoint_sha256", "imported_source"}:
                raise ValueError()
            model_id = component["model_id"]
            if type(model_id) is not int or model_id <= 0 or model_id in ids:
                raise ValueError()
            ids.append(model_id)
            _sha(component["checkpoint_sha256"])
            source = component["imported_source"]
            profile = source["profile"]
            validate_imported_checkpoint({"imported_source": source,
                "dataset_name": "imported:" + source["dataset_id"],
                "classes": source["classes"], "architecture": _ALIASES[profile["architecture"]],
                "audio_config": profile["audio"], "windowing_config": {
                    "hop_seconds": profile["window_hop_seconds"], "aggregation_mode": "max",
                    "gem_p": 3.0, "vad_threshold": 0.0}})
            if source["owner_id"] != owner:
                raise ValueError()
            identities.append({key: source[key] for key in _COMMON})
        if any(identity != identities[0] for identity in identities):
            raise ValueError()
        if manifest["cohort"] != identities[0]:
            raise ValueError()
        return manifest

    def create(self, owner, components, weights):
        try:
            # Validate original types before serialization can coerce them.
            manifest = deepcopy({"type": "imported_triad_composition", "schema_version": 1,
                "components": components, "weights": weights,
                "cohort": {key: components[0]["imported_source"][key] for key in _COMMON}})
            self._validate(owner, manifest)
            data = _bytes(manifest)
            if json.loads(data) != manifest:
                raise ValueError()  # Never silently rewrite a source identity's types.
            artifact_id = hashlib.sha256(data).hexdigest()
            with _root_directory(self.root) as root_fd:
                try:
                    os.stat(artifact_id + ".json", dir_fd=root_fd, follow_symlinks=False)
                except FileNotFoundError:
                    staging = ".pending-" + uuid.uuid4().hex
                    fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o400, dir_fd=root_fd)
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                    try:
                        os.link(staging, artifact_id + ".json", src_dir_fd=root_fd,
                                dst_dir_fd=root_fd, follow_symlinks=False)
                    except FileExistsError:
                        pass  # Concurrent publisher: verify its bytes below, never replace.
                    os.fsync(root_fd)
            return self.get(owner, artifact_id)
        except Exception:
            raise ImportedTriadManifestError() from None

    def get(self, owner, artifact_id):
        try:
            _sha(artifact_id)  # Before any IO, including opening the root.
            if type(owner) is not int or owner <= 0:
                raise ValueError()
            with _root_directory(self.root) as root_fd:
                fd = os.open(artifact_id + ".json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=root_fd)
                with os.fdopen(fd, "rb") as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        raise ValueError()
                    data = stream.read(_MAX_BYTES + 1)
            if len(data) > _MAX_BYTES or hashlib.sha256(data).hexdigest() != artifact_id:
                raise ValueError()
            manifest = self._validate(owner, json.loads(data))
            if _bytes(manifest) != data:
                raise ValueError()
            return {"id": artifact_id, "manifest": manifest}
        except Exception:
            raise ImportedTriadManifestError() from None
