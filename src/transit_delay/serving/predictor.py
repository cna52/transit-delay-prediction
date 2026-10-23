from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from transit_delay.domain import PredictionResult
from transit_delay.models.artifacts import ArtifactManifest
from transit_delay.models.baselines import HistoricalMedianBaseline, PersistenceBaseline
from transit_delay.models.training import TrainedModel


class Predictor:
    def __init__(
        self,
        model: TrainedModel | None,
        manifest: ArtifactManifest | None,
        max_feature_age_seconds: int = 300,
        fallback: HistoricalMedianBaseline | PersistenceBaseline | None = None,
    ):
        self.model = model
        self.manifest = manifest
        self.max_feature_age_seconds = max_feature_age_seconds
        self.fallback = fallback or PersistenceBaseline()

    def predict(self, row: Mapping[str, object], now: datetime | None = None) -> PredictionResult:
        now = now or datetime.now(UTC)
        observed_at = datetime.fromisoformat(str(row["as_of"]))
        if observed_at.tzinfo is None:
            raise ValueError("snapshot timestamp must be timezone-aware")
        age = max(int((now - observed_at).total_seconds()), int(str(row["source_age_seconds"])))
        degraded = age > self.max_feature_age_seconds
        if self.model is None or degraded:
            prediction = self.fallback.predict_one(row)
            reason = "no_promoted_model" if self.model is None else "stale_features"
            version = getattr(self.fallback, "version", "fallback")
            width = 5.0 if degraded else 3.0
            return PredictionResult(
                prediction,
                prediction - width,
                prediction + width,
                version,
                str(row.get("feature_schema_version", "v1")),
                "fallback" if self.model is None else "degraded",
                observed_at,
                age,
                reason,
            )
        prediction = self.model.predict([row])[0]
        quantiles = self.manifest.validation_residual_quantiles if self.manifest else {}
        lower = prediction + float(quantiles.get("q05", -3.0))
        upper = prediction + float(quantiles.get("q95", 3.0))
        return PredictionResult(
            prediction,
            lower,
            upper,
            self.manifest.model_version if self.manifest else self.model.name,
            str(row.get("feature_schema_version", "v1")),
            "normal",
            observed_at,
            age,
        )
