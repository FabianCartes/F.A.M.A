"""ZIP import rules at the public validation interface; synthetic WAV bytes only."""
import io
import wave
import zipfile
import stat
from dataclasses import replace
import pytest


def wav_bytes(sample=1):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(sample.to_bytes(2, "little", signed=True) * 80)
    return buffer.getvalue()


def archive(path, entries, compression=zipfile.ZIP_STORED):
    with zipfile.ZipFile(path, "w", compression=compression) as output:
        for name, contents in entries:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)) if isinstance(name, str) else name
            info.compress_type = compression
            output.writestr(info, contents)
    return path


def test_single_valid_wav_preserves_original_bytes_and_session_provenance(tmp_path):
    from app.services.dataset_zip import validate_zip, ImportLimits

    source = archive(tmp_path / "input.zip", [("aves/chucao/session/a.wav", wav_bytes())])
    result = validate_zip(source, tmp_path / "staged", root="aves", limits=ImportLimits())
    assert result["errors"] == []
    assert result["classes"] == ["chucao"]
    assert result["unique_count"] == 1
    assert result["files"][0]["original_path"] == "aves/chucao/session/a.wav"
    assert result["files"][0]["class_name"] == "chucao"
    assert (tmp_path / "staged" / result["files"][0]["stored_name"]).read_bytes() == wav_bytes()


@pytest.mark.parametrize("name,contents", [
    ("../escape.wav", wav_bytes()), ("/escape.wav", wav_bytes()),
    ("C:/a.wav", wav_bytes()), ("birds\\a.wav", wav_bytes()),
    ("birds/../a.wav", wav_bytes()), ("birds//a.wav", wav_bytes()),
    ("birds/./a.wav", wav_bytes()), ("birds/a.zip", b"PK"),
    ("birds/a.txt", b"text"), ("birds/a.wav", b"not audio"),
    ("a.wav", wav_bytes()), ("birds/\x01.wav", wav_bytes()),
], ids=["parent", "absolute", "drive", "backslash", "traversal", "empty_component", "dot",
        "nested_zip", "text", "invalid_wav", "root_audio", "control"])
def test_rejects_unsafe_or_non_wav_entries_with_actionable_relative_errors(tmp_path, name, contents):
    from app.services.dataset_zip import validate_zip, ImportLimits
    source = archive(tmp_path / "input.zip", [(name, contents)])
    result = validate_zip(source, tmp_path / "staged", root="", limits=ImportLimits())
    assert result["errors"]
    assert all(e["action"] and "path" in e for e in result["errors"])
    assert str(tmp_path) not in str(result)
    assert not (tmp_path / "escape.wav").exists()


def test_duplicates_are_explicit_and_fingerprint_ignores_names_wrapper_order_compression(tmp_path):
    from app.services.dataset_zip import validate_zip, ImportLimits
    first = archive(tmp_path / "first.zip", [("wrap/birds/a.wav", wav_bytes()),
        ("wrap/birds/repeat.wav", wav_bytes()), ("wrap/motors/a.wav", wav_bytes(2)), ("wrap/empty/", b"")])
    result = validate_zip(first, tmp_path / "one", root="wrap", limits=ImportLimits())
    second = archive(tmp_path / "renamed.zip", [("motors/new.wav", wav_bytes(2)),
        ("birds/new.wav", wav_bytes())], zipfile.ZIP_DEFLATED)
    other = validate_zip(second, tmp_path / "two", root="", limits=ImportLimits())
    assert result["errors"] == other["errors"] == []
    assert result["unique_count"] == 2
    assert result["duplicate_count"] == 1
    assert len(result["files"]) == 3
    assert result["files"][1]["duplicate"] is True
    assert result["fingerprint"] == other["fingerprint"]
    assert {w["code"] for w in result["warnings"]} >= {"empty_class", "small_class"}


def test_identical_content_with_different_labels_is_a_conflict(tmp_path):
    from app.services.dataset_zip import validate_zip, ImportLimits
    source = archive(tmp_path / "input.zip", [("birds/a.wav", wav_bytes()), ("motors/a.wav", wav_bytes())])
    result = validate_zip(source, tmp_path / "staged", root="", limits=ImportLimits())
    assert result["errors"][0]["code"] == "label_conflict"


