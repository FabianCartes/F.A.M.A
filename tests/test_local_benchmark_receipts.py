"""Validate retained evidence without rerunning benchmarks or opening assets."""
import json
from pathlib import Path
import statistics

import pytest


RECEIPTS = Path(__file__).resolve().parents[1] / "docs" / "receipts"


def receipt(name):
    return json.loads((RECEIPTS / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["benchmark_local_cpu_20261015.json",
                                "benchmark_local_cpu_inference_20261016.json",
                                "benchmark_local_cpu_inference_validated_20261016.json"])
def test_real_benchmark_preserves_authorized_inputs_and_records_budgets(name):
    data = receipt(name)
    assert data["authorization"]["local_cpu_only"] is True
    assert data["authorization"]["network_allowed"] is False
    assert data["authorization"]["training_allowed"] is False
    assert data["authorization"]["real_database_or_gcs_allowed"] is False
    assert data["abort_reason"] is None
    assert data["observed_peak_rss_bytes"] <= data["budgets"]["rss_bytes"]
    assert data["minimum_available_ram_bytes"] >= data["budgets"]["minimum_available_ram_bytes"]
    assert data["monitor_elapsed_seconds"] <= data["budgets"]["seconds"]
    assert data["worker_result"]["device"] == "cpu"
    assert data["reproduction"]["worker_source"]
    assert data["reproduction"]["monitor_source"]
    for item in data["worker_result"]["inputs"].values():
        assert item["content_and_mtime_unchanged"] is True
        assert item["before"] == item["after"]


def test_failure_history_is_retained_and_noise_path_is_not_claimed_as_classifier_forward():
    initial = receipt("benchmark_local_cpu_20261015.json")
    intermediate = receipt("benchmark_local_cpu_inference_20261016.json")
    final = receipt("benchmark_local_cpu_inference_validated_20261016.json")
    assert initial["status"] == "failed"
    assert intermediate["status"] == "failed"
    assert "backbone.global_pool.p" in initial["worker_result"]["error"]["message"]
    assert final["status"] == "completed"
    result = final["worker_result"]["measurements"]["predictor"]["last_result"]
    assert result["status"] == "noise"
    assert result["classifier_forward_observed"] is False
    assert result["reported_forward_latency_ms"] is None
    assert result["is_mock"] is False
    assert final["worker_result"]["observed_pool_type"] == "avg"
    assert final["worker_result"]["predictor_preprocessing"]["legacy_n_mels"] == 128


@pytest.mark.parametrize("name,stage", [("benchmark_local_cpu_20261015.json", "preprocessing"),
                                      ("benchmark_local_cpu_inference_validated_20261016.json", "predictor")])
def test_summary_matches_recorded_samples_not_an_acceptance_threshold(name, stage):
    measured = receipt(name)["worker_result"]["measurements"][stage]
    assert len(measured["warm_seconds"]) == 5
    assert all(value > 0 for value in measured["warm_seconds"])
    assert measured["warm_median_seconds"] == statistics.median(measured["warm_seconds"])
    assert measured["warm_min_seconds"] == min(measured["warm_seconds"])
    assert measured["warm_max_seconds"] == max(measured["warm_seconds"])


def test_metadata_diagnostic_is_not_a_latency_or_quality_benchmark():
    data = receipt("checkpoint_compatibility_metadata_20261016.json")
    result = data["worker_result"]
    assert data["diagnostic_executed"] is True
    assert result["benchmark_timings"] is None
    assert result["checkpoint_unchanged"] is True
    assert result["selected_metadata"] == {"model_type": "efficientnet_b0", "n_mels": 128}
    assert "pool_type" not in result["payload_keys"]
