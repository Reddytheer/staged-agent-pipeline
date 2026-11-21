"""The deterministic steps: intake, extract, normalize, reconcile, validate.

Rules come first wherever a rule is enough. They are fast, free, explainable and
testable, and they report honest confidence so the orchestrator knows when to
escalate to a model or a person.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .schema import CONSTRUCTION_CLASSES, Citation, Document, FieldValue, Finding
from .synth import CONSTRUCTION_WORDS, LABELS, OCCUPANCY_WORDS, SPRINKLER_WORDS

# ---------------------------------------------------------------- 1. intake
KIND_MARKERS = {"sov": "SCHEDULE OF VALUES", "cope": "COPE SURVEY", "dec_page": "POLICY DECLARATIONS"}


def classify(doc: Document) -> tuple[str, float]:
    head = doc.text.splitlines()[0].upper() if doc.text else ""
    for kind, marker in KIND_MARKERS.items():
        if marker in head:
            return kind, 0.99
    return "unknown", 0.0


# ---------------------------------------------------------------- 2. extract
# Label maps are configuration, not code: onboarding a new provider means adding
# a row here, never a new parser.
LABEL_TO_FIELD = {label.lower(): f for table in LABELS.values() for f, label in table.items()}
LABEL_TO_FIELD.update({"location": "address", "limit of insurance": "policy_limit",
                       "all other perils deductible": "deductible"})

COPE_PATTERNS = {
    "year_built": re.compile(r"constructed in (\d{4})"),
    "stories": re.compile(r"has (\d+) stories"),
    "sprinklered": re.compile(r"Sprinkler coverage observed: (\w+)"),
    "protection_class": re.compile(r"protection class (\d+)", re.I),
}


@dataclass
class Candidate:
    field: str
    raw: str
    doc_kind: str
    citation: Citation


def extract(doc: Document, kind: str) -> list[Candidate]:
    out = []
    for i, line in enumerate(doc.text.splitlines()):
        if kind == "cope":
            for f, pat in COPE_PATTERNS.items():
                m = pat.search(line)
                if m:
                    out.append(Candidate(f, m.group(1), kind, Citation(doc.doc_id, i, line.strip())))
        elif ":" in line:
            label, _, value = line.partition(":")
            f = LABEL_TO_FIELD.get(label.strip().lower())
            if f:
                out.append(Candidate(f, value.strip(), kind, Citation(doc.doc_id, i, line.strip())))
    return out


# ---------------------------------------------------------------- 3. normalize
VALUE_MAP: dict[str, dict[str, str]] = {"construction_class": {}, "occupancy": {}, "sprinklered": {}}
for words in CONSTRUCTION_WORDS.values():
    for w, cls in zip(words, CONSTRUCTION_CLASSES):
        VALUE_MAP["construction_class"][w.lower()] = cls
for table in OCCUPANCY_WORDS.values():
    VALUE_MAP["occupancy"].update({w.lower(): c for c, w in table.items()})
for table in SPRINKLER_WORDS.values():
    VALUE_MAP["sprinklered"].update({w.lower(): c for c, w in table.items()})
VALUE_MAP["sprinklered"].update({c: c for c in ("full", "partial", "none")})

OCR_FIX = str.maketrans({"l": "1", "I": "1", "O": "0", "o": "0", "S": "5"})


def parse_int(raw: str) -> tuple[int | None, float, list[str]]:
    notes, s = [], raw.replace(",", "").replace("$", "").strip()
    mult = 1
    if s[-1:] in "MK" and s[:-1].replace(".", "").isdigit():
        mult, s = (1_000_000 if s[-1] == "M" else 1_000), s[:-1]
        try:
            return int(round(float(s) * mult)), 0.97, ["abbreviated amount expanded"]
        except ValueError:
            return None, 0.0, ["unparseable"]
    if not s.isdigit():
        repaired = s.translate(OCR_FIX)
        if repaired.isdigit():
            return int(repaired), 0.80, [f"OCR repair '{raw}' -> '{repaired}'"]
        return None, 0.0, ["unparseable"]
    return int(s), 0.99, notes


def normalize(c: Candidate, kind: str) -> FieldValue:
    if kind == "enum":
        val = VALUE_MAP[c.field].get(c.raw.lower())
        if val is None:
            return FieldValue(c.field, None, 0.0, c.citation, "rules", notes=[f"unseen value '{c.raw}'"])
        return FieldValue(c.field, val, 0.99, c.citation, "rules")
    if kind == "int":
        val, conf, notes = parse_int(c.raw)
        return FieldValue(c.field, val, conf, c.citation, "rules", notes=notes)
    return FieldValue(c.field, c.raw, 0.99, c.citation, "rules")


# ---------------------------------------------------------------- 4. reconcile
# Which document is authoritative for which field when several mention it.
PRECEDENCE = {"policy_limit": ["dec_page"], "deductible": ["dec_page"], "address": ["sov", "dec_page"]}
DEFAULT_PRECEDENCE = ["sov", "cope", "dec_page"]


def reconcile(field: str, values: list[tuple[str, FieldValue]]) -> tuple[FieldValue | None, bool]:
    """Pick one value per field. Returns (value, conflict). Disagreement is never auto-resolved."""
    if not values:
        return None, False
    order = PRECEDENCE.get(field, DEFAULT_PRECEDENCE)
    values = sorted(values, key=lambda kv: order.index(kv[0]) if kv[0] in order else 99)
    usable = [kv for kv in values if kv[1].value is not None]
    if not usable:                       # every mention was unreadable: escalate the best one
        return values[0][1], False
    if len(usable) < len(values):        # an unreadable mention backed up by a readable one
        usable[0][1].notes.append("recovered from a second document")
    values = usable
    chosen = values[0][1]
    known = {fv.value for _, fv in values if fv.value is not None}
    if len(known) > 1:
        chosen.notes.append("documents disagree: " + " vs ".join(sorted(map(str, known))))
        chosen.confidence = min(chosen.confidence, 0.5)
        return chosen, True
    # Independent documents agreeing is evidence: corroboration lifts confidence.
    chosen.confidence = max(fv.confidence for _, fv in values)
    return chosen, False


# ---------------------------------------------------------------- 5. validate
CONFLICT_CODES = {"year_built": "year_conflict"}
def validate(fields: dict[str, FieldValue], conflicts: list[str]) -> list[Finding]:
    v = {k: f.value for k, f in fields.items()}
    cite = lambda *names: [fields[n].citation for n in names if fields.get(n) and fields[n].citation]
    out = []
    if None not in (v.get("policy_limit"), v.get("building_value"), v.get("contents_value")):
        tiv = v["building_value"] + v["contents_value"]
        if v["policy_limit"] < tiv:
            out.append(Finding("underinsured", "high",
                               f"Limit ${v['policy_limit']:,} is {1 - v['policy_limit'] / tiv:.0%} below total insured value ${tiv:,}",
                               cite("policy_limit", "building_value", "contents_value"),
                               ["policy_limit", "building_value", "contents_value"]))
    if v.get("occupancy") == "habitational" and (v.get("stories") or 0) >= 4 and v.get("sprinklered") not in (None, "full"):
        out.append(Finding("sprinkler_gap", "high", "Mid-rise habitational building without full sprinklers",
                           cite("occupancy", "stories", "sprinklered"), ["occupancy", "stories", "sprinklered"]))
    if (v.get("protection_class") or 0) >= 9:
        out.append(Finding("weak_fire_protection", "warn", f"Protection class {v['protection_class']}",
                           cite("protection_class"), ["protection_class"]))
    for f in conflicts:
        out.append(Finding(CONFLICT_CODES.get(f, f"{f}_conflict"), "warn",
                           f"Documents disagree on {f}; a person decides", cite(f), [f]))
    for name, fv in fields.items():
        if fv.value is None:
            out.append(Finding(f"missing:{name}", "info", f"{name} not provided; request from insured"))
    return out
