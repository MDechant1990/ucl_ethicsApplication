"""Rules: derive everything that should not have to be typed by hand.

Plain functions, no magic. `derive()` returns one dict ("d") that the
templates use next to the project ("p").
"""
import math
from dataclasses import dataclass

from model import Project, with_project_instruments


@dataclass
class Flag:
    code: str      # form question, e.g. "B2"
    level: str     # "high" | "borderline" | "info"
    message: str


def unique(items):
    """Keep order, drop duplicates."""
    return list(dict.fromkeys(items))


def _lookup(lib_part: dict, keys) -> list[dict]:
    return [{"key": k, **lib_part[k]} for k in unique(keys) if k in lib_part]


def used_methods(p: Project, lib) -> list[dict]:
    return _lookup(lib["methods"], (k for ph in p.phases for k in ph.methods))


def used_instruments(p: Project, lib) -> list[dict]:
    return _lookup(with_project_instruments(p, lib)["instruments"], (k for ph in p.phases for k in ph.instruments))


def used_locations(p: Project, lib) -> list[dict]:
    return _lookup(lib["locations"], (ph.location for ph in p.phases))


def used_populations(p: Project, lib) -> list[dict]:
    return _lookup(lib["populations"], p.populations)


def facts(p: Project, lib) -> dict:
    """Flat facts that library/considerations.yaml can match on."""
    return {
        "channels": p.channels,
        "populations": p.populations,
        "methods": [m["key"] for m in used_methods(p, lib)],
        "locations": [loc["key"] for loc in used_locations(p, lib)],
        "org_types": [r.org_type for r in p.external_team],
        "collect_abroad": p.collect_abroad,
        "dual_role": p.dual_role,
        "has_prize": bool(p.prize),
    }


def considerations(p: Project, lib) -> list[dict]:
    """Other ethical issues (I10) whose `when` conditions all match."""
    f = facts(p, lib)

    def matches(key, value):
        have = f.get(key)
        return value in have if isinstance(have, list) else have == value

    return [c for c in lib["considerations"].values() if all(matches(k, v) for k, v in c["when"].items())]


def risk_flags(p: Project, lib) -> list[Flag]:
    flags = []
    if p.min_age < 16 or "under_16" in p.populations:
        flags.append(Flag("B1.2", "high", "Participants under 16 are recruited."))
    for pop in used_populations(p, lib):
        if pop.get("vulnerable"):
            flags.append(Flag("B2", "high", f"Vulnerability: {pop['label']}."))
        elif pop.get("borderline"):
            flags.append(Flag("B2", "borderline",
                              f"Vulnerability (borderline): {pop['label']}. A justification is added to I1.1."))
    for ins in used_instruments(p, lib):
        if ins.get("warning"):
            flags.append(Flag("B2", "high", f"{ins['name']}: {ins['warning']}"))
        elif ins.get("sensitive"):
            flags.append(Flag("B2", "borderline",
                              f"Sensitivity: {ins['name']} asks about {ins['construct'].split(' (')[0]}. "
                              "A justification is added to I1.1."))
    checklist = {
        "deception": "Deception and covert research",
        "disclosures": "Disclosures of illegal/harmful activities or safeguarding concerns",
        "security_sensitive": "Security-sensitive material",
        "researcher_risk": "Researcher wellbeing / safety",
        "medicinal": "Administration of medicinal products or substances",
        "invasive": "Physically invasive procedures",
    }
    for field, label in checklist.items():
        if getattr(p, field):
            flags.append(Flag("B2", "high", label))
    if p.collect_abroad:
        flags.append(Flag("D3", "info", "Data collected outside the UK: complete the overseas section (D3)."))
    if any(loc.get("permission") for loc in used_locations(p, lib)):
        flags.append(Flag("D4.1", "info", "Location permissions needed: upload evidence or confirm before data collection."))
    if any(r.org_type == "Industry partner" for r in p.external_team):
        flags.append(Flag("C6", "info", "Industry partner involved: consider declaring a potential conflict of interest (C6)."))
    if p.dual_role:
        flags.append(Flag("E3.1", "info", "Researchers hold dual roles: power-dynamic mitigation is added to E3.1."))
    return flags


def risk_level(flags: list[Flag]) -> str:
    return "high" if any(f.level == "high" for f in flags) else "low"


def compensation(p: Project) -> list[dict]:
    """Pro-rata payment per study procedure, rounded up to the nearest 50p (pre-screening is unpaid)."""
    rows = []
    for ph in p.study_phases:
        amount = math.ceil(p.rate_per_hour * ph.duration_min / 60 * 2) / 2
        rows.append({"procedure": ph.name, "minutes": ph.duration_min, "amount": f"£{amount:.2f}"})
    return rows


def special_category(p: Project, lib) -> list[str]:
    out = []
    if "ethnicity" in p.demographics:
        out.append("Personal data revealing racial or ethnic origin: self-reported ethnicity, used to describe the sample only.")
    health_tools = [i["name"] for i in used_instruments(p, lib) if i.get("health")]
    if health_tools:
        out.append("Data concerning health: self-reported well-being/health questionnaires ("
                   + ", ".join(health_tools) + "), used for group-level analysis only, not diagnosis.")
    if "neurodivergence status" in p.demographics:
        out.append("Data concerning health: optional self-identified neurodivergence status (yes/no; "
                   "type only if the participant chooses to share it).")
    if any(m.get("exclusions") for m in used_methods(p, lib)) or p.exclusion:
        out.append("Data concerning health: yes/no screening answers about health conditions relevant to eligibility.")
    return out


