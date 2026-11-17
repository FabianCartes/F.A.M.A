import hashlib

from app.services.audio_hashing import sha256_file


def test_sha256_file_streams_in_chunks(tmp_path):
    content = b"abc" * 100_000
    path = tmp_path / "a.wav"
    path.write_bytes(content)
    assert sha256_file(path, chunk_size=1000) == hashlib.sha256(content).hexdigest()
