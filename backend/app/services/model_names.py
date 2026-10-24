"""Shared display identity; never changes storage provenance or technical IDs."""
import re
from collections import defaultdict
from pathlib import Path


def model_display_names(models):
    """Calculate history-compatible display versions over the full persisted set.

    Versions are presentation ordinals, not immutable artifact versions. Explicit
    filename versions retain the legacy rule: they do not advance the counter.
    Unlinked rows retain legacy grouping, but their dataset is not verified.
    """
    labels = {"AvesChilenas": "Aves Chilenas", "engine_diagnostics": "Motores"}
    counts = defaultdict(int)
    result = {}

    def chronological(model):
        date = getattr(model, "fecha_entrenamiento", None)
        return (date.timestamp() if date else 0, model.id_modelo or 0)

    for model in sorted(models, key=chronological):
        dataset = getattr(model, "conjunto_datos", None)
        dataset_name = getattr(dataset, "nombre", None)
        target = getattr(model, "clase_objetivo", None) or "Personalizado"
        lower = target.lower()
        legacy_group = ("Aves Chilenas" if "aves" in lower or "chilenas" in lower
                        else "Motores" if "engine" in lower or "motores" in lower else target)
        display = labels.get(dataset_name, dataset_name) if dataset_name else "Dataset no verificado"
        group = labels.get(dataset_name, dataset_name) if dataset_name else legacy_group
        architecture = model.arquitectura or "AudioCNN"
        filename = Path(model.ruta_binario_gcp or "").name
        match = re.search(r"_v(\d+)\.pt$", filename)
        if match:
            version = int(match.group(1))
        else:
            counts[(group, architecture)] += 1
            version = counts[(group, architecture)]
        result[model.id_modelo] = {
            "name": f"{display} · {architecture} (v{version})",
            "architecture": architecture, "dataset": display, "version": version,
        }
    return result
