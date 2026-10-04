import asyncio
import pytest
from google.api_core.exceptions import NotFound
from app.services import storage


@pytest.mark.parametrize("directories,label,expected", [
    (["rayadito"], "Rayadito", "rayadito"),
    (["Chercán"], "CHERCA\u0301N", "Chercán"),
    (["chercan"], "Chercán", "Chercán"),
    ([], "Rayadito", "Rayadito"),
    (["Rayadito", "rayadito"], "Rayadito", "Rayadito"),
])
def test_class_directory_catalogue_preserves_accents_and_new_labels(monkeypatch, directories, label, expected):
    from types import SimpleNamespace
    class Client:
        def list_blobs(self, bucket, prefix):
            return [SimpleNamespace(name=prefix + "metadata.csv")] + [
                SimpleNamespace(name=prefix + directory + "/existing.wav") for directory in directories]
    monkeypatch.setattr(storage.storage, "Client", Client)
    assert storage.resolve_dataset_class("AvesChilenas", label) == expected


@pytest.mark.parametrize("catalogue", ["ambiguous", "absent", "unavailable"])
def test_unverifiable_catalogue_fails_closed(monkeypatch, catalogue):
    from types import SimpleNamespace
    class Client:
        def list_blobs(self, bucket, prefix):
            if catalogue == "unavailable":
                raise OSError("catalogue unavailable")
            return [] if catalogue == "absent" else [
                SimpleNamespace(name=prefix + directory + "/existing.wav")
                for directory in ("rayadito", "RAYADITO")]
    monkeypatch.setattr(storage.storage, "Client", Client)
    with pytest.raises(OSError if catalogue == "unavailable" else ValueError):
        storage.resolve_dataset_class("AvesChilenas", "Rayadito")


def test_missing_bucket_is_not_simulated_success(monkeypatch):
    monkeypatch.setenv("GCS_MOCK", "true")
    class Client:
        def bucket(self, name): return self
        def blob(self, key): return self
        def upload_from_string(self, *args, **kwargs): raise NotFound("missing bucket")
    monkeypatch.setattr(storage.storage, "Client", Client)
    with pytest.raises(NotFound):
        asyncio.run(storage.upload_audio_to_gcp(b"real audio", "recording.wav"))


@pytest.mark.parametrize("source", ["/etc/passwd", "../audio.wav", "old.wav", "raw_audios/../secret.wav", "gs://other/audio.wav"])
def test_unmanaged_sources_are_never_read(source, monkeypatch):
    def forbidden():
        pytest.fail("Invalid source must not create a cloud client")
    monkeypatch.setattr(storage.storage, "Client", forbidden)
    with pytest.raises(ValueError):
        storage.download_prediction_audio(source)


def test_async_upload_and_download_preserve_bytes(monkeypatch):
    objects = {}
    class Client:
        def bucket(self, name): return self
        def blob(self, key):
            class Blob:
                def upload_from_string(self, data, **kwargs): objects[key] = data
                def download_as_bytes(self): return objects[key]
            return Blob()
    monkeypatch.setattr(storage.storage, "Client", Client)
    filename = "0123456789abcdef0123456789abcdef.wav"
    assert asyncio.run(storage.upload_audio_to_gcp(b"source bytes", filename)) is True
    assert storage.download_prediction_audio(f"raw_audios/{filename}") == b"source bytes"
