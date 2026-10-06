import soundfile as sf
import numpy as np
import pytest
from pathlib import Path
from poc.sanitize import sanitize_audio_file, sanitize_dataset
from poc.train import AudioDataset
import pandas as pd


def test_sanitize_audio_file_converts_to_pcm16_wav(tmp_path):
    # Generar un audio sintético a 44100 Hz
    duration_s = 1.0
    orig_sr = 44100
    target_sr = 22050
    t = np.linspace(0, duration_s, int(orig_sr * duration_s), endpoint=False)
    sine = 0.5 * np.sin(2 * np.pi * 440 * t)
    
    src_file = tmp_path / "input.wav"
    dst_file = tmp_path / "output.wav"
    sf.write(str(src_file), sine, orig_sr)
    
    success = sanitize_audio_file(src_file, dst_file, target_sr=target_sr)
    assert success is True
    assert dst_file.exists()
    
    # Verificar formato PCM_16 y frecuencia de muestreo convertida
    info = sf.info(str(dst_file))
    assert info.samplerate == target_sr
    assert info.subtype == "PCM_16"
    assert info.channels == 1


def test_sanitize_audio_file_handles_corrupt_or_empty_input(tmp_path):
    empty_file = tmp_path / "corrupt.mp3"
    empty_file.write_bytes(b"NOT_AN_AUDIO_FILE")
    dst_file = tmp_path / "output.wav"
    
    success = sanitize_audio_file(empty_file, dst_file)
    assert success is False
    assert not dst_file.exists()


def test_sanitize_dataset_concurrency_and_structure(tmp_path):
    raw_dir = tmp_path / "raw"
    species_dir = raw_dir / "chincol"
    species_dir.mkdir(parents=True)
    
    # Crear dos archivos válidos
    t = np.linspace(0, 0.5, int(22050 * 0.5), endpoint=False)
    audio = 0.3 * np.sin(2 * np.pi * 440 * t)
    sf.write(str(species_dir / "1.wav"), audio, 22050)
    sf.write(str(species_dir / "2.wav"), audio, 22050)
    
    out_dir = tmp_path / "processed_wav"
    index = tmp_path / "raw-index.csv"
    original_rows = [{"file_path": f"chincol/{i}.wav", "file_stage": "raw", "clase": "Chincol",
                      "nombre_archivo": f"{i}.wav", "xc_id": f"000{i}", "source_id": f"000{i}",
                      "recordist": "NA", "hash_archivo": "original-digest", "labels": '["Chincol"]',
                      "custom_provenance": "001"} for i in (1, 2)]
    pd.DataFrame(original_rows).to_csv(index, index=False)
    before = index.read_bytes()
    # Unindexed originals must not be enrolled by the converter.
    sf.write(species_dir / "unindexed.wav", audio, 22050)
    stats = sanitize_dataset(raw_dir, out_dir, target_sr=22050, num_workers=2,
                             metadata_index=index, roots={"raw": raw_dir, "processed": out_dir})
    derived = pd.read_csv(out_dir / "metadata.csv", dtype=str, keep_default_na=False)
    assert derived.to_dict("records") == [{**row, "file_stage": "processed"} for row in original_rows]
    assert index.read_bytes() == before
    assert not (out_dir / "chincol/unindexed.wav").exists()
    
    assert stats["total"] == 2
    assert stats["converted"] == 2
    assert stats["failed"] == 0
    assert (out_dir / "chincol" / "1.wav").exists()
    assert (out_dir / "chincol" / "2.wav").exists()


