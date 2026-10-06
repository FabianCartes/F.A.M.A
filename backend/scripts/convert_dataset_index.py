"""Offline CSV reference conversion; dry-run by default, never rewrites inputs.

Publication is exclusive per file, not a transaction or a locked filesystem
snapshot. Failed apply may leave owned partial files for operator recovery.
Only declared indices and physical roots are consulted; no audio is decoded.
"""
import argparse
from collections.abc import Mapping
import csv
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import unicodedata

# Support the direct script route as well as the backend namespace module route.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
from dataset_references import reference_from_path, resolve_reference


def _path(value, field):
    if not isinstance(value, (str, Path)):
        raise ValueError(f"{field}: expected absolute canonical path")
    text = str(value)
    if (not text.startswith("/") or "\\" in text or ":" in text
            or any(unicodedata.category(c) == "Cc" for c in text)
            or (text != "/" and any(p in ("", ".", "..") for p in text[1:].split("/")))):
        raise ValueError(f"{field}: expected absolute canonical path")
    return Path(text)


def _physical(path, *, kind):
    for ancestor in reversed((path, *path.parents)):
        try:
            mode = ancestor.lstat().st_mode
        except FileNotFoundError:
            if ancestor == path and kind == "target":
                return
            raise ValueError("missing physical parent or input/root") from None
        if stat.S_ISLNK(mode):
            raise ValueError("symlink path or ancestor is forbidden")
        if ancestor != path and not stat.S_ISDIR(mode):
            raise ValueError("ancestor must be a physical directory")
    if kind == "target":
        raise ValueError("destination already exists")
    if not (stat.S_ISDIR(mode) if kind == "directory" else stat.S_ISREG(mode)):
        raise ValueError(f"expected physical {kind}")


def _basename(value):
    if (not value or value in (".", "..") or any(c in value for c in "/\\:")
            or any(unicodedata.category(c) == "Cc" for c in value)):
        raise ValueError("nombre_archivo must be an explicit safe basename")
    return value


def _find(name, stage, roots):
    root = _path(roots[stage], "root")
    _physical(root, kind="directory")
    matches = []
    def failed(error):
        raise error
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=failed):
        # Compatibility links are not discovery routes, including dangling links.
        dirs[:] = [d for d in dirs if not (Path(directory) / d).is_symlink()]
        if name in files:
            candidate = Path(directory) / name
            if candidate.is_symlink():
                raise ValueError("matching symlink file is forbidden")
            matches.append(candidate)
    if len(matches) != 1:
        raise ValueError("basename must match exactly one physical file in selected root")
    return reference_from_path(matches[0], stage, roots)["file_path"]


def _rows(data, role, stage, roots, suffix):
    try:
        text = data.decode("utf-8-sig", errors="strict")
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(reader)
        if not header or any(not h for h in header) or len(set(header)) != len(header):
            raise ValueError("duplicate or empty header")
        output_header = header + [h for h in ("file_path", "file_stage") if h not in header]
        rows = []
        for number, values in enumerate(reader, start=2):
            try:
                if len(values) != len(header):
                    raise ValueError("ragged CSV row")
                row = dict(zip(header, values))
                selected = row.get("file_stage", stage)
                if selected not in ("raw", "processed"):
                    raise ValueError("file_stage must be nonblank raw or processed")
                if "file_path" in row:
                    relative = row["file_path"]
                else:
                    name = _basename(row.get("nombre_archivo", ""))
                    if suffix and name.endswith(suffix[0]):
                        name = name[:-len(suffix[0])] + suffix[1]
                    relative = _find(name, selected, roots)
                resolve_reference(relative, selected, roots)
                row["file_path"] = relative
                row["file_stage"] = selected
                rows.append(row)
            except (ValueError, OSError) as error:
                raise ValueError(f"{role} row {number}: {error}") from error
        return output_header, rows
    except (UnicodeError, csv.Error, StopIteration) as error:
        raise ValueError(f"{role}: invalid UTF-8 or malformed CSV near row {getattr(locals().get('reader'), 'line_num', 1)}") from error
    except ValueError as error:
        raise ValueError(f"{role}: {error}") from error


