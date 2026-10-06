"""Public offline conversion tests; all filesystem members are synthetic."""
import csv
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.convert_dataset_index import convert_indices


@pytest.fixture
def operation(tmp_path):
    roots = {stage: tmp_path / stage for stage in ("raw", "processed")}
    for root in roots.values():
        root.mkdir()
    source = tmp_path / "input.csv"
    candidate = tmp_path / "candidate.csv"
    snapshot = tmp_path / "snapshot.csv"
    def run(data, *, stage="raw", apply=False, **kwargs):
        source.write_bytes(data)
        return convert_indices({"metadata": source}, {"metadata": candidate},
                               {"metadata": snapshot}, stage=stage, roots=roots,
                               apply=apply, **kwargs)
    return roots, source, candidate, snapshot, run


def test_dry_run_preserves_text_and_creates_nothing(operation):
    roots, source, candidate, snapshot, run = operation
    (roots["raw"] / "42.wav").write_bytes(b"synthetic")
    original = b'nombre_archivo,xc_id,clase,hash_archivo\r\n42.wav,00042,Chucao,NA\r\n'
    report = run(original)
    assert report["indices"]["metadata"]["rows"][0] == {
        "nombre_archivo": "42.wav", "xc_id": "00042", "clase": "Chucao",
        "hash_archivo": "NA", "file_path": "42.wav", "file_stage": "raw"}
    assert source.read_bytes() == original
    assert not candidate.exists() and not snapshot.exists()


def test_explicit_suffix_is_lookup_only_and_apply_snapshots_original(operation):
    roots, source, candidate, snapshot, run = operation
    audio = roots["processed"] / "Chucao" / "42.wav"
    audio.parent.mkdir()
    audio.write_bytes(b"opaque")
    (audio.parent / "unindexed.wav").write_bytes(b"ignored")
    original = ('\ufeffnombre_archivo,xc_id,clase,hash_archivo,recordist,source_group,empty\r\n'
                '42.mp3,00042,Chucao,NA,"José,\nPérez",0007,\r\n').encode()
    with pytest.raises(ValueError, match="metadata.*row 2"):
        run(original, stage="processed")
    assert not snapshot.exists()
    report = run(original, stage="processed", legacy_suffix=(".mp3", ".wav"), apply=True)
    row = report["indices"]["metadata"]["rows"][0]
    assert row == {"nombre_archivo": "42.mp3", "xc_id": "00042", "clase": "Chucao",
                   "hash_archivo": "NA", "recordist": "José,\nPérez", "source_group": "0007",
                   "empty": "", "file_path": "Chucao/42.wav", "file_stage": "processed"}
    assert source.read_bytes() == snapshot.read_bytes() == original
    with candidate.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == ["nombre_archivo", "xc_id", "clase", "hash_archivo", "recordist",
                                     "source_group", "empty", "file_path", "file_stage"]
        assert list(reader) == [row]
    with pytest.raises(ValueError, match="exists"):
        run(original, stage="processed", legacy_suffix=(".mp3", ".wav"), apply=True)
    assert snapshot.read_bytes() == original


@pytest.mark.parametrize("data", [
    b'nombre_archivo,file_path\n42.wav,\n',
    b'nombre_archivo,file_path\n42.wav,/42.wav\n',
    b'nombre_archivo,file_path\n42.wav,../42.wav\n',
    b'nombre_archivo,file_path\n42.wav,missing.wav\n',
    b'nombre_archivo,file_stage\n42.wav,\n',
    b'nombre_archivo,file_stage\n42.wav,RAW\n',
    b'nombre_archivo\n../42.wav\n', b'nombre_archivo\nclass/42.wav\n',
    b'nombre_archivo\nC:42.wav\n', b'nombre_archivo\n42\\.wav\n',
    b'nombre_archivo\n"42\x00.wav"\n', b'xc_id\n42\n',
    b'nombre_archivo,nombre_archivo\n42.wav,42.wav\n',
    b'nombre_archivo,\n42.wav,Chucao\n', b'nombre_archivo\n42.wav,Chucao\n',
    b'nombre_archivo,clase\n42.wav\n', b'nombre_archivo\n"42.wav\n',
    b'nombre_archivo\n\xff\n', b'',
])
def test_invalid_csv_or_explicit_fields_never_fallback_or_write(operation, data):
    roots, source, candidate, snapshot, run = operation
    (roots["raw"] / "42.wav").write_bytes(b"opaque")
    with pytest.raises(ValueError):
        run(data, apply=True)
    assert source.read_bytes() == data
    assert not candidate.exists() and not snapshot.exists()


