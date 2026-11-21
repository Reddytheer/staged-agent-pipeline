"""CLI.

  python -m staged_pipeline demo [packet_index]   trace one packet step by step
  python -m staged_pipeline eval                  run all variants, write results/
  python -m staged_pipeline eval --check          also fail on regression vs evals/baseline.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import evals
from .orchestrator import PipelineConfig
from .synth import make_dataset

ROOT = Path(__file__).resolve().parent.parent


def demo(idx: int) -> None:
    data = make_dataset(evals.CALIBRATION + evals.TEST)
    ladder, _ = evals.calibrate(PipelineConfig(), data[: evals.CALIBRATION])
    packet, truth = data[idx]
    pipe = evals.build(PipelineConfig(), {p.packet_id: t.values for p, t in data}, ladder)
    rec = pipe.run(packet)
    print(f"\nPacket {packet.packet_id} · provider {packet.documents[0].provider}\n")
    for t in rec.trace:
        print(f"  step {t.step:<18} {t.latency_s:>5.2f}s  ${t.cost_usd:.4f}  model calls: {t.model_calls}")
    print(f"\n  {'field':<20}{'value':<34}{'conf':>6}  {'source':<15}{'status':<14}check")
    for f, fv in rec.fields.items():
        right = fv.value == truth.values[f]
        ok = ("ok" if right else "FALSE ACCEPT") if fv.status == "auto_accepted" else (
            "person confirms" if right else "missing: ask insured" if fv.value is None else "caught by gate")
        print(f"  {f:<20}{str(fv.value)[:32]:<34}{fv.confidence:>6.2f}  {fv.source:<15}{fv.status:<14}{ok}")
        for note in fv.notes:
            print(f"  {'':<20}note: {note}")
    print("\n  Findings for the underwriter:")
    for x in rec.findings:
        print(f"   [{x.severity}] {x.code}: {x.message}" + ("  (provisional: input awaiting review)" if x.provisional else ""))
    print(f"\n  Total latency {rec.latency_s:.2f}s · model cost ${rec.cost_usd:.4f}\n")


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "demo"
    if cmd == "demo":
        demo(int(argv[1]) if len(argv) > 1 else evals.CALIBRATION)
        return 0
    if cmd == "eval":
        res = evals.run_all()
        evals.write_report(res, ROOT / "results")
        print((ROOT / "results" / "report.md").read_text())
        if "--check" in argv:
            baseline = json.loads((ROOT / "evals" / "baseline.json").read_text())
            errors = evals.check(res, baseline)
            for e in errors:
                print("REGRESSION:", e)
            print("release gate:", "FAIL" if errors else "PASS")
            return 1 if errors else 0
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
