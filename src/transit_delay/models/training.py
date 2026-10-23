from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

CATEGORICAL_FEATURES = ["route_short_name", "direction_id", "target_stop_id", "weekday"]
NUMERIC_FEATURES = [
    "horizon_seconds",
    "current_stop_sequence",
    "stops_to_target",
    "current_delay_seconds",
    "delay_trend_seconds",
    "source_age_seconds",
    "hour",
    "minute",
]


@dataclass(frozen=True)
class TrainedModel:
    name: str
    estimator: object
    feature_names: tuple[str, ...]

    def predict(self, rows: list[Mapping[str, object]]) -> list[float]:
        frame = _frame(rows, list(self.feature_names))
        return [float(value) for value in self.estimator.predict(frame)]  # type: ignore[attr-defined]


def train_ridge(
    rows: list[Mapping[str, object]], labels: list[float], alpha: float = 1.0
) -> TrainedModel:
    try:
        from sklearn.compose import ColumnTransformer
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import Ridge
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OneHotEncoder, StandardScaler
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("scikit-learn is required for training") from exc
    categorical = Pipeline(
        [
            ("impute", SimpleImputer(strategy="most_frequent")),
            ("encode", OneHotEncoder(handle_unknown="ignore")),
        ]
    )
    numeric = Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())])
    preprocessor = ColumnTransformer(
        [("categorical", categorical, CATEGORICAL_FEATURES), ("numeric", numeric, NUMERIC_FEATURES)]
    )
    estimator = Pipeline([("features", preprocessor), ("model", Ridge(alpha=alpha))])
    features = tuple(CATEGORICAL_FEATURES + NUMERIC_FEATURES)
    estimator.fit(_frame(rows, list(features)), labels)
    return TrainedModel(f"ridge-alpha-{alpha:g}", estimator, features)


def train_lightgbm(
    rows: list[Mapping[str, object]], labels: list[float], random_state: int = 42
) -> TrainedModel:
    try:
        from lightgbm import LGBMRegressor
        from sklearn.compose import ColumnTransformer
        from sklearn.impute import SimpleImputer
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OneHotEncoder
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install the strong-model extra to train LightGBM") from exc
    features = tuple(CATEGORICAL_FEATURES + NUMERIC_FEATURES)
    preprocessing = ColumnTransformer(
        [
            (
                "categorical",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        ("encode", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                CATEGORICAL_FEATURES,
            ),
            ("numeric", SimpleImputer(strategy="median"), NUMERIC_FEATURES),
        ]
    )
    estimator = Pipeline(
        [
            ("features", preprocessing),
            (
                "model",
                LGBMRegressor(
                    objective="regression_l1",
                    n_estimators=300,
                    learning_rate=0.04,
                    num_leaves=24,
                    max_depth=6,
                    min_child_samples=40,
                    subsample=0.9,
                    colsample_bytree=0.9,
                    random_state=random_state,
                    n_jobs=-1,
                    verbosity=-1,
                ),
            ),
        ]
    )
    estimator.fit(_frame(rows, list(features)), labels)
    return TrainedModel("lightgbm-v1", estimator, features)


def _frame(rows: list[Mapping[str, object]], features: list[str]) -> Any:
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pandas is required by the scikit-learn training adapter") from exc
    return pd.DataFrame([{feature: row.get(feature) for feature in features} for row in rows])
