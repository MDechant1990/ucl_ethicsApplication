from pathlib import Path

import pytest
import yaml

import model
from checks import check_placeholders, check_project
from model import Instrument, Project, add_to_library, dump_project, instrument_key, load_library, load_project
from render import markdown_to_docx, render_answers, render_documents
from rules import compensation, derive

ROOT = Path(__file__).parent.parent
LIB = load_library()


def example() -> Project:
    """The single fictional example project (examples/example.yaml)."""
    return load_project(ROOT / "examples" / "example.yaml")


def answers(p: Project) -> dict[str, str]:
    return {a["id"]: a["text"] for a in render_answers(p, LIB)}


# ---------- the example ----------
def test_example_is_low_risk_and_renders():
    p = example()
    assert derive(p, LIB)["risk_level"] == "low"
    for text in list(answers(p).values()) + list(render_documents(p, LIB).values()):
        assert "{{" not in text and "{%" not in text


# ---------- questionnaires, overseas procedure, withdrawal ----------
def test_sensitivity_flag():
    flags = derive(example(), LIB)["flags"]
    assert any(f.level == "borderline" and "PHQ-8" in f.message for f in flags)


def test_only_the_overseas_todo_is_left():
    p = example()
    assert check_placeholders(render_answers(p, LIB), render_documents(p, LIB)) == [
        "Debrief: unfilled placeholder [Add equivalent support services for the overseas site.]"]
    assert check_project(p) == []


def test_withdrawal_window_is_consistent_everywhere():
    p = example()
    p.withdrawal_amount = 6
    a, docs = answers(p), render_documents(p, LIB)
    for text in [a["E10"], a["E12"], a["J1.6"], docs["Information sheet"], docs["Consent form"]]:
        assert "6 weeks" in text and "4 weeks" not in text


# ---------- co-design, venues, events, insiders, incentives ----------
def test_locations_need_permissions():
    a = answers(example())
    assert "venue owner" in a["D4.1"] and "event organisers" in a["D4.1"]
    assert "Example Games Expo 2027" in a["D4"]


def test_incentives_and_other_issues():
    a = answers(example())
    assert "retailer vouchers" in a["E6.1"] and "board game" in a["E6.1"] and "£100" in a["E6.1"]
    for title in ["Online recruitment", "Researcher wellbeing", "Community representation", "Prizes"]:
        assert title in a["I10"]
    assert "Dr Jordan Placeholder: Co-organiser of the Example Games Expo" in a["E3.1"]
    assert "Dr Alex Example: Active member" in a["E3.1"]


def test_paper_consent_is_stored_safely():
    a = answers(example())
    assert "paper consent form" in a["E8.2"]
    assert "locked cabinet" in a["J3"]


# ---------- neurodivergent, industry partner, short withdrawal ----------
def test_neurodivergent_is_borderline_with_justification():
    p = example()
    assert any(f.level == "borderline" and "Neurodivergent" in f.message for f in derive(p, LIB)["flags"])
    assert "not considered vulnerable by default" in answers(p)["I1.1"]


def test_special_category_includes_ethnicity_and_health():
    j13 = answers(example())["J1.3/J1.4"]
    assert "racial or ethnic origin" in j13 and "neurodivergence" in j13


def test_industry_partner_gets_no_personal_data():
    a = answers(example())
    assert a["J1.5.1"].startswith("No personal data are transferred outside UCL.")
    assert a["J1.5.1"].count("Example Partner Ltd") == 1  # one line per organisation (two people)
    assert "Industry partner involvement" in a["I10"]


def test_short_withdrawal_window_is_flagged():
    p = example()
    p.withdrawal_amount, p.withdrawal_unit = 5, "working days"
    issues = check_project(p)
    assert any("5 working days is short" in i for i in issues)


def test_pro_rata_pay_on_withdrawal():
    assert "pro rata for the time they took part" in answers(example())["E6.1"]


# ---------- rules ----------
def test_compensation_is_pro_rata():
    p = Project(rate_per_hour=12)
    p.phases[0].duration_min = 45
    assert derive(p, LIB)["compensation"][0]["amount"] == "£9.00"


def test_phq9_and_under_16_are_high_risk():
    p = Project(min_age=14)
    p.phases[0].instruments = ["phq9"]
    d = derive(p, LIB)
    assert d["risk_level"] == "high"
    assert {f.code for f in d["flags"] if f.level == "high"} >= {"B1.2", "B2"}


def test_withdrawal_unit_grammar():
    assert Project(withdrawal_amount=1, withdrawal_unit="weeks").withdrawal == "1 week"
    assert Project(withdrawal_amount=5, withdrawal_unit="working days").withdrawal == "5 working days"


def test_empty_project_renders_and_docx_builds():
    p = Project()
    docs = render_documents(p, LIB)
    assert markdown_to_docx(docs["Consent form"])[:2] == b"PK"  # .docx is a zip
    assert check_project(p)  # empty project has issues


def test_old_team_format_still_loads():
    p = Project.model_validate({"pi": {"first_name": "Ada", "surname": "L"},
                                "ucl_team": [{"first_name": "Bo"}],
                                "external_team": [{"first_name": "Cy", "organisation": "X"}]})
    assert p.pi.first_name == "Ada"
    assert [r.first_name for r in p.ucl_team] == ["Bo"]
    assert [r.first_name for r in p.external_team] == ["Cy"]


