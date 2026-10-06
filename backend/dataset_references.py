"""Validate explicit dataset references without application or ML dependencies.

Persist only ``file_path`` (relative POSIX text) and ``file_stage`` (raw/processed).
Callers supply absolute physical roots, without pre-resolving symlinks. Only the
selected root is checked; missing declarations never trigger discovery/fallback.
File format, nonempty content, labels, hashes and source identity are caller-owned.
These checks describe the filesystem at validation time, not a locked snapshot.
"""

from collections.abc import Mapping
from pathlib import Path
import stat
import unicodedata


def _relative_path(value: str) -> str:
    if (not isinstance(value, str) or not value
            or "\\" in value or ":" in value
            or any(unicodedata.category(char) == "Cc" for char in value)
            or any(part in ("", ".", "..") for part in value.split("/"))):
        raise ValueError("file_path must be a canonical relative POSIX path")
    return value


def _stage_root(file_stage: str, roots: Mapping[str, str | Path]) -> Path:
    if not isinstance(file_stage, str) or file_stage not in ("raw", "processed"):
        raise ValueError("file_stage must be raw or processed")
    if not isinstance(roots, Mapping) or file_stage not in roots:
        raise ValueError("root must be explicitly declared for file_stage")
    value = roots[file_stage]
    root = _absolute_path(value, "root")
    _reject_symlinks(root)
    try:
        if not root.is_dir():
            raise ValueError("root must be an existing physical directory")
    except OSError:
        raise ValueError("root cannot be physically verified") from None
    return root


def _absolute_path(value: str | Path, field: str) -> Path:
    if not isinstance(value, (str, Path)):
        raise ValueError(f"{field} must be an absolute POSIX path")
    text = str(value)
    if not text.startswith("/"):
        raise ValueError(f"{field} must be an absolute POSIX path")
    try:
        if text != "/":
            _relative_path(text[1:])
    except ValueError:
        raise ValueError(f"{field} must be a canonical absolute POSIX path") from None
    return Path(text)


def _reject_symlinks(path: Path) -> None:
    # Inspect the original spelling, not a resolved path that hides aliases.
    for entry in (path, *path.parents):
        try:
            mode = entry.lstat().st_mode
        except FileNotFoundError:
            continue
        except OSError:
            raise ValueError("reference ancestors cannot be physically verified") from None
        if stat.S_ISLNK(mode):
            raise ValueError("reference and root ancestors must not be symlinks")


def resolve_reference(
    file_path: str, file_stage: str, roots: Mapping[str, str | Path]
) -> Path:
    """Validate fields and return an absolute Path for in-memory use only.

    Reject noncanonical text, symlinks in every ancestor (including above the
    root), missing files and nonregular files before returning. Invalid fields,
    configuration and unverifiable filesystem entries raise sanitized ValueError.
    No extension, directory name or filename determines the stage.
    """
    relative = _relative_path(file_path)
    root = _stage_root(file_stage, roots)
    candidate = root / relative
    _reject_symlinks(candidate)
    try:
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root) or not stat.S_ISREG(resolved.stat().st_mode):
            raise ValueError("file_path must identify a regular file under its stage root")
    except (OSError, RuntimeError):
        raise ValueError("file_path cannot be physically verified under its stage root") from None
    return resolved


def reference_from_path(
    path: str | Path, file_stage: str, roots: Mapping[str, str | Path]
) -> dict[str, str]:
    """Produce persistable fields from an existing absolute path in a declared stage.

    Directory discovery belongs to the producer; no stage or root is inferred here.
    """
    root = _stage_root(file_stage, roots)
    candidate = _absolute_path(path, "path")
    try:
        relative = candidate.relative_to(root).as_posix()
    except ValueError:
        raise ValueError("path must be under its declared stage root") from None
    resolve_reference(relative, file_stage, roots)
    return {"file_path": relative, "file_stage": file_stage}
