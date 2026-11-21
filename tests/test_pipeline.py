"""Behavioural tests: the properties the design promises, not implementation details."""
from staged_pipeline import evals, steps
from staged_pipeline.gates import SAMPLED, SUGGEST, AutonomyLadder, wilson_lower
from staged_pipeline.models import SimulatedModel
from staged_pipeline.orchestrator import PipelineConfig
from staged_pipeline.schema import Citation, FieldValue
from staged_pipeline.synth import make_dataset


def test_ocr_damage_is_repaired_but_trusted_less():
    value, conf, notes = steps.parse_int("l,25O,OOO")
    assert value == 1_250_000 and conf < 0.9 and "OCR" in notes[0]


def test_abbreviated_amounts_expand():
    assert steps.parse_int("$1.25M")[0] == 1_250_000
    assert steps.parse_int("$850K")[0] == 850_000


def test_disagreeing_documents_are_never_auto_resolved():
    c = Citation("d", 0, "")
    fv, conflict = steps.reconcile("year_built", [("sov", FieldValue("year_built", 1998, 0.99, c, "rules")),
                                                  ("cope", FieldValue("year_built", 1989, 0.99, c, "rules"))])
    assert conflict and fv.confidence <= 0.5


def test_agreeing_documents_corroborate():
    c = Citation("d", 0, "")
    fv, conflict = steps.reconcile("year_built", [("sov", FieldValue("year_built", 1998, 0.80, c, "rules")),
                                                  ("cope", FieldValue("year_built", 1998, 0.99, c, "rules"))])
    assert not conflict and fv.confidence == 0.99


def test_model_never_invents_a_value_without_evidence():
    model = SimulatedModel("frontier", {"P1": {"deductible": 25_000}})
    assert model.resolve("deductible", "", "P1") == (None, 0.0)


def test_small_samples_cannot_buy_autonomy():
    ladder = AutonomyLadder()
    assert ladder.level_from_evidence("occupancy", 20, 20) == SUGGEST      # 100% on 20 is not enough
    assert wilson_lower(20, 20) < 0.95


def test_coverage_terms_are_capped_at_sampled_review():
    assert AutonomyLadder().level_from_evidence("coverage", 5000, 5000) == SAMPLED


def test_conflicts_and_missing_values_always_reach_a_person():
    data = make_dataset(evals.CALIBRATION + 50)
    ladder, _ = evals.calibrate(PipelineConfig(), data[: evals.CALIBRATION])
    pipe = evals.build(PipelineConfig(), {p.packet_id: t.values for p, t in data}, ladder)
    for packet, truth in data[evals.CALIBRATION:]:
        rec = pipe.run(packet)
        for f, fv in rec.fields.items():
            if fv.value is None or any("disagree" in n for n in fv.notes):
                assert fv.status == "review"


def test_results_are_reproducible():
    assert evals.run_all()["results"] == evals.run_all()["results"]


def test_regression_drill_demotes_the_drifting_route():
    res = evals.run_all()
    assert res["ladder"]["occupancy+model"]["to"] == "sampled review"
    assert res["regression_drill"]["ladder_after_drift"]["occupancy+model"]["to"] == "suggest"
    stale, fixed = res["regression_drill"]["stale"], res["regression_drill"]["recalibrated"]
    assert fixed["false_accept_rate"] < stale["false_accept_rate"]


def test_staged_design_beats_the_monolith_on_what_matters():
    by = {r["variant"]: r for r in evals.run_all()["results"]}
    staged, mono = by["staged_tiered"], by["monolith_frontier"]
    assert staged["false_accept_rate"] < mono["false_accept_rate"] / 10
    assert staged["cost_per_packet_usd"] < mono["cost_per_packet_usd"] / 10


def test_release_gate_passes_on_baseline():
    import json, pathlib
    base = json.loads((pathlib.Path(__file__).parents[1] / "evals" / "baseline.json").read_text())
    assert evals.check(evals.run_all(), base) == []
