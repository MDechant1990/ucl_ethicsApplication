"""Turn a Project into a fill plan: ordered (question, kind, value) actions for ethics@ucl.

kind:  "text"  -> value is a str, or a list of str for questions with several boxes (E1 a/b/c)
       "radio" -> value is the option label (prefix match)
       "check" -> value is a list of option labels (prefix match)
Questions we cannot answer reliably (people pickers, uploads, attestations) are listed in MANUAL.
"""
import re

from model import Project
from render import render_answers
from questions import EMPTY, applicable
from rules import derive, form_choices

MANUAL = [
    "A5 – applicant details (check that they are pre-filled from your UCL profile)",
    "B2 – tick the confirmation box under the risk checklist yourself",
    "C7.1 / C8.1 – add team members with the search / add buttons",
    "D2.2, D2.3, E7, E8.4 – upload flowcharts, tools, adverts, information sheets and consent forms",
    "D3.x – overseas questions (if any)",
    "I11 – insurance confirmation",
    "Declarations & Signatures – always done by you; the filler never opens this page",
]


def _date(iso: str) -> str:
    """'2027-01-01' -> '01/01/2027' (ethics@ucl format)."""
    return "/".join(reversed(iso.split("-"))) if iso else ""


def _split(text: str, *markers: str) -> list[str]:
    """Split a generated answer into the separate boxes the form uses, dropping the marker headings."""
    parts = re.split("|".join(re.escape(m) for m in markers), text)
    return [re.sub(r"^\s*[a-c]\)\s*[^\n]*\n", "", x, count=1).strip() if i == 0 else x.strip()
            for i, x in enumerate(parts)]


def yes(flag: bool) -> str:
    return "Yes" if flag else "No"


def build_plan(p: Project, lib) -> list[tuple[str, str, object]]:
    a = {x["id"]: x["text"] for x in render_answers(p, lib)}
    d = derive(p, lib)

    c = form_choices(p, lib)
    special = c["J1.3"] != ["none of the above"]

    plan = [
        # A – initial questions
        ("A1)", "radio", c["A1"]),
        ("A2)", "radio", c["A2"]),
        ("A3)", "radio", c["A3"]),
        ("A4)", "radio", c["A4"]),
        # B – about your research
        ("B1)", "check", c["B1"]),
        ("B1.2)", "radio", c["B1.2"]),
        ("B2)", "check", c["B2"]),
        # C – project details and team
        ("C1)", "text", p.title),
        ("C2)", "text", _date(p.start_date)),
        ("C3)", "text", _date(p.end_date)),
        ("C4)", "radio", yes(bool(p.related_ethics_id))),
        ("C4.1)", "text", p.related_ethics_id),
        ("C5)", "radio", c["C5"]),
        ("C5.2)", "text", p.funder if p.funded else ""),
        ("C7)", "radio", c["C7"]),
        ("C8)", "radio", c["C8"]),
        # D – research summary and location
        ("D1)", "text", a["D1"]),
        ("D2)", "check", c["D2"]),
        ("D2.1)", "text", a["D2.1"]),
        ("D3)", "radio", c["D3"]),
        ("D4)", "text", a["D4"]),
        ("D4.1)", "radio", c["D4.1"]),
        ("D4.2)", "text", a["D4.1"] if d["permissions"] else ""),
        # E – recruitment, consent, withdrawal, findings
        ("E1)", "text", _split(a["E1"], "b) Justification", "c) Age limits")),
        ("E2)", "text", _split(a["E2"].replace("Inclusion criteria:\n", ""), "Exclusion criteria:")),
        ("E2.1)", "radio", "Yes"),
        ("E2.2)", "text", a["E2.2"]),
        ("E3)", "check", c["E3"]),
        ("E3.1)", "text", a["E3.1"]),
        ("E4)", "text", a["E4"]),
        ("E5)", "text", a["E5"]),
        ("E6)", "radio", c["E6"]),
        ("E6.1)", "text", a["E6.1"]),
        ("E8.2)", "text", a["E8.2"]),
        ("E8.3)", "text", a["E8.3"]),
        ("E10)", "text", _split(a["E10"], "b) After data collection:")),
        ("E11)", "text", a["E11"]),
        ("E12)", "text", a["E12"]),
        ("E13)", "text", a["E13"]),
        ("E14)", "text", a["E14"]),
        # I – risks and benefits
        ("I1)", "text", a["I1"]),
        ("I1.1)", "text", a["I1.1"]),
        ("I2)", "radio", c["I2"]),
        ("I3)", "text", a["I3"]),
        ("I10)", "text", a["I10"]),
        # J – personal data and storage
        ("J1)", "radio", "Yes"),
        ("J1.1)", "text", p.dp_registration),
        ("J1.2)", "text", a["J1.2"]),
        ("J1.2.1)", "text", a["J1.2.1"]),
        ("J1.3)", "check", c["J1.3"]),
        ("J1.3.1)", "text", p.dp_registration if special and p.project_type == "undergraduate" else ""),
        ("J1.4)", "text", a["J1.3/J1.4"] if special else ""),
        ("J1.5)", "radio", c["J1.5"]),
        ("J1.5.1)", "text", a["J1.5.1"] if d["data_recipients"] else ""),
        ("J1.6)", "text", a["J1.6"]),
        ("J2)", "text", a["J2"]),
        ("J3)", "text", a["J3"]),
        ("J4)", "text", a["J4"]),
        ("J5)", "radio", c["J5"]),
        ("J7)", "text", a["J7"]),
    ]
    # Questions asked directly (library/questions.yaml); commitments marked `manual` stay with the applicant.
    kinds = {"yes_no": "radio", "choice": "radio", "multi": "check", "text": "text", "textarea": "text"}
    plan += [(f"{q['number']})", kinds[q["spec"]["kind"]], q["value"])
             for q in applicable(p, lib) if not q["spec"].get("manual")]
    return [(q, kind, v) for q, kind, v in plan if v not in EMPTY]
