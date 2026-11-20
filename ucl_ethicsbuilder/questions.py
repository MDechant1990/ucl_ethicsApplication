"""Questions asked directly (library/questions.yaml): which apply to a project, and their answers.

Answers default to suggest.suggestions() (pre-filled from the project) until the user edits them.
A question applies when its section's `when` and its own `when` hold. Conditions are written in the form's own
terms (question number -> accepted option labels) and are checked against the choices the project implies
(rules.form_choices: A1, B1, B2, D3, ...) plus the answers given to earlier questions in the file.
"""
from model import Project
from rules import form_choices
from suggest import suggestions

EMPTY = (None, "", [])


def _matches(have, wanted: list[str]) -> bool:
    """Prefix match either way, so 'Vulnerability' matches the full form label and vice versa."""
    values = [v for v in (have if isinstance(have, list) else [have]) if v]
    return any(v.lower().startswith(w.lower()) or w.lower().startswith(v.lower()) for v in values for w in wanted)


def _holds(when, values: dict) -> bool:
    return not when or any(all(_matches(values.get(q), opts) for q, opts in alt.items()) for alt in when)


def answer(p: Project, number: str, spec: dict, suggested=None):
    """The user's answer, else the suggestion worked out from the project (suggest.py), else the YAML default."""
    value = p.answers.get(number)
    if value in EMPTY:
        value = suggested
    return spec.get("default") if value in EMPTY else value


def applicable(p: Project, lib) -> list[dict]:
    """Questions that apply, in file order: {number, section, title, step, spec, value, suggestion}."""
    spec_file = lib["questions"]
    values = form_choices(p, lib)
    suggested = suggestions(p, lib)
    out = []
    for number, spec in spec_file["questions"].items():
        section = spec_file["sections"][spec["section"]]
        if not (_holds(section.get("when"), values) and _holds(spec.get("when"), values)):
            continue
        value = answer(p, number, spec, suggested.get(number))
        if value not in EMPTY:
            values[number] = value             # later questions can depend on it
        out.append({"number": number, "section": spec["section"], "title": section["title"],
                    "step": section["step"], "spec": spec, "value": value,
                    "suggestion": suggested.get(number)})
    return out


def as_text(value) -> str:
    return "; ".join(value) if isinstance(value, list) else str(value or "")