@pytest.mark.parametrize("stage,level", [("raw", .25), ("processed", -.5)])
def test_audio_dataset_reads_explicit_stage_after_sanitization(tmp_path, stage, level):
    raw_dir = tmp_path / "raw"
    sp_dir = raw_dir / "chincol"
    sp_dir.mkdir(parents=True)
    
    t = np.linspace(0, 1.0, 22050, endpoint=False)
    audio = 0.2 * np.sin(2 * np.pi * 440 * t)
    
    # An original WAV and its derivative share a basename; extension is not stage.
    processed = tmp_path / "processed"
    (processed / "chincol").mkdir(parents=True)
    sf.write(sp_dir / "100.wav", np.full(22050, .25), 22050)
    sf.write(processed / "chincol/100.wav", np.full(22050, -.5), 22050)
    df = pd.DataFrame([{"nombre_archivo": "not-a-lookup.mp3", "clase": "Chincol", "xc_id": "00100",
                        "file_path": "chincol/100.wav", "file_stage": stage}])
    ds = AudioDataset(df, raw_dir, {"Chincol": 0}, roots={"raw": raw_dir, "processed": processed},
                      duration_seconds=1, return_raw_waveform=True)
    waveform, label = ds[0]
    assert waveform.mean().item() == pytest.approx(level, abs=.001)
    assert label.item() == 0
    pd.testing.assert_frame_equal(ds.df, df)


@pytest.fixture
def indexed_raw(tmp_path):
    raw = tmp_path / "raw"
    (raw / "Chincol").mkdir(parents=True)
    source = raw / "Chincol/0001.wav"
    sf.write(source, np.full(22050, .25), 22050)
    processed = tmp_path / "processed"
    index = tmp_path / "raw.csv"
    rows = [{"file_path": "Chincol/0001.wav", "file_stage": "raw", "clase": "Chincol",
             "nombre_archivo": "0001.wav", "xc_id": "0001", "recordist": "NA",
             "hash_archivo": "original-byte-digest", "labels": '["Chincol"]'}]
    pd.DataFrame(rows).to_csv(index, index=False)
    return raw, processed, index, rows


def convert_index(fixture, **kwargs):
    raw, processed, index, _ = fixture
    return sanitize_dataset(raw, processed, metadata_index=index,
                             roots={"raw": raw, "processed": processed}, num_workers=1, **kwargs)


@pytest.mark.parametrize("defect", ["absolute", "traversal", "missing", "stage", "blank_stage",
                                   "missing_stage", "alias", "source_alias", "empty_audio"])
def test_invalid_index_fails_entire_preflight_without_output(indexed_raw, defect):
    raw, processed, index, rows = indexed_raw
    bad = dict(rows[0])
    if defect == "absolute":
        bad["file_path"] = str(raw / bad["file_path"])
    elif defect == "traversal":
        bad["file_path"] = "Chincol/../Chincol/0001.wav"
    elif defect == "missing":
        bad["file_path"] = "Chincol/missing.wav"
    elif defect in ("stage", "blank_stage"):
        bad["file_stage"] = "processed" if defect == "stage" else ""
    elif defect == "missing_stage":
        rows = [{k: v for k, v in row.items() if k != "file_stage"} for row in rows]
        bad.pop("file_stage")
    elif defect == "alias":
        (raw / "alias").symlink_to(raw / "Chincol", target_is_directory=True)
        bad["file_path"] = "alias/0001.wav"
    elif defect == "source_alias":
        (raw / "linked.wav").symlink_to(raw / "Chincol/0001.wav")
        bad["file_path"] = "linked.wav"
    elif defect == "empty_audio":
        (raw / "empty.wav").write_bytes(b"")
        bad["file_path"] = "empty.wav"
    pd.DataFrame([*rows, bad]).to_csv(index, index=False)
    before = index.read_bytes()
    with pytest.raises(ValueError):
        convert_index(indexed_raw)
    assert not processed.exists()
    assert index.read_bytes() == before


@pytest.mark.parametrize("existing", ["audio", "index"])
def test_existing_processed_outputs_rejected_without_clobber(indexed_raw, existing):
    raw, processed, index, _ = indexed_raw
    target = processed / ("Chincol/0001.wav" if existing == "audio" else "metadata.csv")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"existing bytes must survive")
    before = index.read_bytes()
    with pytest.raises(ValueError):
        convert_index(indexed_raw)
    assert target.read_bytes() == b"existing bytes must survive"
    assert index.read_bytes() == before
    assert not (processed / ("metadata.csv" if existing == "audio" else "Chincol")).exists()


