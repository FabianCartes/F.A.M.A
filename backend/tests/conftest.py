import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

_PROJECT_ROOT = _BACKEND_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# Collection imports the training singleton before function-scoped fixtures run.
# Redirect only its default mkdir; every other filesystem operation remains real.
import tempfile
import os
from contextlib import ExitStack
from unittest.mock import patch

# Only the explicitly selected audio/feedback suites get collection isolation.
# Real create_all still runs, against SQLite; do not replace schema operations.
_focused_suites = {
    "test_prediction_audio_metadata.py", "test_prediction_audio_metadata_migration.py",
    "test_api_feedback.py", "test_api_feedback_sync.py",
    "test_feedback_local_approval.py", "test_feedback_sync_worker.py",
}
_selected_suites = {Path(arg.split("::")[0]).name for arg in sys.argv[1:]
                    if arg.split("::")[0].endswith(".py")}
_collection_isolation = ExitStack()
if _selected_suites and _selected_suites <= _focused_suites:
    _collection_isolation.enter_context(patch.dict(os.environ, {"DATABASE_URL": "sqlite://"}))
    _collection_isolation.enter_context(patch("dotenv.load_dotenv", return_value=False))

_collection_checkpoints = tempfile.TemporaryDirectory(prefix="fama-test-checkpoints-")
_temporary_checkpoints = Path(_collection_checkpoints.name) / "checkpoints"
_default_checkpoints = _BACKEND_DIR / "checkpoints"
_original_mkdir = Path.mkdir
_redirected_checkpoint_mkdirs = []


def _collection_mkdir(path, *args, **kwargs):
    if path == _default_checkpoints:
        _redirected_checkpoint_mkdirs.append(path)
        return _original_mkdir(_temporary_checkpoints, *args, **kwargs)
    return _original_mkdir(path, *args, **kwargs)


with patch("dotenv.load_dotenv", return_value=False), patch.object(Path, "mkdir", _collection_mkdir):
    from app.services import training as _training

assert _redirected_checkpoint_mkdirs == [_default_checkpoints]
_training.training_service.checkpoints_dir = _temporary_checkpoints
assert _training.training_service.checkpoints_dir.is_relative_to(Path(_collection_checkpoints.name))


def pytest_unconfigure(config):
    _collection_checkpoints.cleanup()
    _collection_isolation.close()
