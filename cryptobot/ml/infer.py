"""Rug-classifier inference for the rug detector.

Loads the joblib model from ``ML_MODEL_PATH`` lazily, once, and answers
"probability this token is a rug" for a feature dict. If the model file
doesn't exist (nothing trained yet) or anything fails, returns None —
the deterministic score stays authoritative and the alert flow is never
blocked.

The model file's stored feature_names are checked against the current
FEATURE_NAMES; on mismatch (schema drift after a code change) the model is
ignored until retrained.
"""

from __future__ import annotations

import pathlib
from typing import Any

from cryptobot.config import get_settings
from cryptobot.logging import get_logger
from cryptobot.ml.features import FEATURE_NAMES, to_vector

log = get_logger(__name__)

_model: Any = None
_load_attempted = False


def _load() -> Any:
    global _model, _load_attempted
    if _load_attempted:
        return _model
    _load_attempted = True
    settings = get_settings()
    path = pathlib.Path(settings.ml_model_path)
    if not path.exists():
        log.info("ml.infer.no_model", path=str(path))
        return None
    try:
        import joblib

        bundle = joblib.load(path)
        if bundle.get("feature_names") != FEATURE_NAMES:
            log.warning(
                "ml.infer.feature_mismatch",
                hint="feature schema changed since training; retrain with `cryptobot train-rug-model`",
            )
            return None
        _model = bundle["model"]
        log.info("ml.infer.model_loaded", path=str(path))
    except Exception:
        log.exception("ml.infer.load_failed", path=str(path))
    return _model


def reset_cache() -> None:
    """Forget the loaded model (next call reloads). For tests and retraining."""
    global _model, _load_attempted
    _model = None
    _load_attempted = False


def rug_probability(features: dict[str, float]) -> float | None:
    """P(rug) ∈ [0, 1] for one token, or None when no model is available."""
    model = _load()
    if model is None:
        return None
    try:
        proba = model.predict_proba([to_vector(features)])
        return float(proba[0][1])
    except Exception:
        log.exception("ml.infer.predict_failed")
        return None