def test_exactly_one_ucl_pi_is_required():
    p = example()
    p.team[0].is_pi = False
    assert any("exactly one" in i for i in check_project(p))
    p.team[0].is_pi = True
    p.team[0].external = True
    assert any("must be a UCL member" in i for i in check_project(p))


def test_safeguarding_people_are_named_in_i3():
    p = example()
    assert "Dr Alex Example (Mental Health First Aider), Dr Sam Sample (Clinician / clinical psychologist) are" in answers(p)["I3"]
    p.team[0].safeguarding_role = ""
    assert "Dr Sam Sample (Clinician / clinical psychologist) is" in answers(p)["I3"]
    p.team[1].safeguarding_role = ""
    assert "Safeguarding:" not in answers(p)["I3"]


def test_old_project_level_flags_move_to_the_pi():
    p = Project.model_validate({"team": [{"is_pi": True, "first_name": "Ada"}],
                                "safeguarding": True, "dual_role": True, "dual_role_details": "Organiser"})
    assert p.safeguarding and p.pi.safeguarding_role
    assert p.dual_role and p.pi.dual_role_details == "Organiser"


def test_dual_role_without_details_is_flagged():
    p = example()
    p.team[0].dual_role, p.team[0].dual_role_details = True, ""
    assert any("describe the dual role" in i for i in check_project(p))


# ---------- questionnaires added by the user ----------
def with_pis(**flags) -> Project:
    p = example()
    p.custom_instruments["pis"] = Instrument(name="Player Identification Scale (PIS)", citation="Downs et al., 2019",
                                             url="https://doi.org/10.0000/example",
                                             construct="identification with the player character", **flags)
    p.phases[0].instruments.append("pis")
    return p


def test_custom_questionnaire_is_listed_in_d2_1():
    a = answers(with_pis())
    assert "Player Identification Scale (PIS) (Downs et al., 2019" in a["D2.1"]
    assert any("questionnaires:" in line and "PIS" in line for line in a["D2.1"].splitlines())


def test_custom_questionnaire_flags_flow_into_risk_and_data_protection():
    d = derive(with_pis(sensitive=True, health=True), LIB)
    assert any("Player Identification Scale" in f.message for f in d["flags"])
    assert any("Player Identification Scale" in s for s in d["special_category"])
    assert "Player Identification Scale" in answers(with_pis(sensitive=True))["I1.1"]


def test_custom_questionnaire_survives_save_and_load():
    p = with_pis()
    again = Project.model_validate(yaml.safe_load(dump_project(p)))
    assert again.custom_instruments["pis"].citation == "Downs et al., 2019"
    assert "Player Identification Scale (PIS)" in answers(again)["D2.1"]


def test_custom_questionnaire_without_reference_is_flagged():
    p = with_pis()
    p.custom_instruments["pis"].citation = ""
    assert any("PIS" in i and "reference" in i for i in check_project(p))


def test_instrument_key_is_short_and_unique():
    assert instrument_key("Player Identification Scale (PIS)", {}) == "pis"
    assert instrument_key("Player Identification Scale (PIS)", {"pis": 1}) == "pis_2"
    assert instrument_key("My own scale", {}) == "my_own_scale"


def test_add_to_library_keeps_comments_and_loads(tmp_path, monkeypatch):
    for f in (ROOT / "library").glob("*.yaml"):
        (tmp_path / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(model, "LIBRARY_DIR", tmp_path)
    add_to_library("pis", Instrument(name="Player Identification Scale (PIS)", citation="Downs et al., 2019"))
    text = (tmp_path / "instruments.yaml").read_text(encoding="utf-8")
    assert text.startswith("# Standardised instruments")
    lib = model.load_library()
    assert lib["instruments"]["pis"]["citation"] == "Downs et al., 2019"
    assert "phq9" in lib["instruments"]


# ---------- pre-screening survey as its own procedure ----------
def screening_project(**kw) -> Project:
    p = example().model_dump()
    p["custom_tools"] = p["custom_tools"] + ["Screening questions.pdf"]
    p.update(screening_method="survey", screening_survey=["Screening questions.pdf", "phq8"], **kw)
    return Project.model_validate(p)


def test_screening_survey_becomes_an_unpaid_procedure():
    p = screening_project()
    first = p.phases[0]
    assert first.screening and first.name == "Pre-screening survey" and first.location == "online"
    assert first.custom_tools == ["Screening questions.pdf"] and first.instruments == ["phq8"]
    assert len(p.study_phases) == len(p.phases) - 1
    assert "Pre-screening survey" not in [r["procedure"] for r in compensation(p)]
    a = answers(p)
    assert "Pre-screening survey (Online" in a["D2.1"]
    assert "Pre-screening survey" not in a["E1"]
    assert not [i for i in check_project(p) if "Pre-screening" in i]       # no sample size needed


def test_screening_procedure_is_removed_and_never_duplicated():
    p = screening_project()
    again = Project.model_validate(yaml.safe_load(dump_project(p)))
    assert sum(ph.screening for ph in again.phases) == 1
    data = again.model_dump()
    data["screening_method"] = "own"
    assert not any(ph.screening for ph in Project.model_validate(data).phases)


def test_screening_choice_is_checked():
    p = example()
    p.screening_method = ""
    assert any("Choose how eligibility is checked" in i for i in check_project(p))
    p.screening_method, p.screening_details = "own", ""
    assert any("Describe your screening technique" in i for i in check_project(p))
    assert any("Choose or upload the pre-screening survey" in i
               for i in check_project(Project.model_validate({**example().model_dump(),
                                                              "screening_method": "survey"})))
