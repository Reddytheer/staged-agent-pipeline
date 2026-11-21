"""Evals: score any pipeline variant against ground truth, calibrate the autonomy
ladder, A/B test architectures, and gate releases on regressions.

The metric that matters most is the false-accept rate: a wrong value that no
person ever saw. Everything else is a cost to be traded against it.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import asdict
from pathlib import Path

from .gates import AUTONOMOUS, AutonomyLadder, all_keys, clears_threshold, decision_key
from .models import SimulatedModel
from .orchestrator import Pipeline, PipelineConfig
from .schema import FIELDS
from .synth import make_dataset

REVIEW_SECONDS = 45          # a person confirms or fixes one flagged field with evidence in view
FOLLOW_UP_SECONDS = 300      # a field missing from every document needs a request to the insured
CALIBRATION, TEST = 1000, 300 # packets used to earn autonomy vs packets used to report results
DRIFT = 0.35                 # regression drill: small-model accuracy drop


def build(config: PipelineConfig, oracle: dict, ladder: AutonomyLadder, degrade_small: float = 0.0) -> Pipeline:
    models = {"small": SimulatedModel("small", oracle, degrade=degrade_small),
              "frontier": SimulatedModel("frontier", oracle)}
    return Pipeline(config, models, ladder)


def calibrate(config: PipelineConfig, data, degrade_small: float = 0.0) -> tuple[AutonomyLadder, dict]:
    """Earn autonomy on a calibration split: would each family's confident answers have been right?"""
    oracle = {p.packet_id: t.values for p, t in data}
    probe = AutonomyLadder(levels={k: AUTONOMOUS for k in all_keys()})
    pipe = build(config, oracle, probe, degrade_small)
    outcomes: dict[str, list[bool]] = {k: [] for k in all_keys()}
    for packet, truth in data:
        rec = pipe.run(packet)
        for f, fv in rec.fields.items():
            if fv.status == "auto_accepted" and clears_threshold(f, fv.confidence):
                outcomes[decision_key(f, fv.source)].append(fv.value == truth.values[f])
    ladder = AutonomyLadder()
    return ladder, ladder.calibrate(outcomes)