def derive(p: Project, lib) -> dict:
    methods = used_methods(p, lib)
    instruments = used_instruments(p, lib)
    locations = used_locations(p, lib)
    populations = used_populations(p, lib)
    flags = risk_flags(p, lib)
    channels = _lookup(lib["channels"], p.channels)
    in_person = any(loc.get("in_person") for loc in locations)
    has_audio = any(m.get("audio") for m in methods)
    return {
        "methods": methods,
        "instruments": instruments,
        "locations": locations,
        "custom_tools": unique(t for ph in p.phases for t in ph.custom_tools),
        "screening_tools": [with_project_instruments(p, lib)["instruments"].get(k, {}).get("name", k)
                            for k in p.screening_survey],
        "d2_ticks": unique(m["d2"] for m in methods),
        "flags": flags,
        "risk_level": risk_level(flags),
        "risks": ([r for m in methods for r in m.get("risks", [])]
                  + [r for loc in locations for r in loc.get("risks", [])]
                  + [r for pop in populations for r in pop.get("mitigations", [])]),
        "borderline_populations": [pop for pop in populations if pop.get("borderline")],
        "sensitive_instruments": [i for i in instruments if i.get("sensitive")],
        "considerations": considerations(p, lib),
        "permissions": unique(loc["permission"] for loc in locations if loc.get("permission")),
        "exclusions": unique(p.exclusion + [e for m in methods for e in m.get("exclusions", [])]),
        "data_types": unique(
            [t for m in methods for t in m.get("data_types", [])]
            + ["Electronic consent records (Qualtrics)"]
            + (["Paper consent forms (scanned)"] if p.paper_consent and in_person else [])
            + ["Contact details (names and email addresses)"]),
        "identifiers": unique(["Name and email address (consent, scheduling and compensation)"]
                              + [f"Demographic information ({', '.join(p.demographics)})"] * bool(p.demographics)
                              + [i for m in methods for i in m.get("identifiers", [])]),
        "special_category": special_category(p, lib),
        "has_audio": has_audio,
        "in_person": in_person,
        "has_lab": any(loc["key"] in ("lab", "partner_lab") for loc in locations),
        "channels": channels,
        "channels_text": ", ".join(c["text"] for c in channels) or "[recruitment channels]",
        "population_notes": [pop["note"] for pop in populations if pop.get("note")],
        "compensation": compensation(p),
        "externals": [r for r in p.external_team if r.organisation],
        "data_recipients": [r for r in p.external_team if r.data_access == "pseudonymised"],
        "limited_orgs": list({r.organisation: r for r in p.external_team if r.data_access != "pseudonymised"}.values()),
        "uses_prolific": "prolific" in p.channels,
        "team": [p.pi] + p.ucl_team + p.external_team,
    }


# ---------- choice answers in ethics@ucl (radio/checkbox labels; used by the filler and by questions.py) ----------
B2_FIELDS = [("deception", "Deception"), ("disclosures", "Disclosures"), ("security_sensitive", "Security sensitive"),
             ("researcher_risk", "Researcher wellbeing"), ("medicinal", "My research involves administration"),
             ("invasive", "My research involves physically invasive")]


def yes(flag: bool) -> str:
    return "Yes" if flag else "No"


def b2_ticks(p: Project, lib, d=None) -> list[str]:
    d = d or derive(p, lib)
    ticks = [label for field, label in B2_FIELDS if getattr(p, field)]
    if any(f.level == "high" and f.message.startswith("Vulnerability") for f in d["flags"]):
        ticks.append("Vulnerability")
    if any(i.get("warning") for i in d["instruments"]):
        ticks.append("Sensitivity")
    return ticks or ["None of the above"]


def form_choices(p: Project, lib) -> dict:
    """Question number -> option label(s) as ticked in ethics@ucl, for everything derived from the project."""
    from model import DATA_SOURCES, PROJECT_TYPES
    d = derive(p, lib)
    special = (["personal data revealing racial or ethnic origin"] if "ethnicity" in p.demographics else []) + \
              (["data concerning health"] if any("health" in s for s in d["special_category"]) else [])
    return {
        "A1": PROJECT_TYPES.get(p.project_type, PROJECT_TYPES["staff"]),
        "A2": yes(p.ucl_sponsor),
        "A3": yes(p.nhs_review),
        "A4": yes(p.existing_approval),
        "B1": [DATA_SOURCES[k][1] for k in p.data_sources if k in DATA_SOURCES],
        "B1.2": yes(p.min_age < 16 or "under_16" in p.populations),
        "B2": b2_ticks(p, lib, d),
        "C4": yes(bool(p.related_ethics_id)),
        "C5": yes(p.funded),
        "C7": yes(bool(p.ucl_team)),
        "C8": yes(bool(p.external_team)),
        "D2": list(d["d2_ticks"]) + (["Audio/ video recording or photography in a private place"]
                                     if d["has_audio"] else []),
        "D3": yes(p.collect_abroad),
        "D4.1": yes(bool(d["permissions"])),
        "E2.1": "Yes",
        "E3": ["a) UCL researcher(s)"] + (["c) Research collaborator(s) outside UCL"] if d["externals"] else []),
        "E6": yes(p.rate_per_hour > 0 or bool(p.in_kind)),
        "I2": yes(p.researcher_risk),
        "J1": "Yes",
        "J1.3": special or ["none of the above"],
        "J1.5": yes(bool(d["data_recipients"])),
        "J5": yes(p.open_data),
    }