@pytest.mark.parametrize("collision", ["same_stem", "duplicate", "ancestor", "index_ancestor", "index_descendant"])
def test_output_collisions_fail_before_any_conversion(indexed_raw, collision):
    raw, processed, index, rows = indexed_raw
    kwargs = {}
    if collision == "same_stem":
        source = raw / "Chincol/0001.flac"
        sf.write(source, np.full(22050, .5), 22050)
        rows.append({**rows[0], "file_path": "Chincol/0001.flac"})
    elif collision == "duplicate":
        rows.append(dict(rows[0]))
    elif collision == "ancestor":
        # A raw folder can collide with a different original's WAV derivative.
        (raw / "Chincol/0001.wav").rename(raw / "Chincol/0001.mp3")
        rows[0]["file_path"] = "Chincol/0001.mp3"
        source = raw / "Chincol/0001.wav/nested.wav"
        source.parent.mkdir()
        sf.write(source, np.full(22050, .5), 22050)
        rows.append({**rows[0], "file_path": "Chincol/0001.wav/nested.wav"})
    elif collision == "index_ancestor":
        kwargs["output_index"] = processed / "Chincol"
    else:
        kwargs["output_index"] = processed / "Chincol/0001.wav/index.csv"
    pd.DataFrame(rows).to_csv(index, index=False)
    with pytest.raises(ValueError):
        convert_index(indexed_raw, **kwargs)
    assert not processed.exists()


@pytest.mark.parametrize("alias", ["output_root", "output_parent", "index_parent", "input_index", "raw_root"])
def test_alias_configuration_rejected_before_output(indexed_raw, alias, tmp_path):
    raw, processed, index, rows = indexed_raw
    kwargs = {}
    if alias == "output_root":
        physical = tmp_path / "physical"
        physical.mkdir()
        processed.symlink_to(physical, target_is_directory=True)
    elif alias == "output_parent":
        processed.mkdir()
        physical = tmp_path / "physical"
        physical.mkdir()
        (processed / "Chincol").symlink_to(physical, target_is_directory=True)
    elif alias == "index_parent":
        physical = tmp_path / "physical"
        physical.mkdir()
        link = tmp_path / "link"
        link.symlink_to(physical, target_is_directory=True)
        kwargs["output_index"] = link / "new.csv"
    elif alias == "input_index":
        physical = tmp_path / "physical.csv"
        index.rename(physical)
        index.symlink_to(physical)
    else:
        physical = tmp_path / "physical-raw"
        raw.rename(physical)
        raw.symlink_to(physical, target_is_directory=True)
    with pytest.raises(ValueError):
        convert_index(indexed_raw, **kwargs)
    assert not (processed / "metadata.csv").exists()
    assert not (processed / "Chincol/0001.wav").exists()


@pytest.mark.parametrize("configuration", ["input_index", "raw_index", "raw_output", "overlapping_root"])
def test_bad_configuration_cannot_overwrite_originals(indexed_raw, configuration):
    raw, processed, index, _ = indexed_raw
    before = index.read_bytes()
    original = (raw / "Chincol/0001.wav").read_bytes()
    if configuration == "overlapping_root":
        with pytest.raises(ValueError):
            sanitize_dataset(raw, raw / "derivatives", metadata_index=index,
                             roots={"raw": raw, "processed": raw / "derivatives"})
    else:
        output_index = {"input_index": index, "raw_index": raw / "new.csv",
                        "raw_output": raw / "Chincol/0001.wav"}[configuration]
        with pytest.raises(ValueError):
            convert_index(indexed_raw, output_index=output_index)
    assert index.read_bytes() == before
    assert (raw / "Chincol/0001.wav").read_bytes() == original
    assert not processed.exists()


def test_empty_index_and_failed_conversion_create_no_index_or_outputs(indexed_raw):
    raw, processed, index, rows = indexed_raw
    pd.DataFrame(columns=rows[0]).to_csv(index, index=False)
    assert convert_index(indexed_raw) == {"total": 0, "converted": 0, "failed": 0,
                                        "output_dir": str(processed)}
    assert not processed.exists()
    (raw / "corrupt.mp3").write_bytes(b"not valid audio")
    pd.DataFrame([{**rows[0], "file_path": "corrupt.mp3"}]).to_csv(index, index=False)
    before = index.read_bytes()
    assert convert_index(indexed_raw)["failed"] == 1
    assert not processed.exists()
    assert index.read_bytes() == before


