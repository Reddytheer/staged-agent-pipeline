# Design decisions

Short records of the choices that shaped this system: what was decided, what else was on the table, and what it costs. Numbers refer to [results/report.md](../results/report.md).

### 1. A pipeline of specialists instead of one long-context call
**Decision.** Five steps with typed inputs and outputs; models only inside steps, only for what rules could not settle.
**Alternative.** Send all documents to one strong model and ask for the whole record.
**Why.** The single call has no place to catch an error, so a wrong value travels straight to the underwriter. It also hides disagreement between documents. In the A/B it silently accepted 4.2% wrong values against 0.1%, surfaced 79% of underwriting issues against 96%, and cost 20x more per packet.
**Cost.** More moving parts: state per step, more code to maintain, more interfaces to test.

### 2. Rules first, models second
**Decision.** Deterministic parsing and mapping run first and report honest confidence; a model sees a field only when rules fall below 0.90.
**Why.** Rules are fast, free, explainable and stable. About 96% of fields never need a model (44% of packets make at least one call), which is why p50 latency is milliseconds and model cost is a third of a cent per packet.
**Cost.** Label and value maps must be maintained. They are kept as configuration so onboarding a provider is a data change, not a release.

### 3. Pick the model tier by the cost of being wrong
**Decision.** High-stakes fields (values, coverage, construction class, sprinklers) go to the frontier tier; medium and low stakes go to the small tier.
**Alternative.** Frontier for everything.
**Why.** Frontier-only matched the tiered design on accuracy at 2.7x the model cost. Spending the expensive model where errors are cheap buys nothing.
**Cost.** Two tiers means two eval surfaces and two drift risks, which is exactly what decision 7 watches.

### 4. Confidence per field, not per document
**Decision.** Each field is gated on its own confidence against a threshold set by its stakes (0.80 / 0.90 / 0.97).
**Alternative.** One document-level score: accept the record or review all of it.
**Why.** Document-level gating either sends good fields to review with the bad one or lets the bad one through with the good ones. The monolith baseline did both: more review minutes and more false accepts.
**Cost.** Thresholds have to be tuned per stakes level, and confidence has to mean something, which is why the ladder checks it against outcomes rather than trusting it.

### 5. Disagreement goes to a person; missing data is never invented
**Decision.** If two documents disagree, confidence is capped and the field goes to review without a model call. If a value is in no document, the system asks for it rather than infers it.
**Why.** A model choosing between two conflicting documents produces a confident answer with no basis for its confidence. Inventing a missing value is worse. Both are the failures that destroy trust in a regulated workflow.
**Cost.** Follow-ups for missing values are now 75% of reviewer time. That is the honest cost of the rule, and it points to the next improvement: ask for complete data at intake.

### 6. Autonomy is earned on a lower bound, per decision route
**Decision.** Each route (`occupancy`, `occupancy+model`, …) starts at *suggest* and is promoted only when the 95% Wilson lower bound on its precision clears 0.95 (sampled) or 0.98 (autonomous) over at least 30 decisions.
**Alternatives.** One global switch; promotion on average accuracy; per-field tracking.
**Why.** Averages let small samples look perfect. Per-route tracking keeps a reliable rule path from being held back by a shaky model path, and stops a shaky model path from hiding inside a reliable field. In the evals the small model's occupancy route earned sampled review only after 306 calibration decisions.
**Cost.** New routes start slow. That is intended.

### 7. Autonomy can be taken back, automatically
**Decision.** Recalibration on fresh outcomes moves routes down as readily as up. The release gate fails CI if false accepts exceed 0.5%, auto-accept drops more than 2 points, or cost per packet rises more than 10%.
**Why.** Models drift and providers change formats. In the drill, a 35-point drop in the small model raised false accepts 4x under a stale ladder; recalibration demoted exactly one route and restored the baseline.
**Cost.** Calibration needs a steady supply of reviewed outcomes, so the review queue is also the evidence pipeline. Sampled review exists partly to keep that supply flowing.

### 8. Coverage terms keep a human sample, always
**Decision.** The coverage family is capped at sampled review even with perfect evidence.
**Why.** Limits and deductibles define what the customer is protected for. The cost of a rare error is asymmetric and lands on someone who did not choose the risk.
**Cost.** A permanent review floor of roughly 0.2 fields per packet.

### 9. Findings are provisional until their inputs are confirmed
**Decision.** A finding that depends on a field awaiting review is labelled provisional.
**Why.** "Underinsured by 1%" computed from an unconfirmed value should not read like a conclusion.
**Cost.** Underwriters see more qualified findings; the UI has to make that easy to scan.
