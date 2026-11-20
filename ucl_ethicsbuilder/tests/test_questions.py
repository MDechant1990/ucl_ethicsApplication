"""Questions asked directly (library/questions.yaml): consistency with the form, conditions, plan and checks."""
import json
from pathlib import Path

import pytest
import yaml

from checks import check_questions
from filler.answers import build_plan
from model import Project, dump_project, load_library, load_project
from questions import _matches, applicable
from render import render_answers
from rules import form_choices

ROOT = Path(__file__).parent.parent
LIB = load_library()
SPEC = LIB["questions"]
FORM = {q["number"]: q for p in json.loads((ROOT / "filler" / "form_inventory.json").read_text(encoding="utf-8"))
        ["pages"].values() for q in p["questions"] if q["number"]}
TISSUE_NEW = "b) I will collect new samples of relevant material from participants"


def numbers(p: Project) -> list[str]:
    return [q["number"] for q in applicable(p, LIB)]


# ---------- the YAML matches the real form ----------
@pytest.mark.parametrize("number", list(SPEC["questions"]))
def test_question_exists_in_form_with_same_options(number):
    spec = SPEC["questions"][number]
    assert number in FORM
    assert spec["section"] in SPEC["sections"]
    if "options" in spec:
        assert spec["options"] == [o["label"] for o in FORM[number]["options"]]
    if spec["kind"] == "yes_no":
        assert [o["label"] for o in FORM[number]["options"]] == ["Yes", "No"]


def all_conditions():
    for key, sec in SPEC["sections"].items():
        for alt in sec.get("when", []):
            yield from ((f"section {key}", q, opts) for q, opts in alt.items())
    for number, spec in SPEC["questions"].items():
        for alt in spec.get("when", []):
            yield from ((number, q, opts) for q, opts in alt.items())


@pytest.mark.parametrize("where,source,options", list(all_conditions()))
def test_conditions_use_real_form_options(where, source, options):
    known = set(form_choices(Project(), LIB)) | set(SPEC["questions"])
    assert source in known, f"{where}: condition on {source}, which the tool neither derives nor asks"
    labels = [o["label"] for o in FORM[source]["options"]]
    for opt in options:
        assert any(_matches(label, [opt]) for label in labels), f"{where}: '{opt}' is not an option of {source}"


# ---------- which questions apply ----------
def test_typical_low_risk_study_gets_only_a_few_questions():
    asked = numbers(load_project(ROOT / "examples" / "meet.yaml"))
    assert len(asked) <= 10
    assert not [n for n in asked if n[0] in "FGH" or n.startswith(("I4", "I5", "I6", "I7", "I8", "I9", "E9"))]


def test_sections_follow_screening_answers():
    p = Project(data_sources=["new_data", "human_tissue", "secondary_data"], min_age=12, deception=True,
                medicinal=True)
    asked = numbers(p)
    for n in ["B1.4", "G1", "G2", "E9", "I6", "H1.1", "H3", "F10"]:
        assert n in asked
    assert "F1" not in asked                       # needs B1.4 (new or existing samples) first


def test_follow_ups_appear_and_disappear_with_answers():
    p = Project(data_sources=["human_tissue"], answers={"B1.4": [TISSUE_NEW], "F4": "Yes", "F4.1": "Report to GP"})
    assert {"F1", "F4", "F4.1"} <= set(numbers(p))
    assert "F5" not in numbers(p)                  # existing samples not selected
    p.answers["F4"] = "No"
    assert "F4.1" not in numbers(p)
    plan = dict((q, v) for q, _, v in build_plan(p, LIB))
    assert "F4.1)" not in plan                     # stale answer is not filled in


def test_default_answer_and_its_follow_up():
    p = Project()
    assert "E8" in numbers(p) and "E8.1" not in numbers(p)       # E8 defaults to Yes
    p.answers["E8"] = "No"
    assert "E8.1" in numbers(p)


# ---------- plan, generated text, checks, save/load ----------
def test_plan_uses_screening_fields_and_answers_but_never_ticks_commitments():
    p = Project(project_type="masters", ucl_sponsor=False, security_sensitive=True,
                answers={"A2.1": "Led by partner university", "I9": ["e) None of the above, but my research is "
                                                                     "security-sensitive for another reason"],
                         "I9.13": "Details", "I9.11": "I have already discussed the research with UCL ISG"})
    plan = {q: (kind, v) for q, kind, v in build_plan(p, LIB)}
    assert plan["A1)"] == ("radio", "UCL Master's student project")
    assert plan["A2)"] == ("radio", "No")
    assert plan["A2.1)"] == ("text", "Led by partner university")
    assert plan["I9)"][0] == "check" and plan["I9.13)"] == ("text", "Details")
    assert "I9.11)" not in plan                    # manual commitment
    assert any(a["id"] == "A2.1" and a["text"] == "Led by partner university" for a in render_answers(p, LIB))


def test_unanswered_questions_are_flagged():
    p = Project(deception=True)
    issues = check_questions(p, LIB)
    assert any(i.startswith("I6:") for i in issues)
    assert not any(i.startswith("I6.1:") for i in issues)          # suggested: full debrief (Yes)
    p.answers.update({"I6": "x", "I6.1": "Yes", "I6.2": "y", "C6": "No", "D2.4": "No"})
    assert not [i for i in check_questions(p, LIB) if i.startswith("I6")]


def test_answers_survive_save_and_load():
    p = Project(data_sources=["secondary_data"], answers={"G1": ["Data previously collected for research purposes."],
                                                          "G1.5": ["Yes"], "G1.6": "Approved by X"})
    again = Project.model_validate(yaml.safe_load(dump_project(p)))
    assert again.answers == p.answers and again.data_sources == ["secondary_data"]
    assert "G1.6" in numbers(again)


