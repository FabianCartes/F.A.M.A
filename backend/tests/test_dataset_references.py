from pathlib import Path

import pytest

import dataset_references
from dataset_references import resolve_reference


def test_raw_mp3_resolves_to_absolute_path_in_memory(tmp_path):
    raw = tmp_path / "raw"
    audio = raw / "chucao" / "42.mp3"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"audio")
    assert resolve_reference("chucao/42.mp3", "raw", {"raw": raw}) == audio
    assert audio.is_absolute()


@pytest.mark.parametrize("file_path", [
    None, "", 42, Path("audio.wav"), "/audio.wav", "C:/audio.wav",
    "C:audio.wav", "https://host/audio.wav", "file:///audio.wav",
    "../audio.wav", "class/../audio.wav", "./audio.wav", "class/./audio.wav",
    "class//audio.wav", "class/audio.wav/", "class\\audio.wav",
    "audio\x00.wav", "audio\n.wav", "audio\x7f.wav", "audio\x85.wav",
])
def test_rejects_noncanonical_file_path(tmp_path, file_path):
    with pytest.raises(ValueError, match="file_path"):
        resolve_reference(file_path, "raw", {"raw": tmp_path})


@pytest.mark.parametrize("stage", [None, "", "legacy", "RAW", " raw", 1, []])
def test_requires_known_stage(tmp_path, stage):
    with pytest.raises(ValueError, match="file_stage"):
        resolve_reference("audio.wav", stage, {"raw": tmp_path})


@pytest.mark.parametrize("roots", [{}, {"processed": "/unused"}, None, []])
def test_requires_declared_stage_root(roots):
    with pytest.raises(ValueError, match="root"):
        resolve_reference("audio.wav", "raw", roots)


@pytest.mark.parametrize("root", [None, 1, "", "relative", "C:/root", "file:///root"])
def test_rejects_invalid_root_value(root):
    with pytest.raises(ValueError, match="root"):
        resolve_reference("audio.wav", "raw", {"raw": root})


@pytest.mark.parametrize("kind", ["missing", "file", "dot", "traversal", "separator"])
def test_requires_physical_canonical_root(tmp_path, kind):
    root = tmp_path / "root"
    if kind == "file":
        root.write_bytes(b"not a directory")
    elif kind != "missing":
        root.mkdir()
        root = {"dot": f"{root}/.", "traversal": f"{root}/../root",
                "separator": f"{tmp_path}//root"}[kind]
    with pytest.raises(ValueError, match="root"):
        resolve_reference("audio.wav", "raw", {"raw": root})


@pytest.mark.parametrize("kind", ["file", "internal", "dangling", "root", "ancestor", "compat"])
def test_rejects_symlinks_before_resolution(tmp_path, kind):
    raw = tmp_path / "raw"
    raw.mkdir()
    physical = tmp_path / "processed" / "processed_wav"
    physical.mkdir(parents=True)
    (physical / "audio.wav").write_bytes(b"audio")
    reference = "audio.wav"
    if kind == "file":
        (raw / reference).symlink_to(physical / "audio.wav")
    elif kind == "internal":
        (raw / "real").mkdir()
        (raw / "real" / reference).write_bytes(b"audio")
        (raw / "alias").symlink_to(raw / "real", target_is_directory=True)
        reference = "alias/audio.wav"
    elif kind == "dangling":
        (raw / "alias").symlink_to(tmp_path / "missing", target_is_directory=True)
        reference = "alias/audio.wav"
    elif kind == "root":
        alias = tmp_path / "alias"
        alias.symlink_to(physical, target_is_directory=True)
        raw = alias
    elif kind == "ancestor":
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path / "processed", target_is_directory=True)
        raw = alias / "processed_wav"
    else:
        (raw / "processed_wav").symlink_to(physical, target_is_directory=True)
        reference = "processed_wav/audio.wav"
    with pytest.raises(ValueError, match="symlink"):
        resolve_reference(reference, "raw", {"raw": raw, "processed": physical})


