# Time, scale and impact

Back-of-envelope numbers from the eval results, for a book of **10,000 renewal packets a month**. Inputs from [results/metrics.json](../results/metrics.json); assumptions are marked.

## Unit economics

| | Staged + tiered | Frontier only | Single call |
|---|---|---|---|
| Model cost / packet | $0.0029 | $0.0078 | $0.060 |
| Model cost / month | **$29** | $78 | $600 |
| Reviewer minutes / packet | 1.52 | 1.50 | 3.18 |
| Reviewer hours / month | **253** | 250 | 530 |
| Wrong values no one saw / month | **~100** | ~70 | ~5,000 |

Model spend is a rounding error next to people's time, so the design optimises for the right human minutes and for silent errors, not for tokens. The tiered design is still 2.7x cheaper than frontier-only for the same quality, which matters once packets carry dozens of properties rather than one.

**Against manual processing** (assumption: 20 minutes to key and reconcile three documents by hand), the same 10,000 packets take about 3,300 hours. The staged pipeline needs about 253, roughly **92% less**, and every remaining minute is a judgment call rather than typing.

## Where human time goes

| | Minutes / packet | Share |
|---|---|---|
| Following up on values missing from every document | 1.15 | 76% |
| Confirming or fixing flagged values | 0.37 | 24% |

This is the most useful number in the repo. Better models barely move it. A better intake request (ask for the fields underwriting needs before the packet arrives) would. Evals that show *where* the cost is point to product work, not just model work.

## Time

- **Time to a record:** p50 0.08 s, p95 2.9 s. Deterministic steps take milliseconds; one round of parallel model calls sets the tail. The human queue, not compute, sets end-to-end time.
- **Time to onboard a provider:** one set of label and value mappings in config. No parser, no release. The eval harness confirms it before it goes live.
- **Time for a model route to earn autonomy:** a few hundred reviewed decisions. In the evals, `occupancy+model` reached sampled review at n = 306, about 1,000 packets of traffic since roughly 30% of packets use that route. At 10,000 packets a month that is two to three days. A rarer route takes proportionally longer, which is the right pace for trust.

## Throughput and what breaks at scale

10,000 packets a month is about 460 per working day. Compute is trivial at that volume; the constraints are elsewhere:

| Pressure | What happens | Response |
|---|---|---|
| Review queue | ~12 reviewer hours a day at this volume | Prioritise by stakes and deadline; batch follow-ups per insured |
| New provider formats | Unseen labels show up as missing fields | Monitor missing-rate per provider; alert on spikes, add mappings |
| Model drift or version change | False accepts rise in one route | Weekly recalibration on reviewed outcomes; release gate in CI |
| Threshold creep | Pressure to lower thresholds to cut review | Thresholds change only through the release gate, never by hand |
| Multi-property schedules | Hundreds of rows per packet | Same steps per row; parallelise rows; per-row gating keeps review proportional |
| Audit and privacy | Every value must be traceable | Citations and source per field already; add immutable audit log and PII redaction at intake |

## Impact, in one line

Most fields flow straight through, every risky value meets a person with the evidence in front of them, silent errors are a fraction of a percent, and the system notices on its own when a component gets worse.
