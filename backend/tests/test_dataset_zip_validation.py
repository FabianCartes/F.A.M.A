"""ZIP import rules at the public validation interface; synthetic WAV bytes only."""
import io
import wave
import zipfile
import stat
import struct
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


def zip64_archive(path, sentinel="count"):
    """Small real archive with independently saturated classic EOCD fields."""
    archive(path, [("birds/a.wav", wav_bytes())])
    data = path.read_bytes()
    end = len(data) - 22
    fields = list(struct.unpack_from("<4H2IH", data, end + 4))
    count, size, offset = fields[3:6]
    record = struct.pack("<4sQ2H2I4Q", b"PK\x06\x06", 44, 45, 45, 0, 0,
                         count, count, size, offset)
    locator = struct.pack("<4sIQI", b"PK\x06\x07", 0, end, 1)
    index = {"disk_count": 2, "count": 3, "size": 4, "offset": 5}[sentinel]
    fields[index] = 0xFFFF if index < 4 else 0xFFFFFFFF
    path.write_bytes(data[:end] + record + locator + b"PK\x05\x06" + struct.pack("<4H2IH", *fields))
    return path


@pytest.mark.parametrize("sentinel", ["count", "disk_count", "size", "offset"])
def test_zip64_independent_sentinels_preserve_original_wav(tmp_path, sentinel):
    from app.services.dataset_zip import validate_zip, ImportLimits

    source = zip64_archive(tmp_path / "zip64.zip", sentinel)
    result = validate_zip(source, tmp_path / "staged", root="", limits=ImportLimits())
    assert result["errors"] == []
    assert result["unique_count"] == 1
    assert (tmp_path / "staged" / result["files"][0]["stored_name"]).read_bytes() == wav_bytes()


def test_zip64_large_directory_offset_without_saturated_counts(tmp_path):
    from app.services.dataset_zip import validate_zip, ImportLimits

    source = archive(tmp_path / "sparse.zip", [("birds/a.wav", wav_bytes())])
    original = source.read_bytes()
    fields = list(struct.unpack_from("<4H2IH", original, len(original) - 18))
    directory = original[fields[5]:-22]
    position = 2**32 + 17
    record_at = position + len(directory)
    record = struct.pack("<4sQ2H2I4Q", b"PK\x06\x06", 44, 45, 45, 0, 0,
                         1, 1, len(directory), position)
    fields[5] = 0xFFFFFFFF
    # Sparse private file: logical offset >4GiB, not a 4GiB allocation or read.
    with source.open("wb") as stream:
        stream.write(original[:original.index(b"PK\x01\x02")])
        stream.seek(position)
        stream.write(directory + record + struct.pack("<4sIQI", b"PK\x06\x07", 0, record_at, 1)
                     + b"PK\x05\x06" + struct.pack("<4H2IH", *fields))
    result = validate_zip(source, tmp_path / "staged", root="",
                          limits=replace(ImportLimits(), received_bytes=5 * 1024**3))
    assert result["errors"] == []
    assert (tmp_path / "staged" / result["files"][0]["stored_name"]).read_bytes() == wav_bytes()


@pytest.mark.parametrize("kind", ["missing_locator", "locator_disk", "locator_offset", "multiple_disks",
    "record_size", "record_disk", "record_count", "classic_count", "central_offset", "huge_count",
    "huge_size", "truncated", "hidden_entries"])
def test_zip64_rejects_incoherent_or_over_budget_directory_before_allocation(tmp_path, monkeypatch, kind):
    from app.services.dataset_zip import validate_zip, ImportLimits

    source = zip64_archive(tmp_path / "invalid.zip")
    data = bytearray(source.read_bytes())
    record = data.index(b"PK\x06\x06")
    locator = data.index(b"PK\x06\x07")
    end = data.index(b"PK\x05\x06")
    changes = {
        "locator_disk": ("<I", locator + 4, 1), "locator_offset": ("<Q", locator + 8, 2**63),
        "multiple_disks": ("<I", locator + 16, 2), "record_size": ("<Q", record + 4, 2**63),
        "record_disk": ("<I", record + 16, 1), "record_count": ("<Q", record + 24, 2),
        "classic_count": ("<H", end + 8, 2), "central_offset": ("<Q", record + 48, 1),
        "huge_size": ("<Q", record + 40, 2**63),
    }
    if kind in changes:
        format_string, position, value = changes[kind]
        struct.pack_into(format_string, data, position, value)
    elif kind == "huge_count":
        struct.pack_into("<2Q", data, record + 24, 65536, 65536)
        struct.pack_into("<H", data, end + 8, 0xFFFF)
    elif kind == "hidden_entries":
        struct.pack_into("<2Q", data, record + 24, 0, 0)
        struct.pack_into("<H", data, end + 8, 0)
    elif kind == "missing_locator":
        data[locator:locator + 4] = b"NONE"
    elif kind == "truncated":
        del data[record + 40:record + 48]
    source.write_bytes(data)

    def allocation_forbidden(*args, **kwargs):
        pytest.fail("ZipInfo allocation must not precede directory validation")

    monkeypatch.setattr(zipfile, "ZipFile", allocation_forbidden)
    result = validate_zip(source, tmp_path / "staged", root="", limits=ImportLimits())
    assert result["errors"]
    assert result["files"] == []
    assert source.read_bytes() == data
    assert not list((tmp_path / "staged").iterdir())


def test_expanded_budget_counts_all_extracted_members(tmp_path):
    from app.services.dataset_zip import validate_zip, ImportLimits

    source = archive(tmp_path / "compressed.zip", [("birds/a.wav", wav_bytes()),
                     ("birds/b.wav", wav_bytes(2))], zipfile.ZIP_DEFLATED)
    result = validate_zip(source, tmp_path / "staged", root="",
                          limits=replace(ImportLimits(), expanded_bytes=len(wav_bytes()) * 2 - 1))
    assert result["errors"][0]["code"] == "expanded_limit"
    assert len(result["files"]) == 1


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


@pytest.mark.parametrize("entry", [
    "aves/chucao/audio.wav", "chucao/session/audio.wav", "chucao/empty/", "audio.wav",
])
def test_class_folders_layout_rejects_wrappers_and_all_nested_directories(tmp_path, entry):
    from app.services.dataset_zip import validate_zip, ImportLimits

    source = archive(tmp_path / "input.zip", [(entry, b"" if entry.endswith("/") else wav_bytes())])
    original = source.read_bytes()
    result = validate_zip(source, tmp_path / "staged", root="", limits=ImportLimits(), layout="class_folders")
    assert result["errors"] == [{"path": entry, "code": "class_folders_required",
        "action": "Organiza el ZIP como clase/audio.wav, sin carpeta contenedora ni subcarpetas."}]
    assert result["files"] == []
    assert source.read_bytes() == original


def test_class_folders_layout_accepts_one_class_and_preserves_original_audio(tmp_path):
    from app.services.dataset_zip import validate_zip, ImportLimits

    source = archive(tmp_path / "input.zip", [("chucao/", b""), ("chucao/audio.wav", wav_bytes())])
    result = validate_zip(source, tmp_path / "staged", root="", limits=ImportLimits(), layout="class_folders")
    assert result["errors"] == []
    assert result["classes"] == ["chucao"]
    assert result["unique_count"] == 1
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
