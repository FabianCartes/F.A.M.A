"""Bounded, structured upload through the agreed HTTP/service interfaces."""
import io
import struct
from pathlib import Path

import pytest
import soundfile as sf

from tests.test_api_ingestion_validation import client
from tests.test_ingestion_upload_integrity import upload_environment, synthetic_wav
from tests.test_ingestion_sync_integrity import BlobFixture


def cbr_mp3_with_tags():
    # Synthetic silence, 40 complete MPEG-1 Layer III frames, no Xing/Info table.
    # libsndfile/LAME generated at 44.1 kHz, mono, 160 kbps; no field recording.
    audio = (Path(__file__).parent / "fixtures/audio/cbr_without_seek_table.mp3").read_bytes()
    return b"ID3\x04\x00\x00\x00\x00\x20\x00" + b"\0" * 4096 + audio


def test_complete_mp3_with_estimated_length_uploads_unchanged_and_records_decoded_duration(client, upload_environment):
    _, _, objects = upload_environment
    content = cbr_mp3_with_tags()

    response = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"},
                           files={"files": ("silence.mp3", content, "audio/mpeg")})

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["db_persisted"] is True
    assert objects["datasets/AvesChilenas/General/silence.mp3"] == content
    audio, = client.get("/api/ingestion/datasets/AvesChilenas/files").json()["files"]
    assert audio["recorded_metadata"]["duration_seconds"] == pytest.approx(46080 / 44100)


def test_incomplete_mp3_frame_rejects_entire_batch_before_transfer(client, upload_environment):
    _, _, objects = upload_environment
    response = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"}, files=[
        ("files", ("valid.wav", synthetic_wav(), "audio/wav")),
        ("files", ("cut.mp3", cbr_mp3_with_tags()[:-10], "audio/mpeg")),
    ])

    assert response.status_code == 422
    assert response.json()["detail"] == "Archivo de audio inválido o formato no admitido."
    assert objects == {}
    assert client.get("/api/training/datasets").json() == {"datasets": []}


def test_mp3_with_ape_and_id3v1_metadata_preserves_original_tags(client, upload_environment):
    _, _, objects = upload_environment
    item = struct.pack("<II", 4, 0) + b"Title\0Test"
    header = struct.pack("<8sIIII8s", b"APETAGEX", 2000, len(item) + 32, 1, 0xA0000000, b"\0" * 8)
    footer = struct.pack("<8sIIII8s", b"APETAGEX", 2000, len(item) + 32, 1, 0x80000000, b"\0" * 8)
    content = cbr_mp3_with_tags() + header + item + footer + b"TAG" + b"\0" * 125

    response = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"},
                           files={"files": ("tagged.mp3", content, "audio/mpeg")})

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert objects["datasets/AvesChilenas/General/tagged.mp3"] == content


def test_mp3_with_underestimated_duration_is_read_until_decoder_eof(client):
    content = (Path(__file__).parent / "fixtures/audio/vbr_without_seek_table.mp3").read_bytes()
    response = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"},
                           files={"files": ("variable.mp3", content, "audio/mpeg")})

    assert response.status_code == 200
    audio, = client.get("/api/ingestion/datasets/AvesChilenas/files").json()["files"]
    assert audio["recorded_metadata"]["duration_seconds"] == pytest.approx(46080 / 44100)


def test_mp3_download_records_the_same_duration_as_upload(client, monkeypatch):
    content = (Path(__file__).parent / "fixtures/audio/vbr_without_seek_table.mp3").read_bytes()
    blob = BlobFixture(content, "datasets/AvesChilenas/General/variable.mp3")
    monkeypatch.setattr("google.cloud.storage.Client.list_blobs", lambda *args, **kwargs: [blob])

    response = client.post("/api/ingestion/sync", json={"datasets": ["AvesChilenas"]})

    assert response.status_code == 200
    audio, = client.get("/api/ingestion/datasets/AvesChilenas/files").json()["files"]
    assert audio["recorded_metadata"]["sample_rate_hz"] == 44100
    assert audio["recorded_metadata"]["duration_seconds"] == pytest.approx(46080 / 44100)


def test_http_rejects_oversized_audio_before_any_transfer(client, upload_environment, monkeypatch):
    _, _, objects = upload_environment
    monkeypatch.setenv("FAMA_UPLOAD_MAX_FILE_BYTES", "16043")
    monkeypatch.setenv("FAMA_UPLOAD_MAX_BATCH_BYTES", "65536")

    response = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"},
                           files={"files": ("audio.wav", synthetic_wav(), "audio/wav")})

    assert response.status_code == 413
    assert response.json()["detail"] == "La carga supera los límites permitidos."
    assert objects == {}


def test_http_rejects_combined_batch_size_before_transferring_first_file(client, upload_environment, monkeypatch):
    _, _, objects = upload_environment
    monkeypatch.setenv("FAMA_UPLOAD_MAX_FILE_BYTES", "20000")
    monkeypatch.setenv("FAMA_UPLOAD_MAX_BATCH_BYTES", "30000")

    response = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"}, files=[
        ("files", ("first.wav", synthetic_wav(), "audio/wav")),
        ("files", ("last.wav", synthetic_wav(), "audio/wav")),
    ])

    assert response.status_code == 413
    assert response.json()["detail"] == "La carga supera los límites permitidos."
    assert objects == {}


