from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

TargetType = Literal["measured_arrival", "reported_delay_state", "reported_delay_state_fixed_lag"]


@dataclass(frozen=True)
class LabelPolicy:
    version: str
    target_type: TargetType
    audit_sha256: str
    approved_at: str
    minimum_join_rate: float = 0.9
    minimum_candidate_coverage: float = 0.7
    notes: str = ""
    review_sha256: str = ""
    label_lag_seconds: int | None = None
    candidate_window_seconds: int = 1800
    routes: tuple[str, ...] = ()
    scope_report_sha256: str = ""

    @classmethod
    def load(cls, path: Path) -> LabelPolicy:
        value = json.loads(path.read_text())
        value["routes"] = tuple(value.get("routes") or ())
        policy = cls(**value)
        if policy.target_type not in {
            "measured_arrival",
            "reported_delay_state",
            "reported_delay_state_fixed_lag",
        }:
            raise ValueError(f"unsupported label target: {policy.target_type}")
        if policy.target_type == "reported_delay_state_fixed_lag" and (
            policy.label_lag_seconds is None
            or policy.label_lag_seconds <= 0
            or policy.candidate_window_seconds <= 0
            or not policy.routes
            or not policy.scope_report_sha256
        ):
            raise ValueError("fixed-lag policy requires a positive lag, window, and route scope")
        return policy

    @classmethod
    def from_audit(
        cls,
        audit_path: Path,
        target_type: TargetType = "reported_delay_state",
        notes: str = "",
        review_path: Path | None = None,
        label_lag_seconds: int | None = None,
        candidate_window_seconds: int = 1800,
        routes: tuple[str, ...] = (),
        scope_report_path: Path | None = None,
    ) -> LabelPolicy:
        if target_type == "reported_delay_state_fixed_lag" and (
            label_lag_seconds is None
            or label_lag_seconds <= 0
            or candidate_window_seconds <= 0
            or not routes
            or scope_report_path is None
        ):
            raise ValueError("fixed-lag policy requires a positive lag, window, and route scope")
        payload = audit_path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        review_digest = hashlib.sha256(review_path.read_bytes()).hexdigest() if review_path else ""
        scope_digest = (
            hashlib.sha256(scope_report_path.read_bytes()).hexdigest() if scope_report_path else ""
        )
        identity = hashlib.sha256(
            f"{digest}:{target_type}:{review_digest}:{label_lag_seconds}:"
            f"{candidate_window_seconds}:{','.join(routes)}:{scope_digest}".encode()
        ).hexdigest()[:12]
        return cls(
            version=f"label-{target_type.replace('_', '-')}-{identity}",
            target_type=target_type,
            audit_sha256=digest,
            approved_at=datetime.now(UTC).isoformat(),
            notes=notes,
            review_sha256=review_digest,
            label_lag_seconds=label_lag_seconds,
            candidate_window_seconds=candidate_window_seconds,
            routes=routes,
            scope_report_sha256=scope_digest,
        )

    def verify_audit(self, audit_path: Path) -> None:
        digest = hashlib.sha256(audit_path.read_bytes()).hexdigest()
        if digest != self.audit_sha256:
            raise RuntimeError("label policy audit checksum does not match the current audit")

    def verify_review(self, review_path: Path) -> None:
        digest = hashlib.sha256(review_path.read_bytes()).hexdigest()
        if not self.review_sha256 or digest != self.review_sha256:
            raise RuntimeError("label policy review checksum does not match the approved review")

    def verify_archives(self, data_dir: Path) -> None:
        state = data_dir / "state"
        self.verify_audit(state / "label-audits" / f"{self.audit_sha256}.json")
        self.verify_review(state / "label-reviews" / f"{self.review_sha256}.json")
        if self.scope_report_sha256:
            scope_path = state / "route-scopes" / f"{self.scope_report_sha256}.json"
            if hashlib.sha256(scope_path.read_bytes()).hexdigest() != self.scope_report_sha256:
                raise RuntimeError("label policy route-scope checksum does not match")

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), indent=2, sort_keys=True))
        temporary.replace(path)
