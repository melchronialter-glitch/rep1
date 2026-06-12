"""Train the rug classifier from labeled risk_scores rows.

Dataset = every ``risk_scores`` row whose address appears in ``rug_labels``
(label "rug" → 1, "notrug" → 0). Features come from the stored safety JSONB
via :mod:`cryptobot.ml.features`, so training sees exactly what the detector
saw at alert time — no lookahead.

Trains a sklearn GradientBoostingClassifier (no extra deps), reports
accuracy + a 5-fold cross-val score when there's enough data, snapshots the
feature rows into ``ml_features``, and saves the model with joblib to
``ML_MODEL_PATH``. Refuses to train below ``RUG_FORENSIC_MIN_SAMPLES``
labeled examples — a model trained on 6 rows is worse than no model.

Run via ``cryptobot train-rug-model``.
"""

from __future__ import annotations

import json
import pathlib
import uuid
from typing import Any

from cryptobot.config import get_settings
from cryptobot.db import execute, fetch
from cryptobot.logging import get_logger
from cryptobot.ml.features import FEATURE_NAMES, extract_features, to_vector

log = get_logger(__name__)


async def build_dataset() -> tuple[list[list[float]], list[int], list[dict[str, Any]]]:
    """Join risk_scores with rug_labels → (X, y, meta). Latest score per address wins."""
    rows = await fetch(
        "SELECT DISTINCT ON (rs.address) "
        "  rs.address, rs.chain, rs.score, rs.safety, rs.liquidity_usd, l.label "
        "FROM risk_scores rs "
        "JOIN rug_labels l ON l.address = rs.address "
        "ORDER BY rs.address, rs.ts DESC"
    )
    X: list[list[float]] = []
    y: list[int] = []
    meta: list[dict[str, Any]] = []
    for r in rows:
        safety = r["safety"] if isinstance(r["safety"], dict) else json.loads(r["safety"] or "{}")
        liquidity = float(r["liquidity_usd"]) if r["liquidity_usd"] is not None else None
        feats = extract_features(safety, liquidity)
        X.append(to_vector(feats))
        y.append(1 if r["label"] == "rug" else 0)
        meta.append(
            {
                "address": r["address"],
                "chain": r["chain"],
                "label": r["label"],
                "features": feats,
                "score_at_detection": r["score"],
            }
        )
    return X, y, meta


async def _snapshot_features(meta: list[dict[str, Any]]) -> None:
    """Persist the training rows to ml_features for auditability. Best-effort."""
    for m in meta:
        try:
            await execute(
                "INSERT INTO ml_features (id, address, chain, label, features, score_at_detection) "
                "VALUES ($1::uuid, $2, $3, $4, $5::jsonb, $6)",
                str(uuid.uuid4()),
                m["address"],
                m["chain"],
                m["label"],
                json.dumps(m["features"]),
                m["score_at_detection"],
            )
        except Exception:
            log.exception("ml.train.snapshot_failed", address=m["address"])


async def train() -> dict[str, Any]:
    """Train and save the model. Returns a metrics dict (or a refusal reason)."""
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.model_selection import cross_val_score

    settings = get_settings()
    X, y, meta = await build_dataset()

    n_rug = sum(y)
    n_notrug = len(y) - n_rug
    if len(y) < settings.rug_forensic_min_samples:
        msg = (
            f"only {len(y)} labeled samples ({n_rug} rug / {n_notrug} notrug); "
            f"need {settings.rug_forensic_min_samples}. Label more with /rug and /notrug."
        )
        log.warning("ml.train.refused", reason=msg)
        return {"trained": False, "reason": msg, "samples": len(y)}
    if n_rug == 0 or n_notrug == 0:
        msg = f"need both classes; have {n_rug} rug / {n_notrug} notrug"
        log.warning("ml.train.refused", reason=msg)
        return {"trained": False, "reason": msg, "samples": len(y)}

    model = GradientBoostingClassifier(
        n_estimators=200, max_depth=3, learning_rate=0.05, random_state=42
    )
    model.fit(X, y)
    train_acc = float(model.score(X, y))

    cv_acc: float | None = None
    if len(y) >= 25:
        try:
            scores = cross_val_score(
                GradientBoostingClassifier(
                    n_estimators=200, max_depth=3, learning_rate=0.05, random_state=42
                ),
                X,
                y,
                cv=5,
            )
            cv_acc = float(scores.mean())
        except Exception:
            log.exception("ml.train.cv_failed")

    import joblib

    model_path = pathlib.Path(settings.ml_model_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "feature_names": FEATURE_NAMES}, model_path)

    await _snapshot_features(meta)

    importances = dict(
        sorted(
            zip(FEATURE_NAMES, (float(v) for v in model.feature_importances_)),
            key=lambda kv: kv[1],
            reverse=True,
        )
    )
    metrics = {
        "trained": True,
        "samples": len(y),
        "rug": n_rug,
        "notrug": n_notrug,
        "train_accuracy": round(train_acc, 4),
        "cv_accuracy": round(cv_acc, 4) if cv_acc is not None else None,
        "model_path": str(model_path),
        "top_features": dict(list(importances.items())[:5]),
    }
    log.info("ml.train.done", **metrics)
    return metrics
