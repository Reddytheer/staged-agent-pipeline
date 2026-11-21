"""Model tiers behind one interface.

`ModelClient` is the seam: plug a real LLM client in here and nothing else in the
pipeline changes. The bundled `SimulatedModel` lets the repo run without an API
key. It answers from ground truth with a tier-specific error rate, latency and
price, and it is sometimes confidently wrong, which is the failure the gates
exist to catch. Its numbers are assumptions for demonstrating trade-offs, not
benchmarks of any real model.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Any, Protocol

from .schema import FIELDS


@dataclass(frozen=True)
class TierProfile:
    name: str
    accuracy: float         # chance of the right answer on an ambiguous field
    latency_s: float        # per call
    cost_usd: float         # per call
    overconfidence: float   # chance a wrong answer still reports high confidence


TIERS = {
    "small": TierProfile("small", accuracy=0.93, latency_s=0.6, cost_usd=0.0006, overconfidence=0.20),
    "frontier": TierProfile("frontier", accuracy=0.97, latency_s=2.8, cost_usd=0.015, overconfidence=0.15),
}


class ModelClient(Protocol):
    tier: TierProfile

    def resolve(self, field: str, evidence: str, packet_id: str) -> tuple[Any, float]:
        """Return (value or None, self-reported confidence) for one ambiguous field."""


class SimulatedModel:
    def __init__(self, tier: str, oracle: dict[str, dict], seed: int = 0, degrade: float = 0.0):
        self.tier = TIERS[tier]
        self.oracle = oracle            # packet_id -> true values (simulation only)
        self.seed = seed
        self.degrade = degrade          # used in tests to simulate a model regression

    def _rng(self, packet_id: str, field: str) -> random.Random:
        h = hashlib.sha256(f"{self.seed}|{self.tier.name}|{packet_id}|{field}".encode()).hexdigest()
        return random.Random(int(h[:12], 16))

    def resolve(self, field: str, evidence: str, packet_id: str) -> tuple[Any, float]:
        rng = self._rng(packet_id, field)
        truth = self.oracle[packet_id][field]
        if not evidence.strip():
            return None, 0.0            # nothing to read: never invent a value
        if rng.random() < self.tier.accuracy - self.degrade:
            return truth, rng.uniform(0.90, 0.995)
        wrong = _plausible_wrong(field, truth, rng)
        conf = rng.uniform(0.95, 0.99) if rng.random() < self.tier.overconfidence else rng.uniform(0.55, 0.85)
        return wrong, conf


def _plausible_wrong(field: str, truth: Any, rng: random.Random) -> Any:
    spec = FIELDS[field]
    if spec.kind == "enum":
        return rng.choice([c for c in spec.choices if c != truth])
    if spec.kind == "int":
        return int(truth * rng.choice([0.9, 1.1, 10, 0.1])) if truth > 100 else truth + rng.choice([-2, -1, 1, 2])
    return f"{truth} (unverified)"