def test_late_destination_is_not_truncated_during_codec_publication(tmp_path, monkeypatch):
    source = tmp_path / "source.wav"
    dest = tmp_path / "destination.wav"
    sf.write(source, np.full(22050, .25), 22050)
    original_write = sf.write
    def competing_write(*args, **kwargs):
        original_write(*args, **kwargs)
        dest.write_bytes(b"late competitor")
    monkeypatch.setattr(sf, "write", competing_write)
    with pytest.raises(ValueError):
        sanitize_audio_file(source, dest)
    assert dest.read_bytes() == b"late competitor"


def test_late_index_is_not_truncated_after_derivative_publication(indexed_raw, monkeypatch):
    raw, processed, index, _ = indexed_raw
    original_write = sf.write
    def competing_index(*args, **kwargs):
        original_write(*args, **kwargs)
        processed.mkdir(exist_ok=True)
        (processed / "metadata.csv").write_bytes(b"late index competitor")
    monkeypatch.setattr(sf, "write", competing_index)
    with pytest.raises(FileExistsError):
        convert_index(indexed_raw)
    assert (processed / "metadata.csv").read_bytes() == b"late index competitor"
    assert (processed / "Chincol/0001.wav").is_file()


@pytest.mark.parametrize("explicit", [False, True])
def test_sanitize_cli_binds_physical_roots_and_raw_index(tmp_path, monkeypatch, explicit):
    from poc import sanitize
    roots = {"raw": tmp_path / "configured-raw", "processed": tmp_path / "configured-processed"}
    lookups = []
    def configured(name):
        assert name == "AvesChilenas"
        lookups.append(name)
        return roots
    monkeypatch.setattr(sanitize, "get_dataset_roots", configured)
    observed = []
    def boundary(raw, processed, **kwargs):
        observed.append((raw, processed, kwargs))
        return {"total": 0, "converted": 0, "failed": 0}
    monkeypatch.setattr(sanitize, "sanitize_dataset", boundary)
    index = tmp_path / "indexes" / "raw.csv"
    output_index = tmp_path / "indexes" / "derived.csv"
    argv = ["--metadata-index", str(index), "--output-index", str(output_index), "--workers", "1", "--sr", "8000"]
    if explicit:
        roots = {"raw": tmp_path / "override-raw", "processed": tmp_path / "override-processed"}
        argv += ["--raw-dir", str(roots["raw"]), "--output-dir", str(roots["processed"])]
    sanitize.main(argv)
    assert observed == [(roots["raw"], roots["processed"],
                         {"target_sr": 8000, "num_workers": 1, "show_progress": True,
                          "metadata_index": index, "roots": roots, "output_index": output_index})]
    assert lookups == ([] if explicit else ["AvesChilenas"])
    assert list(tmp_path.iterdir()) == []


def test_mixed_conversion_indexes_only_successful_derivatives(indexed_raw):
    raw, processed, index, rows = indexed_raw
    (raw / "corrupt.mp3").write_bytes(b"not valid audio")
    pd.DataFrame([*rows, {**rows[0], "file_path": "corrupt.mp3"}]).to_csv(index, index=False)
    before = index.read_bytes()
    stats = convert_index(indexed_raw)
    assert (stats["total"], stats["converted"], stats["failed"]) == (2, 1, 1)
    derived = pd.read_csv(processed / "metadata.csv", dtype=str, keep_default_na=False)
    assert derived.to_dict("records") == [{**rows[0], "file_stage": "processed"}]
    assert not (processed / "corrupt.wav").exists()
    assert index.read_bytes() == before


def test_explicit_output_index_does_not_change_processed_root(indexed_raw, tmp_path):
    from dataset_references import resolve_reference
    raw, processed, index, _ = indexed_raw
    output_index = tmp_path / "indexes" / "derived.csv"
    convert_index(indexed_raw, output_index=output_index)
    row = pd.read_csv(output_index, dtype=str, keep_default_na=False).iloc[0]
    assert resolve_reference(row["file_path"], row["file_stage"], {"processed": processed}) == processed / "Chincol/0001.wav"
    assert not (processed / "metadata.csv").exists()
