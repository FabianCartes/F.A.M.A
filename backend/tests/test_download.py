import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from poc.download import (
    compute_file_sha256,
    create_metadata_row,
    search_recordings,
    download_file,
    EXPECTED_COLUMNS,
    run_download_pipeline,
)

def test_compute_file_sha256(tmp_path):
    test_file = tmp_path / "sample.mp3"
    test_file.write_bytes(b"FAMA_AUDIO_TEST_CONTENT_12345")
    # echo -n "FAMA_AUDIO_TEST_CONTENT_12345" | sha256sum
    # sha256 of b"FAMA_AUDIO_TEST_CONTENT_12345":
    import hashlib
    expected_hash = hashlib.sha256(b"FAMA_AUDIO_TEST_CONTENT_12345").hexdigest()
    
    computed_hash = compute_file_sha256(test_file)
    assert computed_hash == expected_hash
    assert len(computed_hash) == 64

def test_create_metadata_row(tmp_path):
    test_file = tmp_path / "12345.mp3"
    test_file.write_bytes(b"dummy_audio_bytes")
    
    rec_payload = {
        "id": "12345",
        "gen": "Turdus",
        "sp": "falcklandii",
        "en": "Austral Thrush",
        "rec": "Juan Perez",
        "lic": "//creativecommons.org/licenses/by-nc-sa/4.0/",
        "cnt": "Chile",
        "loc": "Parque Nacional Nahuelbuta",
        "lat": "-37.80",
        "lng": "-73.01",
        "q": "A",
        "smp": "44100",
        "length": "0:30"
    }
    
    audio_info = {
        "frecuencia_muestreo": 44100,
        "duracion_segundos": 30.5
    }
    
    row = create_metadata_row(
        rec=rec_payload,
        file_path=test_file,
        clase="Zorzal patagónico",
        audio_info=audio_info,
        roots={"raw": tmp_path},
    )
    
    assert list(row.keys()) == EXPECTED_COLUMNS
    assert row["file_path"] == "12345.mp3"
    assert row["file_stage"] == "raw"
    assert row["nombre_archivo"] == "12345.mp3"
    assert row["clase"] == "Zorzal patagónico"
    assert row["frecuencia_muestreo"] == 44100
    assert row["duracion_segundos"] == 30.5
    assert row["tamano_bytes"] == len(b"dummy_audio_bytes")
    assert row["xc_id"] == "12345"
    assert row["recordist"] == "Juan Perez"
    assert row["pais"] == "Chile"
    assert row["calidad"] == "A"
    assert len(row["hash_archivo"]) == 64

@patch("poc.download.requests.Session")
def test_search_recordings_pagination(mock_session_cls):
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    
    resp_page1 = MagicMock()
    resp_page1.status_code = 200
    resp_page1.json.return_value = {
        "numRecordings": "2",
        "numPages": 2,
        "page": 1,
        "recordings": [{"id": "1", "q": "A"}, {"id": "2", "q": "A"}]
    }
    
    resp_page2 = MagicMock()
    resp_page2.status_code = 200
    resp_page2.json.return_value = {
        "numRecordings": "2",
        "numPages": 2,
        "page": 2,
        "recordings": [{"id": "3", "q": "A"}]
    }
    
    mock_session.get.side_effect = [resp_page1, resp_page2]
    
    recs = search_recordings("Turdus falcklandii", api_key="dummy_key", qualities=["A"], session=mock_session)
    assert len(recs) == 3
    assert [r["id"] for r in recs] == ["1", "2", "3"]

@patch("poc.download.requests.Session")
def test_download_file_success(mock_session_cls, tmp_path):
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_content.return_value = [b"chunk1", b"chunk2"]
    mock_resp.__enter__.return_value = mock_resp
    mock_session.get.return_value = mock_resp
    
    dest = tmp_path / "out.mp3"
    ok = download_file("https://xeno-canto.org/123/download", dest, session=mock_session)
    
    assert ok is True
    assert dest.exists()
    assert dest.read_bytes() == b"chunk1chunk2"


@pytest.fixture
def acquisition(tmp_path, monkeypatch):
    import pandas as pd
    raw = tmp_path / "physical-raw"
    raw.mkdir()
    index = tmp_path / "indexes" / "raw.csv"
    session = MagicMock()
    downloads = []
    payloads = {"0007": b"original audio", "0008": b"", "0009": None}

    def get(url, **kwargs):
        response = MagicMock()
        response.__enter__.return_value = response
        if "/api/" in url:
            response.status_code = 200
            response.json.return_value = {
                "numPages": 1,
                "recordings": [{"id": key, "file": f"https://fake/{key}", "rec": "NA",
                                "loc": "001", "lic": "CC", "q": "A"}
                               for key in payloads],
            }
        else:
            key = url.rsplit("/", 1)[1]
            downloads.append(key)
            response.status_code = 200 if payloads[key] is not None else 404
            response.iter_content.return_value = [payloads[key]]
        return response

    session.get.side_effect = get
    monkeypatch.setattr("poc.download.requests.Session", lambda: session)
    monkeypatch.setattr("poc.download.time.sleep", lambda seconds: None)
    return raw, index, payloads, downloads


