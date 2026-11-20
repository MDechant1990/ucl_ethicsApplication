"""Suggested answers for questions in library/questions.yaml, worked out from what the project already knows.

Suggestions are never stored: the app shows them pre-filled, and they follow later changes to the project until
the user edits them (then the user's text is kept in Project.answers). Text suggestions come from
templates/suggest/<number>.j2; a `[placeholder]` marks what only the researcher can write.
"""
from model import Project
from rules import derive
from templating import environment

TEXT = ["D3.1", "D3.3", "I2.1", "I4", "I4.2", "I5", "I5.1", "I7.1", "J6"]
NOT_SHARED = ("audio", "consent", "contact")      # data types never deposited in a repository (J6)


def context(p: Project, lib, d: dict) -> dict:
    loc = lib["locations"]
    abroad = [{"name": ph.name, "label": loc.get(ph.location, {}).get("label", ph.location), "venue": ph.lab_location,
               "in_person": bool(loc.get(ph.location, {}).get("in_person"))} for ph in p.phases if ph.outside_uk]
    vulnerable = [pop for pop in (lib["populations"].get(k) for k in p.populations) if pop and pop.get("vulnerable")]
    safeguarding = p.safeguarding_team
    return {
        "abroad": abroad,
        "abroad_in_person": any(a["in_person"] for a in abroad),
        "externals_abroad": [r for r in p.external_team if r.country and r.country != "United Kingdom"],
        "in_person": list(dict.fromkeys(l["label"] for l in d["locations"] if l.get("in_person"))),
        "vulnerable": vulnerable,
        "vulnerable_mitigations": [m for pop in vulnerable for m in pop.get("mitigations", [])],
        "sensitive": [i for i in d["instruments"] if i.get("sensitive") or i.get("warning")],
        "warning": [i for i in d["instruments"] if i.get("warning")],
        "safeguarding_names": ", ".join(f"{r.full_name} ({r.safeguarding_role})" for r in safeguarding if r.full_name),
        "safeguarding": safeguarding,
        "shareable": [t for t in d["data_types"] if not any(w in t.lower() for w in NOT_SHARED)],
    }


def suggestions(p: Project, lib) -> dict:
    """Question number -> suggested answer (only for questions with a suggestion)."""
    d = derive(p, lib)
    s = context(p, lib, d)
    env = environment(lib)
    out = {
        # tick boxes
        "D3.2": "Yes" if s["abroad_in_person"] else "No",     # someone travels only for in-person sessions abroad
        "C6": "Yes" if any(r.org_type == "Industry partner" for r in p.external_team) else "No",
        "I6.1": "Yes",                                        # full debrief is the normal case
        "E9": "Yes",                                          # opt-in parental consent is the standard route
    }
    for number in TEXT:
        text = env.get_template(f"suggest/{number.replace('.', '_')}.j2").render(p=p, d=d, s=s).strip()
        if text:
            out[number] = text
    return out