# ---------- streamlined study procedures ----------
def test_d2_6_only_after_stakeholder_input():
    p = load_project(ROOT / "examples" / "meet.yaml")
    assert "D2.4" in numbers(p) and "D2.6" not in numbers(p)
    p.answers["D2.4"] = "Yes"
    assert {"D2.5", "D2.6"} <= set(numbers(p))


def test_overseas_questions_follow_the_procedure_flags():
    p = load_project(ROOT / "examples" / "meet.yaml")
    assert not p.collect_abroad and "D3.1" not in numbers(p)
    assert form_choices(p, LIB)["D3"] == "No"
    p.phases[0].outside_uk = True
    assert p.collect_abroad and form_choices(p, LIB)["D3"] == "Yes"
    assert {"D3.1", "D3.2", "D3.6", "D3.9"} <= set(numbers(p))


def test_old_project_wide_abroad_flag_moves_to_online_procedures():
    p = Project.model_validate({"collect_abroad": True, "phases": [{"name": "Survey", "location": "online"},
                                                                    {"name": "Lab", "location": "lab"}]})
    assert [ph.outside_uk for ph in p.phases] == [True, False]
    assert "collect_abroad" not in yaml.safe_load(dump_project(p))
    p = Project.model_validate({"collect_abroad": True, "phases": [{"name": "Lab", "location": "lab"}]})
    assert p.phases[0].outside_uk


# ---------- suggested answers (suggest.py) ----------
def value(p: Project, number: str):
    return next(q["value"] for q in applicable(p, LIB) if q["number"] == number)


def test_travel_follows_in_person_procedures_abroad():
    p = load_project(ROOT / "examples" / "gaze.yaml")             # Phase 2: lab in Frankfurt
    assert value(p, "D3.2") == "Yes"
    for ph in p.phases:
        ph.outside_uk = ph.location == "online"                    # only online participants abroad
    assert value(p, "D3.2") == "No"
    assert "No data are collected in person outside the UK" in value(p, "D3.3")


def test_overseas_locations_listed_from_procedures():
    text = value(load_project(ROOT / "examples" / "grimdark.yaml"), "D3.1")
    assert "Conference gaming and painting event" in text and "Frankfurt" in text


def test_conflict_of_interest_follows_industry_partner():
    assert value(load_project(ROOT / "examples" / "meet.yaml"), "C6") == "Yes"     # industry partner
    assert value(load_project(ROOT / "examples" / "gaze.yaml"), "C6") == "No"


def test_users_own_answer_wins_over_suggestion():
    p = load_project(ROOT / "examples" / "meet.yaml")
    p.answers["C6"] = "No"
    assert value(p, "C6") == "No"


def e2_2(p: Project) -> str:
    """E2.2 is generated from the screening box (not asked as a question)."""
    assert "E2.2" not in SPEC["questions"]
    return next(a["text"] for a in render_answers(p, LIB) if a["id"] == "E2.2")


def test_screening_text_follows_the_chosen_technique():
    p = load_project(ROOT / "examples" / "gaze.yaml")
    assert e2_2(p) == p.screening_details               # own technique: the applicant's words
    p.screening_method, p.screening_survey = "survey", ["phq8"]
    text = e2_2(p)
    assert "pre-screening survey (Patient Health Questionnaire (PHQ-8)" in text
    assert p.inclusion[0] in text and any(e in text for e in derive_exclusions(p))
    p.screening_method = "self_declaration"
    assert "confirm that they meet each eligibility criterion" in e2_2(p)
    p.screening_method = ""
    assert "[Choose how eligibility is checked" in e2_2(p)


def derive_exclusions(p):
    from rules import derive
    return derive(p, LIB)["exclusions"]


def test_sensitive_topics_named_and_self_harm_protocol_left_to_researcher():
    p = load_project(ROOT / "examples" / "gaze.yaml")
    p.phases[0].instruments = ["phq9"]
    p.answers["I5"] = ""                                           # empty answers fall back to the suggestion
    assert "PHQ-9" in value(p, "I5")
    assert "[describe the risk protocol" in value(p, "I5.1")


def test_disclosures_name_the_safeguarding_lead_or_leave_a_placeholder():
    p = Project(disclosures=True)
    assert "[Name the team member" in value(p, "I7.1")
    p.team[0].first_name, p.team[0].surname, p.team[0].safeguarding_role = "Ada", "Lovelace", "Safeguarding lead"
    assert "Ada Lovelace (Safeguarding lead)" in value(p, "I7.1")


def test_placeholders_in_suggestions_are_caught_by_checks():
    from checks import check_placeholders
    p = Project(researcher_risk=True)
    answers = render_answers(p, LIB)
    assert any(i.startswith("I2.1: unfilled placeholder") for i in check_placeholders(answers, {}))


def test_data_sharing_text_excludes_recordings_and_uses_retention():
    p = load_project(ROOT / "examples" / "grimdark.yaml")
    p.open_data = True
    text = value(p, "J6")
    assert f"{p.retention_years} years" in text
    assert "recordings" in text and "audio recordings" not in text.split("(")[1].split(")")[0].lower()


def test_undergraduate_special_category_number_reuses_j1_1():
    p = load_project(ROOT / "examples" / "meet.yaml")              # ethnicity + health data
    p.project_type, p.dp_registration = "undergraduate", "Z6364106/2025/01/23"
    plan = {q: v for q, _, v in build_plan(p, LIB)}
    assert plan["J1.3.1)"] == "Z6364106/2025/01/23"
    p.project_type = "staff"
    assert "J1.3.1)" not in {q for q, _, _ in build_plan(p, LIB)}