@pytest.mark.parametrize("kind", ["missing", "directory", "wrong_stage"])
def test_requires_regular_file_in_selected_stage(tmp_path, kind):
    raw = tmp_path / "raw"
    processed = tmp_path / "processed" / "processed_wav"
    raw.mkdir()
    processed.mkdir(parents=True)
    if kind == "directory":
        (raw / "audio.wav").mkdir()
    elif kind == "wrong_stage":
        (processed / "audio.wav").write_bytes(b"audio")
    with pytest.raises(ValueError, match="file"):
        resolve_reference("audio.wav", "raw", {"raw": raw, "processed": processed})


@pytest.mark.parametrize("stage, relative", [
    ("raw", "chucao/42.mp3"), ("raw", "Chucao/feedback_6.wav"),
    ("processed", "chucao/42.wav"),
])
def test_producer_serializes_relative_fields(tmp_path, stage, relative):
    roots = {"raw": tmp_path / "raw",
             "processed": tmp_path / "processed" / "processed_wav"}
    audio = roots[stage] / relative
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"audio")
    fields = dataset_references.reference_from_path(audio, stage, roots)
    assert fields == {"file_path": relative, "file_stage": stage}
    assert resolve_reference(**fields, roots=roots) == audio


def test_same_reference_is_portable_between_physical_roots(tmp_path):
    fields = {"file_path": "chucao/42.wav", "file_stage": "processed"}
    for deployment in ("host", "container"):
        root = tmp_path / deployment / "processed_wav"
        audio = root / "chucao" / "42.wav"
        audio.parent.mkdir(parents=True)
        audio.write_bytes(b"audio")
        assert resolve_reference(**fields, roots={"processed": root}) == audio
        assert fields == {"file_path": "chucao/42.wav", "file_stage": "processed"}


@pytest.mark.parametrize("stage", ["raw", "processed"])
def test_content_and_extension_policy_belongs_to_caller(tmp_path, stage):
    audio = tmp_path / "opaque.data"
    audio.write_bytes(b"")
    assert resolve_reference("opaque.data", stage, {stage: tmp_path}) == audio


@pytest.mark.parametrize("kind", ["outside", "relative", "missing", "directory", "symlink", "dot"])
def test_producer_rejects_invalid_actual_path(tmp_path, kind):
    raw = tmp_path / "raw"
    raw.mkdir()
    audio = raw / "audio.wav"
    if kind == "outside":
        audio = tmp_path / "processed" / "audio.wav"
        audio.parent.mkdir()
        audio.write_bytes(b"audio")
    elif kind == "relative":
        audio = "audio.wav"
    elif kind == "directory":
        audio.mkdir()
    elif kind == "symlink":
        (raw / "real.wav").write_bytes(b"audio")
        audio.symlink_to(raw / "real.wav")
    elif kind == "dot":
        audio.write_bytes(b"audio")
        audio = f"{raw}/./audio.wav"
    with pytest.raises(ValueError):
        dataset_references.reference_from_path(audio, "raw", {"raw": raw})


@pytest.mark.parametrize("dangling", [False, True])
def test_processed_root_cannot_be_raw_compatibility_link(tmp_path, dangling):
    raw = tmp_path / "raw"
    raw.mkdir()
    physical = tmp_path / "processed" / "processed_wav"
    if not dangling:
        physical.mkdir(parents=True)
        (physical / "audio.wav").write_bytes(b"audio")
    compat = raw / "processed_wav"
    compat.symlink_to(physical, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        resolve_reference("audio.wav", "processed", {"processed": compat})


def test_filesystem_errors_do_not_disclose_input(tmp_path):
    private_name = "private-location-" + "a" * 300
    with pytest.raises(ValueError) as failure:
        resolve_reference(private_name, "raw", {"raw": tmp_path})
    assert private_name not in str(failure.value)
    assert failure.value.__suppress_context__
