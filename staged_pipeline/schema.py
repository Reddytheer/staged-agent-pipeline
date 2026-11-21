"""Canonical record, field specs and the small data types every step shares.

The canonical schema is deliberately generic: public COPE/SOV concepts that any
commercial property underwriter would recognise. Nothing here is taken from a
real carrier's or vendor's data model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# How costly a wrong auto-accepted value is. Drives the confidence threshold
# and how far up the autonomy ladder a field family may climb.
STAKES = ("low", "medium", "high")

CONSTRUCTION_CLASSES = (  # ISO construction classes 1-6, public taxonomy
    "frame", "joisted_masonry", "non_combustible",
    "masonry_non_combustible", "modified_fire_resistive", "fire_resistive",
)
OCCUPANCIES = ("habitational", "office", "retail", "warehouse")
SPRINKLER = ("full", "partial", "none")


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: str          # "int" | "enum" | "str"
    family: str        # decision type the autonomy ladder tracks
    stakes: str        # "low" | "medium" | "high"
    choices: tuple = ()


FIELDS: dict[str, FieldSpec] = {s.name: s for s in [
    FieldSpec("address", "str", "identity", "low"),
    FieldSpec("year_built", "int", "construction", "medium"),
    FieldSpec("construction_class", "enum", "construction", "high", CONSTRUCTION_CLASSES),
    FieldSpec("stories", "int", "construction", "medium"),
    FieldSpec("square_feet", "int", "construction", "medium"),
    FieldSpec("occupancy", "enum", "occupancy", "medium", OCCUPANCIES),
    FieldSpec("sprinklered", "enum", "protection", "high", SPRINKLER),
    FieldSpec("protection_class", "int", "protection", "medium"),
    FieldSpec("building_value", "int", "values", "high"),
    FieldSpec("contents_value", "int", "values", "high"),
    FieldSpec("policy_limit", "int", "coverage", "high"),
    FieldSpec("deductible", "int", "coverage", "high"),
]}


@dataclass
class Citation:
    doc_id: str
    line: int
    text: str


@dataclass
class FieldValue:
    """One field as it moves through the pipeline, with its evidence."""
    name: str
    value: Any
    confidence: float
    citation: Citation | None
    source: str                      # "rules" | "model:small" | "model:frontier" | "human"
    status: str = "pending"          # "auto_accepted" | "review" | "human_corrected" | "human_confirmed"
    notes: list[str] = field(default_factory=list)


@dataclass
class Document:
    doc_id: str
    kind: str          # "sov" | "cope" | "dec_page" | "unknown"
    provider: str
    text: str


@dataclass
class Packet:
    packet_id: str
    documents: list[Document]


@dataclass
class Finding:
    """A validation result an underwriter should see, with its evidence."""
    code: str
    severity: str      # "info" | "warn" | "high"
    message: str
    citations: list[Citation] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    provisional: bool = False      # rests on a value a person has not yet confirmed


@dataclass
class StepTrace:
    step: str
    latency_s: float
    cost_usd: float
    model_calls: int = 0


@dataclass
class UnderwritingRecord:
    packet_id: str
    fields: dict[str, FieldValue]
    findings: list[Finding]
    trace: list[StepTrace]

    @property
    def latency_s(self) -> float:
        return sum(t.latency_s for t in self.trace)

    @property
    def cost_usd(self) -> float:
        return sum(t.cost_usd for t in self.trace)
