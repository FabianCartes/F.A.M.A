"""Las dependencias que forman parte de ``runtime_versions`` deben fijarse exactamente."""

import re
from pathlib import Path

REQUIREMENTS = Path(__file__).resolve().parents[1] / "requirements.txt"
PINNED_PACKAGES = ("torch", "torchaudio", "torchvision", "numpy", "librosa")


def _requirement_lines() -> dict[str, str]:
    lines: dict[str, str] = {}
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        match = re.match(r"^([A-Za-z0-9_.-]+)", line)
        if match:
            lines[match.group(1).lower()] = line
    return lines


def test_runtime_packages_are_pinned_to_exact_versions_without_build_suffix():
    declared = _requirement_lines()
    for package in PINNED_PACKAGES:
        assert package in declared, f"{package} no está declarado en requirements.txt"
        assert re.fullmatch(
            rf"{package}==\d+(\.\d+)*", declared[package]
        ), f"{package} debe fijarse con == y sin sufijo de build: {declared[package]!r}"