def test_pipeline_publishes_only_successful_raw_and_preserves_existing_fields(acquisition):
    import pandas as pd
    raw, index, payloads, downloads = acquisition
    index.parent.mkdir()
    (raw / "old.wav").write_bytes(b"previous original")
    previous = {"xc_id": "0006", "nombre_archivo": "old.wav", "clase": "Chincol",
                "file_path": "old.wav", "file_stage": "raw", "recordist": "NA",
                "source_id": "0006", "hash_archivo": "original-digest", "labels": '["Chincol"]',
                "custom_provenance": "001"}
    pd.DataFrame([previous]).to_csv(index, index=False)
    result = run_download_pipeline(data_dir=raw, metadata_index=index, api_key="fake",
                                   species_list=[("Chincol", "Fake species")])
    persisted = pd.read_csv(index, dtype=str, keep_default_na=False)
    assert len(result) == len(persisted) == 2
    assert persisted.iloc[0][list(previous)].to_dict() == previous
    new = persisted.iloc[1]
    assert (new["xc_id"], new["file_path"], new["file_stage"], new["recordist"], new["localidad"]) == (
        "0007", "chincol/0007.mp3", "raw", "NA", "001")
    assert (raw / new["file_path"]).read_bytes() == b"original audio"
    payloads.clear()
    payloads["0007"] = b"must not replace"
    downloads.clear()
    before = index.read_bytes()
    run_download_pipeline(data_dir=raw, metadata_index=index, api_key="fake",
                          species_list=[("Chincol", "Fake species")])
    assert downloads == []
    assert index.read_bytes() == before


@pytest.mark.parametrize("fields", [{}, {"file_path": "old.wav"},
                                     {"file_path": "missing.wav", "file_stage": "raw"}])
def test_pipeline_rejects_noncanonical_existing_index_before_network_or_writes(acquisition, fields):
    import pandas as pd
    raw, index, _, downloads = acquisition
    index.parent.mkdir()
    pd.DataFrame([{"xc_id": "0006", "clase": "Chincol", **fields}]).to_csv(index, index=False)
    before = index.read_bytes()
    with pytest.raises(ValueError):
        run_download_pipeline(data_dir=raw, metadata_index=index, api_key="fake",
                              species_list=[("Chincol", "Fake species")])
    assert downloads == []
    assert index.read_bytes() == before
    assert list(raw.iterdir()) == []


@pytest.mark.parametrize("invalid", ["empty", "missing", "alias", "outside"])
def test_raw_metadata_requires_verified_nonempty_physical_source(tmp_path, invalid):
    source = tmp_path / "raw.wav"
    source.write_bytes(b"original")
    root = tmp_path
    if invalid == "empty":
        source.write_bytes(b"")
    elif invalid == "missing":
        source = tmp_path / "missing.wav"
    elif invalid == "alias":
        link = tmp_path / "linked.wav"
        link.symlink_to(source)
        source = link
    else:
        root = tmp_path / "other-root"
        root.mkdir()
    with pytest.raises(ValueError):
        create_metadata_row({"id": "0001"}, source, "Chincol", roots={"raw": root})


@pytest.mark.parametrize("alias", ["raw", "index"])
def test_download_rejects_alias_configuration_before_http(acquisition, alias, tmp_path):
    raw, index, _, downloads = acquisition
    if alias == "raw":
        physical = tmp_path / "physical"
        raw.rename(physical)
        raw.symlink_to(physical, target_is_directory=True)
    else:
        physical = tmp_path / "physical-indexes"
        physical.mkdir()
        index.parent.symlink_to(physical, target_is_directory=True)
    with pytest.raises(ValueError):
        run_download_pipeline(data_dir=raw, metadata_index=index, api_key="fake")
    assert downloads == []
    assert not index.exists()


@pytest.mark.parametrize("explicit", [False, True])
def test_download_cli_binds_physical_root_and_independent_index(tmp_path, monkeypatch, explicit):
    from poc import download
    roots = {"raw": tmp_path / "configured-raw", "processed": tmp_path / "configured-processed"}
    lookups = []
    def configured(name):
        assert name == "AvesChilenas"
        lookups.append(name)
        return roots
    monkeypatch.setattr(download, "get_dataset_roots", configured)
    observed = []
    monkeypatch.setattr(download, "run_download_pipeline", lambda **kwargs: observed.append(kwargs))
    index = tmp_path / "independent" / "raw.csv"
    argv = ["--metadata-index", str(index), "--max-per-species", "2"]
    if explicit:
        argv += ["--raw-dir", str(tmp_path / "override")]
    download.main(argv)
    assert observed == [{"data_dir": tmp_path / "override" if explicit else roots["raw"],
                         "metadata_index": index, "max_per_species": 2}]
    assert lookups == ([] if explicit else ["AvesChilenas"])
    assert list(tmp_path.iterdir()) == []


def test_late_download_target_is_not_truncated(tmp_path):
    dest = tmp_path / "out.mp3"
    session = MagicMock()
    response = MagicMock(status_code=200)
    response.__enter__.return_value = response
    def late_chunks(**kwargs):
        dest.write_bytes(b"late original")
        yield b"new download"
    response.iter_content.side_effect = late_chunks
    session.get.return_value = response
    with pytest.raises(ValueError):
        download_file("https://fake/download", dest, session=session)
    assert dest.read_bytes() == b"late original"
