"""Shared opt-in runtime; construction never provisions paths or database state."""
import json
import os
from pathlib import Path
import stat

from fastapi import HTTPException
from app.services.dataset_storage import PhysicalStorage, UNAVAILABLE


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_profile_field")
        result[key] = value
    return result


def runtime_import_service(root, *, attempt_root=None):
    """Select an explicit JSON profile, or preserve the unconfigured service."""
    from app.services.dataset_imports import DatasetImports
    selected = os.environ.get("FAMA_IMPORT_STORAGE_PROFILE")
    if selected is None:
        return DatasetImports(root)
    try:
        path = Path(selected)
        if (not selected or not path.is_absolute() or path != path.resolve(strict=True)
                or any(part.is_symlink() for part in (path, *path.parents))):
            raise ValueError("physical_profile_required")
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError("regular_profile_required")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o022 or info.st_size > 65536):
                raise ValueError("owned_bounded_profile_required")
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError("profile_too_large")
        configuration = json.loads(raw, object_pairs_hook=_unique_fields)
        if (not isinstance(configuration, dict)
                or set(configuration) - {"roots", "pools", "free_floors", "manifest_bytes"}
                or any(not isinstance(configuration.get(key), dict)
                       for key in ("roots", "pools", "free_floors"))):
            raise ValueError("profile_mappings_required")
        policy = PhysicalStorage(**configuration)
        from app.services.dataset_import_worker import _private_root
        for role, value in policy.roots.items():
            if _private_root(str(value)) != value:
                raise ValueError("incompatible_private_root")
        if Path(root) != policy.roots["imports"]:
            raise ValueError("profile_import_root_mismatch")
        if attempt_root is not None and Path(attempt_root) != policy.roots["attempts"]:
            raise ValueError("profile_attempt_root_mismatch")
        return DatasetImports(root, storage_policy=policy)
    except (OSError, ValueError, TypeError, KeyError, RecursionError, StopIteration):
        raise HTTPException(503, UNAVAILABLE) from None
