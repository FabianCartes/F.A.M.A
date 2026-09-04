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
    EXPECTED_COLUMNS
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
        audio_info=audio_info
    )
    
    assert list(row.keys()) == EXPECTED_COLUMNS
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
