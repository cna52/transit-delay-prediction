from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from transit_delay.models.training import TrainedModel


@dataclass(frozen=True)
class ArtifactManifest:
    model_version: str
    model_name: str
    created_at: str
    dataset_version: str
    feature_schema_version: str
    python_version: str
    dependency_fingerprint: str
    git_commit: str
    model_sha256: str
    validation_residual_quantiles: dict[str, float]


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = root

    def save(
        self,
        model: TrainedModel,
        dataset_version: str,
        residual_quantiles: dict[str, float],
    ) -> ArtifactManifest:
        import joblib

        identity = json.dumps(
            {"name": model.name, "dataset": dataset_version, "features": model.feature_names},
            sort_keys=True,
        )
        version = f"model-{hashlib.sha256(identity.encode()).hexdigest()[:12]}"
        directory = self.root / version
        directory.mkdir(parents=True, exist_ok=True)
        model_path = directory / "model.joblib"
        temporary = model_path.with_suffix(".tmp")
        joblib.dump(model, temporary)
        os.replace(temporary, model_path)
        digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
        manifest = ArtifactManifest(
            version,
            model.name,
            datetime.now(UTC).isoformat(),
            dataset_version,
            "v1",
            platform.python_version(),
            _dependency_fingerprint(),
            _git_commit(),
            digest,
            residual_quantiles,
        )
        (directory / "manifest.json").write_text(
            json.dumps(asdict(manifest), indent=2, sort_keys=True)
        )
        return manifest

    def promote(self, model_version: str) -> None:
        directory = self.root / model_version
        if not (directory / "manifest.json").exists():
            raise FileNotFoundError(f"unknown model version: {model_version}")
        temporary = self.root / "champion.tmp"
        temporary.write_text(json.dumps({"model_version": model_version}, sort_keys=True))
        os.replace(temporary, self.root / "champion.json")

    def load_champion(self) -> tuple[TrainedModel, ArtifactManifest]:
        import joblib

        pointer = json.loads((self.root / "champion.json").read_text())
        directory = self.root / pointer["model_version"]
        manifest = ArtifactManifest(**json.loads((directory / "manifest.json").read_text()))
        model_path = directory / "model.joblib"
        if hashlib.sha256(model_path.read_bytes()).hexdigest() != manifest.model_sha256:
            raise RuntimeError("model artifact checksum mismatch")
        if platform.python_version() != manifest.python_version:
            raise RuntimeError("model Python version does not match serving environment")
        return joblib.load(model_path), manifest


def _dependency_fingerprint() -> str:
    try:
        output = subprocess.check_output(
            [sys.executable, "-m", "pip", "freeze"], text=True, stderr=subprocess.DEVNULL
        )
    except (OSError, subprocess.SubprocessError):
        output = "unavailable"
    return hashlib.sha256(output.encode()).hexdigest()


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "uncommitted"
