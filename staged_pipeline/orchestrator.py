"""The orchestrator: runs the steps, routes ambiguity to the right model tier, and
decides per field whether a person needs to look.

Two architectures live here so they can be A/B tested on the same packets:
  * staged   - specialist steps, rules first, per-field gates (the design)
  * monolith - one long-context call, one document-level confidence (the baseline)
"""
from __future__ import annotations

from dataclasses import dataclass

from . import steps
from .gates import AutonomyLadder, clears_threshold
from .models import TierProfile, SimulatedModel
from .schema import FIELDS, FieldValue, Packet, StepTrace, UnderwritingRecord

RULE_STEP_LATENCY_S = 0.02     # deterministic steps: effectively free


@dataclass
class PipelineConfig:
    name: str = "staged_tiered"
    mode: str = "staged"          # "staged" | "monolith"
    routing: str = "tiered"       # "tiered" | "frontier_only"
    gates: bool = True
    escalate_below: float = 0.90  # rules confidence below this asks a model


MONOLITH = TierProfile("frontier-long-context", accuracy=0.93, latency_s=9.0, cost_usd=0.06, overconfidence=0.25)


class Pipeline:
    def __init__(self, config: PipelineConfig, models: dict[str, SimulatedModel], ladder: AutonomyLadder):
        self.cfg, self.models, self.ladder = config, models, ladder

    # ------------------------------------------------------------ routing
    def tier_for(self, field: str) -> str:
        if self.cfg.routing == "frontier_only":
            return "frontier"
        return "frontier" if FIELDS[field].stakes == "high" else "small"

    # ------------------------------------------------------------ staged
    def run(self, packet: Packet) -> UnderwritingRecord:
        if self.cfg.mode == "monolith":
            return self._run_monolith(packet)
        trace: list[StepTrace] = []

        kinds = {d.doc_id: steps.classify(d)[0] for d in packet.documents}
        trace.append(StepTrace("intake", RULE_STEP_LATENCY_S, 0.0))

        by_field: dict[str, list] = {f: [] for f in FIELDS}
        evidence: dict[str, str] = {f: "" for f in FIELDS}
        for d in packet.documents:
            for c in steps.extract(d, kinds[d.doc_id]):
                by_field[c.field].append((c.doc_kind, steps.normalize(c, FIELDS[c.field].kind)))
                evidence[c.field] += c.citation.text + "\n"
        trace.append(StepTrace("extract+normalize", RULE_STEP_LATENCY_S, 0.0))

        fields, conflicts = {}, []
        for f in FIELDS:
            fv, conflict = steps.reconcile(f, by_field[f])
            fields[f] = fv or FieldValue(f, None, 0.0, None, "rules", notes=["not found in any document"])
            if conflict:
                conflicts.append(f)

        # Escalate only what rules could not settle. Conflicts skip the model:
        # when documents disagree, a person decides.
        calls, cost, slowest = 0, 0.0, 0.0
        for f, fv in fields.items():
            if f in conflicts or not evidence[f] or fv.confidence >= self.cfg.escalate_below:
                continue
            model = self.models[self.tier_for(f)]
            value, conf = model.resolve(f, evidence[f], packet.packet_id)
            fields[f] = FieldValue(f, value, conf, fv.citation, f"model:{model.tier.name}", notes=fv.notes)
            calls, cost = calls + 1, cost + model.tier.cost_usd
            slowest = max(slowest, model.tier.latency_s)   # calls run in parallel
        trace.append(StepTrace("model escalation", slowest, cost, calls))

        findings = steps.validate(fields, conflicts)
        trace.append(StepTrace("validate", RULE_STEP_LATENCY_S, 0.0))

        for f, fv in fields.items():
            auto = (self.cfg.gates is False and fv.value is not None) or (
                fv.value is not None and f not in conflicts
                and clears_threshold(f, fv.confidence) and self.ladder.allows_auto(f, fv.source, packet.packet_id))
            fv.status = "auto_accepted" if auto else "review"
        for x in findings:   # never present a conclusion as settled while its inputs are not
            x.provisional = any(fields[f].status == "review" for f in x.depends_on)
        trace.append(StepTrace("gate", RULE_STEP_LATENCY_S, 0.0))
        return UnderwritingRecord(packet.packet_id, fields, findings, trace)

    # ------------------------------------------------------------ monolith baseline
    def _run_monolith(self, packet: Packet) -> UnderwritingRecord:
        model = self.models["frontier"]
        everything = "\n".join(d.text for d in packet.documents)
        mentioned = {c.field for d in packet.documents for c in steps.extract(d, steps.classify(d)[0])}
        sim = SimulatedModel("frontier", model.oracle, seed=model.seed + 1, degrade=0.97 - MONOLITH.accuracy)
        fields = {}
        for f in FIELDS:
            value, conf = sim.resolve(f, everything if f in mentioned else "", packet.packet_id)
            fields[f] = FieldValue(f, value, conf, None, "model:monolith")
        doc_conf = sum(fv.confidence for fv in fields.values()) / len(fields)
        for fv in fields.values():
            accept = fv.value is not None and (not self.cfg.gates or doc_conf >= 0.90)
            fv.status = "auto_accepted" if accept else "review"
        findings = steps.validate(fields, conflicts=[])   # disagreement is invisible in one pass
        trace = [StepTrace("single call", MONOLITH.latency_s, MONOLITH.cost_usd, 1)]
        return UnderwritingRecord(packet.packet_id, fields, findings, trace)
