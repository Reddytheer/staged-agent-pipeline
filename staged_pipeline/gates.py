"""Confidence gates and the autonomy ladder.

A field is auto-accepted only if (a) its confidence clears the threshold for its
stakes and (b) its decision type has *earned* autonomy on measured evidence.
Autonomy is per decision type, promoted on a statistical lower bound rather than
an average, capped for high-stakes families, and taken back automatically when
quality drops.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

from .schema import FIELDS

# Confidence a value needs before it may skip a person, by cost of being wrong.
THRESHOLDS = {"low": 0.80, "medium": 0.90, "high": 0.97}

SUGGEST, SAMPLED, AUTONOMOUS = 0, 1, 2
LEVEL_NAMES = {SUGGEST: "suggest", SAMPLED: "sampled review", AUTONOMOUS: "autonomous"}


def wilson_lower(successes: int, n: int, z: float = 1.96) -> float:
    """95% lower bound on a success rate. Small samples cannot buy autonomy."""
    if n == 0:
        return 0.0
    p = successes / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / denom


@dataclass
class LadderPolicy:
    min_samples: int = 30
    promote_sampled: float = 0.95     # lower bound on precision of auto-accepted values
    promote_autonomous: float = 0.98
    sample_rate: float = 0.10         # share of auto-accepts still checked at SAMPLED
    # Coverage terms set what the customer is actually protected for: a person
    # always samples them, however good the numbers look.
    caps: dict = field(default_factory=lambda: {"coverage": SAMPLED})


class AutonomyLadder:
    def __init__(self, policy: LadderPolicy | None = None, levels: dict[str, int] | None = None):
        self.policy = policy or LadderPolicy()
        self.levels = levels or {k: SUGGEST for k in all_keys()}
        self.evidence: dict[str, tuple[int, int]] = {}

    def level_from_evidence(self, family: str, correct: int, n: int) -> int:
        p = self.policy
        lb = wilson_lower(correct, n)
        level = SUGGEST
        if n >= p.min_samples and lb >= p.promote_sampled:
            level = SAMPLED
        if n >= p.min_samples and lb >= p.promote_autonomous:
            level = AUTONOMOUS
        return min(level, p.caps.get(family.split("+")[0], AUTONOMOUS))

    def calibrate(self, outcomes: dict[str, list[bool]]) -> dict[str, dict]:
        """Set each family's level from would-be auto-accept outcomes. Moves up or down."""
        report = {}
        for fam, results in outcomes.items():
            n, ok = len(results), sum(results)
            old, new = self.levels.get(fam, SUGGEST), self.level_from_evidence(fam, ok, n)
            self.levels[fam], self.evidence[fam] = new, (ok, n)
            report[fam] = {"n": n, "precision": ok / n if n else None,
                           "lower_bound": round(wilson_lower(ok, n), 4),
                           "from": LEVEL_NAMES[old], "to": LEVEL_NAMES[new]}
        return report

    def allows_auto(self, field_name: str, source: str, packet_id: str) -> bool:
        level = self.levels.get(decision_key(field_name, source), SUGGEST)
        if level == AUTONOMOUS:
            return True
        if level == SAMPLED:      # deterministic sampling so runs are reproducible
            h = int(hashlib.sha256(f"{packet_id}|{field_name}".encode()).hexdigest()[:8], 16)
            return (h % 1000) / 1000 >= self.policy.sample_rate
        return False


def decision_key(field_name: str, source: str) -> str:
    """Evidence is tracked where the uncertainty is: a clean rule parse and a model's
    judgment on an ambiguous value are different decisions, even for the same field."""
    family = FIELDS[field_name].family
    return family if source == "rules" else f"{family}+model"


def all_keys() -> set[str]:
    fams = {s.family for s in FIELDS.values()}
    return fams | {f"{f}+model" for f in fams}


def clears_threshold(field_name: str, confidence: float) -> bool:
    return confidence >= THRESHOLDS[FIELDS[field_name].stakes]
