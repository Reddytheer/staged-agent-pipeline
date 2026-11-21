# Architecture

One packet (three documents about one property) becomes one underwriting record: twelve canonical fields, each with a value, a confidence, a citation to the line it came from, a source (`rules`, `model:small`, `model:frontier`) and a status (`auto_accepted` or `review`), plus findings an underwriter should see.

## Flow

| Step | Module | What it does | Fails how | Then what |
|---|---|---|---|---|
| 1. Intake | `steps.classify` | Identifies each document by its header | Unknown document type | Label matching still runs; free-text fields surface as missing |
| 2. Extract | `steps.extract` | Maps provider-specific labels to canonical fields; regexes for free-text surveys; keeps the source line as a citation | Label not in the map | Field shows as missing; adding the label is a config change |
| 3. Normalize | `steps.normalize` | Parses amounts (`$1.25M`, `1,250,000`), repairs OCR damage, maps value vocabularies to canonical enums | Unseen phrase, unrepairable text | Confidence 0, escalates to a model |
| 4. Reconcile | `steps.reconcile` | Chooses one value per field by document precedence; agreement raises confidence | Documents disagree | Conflict: confidence capped at 0.5, goes to a person, never to a model |
| 5. Escalate | `orchestrator` | Fields below 0.90 confidence with evidence go to a model tier chosen by stakes | Model is wrong, sometimes confidently | The gate and the ladder decide whether anyone checks |
| 6. Validate | `steps.validate` | Underinsurance, sprinkler gaps, weak fire protection, conflicts, missing data; each finding cites its inputs | A finding rests on an unreviewed value | Marked provisional until a person confirms the input |
| 7. Gate | `gates` | Auto-accept only if confidence clears the stakes threshold **and** the decision route has earned autonomy | | Everything else goes to the review queue with its evidence |

## Two ideas that carry the design

**Stakes drive everything.** Each field has a stakes level (`low`, `medium`, `high`) that sets three things at once: the confidence threshold (0.80 / 0.90 / 0.97), the model tier that resolves ambiguity (small for low and medium, frontier for high) and how much evidence its decision type needs before it may act alone.

**Autonomy is tracked per decision route, not per field.** A clean rule parse of `Occupancy: Apartments` and a model's guess at what "student housing" means are different decisions even though both fill `occupancy`. The ladder keys evidence by `family` and `family+model`, so a reliable rule path is not held back by a shaky model path, and a shaky model path cannot hide behind a reliable rule path.

## The autonomy ladder

| Level | Behaviour | Earned when |
|---|---|---|
| Suggest | Every value goes to a person | Default for any new route |
| Sampled review | Auto-accepts above threshold; 10% still checked | 95% lower bound on precision ≥ 0.95 over ≥ 30 decisions |
| Autonomous | Auto-accepts above threshold | Lower bound ≥ 0.98 |

The bound is a Wilson 95% lower bound, so 20 out of 20 correct does not buy autonomy. Coverage terms are capped at sampled review regardless of evidence. Recalibration runs on fresh outcomes and moves routes down as easily as up.

## Interfaces

- `ModelClient.resolve(field, evidence, packet_id) -> (value | None, confidence)` is the only seam a real model needs. It must return `None` when there is no evidence: the pipeline never invents values.
- Provider onboarding is configuration: `LABELS`, `CONSTRUCTION_WORDS`, `OCCUPANCY_WORDS` and `SPRINKLER_WORDS` in `synth.py` double as the rule maps in `steps.py`. In a real system these live in per-provider config, not code.
- `PipelineConfig` switches mode (`staged` / `monolith`), routing (`tiered` / `frontier_only`) and gates, which is how the A/B variants run on identical inputs.

## Deliberately out of scope

Real OCR and PDF parsing, a review UI, persistence, retries and idempotency, PII handling, multi-property schedules. Each matters in production; none changes the decisions this repo is about. [SCALE.md](SCALE.md) covers what they would look like.