def convert_indices(inputs, candidates, snapshots, *, stage, roots,
                    legacy_suffix=None, apply=False):
    """Plan or exclusively publish metadata or the complete train/val/test trio.

    All three mappings have identical role keys and explicit absolute paths.
    Return JSON-serializable rows/counts/destinations. Roots are copied once.
    Exact basename matching is default; suffix replacement is opt-in lookup only.
    ValueError/OSError signal rejected plans or publication failures. No mkdir,
    rollback deletion, overwrite, lock, discovery of indices, or hash calculation.
    """
    if stage not in ("raw", "processed"):
        raise ValueError("stage must be raw or processed")
    if not all(isinstance(m, Mapping) for m in (inputs, candidates, snapshots, roots)):
        raise ValueError("indices and roots must be explicit mappings")
    inputs, candidates, snapshots, roots = map(dict, (inputs, candidates, snapshots, roots))
    roles = set(inputs)
    if roles not in ({"metadata"}, {"train", "val", "test"}) or roles != set(candidates) or roles != set(snapshots):
        raise ValueError("roles must be metadata OR complete train/val/test with equal mapping keys")
    if set(roots) != {"raw", "processed"}:
        raise ValueError("declare raw and processed roots explicitly")
    roots = {s: _path(p, "root") for s, p in roots.items()}
    # The chosen root must be safe even for an empty CSV. Unused roots may be absent.
    _physical(roots[stage], kind="directory")
    if legacy_suffix is not None:
        if (not isinstance(legacy_suffix, (tuple, list)) or len(legacy_suffix) != 2
                or any(not isinstance(s, str) or not re.fullmatch(r"\.[A-Za-z0-9]+", s) for s in legacy_suffix)):
            raise ValueError("legacy_suffix must contain two dot extensions")
        legacy_suffix = tuple(legacy_suffix)
    paths = []
    for mapping, kind in ((inputs, "file"), (candidates, "target"), (snapshots, "target")):
        for role in inputs:
            mapping[role] = _path(mapping[role], f"{role} {kind}")
            paths.append(mapping[role])
    for i, path in enumerate(paths):
        for other in paths[:i]:
            if path == other or path in other.parents or other in path.parents:
                raise ValueError("input/output/snapshot path or ancestor collision")
    for mapping, kind in ((inputs, "file"), (candidates, "target"), (snapshots, "target")):
        for path in mapping.values():
            _physical(path, kind=kind)
    identities = [(p.stat().st_dev, p.stat().st_ino) for p in inputs.values()]
    if len(set(identities)) != len(identities):
        raise ValueError("hardlink input alias collision")
    originals = {role: path.read_bytes() for role, path in inputs.items()}
    plan = {"apply": bool(apply), "indices": {}}
    generated = {}
    for role in inputs:
        header, rows = _rows(originals[role], role, stage, roots, legacy_suffix)
        plan["indices"][role] = {"input": str(inputs[role]), "candidate": str(candidates[role]),
                                 "snapshot": str(snapshots[role]), "count": len(rows), "rows": rows}
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
        generated[role] = stream.getvalue().encode("utf-8")
    if not apply:
        return plan
    # Recheck the entire group before the first write; still not a filesystem lock.
    for role, path in inputs.items():
        _physical(path, kind="file")
        if path.read_bytes() != originals[role]:
            raise ValueError(f"{role}: input bytes changed during preflight")
        _, rows = _rows(originals[role], role, stage, roots, legacy_suffix)
        if rows != plan["indices"][role]["rows"]:
            raise ValueError(f"{role}: references changed during preflight")
    for path in (*candidates.values(), *snapshots.values()):
        _physical(path, kind="target")
    for role in inputs:
        for path, data in ((snapshots[role], originals[role]), (candidates[role], generated[role])):
            _physical(path, kind="target")
            # xb excludes competitors; failures intentionally retain partial outputs.
            with path.open("xb") as output:
                output.write(data)
    return plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", action="append", nargs=4, required=True,
                        metavar=("ROLE", "INPUT", "CANDIDATE", "SNAPSHOT"))
    parser.add_argument("--stage", choices=("raw", "processed"), required=True)
    parser.add_argument("--raw-root", required=True)
    parser.add_argument("--processed-root", required=True)
    parser.add_argument("--legacy-suffix", nargs=2, metavar=("FROM", "TO"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    inputs, candidates, snapshots = {}, {}, {}
    try:
        for role, source, candidate, snapshot in args.index:
            if role in inputs:
                raise ValueError(f"duplicate role: {role}")
            inputs[role], candidates[role], snapshots[role] = source, candidate, snapshot
        report = convert_indices(inputs, candidates, snapshots, stage=args.stage,
                                 roots={"raw": args.raw_root, "processed": args.processed_root},
                                 legacy_suffix=args.legacy_suffix, apply=args.apply)
    except (ValueError, OSError) as error:
        parser.exit(1, f"conversion rejected: {error}\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