def score(config: PipelineConfig, data, ladder: AutonomyLadder, degrade_small: float = 0.0) -> dict:
    oracle = {p.packet_id: t.values for p, t in data}
    pipe = build(config, oracle, ladder, degrade_small)
    n_fields = auto = auto_wrong = review = follow_ups = straight_through = 0
    f_tp = f_fp = f_fn = 0
    latencies, costs, review_secs = [], [], []
    per_family = {s.family: [0, 0] for s in FIELDS.values()}     # [auto, wrong]
    for packet, truth in data:
        rec = pipe.run(packet)
        secs = 0
        for f, fv in rec.fields.items():
            n_fields += 1
            if fv.status == "auto_accepted":
                auto += 1
                per_family[FIELDS[f].family][0] += 1
                if fv.value != truth.values[f]:
                    auto_wrong += 1
                    per_family[FIELDS[f].family][1] += 1
            else:
                review += 1
                secs += FOLLOW_UP_SECONDS if fv.value is None else REVIEW_SECONDS
                follow_ups += fv.value is None
        straight_through += secs == 0
        found = {x.code for x in rec.findings if not x.code.startswith("missing:")}
        f_tp += len(found & truth.findings)
        f_fp += len(found - truth.findings)
        f_fn += len(truth.findings - found)
        latencies.append(rec.latency_s)
        costs.append(rec.cost_usd)
        review_secs.append(secs)
    n = len(data)
    lat = sorted(latencies)
    return {
        "variant": config.name, "packets": n, "fields": n_fields,
        "auto_accept_rate": round(auto / n_fields, 4),
        "false_accept_rate": round(auto_wrong / n_fields, 4),
        "auto_precision": round(1 - auto_wrong / auto, 4) if auto else None,
        "straight_through_rate": round(straight_through / n, 4),
        "review_items_per_packet": round(review / n, 2),
        "follow_ups_per_packet": round(follow_ups / n, 2),
        "review_minutes_per_packet": round(statistics.mean(review_secs) / 60, 2),
        "finding_recall": round(f_tp / (f_tp + f_fn), 4) if f_tp + f_fn else None,
        "finding_precision": round(f_tp / (f_tp + f_fp), 4) if f_tp + f_fp else None,
        "latency_p50_s": round(lat[n // 2], 2), "latency_p95_s": round(lat[int(n * 0.95) - 1], 2),
        "cost_per_packet_usd": round(statistics.mean(costs), 4),
        "false_accepts_by_family": {k: v[1] for k, v in per_family.items() if v[1]},
    }


VARIANTS = [
    PipelineConfig("staged_tiered"),
    PipelineConfig("staged_frontier_only", routing="frontier_only"),
    PipelineConfig("staged_no_gates", gates=False),
    PipelineConfig("monolith_frontier", mode="monolith"),
]


def run_all(seed: int = 7) -> dict:
    data = make_dataset(CALIBRATION + TEST, seed)
    cal, test = data[:CALIBRATION], data[CALIBRATION:]
    results, ladders = [], {}
    for cfg in VARIANTS:
        ladder, report = calibrate(cfg, cal)
        if cfg.mode == "monolith" or not cfg.gates:
            ladder = AutonomyLadder(levels={k: AUTONOMOUS for k in all_keys()})
            report = {}
        ladders[cfg.name] = report
        results.append(score(cfg, test, ladder))

    # Regression drill: the small model silently gets worse. Does the system notice?
    ladder_bad, drill = calibrate(VARIANTS[0], cal, degrade_small=DRIFT)
    degraded = score(VARIANTS[0], test, ladder_bad, degrade_small=DRIFT)
    degraded["variant"] = "staged_tiered + degraded small model (recalibrated)"
    ladder_stale, _ = calibrate(VARIANTS[0], cal)
    stale = score(VARIANTS[0], test, ladder_stale, degrade_small=DRIFT)
    stale["variant"] = "staged_tiered + degraded small model (NOT recalibrated)"
    return {"seed": seed, "calibration_packets": CALIBRATION, "test_packets": TEST,
            "results": results, "ladder": ladders["staged_tiered"],
            "regression_drill": {"ladder_after_drift": drill, "recalibrated": degraded, "stale": stale}}


GATE = {"max_false_accept_rate": 0.005, "max_auto_accept_drop": 0.02, "max_cost_increase": 0.10}


def check(current: dict, baseline: dict) -> list[str]:
    """Release gate: fail on any regression that matters, not on an average."""
    cur = next(r for r in current["results"] if r["variant"] == "staged_tiered")
    base = next(r for r in baseline["results"] if r["variant"] == "staged_tiered")
    errors = []
    if cur["false_accept_rate"] > GATE["max_false_accept_rate"]:
        errors.append(f"false-accept rate {cur['false_accept_rate']:.2%} > {GATE['max_false_accept_rate']:.2%}")
    if cur["auto_accept_rate"] < base["auto_accept_rate"] - GATE["max_auto_accept_drop"]:
        errors.append(f"auto-accept dropped {base['auto_accept_rate']:.1%} -> {cur['auto_accept_rate']:.1%}")
    if cur["cost_per_packet_usd"] > base["cost_per_packet_usd"] * (1 + GATE["max_cost_increase"]):
        errors.append(f"cost/packet rose ${base['cost_per_packet_usd']} -> ${cur['cost_per_packet_usd']}")
    return errors


def write_report(res: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics.json").write_text(json.dumps(res, indent=2))
    cols = [("auto_accept_rate", "Auto-accepted", "%"), ("false_accept_rate", "False accepts", "%"),
            ("straight_through_rate", "Straight-through packets", "%"),
            ("review_minutes_per_packet", "Review min / packet", ""), ("finding_recall", "Finding recall", "%"),
            ("latency_p50_s", "p50 latency (s)", ""), ("latency_p95_s", "p95 latency (s)", ""),
            ("cost_per_packet_usd", "Model cost / packet", "$")]
    fmt = lambda v, u: "n/a" if v is None else (f"{v:.1%}" if u == "%" else f"${v:.4f}" if u == "$" else f"{v}")
    rows = [res["results"][0], *res["results"][1:], res["regression_drill"]["stale"], res["regression_drill"]["recalibrated"]]
    lines = ["# Eval report (generated)", "",
             f"Seed {res['seed']} · {res['calibration_packets']} calibration packets · "
             f"{res['test_packets']} test packets · 12 fields each. Synthetic data and simulated model tiers; "
             "see docs/EVALS.md for what these numbers do and do not mean.", "",
             "| Variant | " + " | ".join(c[1] for c in cols) + " |", "|---" * (len(cols) + 1) + "|"]
    for r in rows:
        lines.append(f"| {r['variant']} | " + " | ".join(fmt(r[c[0]], c[2]) for c in cols) + " |")
    lines += ["", "## Autonomy earned on the calibration split (staged_tiered)", "",
              "| Decision type | n | Precision | 95% lower bound | Level |", "|---|---|---|---|---|"]
    for fam, r in sorted(res["ladder"].items()):
        prec = "n/a" if r["precision"] is None else f"{r['precision']:.1%}"
        lines.append(f"| {fam} | {r['n']} | {prec} | {r['lower_bound']:.1%} | {r['to']} |")
    lines += ["", f"## Regression drill: small-model accuracy drops {DRIFT * 100:.0f} points", "",
              "| Decision type | Level before | Level after recalibration |", "|---|---|---|"]
    for fam, r in sorted(res["regression_drill"]["ladder_after_drift"].items()):
        lines.append(f"| {fam} | {res['ladder'][fam]['to']} | {r['to']} |")
    (out_dir / "report.md").write_text("\n".join(lines) + "\n")