def test_mixed_canonical_stages_and_path_only_append(operation):
    roots, source, candidate, snapshot, run = operation
    for root in roots.values():
        (root / "42.wav").write_bytes(b"opaque")
    report = run(b'file_path,file_stage,clase\n42.wav,raw,Chucao\n42.wav,processed,Chucao\n',
                 stage="processed")
    assert [r["file_stage"] for r in report["indices"]["metadata"]["rows"]] == ["raw", "processed"]
    report = run(b'file_path\n42.wav\n')
    assert report["indices"]["metadata"]["rows"] == [{"file_path": "42.wav", "file_stage": "raw"}]


@pytest.mark.parametrize("suffix", [("mp3", ".wav"), (".mp3", "../wav"), (".mp3", ".w:av"),
                                   ("..", ".wav"), (".mp3", ".wa\nv"), (".mp3",)])
def test_suffix_syntax_checked_even_empty_csv(operation, suffix):
    *_, run = operation
    with pytest.raises(ValueError, match="suffix"):
        run(b'nombre_archivo\n', legacy_suffix=suffix)


@pytest.mark.parametrize("kind", ["ambiguous", "file_link", "root_link", "ancestor_link", "missing_root"])
def test_physical_selected_root_and_matches(operation, tmp_path, kind):
    roots, source, candidate, snapshot, run = operation
    physical = roots["raw"]
    (physical / "42.wav").write_bytes(b"opaque")
    if kind == "ambiguous":
        for directory in ("Chucao", "chucao"):
            (physical / directory).mkdir()
            (physical / directory / "42.wav").write_bytes(b"opaque")
    elif kind == "file_link":
        (physical / "Chucao").mkdir()
        (physical / "Chucao" / "42.wav").symlink_to(physical / "42.wav")
    elif kind == "root_link":
        alias = tmp_path / "alias"
        alias.symlink_to(physical, target_is_directory=True)
        roots["raw"] = alias
    elif kind == "ancestor_link":
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path, target_is_directory=True)
        roots["raw"] = alias / "raw"
    else:
        roots["raw"] = tmp_path / "missing"
    with pytest.raises(ValueError):
        run(b'nombre_archivo\n42.wav\n', apply=True)
    assert not candidate.exists() and not snapshot.exists()


def test_unused_missing_root_and_unrelated_compatibility_link(operation, tmp_path):
    roots, source, candidate, snapshot, run = operation
    (roots["raw"] / "42.wav").write_bytes(b"opaque")
    (roots["raw"] / "compat").symlink_to(roots["processed"], target_is_directory=True)
    roots["processed"] = tmp_path / "absent"
    assert run(b'nombre_archivo\n42.wav\n')["indices"]["metadata"]["count"] == 1


@pytest.mark.parametrize("roles", [("train",), ("train", "val"), ("metadata", "train")])
def test_partial_or_mixed_group_zero_writes(operation, roles):
    roots, source, candidate, snapshot, _ = operation
    source.write_bytes(b'file_path\n')
    with pytest.raises(ValueError, match="roles"):
        convert_indices(dict.fromkeys(roles, source), dict.fromkeys(roles, candidate),
                        dict.fromkeys(roles, snapshot), stage="raw", roots=roots, apply=True)
    assert not snapshot.exists() and not candidate.exists()


@pytest.mark.parametrize("bad_last", [False, True])
def test_complete_splits_preserve_members_and_preflight_entire_group(operation, tmp_path, bad_last):
    roots, *_ = operation
    (roots["raw"] / "42.wav").write_bytes(b"opaque")
    inputs, candidates, snapshots = {}, {}, {}
    for role in ("train", "val", "test"):
        inputs[role] = tmp_path / f'{role}.csv'
        candidates[role] = tmp_path / f'{role}.candidate.csv'
        snapshots[role] = tmp_path / f'{role}.snapshot.csv'
        inputs[role].write_bytes(b'nombre_archivo,clase\n42.wav,Chucao\n42.wav,Chucao\n')
    if bad_last:
        inputs["test"].write_bytes(b'nombre_archivo\n42.wav\nmissing.wav\n')
        with pytest.raises(ValueError, match="test.*row 3"):
            convert_indices(inputs, candidates, snapshots, stage="raw", roots=roots, apply=True)
        assert not any(p.exists() for p in (*candidates.values(), *snapshots.values()))
    else:
        result = convert_indices(inputs, candidates, snapshots, stage="raw", roots=roots, apply=True)
        assert [result["indices"][r]["count"] for r in inputs] == [2, 2, 2]
        for role in inputs:
            assert inputs[role].read_bytes() == snapshots[role].read_bytes()
            with candidates[role].open(newline="") as stream:
                assert [r["nombre_archivo"] for r in csv.DictReader(stream)] == ["42.wav", "42.wav"]


