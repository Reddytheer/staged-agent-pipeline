# Eval report (generated)

Seed 7 · 1000 calibration packets · 300 test packets · 12 fields each. Synthetic data and simulated model tiers; see docs/EVALS.md for what these numbers do and do not mean.

| Variant | Auto-accepted | False accepts | Straight-through packets | Review min / packet | Finding recall | p50 latency (s) | p95 latency (s) | Model cost / packet |
|---|---|---|---|---|---|---|---|---|
| staged_tiered | 93.9% | 0.1% | 47.0% | 1.52 | 96.2% | 0.08 | 2.88 | $0.0029 |
| staged_frontier_only | 94.1% | 0.1% | 47.7% | 1.5 | 97.1% | 0.08 | 2.88 | $0.0078 |
| staged_no_gates | 98.1% | 0.2% | 79.7% | 1.13 | 96.2% | 0.08 | 2.88 | $0.0029 |
| monolith_frontier | 75.3% | 4.2% | 75.3% | 3.18 | 79.3% | 9.0 | 9.0 | $0.0600 |
| staged_tiered + degraded small model (NOT recalibrated) | 93.3% | 0.4% | 44.0% | 1.57 | 92.3% | 0.08 | 2.88 | $0.0029 |
| staged_tiered + degraded small model (recalibrated) | 91.6% | 0.1% | 33.3% | 1.72 | 92.3% | 0.08 | 2.88 | $0.0029 |

## Autonomy earned on the calibration split (staged_tiered)

| Decision type | n | Precision | 95% lower bound | Level |
|---|---|---|---|---|
| construction | 3651 | 99.6% | 99.4% | autonomous |
| construction+model | 59 | 98.3% | 91.0% | suggest |
| coverage | 2000 | 100.0% | 99.8% | sampled review |
| coverage+model | 0 | n/a | 0.0% | suggest |
| identity | 1000 | 100.0% | 99.6% | autonomous |
| identity+model | 0 | n/a | 0.0% | suggest |
| occupancy | 621 | 100.0% | 99.4% | autonomous |
| occupancy+model | 306 | 98.4% | 96.2% | sampled review |
| protection | 2000 | 100.0% | 99.8% | autonomous |
| protection+model | 0 | n/a | 0.0% | suggest |
| values | 1803 | 100.0% | 99.8% | autonomous |
| values+model | 19 | 100.0% | 83.2% | suggest |

## Regression drill: small-model accuracy drops 35 points

| Decision type | Level before | Level after recalibration |
|---|---|---|
| construction | autonomous | autonomous |
| construction+model | suggest | suggest |
| coverage | sampled review | sampled review |
| coverage+model | suggest | suggest |
| identity | autonomous | autonomous |
| identity+model | suggest | suggest |
| occupancy | autonomous | autonomous |
| occupancy+model | sampled review | suggest |
| protection | autonomous | autonomous |
| protection+model | suggest | suggest |
| values | autonomous | autonomous |
| values+model | suggest | suggest |
