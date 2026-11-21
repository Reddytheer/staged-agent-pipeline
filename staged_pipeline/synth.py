"""Synthetic renewal packets with ground truth.

Every packet is generated from a seed, so evals are reproducible. Three fictional
data providers format the same facts differently, and a noise model injects the
problems real submissions have: missing fields, OCR damage, documents that
disagree, and descriptions the rules have never seen.

All names, addresses and values are invented.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .schema import CONSTRUCTION_CLASSES, Document, Packet

STREETS = ["Harbor", "Maple", "Granite", "Willow", "Summit", "Cedar", "Lakeview", "Orchard"]
SUFFIX = ["St", "Ave", "Blvd", "Rd", "Way"]
CITIES = [("Riverton", "NH"), ("Elm Falls", "MA"), ("Bayside", "ME"), ("Northgate", "VT")]

# How each fictional provider spells the same field label.
LABELS = {
    "provider_a": {"address": "Location Address", "year_built": "Year Built", "construction_class": "Construction",
                   "stories": "No. of Stories", "square_feet": "Total Sq Ft", "occupancy": "Occupancy",
                   "sprinklered": "Sprinkler System", "protection_class": "Protection Class",
                   "building_value": "Building Value", "contents_value": "Contents Value"},
    "provider_b": {"address": "Site", "year_built": "YearBuilt", "construction_class": "ConstructionType",
                   "stories": "Floors", "square_feet": "Area (sf)", "occupancy": "OccupancyType",
                   "sprinklered": "Sprinklers", "protection_class": "PPC",
                   "building_value": "BuildingTIV", "contents_value": "BPP"},
    "provider_c": {"address": "Property", "year_built": "Built", "construction_class": "Const Class",
                   "stories": "Storeys", "square_feet": "Square Footage", "occupancy": "Use",
                   "sprinklered": "Fire Sprinklers", "protection_class": "Public Protection",
                   "building_value": "Bldg Limit Value", "contents_value": "Personal Property"},
}

CONSTRUCTION_WORDS = {
    "provider_a": ["Frame", "Joisted Masonry", "Non-Combustible", "Masonry Non-Combustible",
                   "Modified Fire Resistive", "Fire Resistive"],
    "provider_b": [f"ISO {i}" for i in range(1, 7)],
    "provider_c": [f"Class {i}" for i in range(1, 7)],
}
# Real-world phrasings the rule map does not know. The truth is fixed so evals can score them.
UNSEEN_CONSTRUCTION = {"heavy timber": "joisted_masonry", "steel frame": "non_combustible",
                       "concrete block": "masonry_non_combustible", "tilt-up concrete": "masonry_non_combustible"}
UNSEEN_OCCUPANCY = {"habitational": ["garden apartments", "mixed-use residential", "senior living", "student housing"],
                    "office": ["professional offices", "medical office"], "retail": ["shopping plaza", "storefronts"],
                    "warehouse": ["distribution center", "light industrial"]}
NUMBER_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
OCCUPANCY_WORDS = {
    "provider_a": {"habitational": "Apartments", "office": "Office", "retail": "Retail", "warehouse": "Warehouse"},
    "provider_b": {"habitational": "HAB", "office": "OFF", "retail": "RET", "warehouse": "WHS"},
    "provider_c": {"habitational": "Multifamily", "office": "Office building", "retail": "Retail strip",
                   "warehouse": "Warehouse/storage"},
}
SPRINKLER_WORDS = {
    "provider_a": {"full": "Yes", "partial": "Partial", "none": "No"},
    "provider_b": {"full": "100%", "partial": "50%", "none": "0%"},
    "provider_c": {"full": "fully sprinklered", "partial": "partial", "none": "none"},
}


@dataclass
class Truth:
    values: dict
    findings: set[str]
    hard_fields: set[str] = field(default_factory=set)   # fields the noise model damaged


@dataclass
class NoiseModel:
    p_missing: float = 0.05
    p_ocr: float = 0.05
    p_year_conflict: float = 0.12
    p_unseen_construction: float = 0.08
    p_unseen_occupancy: float = 0.30
    p_stories_in_words: float = 0.12


def _money(provider: str, v: int) -> str:
    if provider == "provider_a":
        return f"{v:,}"
    if provider == "provider_b":
        return f"${v / 1_000_000:.2f}M" if v >= 1_000_000 else f"${v / 1000:.0f}K"
    return str(v)


def _ocr(s: str, rng: random.Random) -> str:
    table = {"1": "l", "0": "O", "5": "S"}
    chars = [table.get(c, c) if c in table and rng.random() < 0.5 else c for c in s]
    damaged = "".join(chars)
    return damaged if damaged != s else s.replace("1", "l", 1).replace("0", "O", 1)


def make_truth(rng: random.Random) -> dict:
    occupancy = rng.choice(["habitational"] * 3 + ["office", "retail", "warehouse"])
    stories = rng.randint(1, 3) if occupancy != "habitational" else rng.randint(2, 8)
    sqft = rng.randrange(8_000, 180_000, 500)
    building_value = round(sqft * rng.uniform(140, 260), -4)
    contents_value = round(building_value * rng.uniform(0.05, 0.25), -4)
    tiv = building_value + contents_value
    underinsured = rng.random() < 0.18
    limit = round(tiv * (rng.uniform(0.70, 0.92) if underinsured else rng.uniform(1.0, 1.15)), -4)
    num = rng.randint(10, 990)
    street, suffix = rng.choice(STREETS), rng.choice(SUFFIX)
    city, state = rng.choice(CITIES)
    return {
        "address": f"{num} {street} {suffix}, {city}, {state}",
        "year_built": rng.randint(1955, 2022),
        "construction_class": rng.choice(CONSTRUCTION_CLASSES),
        "stories": stories,
        "square_feet": sqft,
        "occupancy": occupancy,
        "sprinklered": rng.choice(["full", "full", "partial", "none"]),
        "protection_class": rng.choice([2, 3, 3, 4, 5, 6, 9, 10]),
        "building_value": int(building_value),
        "contents_value": int(contents_value),
        "policy_limit": int(limit),
        "deductible": rng.choice([10_000, 25_000, 50_000, 100_000]),
    }


def truth_findings(v: dict, year_conflict: bool) -> set[str]:
    out = set()
    if v["policy_limit"] < v["building_value"] + v["contents_value"]:
        out.add("underinsured")
    if v["occupancy"] == "habitational" and v["stories"] >= 4 and v["sprinklered"] != "full":
        out.add("sprinkler_gap")
    if v["protection_class"] >= 9:
        out.add("weak_fire_protection")
    if year_conflict:
        out.add("year_conflict")
    return out


def make_packet(idx: int, seed: int = 7, noise: NoiseModel | None = None) -> tuple[Packet, Truth]:
    noise = noise or NoiseModel()
    rng = random.Random(seed * 100_003 + idx)
    v = make_truth(rng)
    provider = rng.choice(list(LABELS))
    hard: set[str] = set()

    # --- Schedule of values (SOV): one property, provider-specific labels and formats
    construction_text = CONSTRUCTION_WORDS[provider][CONSTRUCTION_CLASSES.index(v["construction_class"])]
    if rng.random() < noise.p_unseen_construction:
        phrase = rng.choice(list(UNSEEN_CONSTRUCTION))
        v["construction_class"] = UNSEEN_CONSTRUCTION[phrase]
        construction_text = phrase
        hard.add("construction_class")
    raw = {
        "address": v["address"], "year_built": str(v["year_built"]), "construction_class": construction_text,
        "stories": str(v["stories"]), "square_feet": f"{v['square_feet']:,}",
        "occupancy": OCCUPANCY_WORDS[provider][v["occupancy"]],
        "sprinklered": SPRINKLER_WORDS[provider][v["sprinklered"]],
        "protection_class": str(v["protection_class"]),
        "building_value": _money(provider, v["building_value"]),
        "contents_value": _money(provider, v["contents_value"]),
    }
    if rng.random() < noise.p_unseen_occupancy:
        raw["occupancy"] = rng.choice(UNSEEN_OCCUPANCY[v["occupancy"]])
        hard.add("occupancy")
    if rng.random() < noise.p_stories_in_words:
        raw["stories"] = NUMBER_WORDS[v["stories"]]
        hard.add("stories")
    sov_lines = [f"SCHEDULE OF VALUES ({provider})"]
    for name, text in raw.items():
        if name != "address" and rng.random() < noise.p_missing:
            hard.add(name)
            continue
        if name in ("year_built", "square_feet", "building_value", "contents_value") and rng.random() < noise.p_ocr:
            text = _ocr(text, rng)
            hard.add(name)
        sov_lines.append(f"{LABELS[provider][name]}: {text}")

    # --- COPE survey: free text, sometimes disagrees with the SOV on year built
    year_conflict = rng.random() < noise.p_year_conflict
    survey_year = v["year_built"] + rng.choice([-9, -5, -2, 3, 7]) if year_conflict else v["year_built"]
    if year_conflict:
        hard.add("year_built")
    cope = (f"COPE SURVEY\nInspector notes: building originally constructed in {survey_year}.\n"
            f"The structure has {v['stories']} stories.\n"
            f"Sprinkler coverage observed: {v['sprinklered']}.\n"
            f"Public protection class {v['protection_class']} per local fire district.")

    # --- Declarations page: coverage terms
    dec = (f"POLICY DECLARATIONS\nNamed Insured: Example Property Holdings {idx} LLC\n"
           f"Location: {v['address']}\nLimit of Insurance: ${v['policy_limit']:,}\n"
           f"All Other Perils Deductible: ${v['deductible']:,}")

    docs = [Document(f"P{idx:04d}-sov", "unknown", provider, "\n".join(sov_lines)),
            Document(f"P{idx:04d}-cope", "unknown", provider, cope),
            Document(f"P{idx:04d}-dec", "unknown", provider, dec)]
    rng.shuffle(docs)
    return Packet(f"P{idx:04d}", docs), Truth(v, truth_findings(v, year_conflict), hard)


def make_dataset(n: int, seed: int = 7, noise: NoiseModel | None = None):
    return [make_packet(i, seed, noise) for i in range(n)]