@pytest.mark.parametrize("kind", ["existing", "same", "ancestor", "hardlink", "parent", "symlink", "spelling"])
def test_destination_and_input_collisions_reject_before_snapshot(operation, tmp_path, kind):
    roots, source, candidate, snapshot, _ = operation
    source.write_bytes(b'file_path\n')
    target = candidate
    if kind == "existing":
        candidate.write_bytes(b"")
    elif kind == "same":
        target = source
    elif kind == "ancestor":
        target = source / "child.csv"
    elif kind == "hardlink":
        os.link(source, candidate)
    elif kind == "parent":
        target = tmp_path / "absent" / "candidate.csv"
    elif kind == "symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path, target_is_directory=True)
        target = alias / "candidate.csv"
    else:
        target = str(tmp_path) + '/./candidate.csv'
    with pytest.raises(ValueError):
        convert_indices({"metadata": source}, {"metadata": target}, {"metadata": snapshot},
                        stage="raw", roots=roots, apply=True)
    assert not snapshot.exists()
    assert source.read_bytes() == b'file_path\n'
    assert not (tmp_path / "absent").exists()


def test_late_competitor_bytes_preserved_without_fake_transaction(operation, monkeypatch):
    roots, source, candidate, snapshot, run = operation
    (roots["raw"] / "42.wav").write_bytes(b"opaque")
    real_open = Path.open
    def competing_open(path, mode="r", *args, **kwargs):
        if path == candidate and mode == "xb":
            with real_open(path, "xb") as competitor:
                competitor.write(b"competitor")
        return real_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", competing_open)
    original = b'nombre_archivo\n42.wav\n'
    with pytest.raises(FileExistsError):
        run(original, apply=True)
    assert candidate.read_bytes() == b"competitor"
    assert snapshot.read_bytes() == source.read_bytes() == original


@pytest.mark.parametrize("field,value", [("stage", "RAW"), ("stage", ""),
                                            ("root", "relative"), ("root", "/tmp/../tmp")])
def test_empty_indices_cannot_bypass_declaration_validation(operation, field, value):
    roots, source, candidate, snapshot, _ = operation
    source.write_bytes(b'file_path\n')
    stage = value if field == "stage" else "raw"
    if field == "root":
        roots["raw"] = value
    with pytest.raises(ValueError):
        convert_indices({"metadata": source}, {"metadata": candidate}, {"metadata": snapshot},
                        stage=stage, roots=roots, apply=True)
    assert not candidate.exists() and not snapshot.exists()


def test_explicit_reference_cannot_use_compatibility_directory(operation):
    roots, source, candidate, snapshot, run = operation
    (roots["processed"] / "42.wav").write_bytes(b"opaque")
    (roots["raw"] / "compat").symlink_to(roots["processed"], target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        run(b'file_path\ncompat/42.wav\n', apply=True)
    assert not snapshot.exists()


def test_input_byte_change_before_publication_rejects_without_outputs(operation, monkeypatch):
    roots, source, candidate, snapshot, run = operation
    (roots["raw"] / "42.wav").write_bytes(b"opaque")
    real_read = Path.read_bytes
    reads = 0
    def changing_read(path):
        nonlocal reads
        if path == source:
            reads += 1
            if reads == 2:
                source.write_bytes(b'nombre_archivo\nchanged.wav\n')
        return real_read(path)
    monkeypatch.setattr(Path, "read_bytes", changing_read)
    with pytest.raises(ValueError, match="bytes changed"):
        run(b'nombre_archivo\n42.wav\n', apply=True)
    assert not candidate.exists() and not snapshot.exists()


def test_import_is_stdlib_plus_reference_core_only(operation):
    _, source, *_ = operation
    backend = Path(__file__).absolute().parents[1]
    code = ("import sys; import scripts.convert_dataset_index; "
            "assert not any(n.split('.')[0] in "
            "{'app','training','poc','torch','numpy','dotenv','sqlalchemy'} for n in sys.modules)")
    result = subprocess.run([sys.executable, "-c", code], cwd=backend, capture_output=True,
                            text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("route", ["script", "module"])
def test_cli_routes_are_offline_dry_runs(operation, route):
    roots, source, candidate, snapshot, _ = operation
    (roots["raw"] / "42.wav").write_bytes(b"opaque")
    source.write_bytes(b'nombre_archivo\n42.wav\n')
    backend = Path(__file__).absolute().parents[1]
    command = [sys.executable]
    command += [str(backend / "scripts" / "convert_dataset_index.py")] if route == "script" else ["-m", "scripts.convert_dataset_index"]
    args = ["--index", "metadata", str(source), str(candidate), str(snapshot),
            "--stage", "raw", "--raw-root", str(roots["raw"]), "--processed-root", str(roots["processed"])]
    result = subprocess.run(command + args, cwd=source.parent if route == "script" else backend,
                            capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["indices"]["metadata"]["count"] == 1
    assert not candidate.exists() and not snapshot.exists()
    duplicate = subprocess.run(command + args + args[:5], cwd=backend, capture_output=True,
                               text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert duplicate.returncode != 0 and "duplicate role" in duplicate.stderr
