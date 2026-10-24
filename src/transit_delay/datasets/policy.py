from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

TargetType = Literal["measured_arrival", "reported_delay_state"]


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

    @classmethod
    def load(cls, path: Path) -> LabelPolicy:
        value = json.loads(path.read_text())
        policy = cls(**value)
        if policy.target_type not in {"measured_arrival", "reported_delay_state"}:
            raise ValueError(f"unsupported label target: {policy.target_type}")
        return policy

    @classmethod
    def from_audit(
        cls,
        audit_path: Path,
        target_type: TargetType = "reported_delay_state",
        notes: str = "",
        review_path: Path | None = None,
    ) -> LabelPolicy:
        payload = audit_path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        review_digest = hashlib.sha256(review_path.read_bytes()).hexdigest() if review_path else ""
        identity = hashlib.sha256(f"{digest}:{target_type}:{review_digest}".encode()).hexdigest()[
            :12
        ]
        return cls(
            version=f"label-{target_type.replace('_', '-')}-{identity}",
            target_type=target_type,
            audit_sha256=digest,
            approved_at=datetime.now(UTC).isoformat(),
            notes=notes,
            review_sha256=review_digest,
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

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), indent=2, sort_keys=True))
        temporary.replace(path)