def test_corrupt_deflate_member_returns_diagnostics_without_changing_source(tmp_path):
    import struct
    from app.services.dataset_zip import validate_zip, ImportLimits

    source = archive(tmp_path / "input.zip", [("birds/a.wav", wav_bytes())], zipfile.ZIP_DEFLATED)
    content = bytearray(source.read_bytes())
    name_length, extra_length = struct.unpack_from("<HH", content, 26)
    # Reserved DEFLATE block type; retain the valid directory and member header.
    content[30 + name_length + extra_length] = 0x07
    source.write_bytes(content)
    staging = tmp_path / "staged"
    result = validate_zip(source, staging, root="", limits=ImportLimits())
    assert result["files"] == []
    assert result["errors"] == [{"path": "birds/a.wav", "code": "invalid_archive_or_wav",
                                "action": "Corrige la ruta, estructura o contenido y vuelve a subir el ZIP."}]
    assert source.read_bytes() == content
    assert not list(staging.glob("*.wav"))


@pytest.mark.parametrize("kind", ["duplicate", "case", "unicode", "symlink", "special", "corrupt", "empty", "outside_root"])
def test_rejects_ambiguous_special_empty_or_corrupt_archives(tmp_path, kind):
    from app.services.dataset_zip import validate_zip, ImportLimits
    entries = [("birds/a.wav", wav_bytes())]
    root = ""
    if kind in ("duplicate", "case", "unicode"):
        first, second = {"duplicate": ("a", "a"), "case": ("a", "A"), "unicode": ("é", "e\u0301")}[kind]
        entries = [(f"birds/{first}.wav", wav_bytes()), (f"birds/{second}.wav", wav_bytes(2))]
    elif kind in ("symlink", "special"):
        info = zipfile.ZipInfo("birds/a.wav")
        info.create_system = 3
        info.external_attr = ((stat.S_IFLNK if kind == "symlink" else stat.S_IFIFO) | 0o600) << 16
        entries = [(info, wav_bytes())]
    elif kind == "empty":
        entries = []
    elif kind == "outside_root":
        root = "other"
    source = archive(tmp_path / "input.zip", entries)
    if kind == "corrupt":
        source.write_bytes(b"not a zip")
    result = validate_zip(source, tmp_path / "staged", root=root, limits=ImportLimits())
    assert result["errors"]
    assert str(tmp_path) not in str(result)


@pytest.mark.parametrize("field,value", [("received_bytes", 1), ("expanded_bytes", 1),
    ("entries", 0), ("depth", 1), ("path_bytes", 1), ("audio_bytes", 1),
    ("audio_seconds", 0), ("validation_seconds", 0), ("free_bytes", 10**18)])
def test_enforces_server_limits(tmp_path, field, value):
    from app.services.dataset_zip import validate_zip, ImportLimits
    source = archive(tmp_path / "input.zip", [("birds/a.wav", wav_bytes())])
    result = validate_zip(source, tmp_path / "staged", root="", limits=replace(ImportLimits(), **{field: value}))
    assert result["errors"]


@pytest.mark.parametrize("kind", ["truncated", "encrypted", "nul", "prefix_collision"])
def test_rejects_header_and_path_ambiguities(tmp_path, kind):
    from app.services.dataset_zip import validate_zip, ImportLimits
    entries = [("birds/a.wav", wav_bytes()[:-20] if kind == "truncated" else wav_bytes())]
    if kind == "nul":
        entries = [("birds/a.wav\x00extra", wav_bytes())]
    if kind == "prefix_collision":
        entries = [("birds/a.wav/nested.wav", wav_bytes()), ("birds/a.wav", wav_bytes(2))]
    source = archive(tmp_path / "input.zip", entries)
    if kind == "encrypted":
        data = bytearray(source.read_bytes())
        import struct
        for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
            index = data.index(signature) + offset
            struct.pack_into("<H", data, index, struct.unpack_from("<H", data, index)[0] | 1)
        source.write_bytes(data)
    if kind == "nul":
        # zipfile's writer strips NUL; mutate equal-length filename bytes instead.
        source.write_bytes(source.read_bytes().replace(b"birds/a.wav", b"birds/a\x00wav"))
    result = validate_zip(source, tmp_path / "staged", root="", limits=ImportLimits())
    assert result["errors"]
