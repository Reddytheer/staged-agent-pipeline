# Evals

## Method

- **Data.** 1,300 seeded synthetic packets (seed 7): 1,000 to calibrate the autonomy ladder, 300 held out to report results. Each packet has a schedule of values, a COPE survey and a declarations page in one of three provider formats, with ground truth for all 12 fields and for the underwriting findings.
- **Noise model.** Missing fields (5%), OCR damage on amounts and years (5%), a survey that disagrees with the schedule on year built (12%), construction phrases the rules have never seen (8%), free-text occupancy descriptions (30%), stories written as words (12%). These are the failure modes real submissions have, at rates chosen to exercise every path.
- **Models.** `SimulatedModel` answers from ground truth with a tier-specific accuracy, latency, price and overconfidence rate (small: 93%, 0.6 s, $0.0006; frontier: 97%, 2.8 s, $0.015; long-context single call: 93%, 9 s, $0.06). Wrong answers are sometimes reported with high confidence, because that is the failure gates exist for.
- **Variants.** Same packets, same models, one config change each: `staged_tiered` (the design), `staged_frontier_only`, `staged_no_gates`, `monolith_frontier`.
- **Drift drill.** The small model's accuracy drops 35 points. Scored twice: with the old ladder (stale) and after recalibration.

## Metrics, in order of importance

| Metric | Definition | Why it matters |
|---|---|---|
| False-accept rate | Wrong values auto-accepted ÷ all fields | The only error nobody catches. The release gate fails above 0.5%. |
| Finding recall | Truth findings surfaced ÷ truth findings | Did the underwriter learn about underinsurance, sprinkler gaps, conflicts? |
| Auto-accept rate | Fields accepted without a person ÷ all fields | The automation the system actually delivers |
| Review minutes per packet | 45 s per flagged field, 5 min per missing-value follow-up | Human cost, and where it goes |
| Straight-through rate | Packets with nothing for a person to do | Operational simplicity; sampling deliberately lowers it |
| Latency p50 / p95 | Sum of step latencies; model calls in a step run in parallel | Time to an underwriting-ready record |
| Model cost per packet | Sum of model calls at tier prices | Unit economics |

Auto-accept precision and per-family false-accept counts are in `results/metrics.json`.

## Results (held-out 300 packets)

| Variant | False accepts | Auto-accepted | Finding recall | Review min | p95 latency | Cost |
|---|---|---|---|---|---|---|
| **staged_tiered** | **0.1%** | 93.9% | 96.2% | 1.52 | 2.9 s | $0.0029 |
| staged_frontier_only | 0.1% | 94.1% | 97.1% | 1.50 | 2.9 s | $0.0078 |
| staged_no_gates | 0.2% | 98.1% | 96.2% | 1.13 | 2.9 s | $0.0029 |
| monolith_frontier | 4.2% | 75.3% | 79.3% | 3.18 | 9.0 s | $0.0600 |
| drift, stale ladder | 0.4% | 93.3% | 92.3% | 1.57 | 2.9 s | $0.0029 |
| drift, recalibrated | 0.1% | 91.6% | 92.3% | 1.72 | 2.9 s | $0.0029 |

**Reading it.** Gates cost 0.4 reviewer minutes per packet and cut silent errors by two thirds. Frontier-only routing buys almost nothing for 2.7x the cost. The single-call baseline is worse on every axis that matters. Under drift, the stale ladder's extra errors were concentrated in `occupancy+model`; recalibration demoted that route to *suggest* and recovered the error rate at a cost of 1.7 points of automation, which is the right trade.

## Release gate

`python -m staged_pipeline eval --check` (run in CI) fails if, against `evals/baseline.json`:
- false-accept rate exceeds 0.5%, or
- auto-accept rate drops more than 2 points, or
- model cost per packet rises more than 10%.

Change a threshold, a prompt, a model or a rule map, and the gate tells you whether you made things better on the axes that matter, not on an average.

## What these numbers are not

They are not benchmarks of any real model, and not results from any production system. The simulator's accuracy and confidence behaviour are assumptions, so absolute values mean little. What carries over is the *comparison*: under identical inputs and assumptions, which architecture fails silently, which spends money without buying quality, and whether the system notices when a component gets worse. With a real `ModelClient` plugged in, the same harness measures the real thing.

Known gaps: reviewers are assumed always right; review time is a fixed cost per item; the noise model has no adversarial inputs; documents are text, not scans.