@pytest.mark.parametrize("file_limit,batch_limit", [("0", "65536"), ("-1", "65536"),
                                                   ("synthetic-secret", "65536"), ("20000", "10000")])
def test_invalid_upload_limits_fail_closed_with_sanitized_503(client, upload_environment, monkeypatch, file_limit, batch_limit):
    _, _, objects = upload_environment
    monkeypatch.setenv("FAMA_UPLOAD_MAX_FILE_BYTES", file_limit)
    monkeypatch.setenv("FAMA_UPLOAD_MAX_BATCH_BYTES", batch_limit)

    response = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"},
                           files={"files": ("audio.wav", synthetic_wav(), "audio/wav")})

    assert response.status_code == 503
    assert response.json()["detail"] == "Configuración de carga no disponible."
    assert "synthetic-secret" not in response.text
    assert objects == {}


@pytest.mark.parametrize("files", [[("audio.wav", synthetic_wav())],
                                   [("first.wav", synthetic_wav()), ("last.wav", synthetic_wav())]],
                         ids=["file-limit", "batch-limit"])
def test_service_cannot_bypass_upload_size_policy(upload_environment, monkeypatch, files):
    service, db, objects = upload_environment
    monkeypatch.setenv("FAMA_UPLOAD_MAX_FILE_BYTES", "16043" if len(files) == 1 else "20000")
    monkeypatch.setenv("FAMA_UPLOAD_MAX_BATCH_BYTES", "65536" if len(files) == 1 else "30000")

    with pytest.raises(ValueError, match="limits"):
        service.upload_files_to_gcs(files, "AvesChilenas", db=db)

    assert objects == {}


@pytest.mark.parametrize("filename,content", [("empty.wav", b""), ("invalid.wav", b"synthetic invalid audio"),
                                             ("empty.wav", synthetic_wav(frames=0)),
                                             ("audio.txt", synthetic_wav()), ("wrong.flac", synthetic_wav())],
                         ids=["empty-file", "unreadable", "zero-frames", "unsupported-extension", "mismatched-header"])
def test_invalid_audio_rejects_whole_batch_before_any_transfer(client, upload_environment, filename, content):
    _, _, objects = upload_environment

    response = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"}, files=[
        ("files", ("valid.wav", synthetic_wav(), "audio/wav")),
        ("files", (filename, content, "application/octet-stream")),
    ])

    assert response.status_code == 422
    assert response.json()["detail"] == "Archivo de audio inválido o formato no admitido."
    assert objects == {}


def test_decoding_rejects_truncated_flac_even_when_header_is_readable(client, upload_environment):
    _, _, objects = upload_environment
    stream = io.BytesIO()
    sf.write(stream, [0.0] * 8000, 8000, format="FLAC")
    truncated = stream.getvalue()[:-8]
    assert sf.info(io.BytesIO(truncated)).frames == 8000

    response = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"},
                           files={"files": ("audio.flac", truncated, "audio/flac")})

    assert response.status_code == 422
    assert response.json()["detail"] == "Archivo de audio inválido o formato no admitido."
    assert objects == {}


@pytest.mark.parametrize("extension,format_name", [("wav", "WAV"), ("flac", "FLAC"), ("ogg", "OGG"), ("mp3", "MP3")])
def test_supported_audio_formats_are_decoded_before_upload(client, upload_environment, extension, format_name):
    _, _, objects = upload_environment
    stream = io.BytesIO()
    sf.write(stream, [0.01] * 11025, 22050, format=format_name)

    response = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"},
                           files={"files": (f"audio.{extension}", stream.getvalue(), "application/octet-stream")})

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["db_persisted"] is True
    assert f"datasets/AvesChilenas/General/audio.{extension}" in objects


def test_exact_file_and_batch_limits_allow_valid_audio(client, upload_environment, monkeypatch):
    _, _, objects = upload_environment
    monkeypatch.setenv("FAMA_UPLOAD_MAX_FILE_BYTES", "16044")
    monkeypatch.setenv("FAMA_UPLOAD_MAX_BATCH_BYTES", "32088")

    response = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"}, files=[
        ("files", ("first.wav", synthetic_wav(), "audio/wav")),
        ("files", ("last.wav", synthetic_wav(), "audio/wav")),
    ])

    assert response.status_code == 200
    assert response.json()["uploaded"] == 2
    assert len(objects) == 2


def test_audio_larger_than_a_read_block_is_not_truncated(client, upload_environment, monkeypatch):
    _, _, objects = upload_environment
    content = synthetic_wav(frames=600000)
    monkeypatch.setenv("FAMA_UPLOAD_MAX_FILE_BYTES", "1200044")
    monkeypatch.setenv("FAMA_UPLOAD_MAX_BATCH_BYTES", "1200044")

    response = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"},
                           files={"files": ("audio.wav", content, "audio/wav")})

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert objects["datasets/AvesChilenas/General/audio.wav"] == content


def test_service_cannot_bypass_structural_audio_validation(upload_environment):
    service, db, objects = upload_environment

    with pytest.raises(ValueError, match="audio"):
        service.upload_files_to_gcs([("valid.wav", synthetic_wav()), ("invalid.wav", b"invalid audio")],
                                    "AvesChilenas", db=db)

    assert objects == {}
