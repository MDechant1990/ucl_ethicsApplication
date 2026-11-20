"""Headless UI tests: pages render, edits flow into the generated text, procedures can be managed."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).parent.parent / "app.py")
N_STEPS = 7


def go(at, step):
    radio = at.sidebar.radio[0]
    return radio.set_value(radio.options[step]).run()


def new_app():
    return AppTest.from_file(APP, default_timeout=30).run()


EXAMPLE = Path(__file__).parent.parent / "examples" / "example.yaml"


def load_example(at, uk_only=False):
    """Load the example file through the sidebar's Load project uploader, like a user would.
    uk_only: the same project with every procedure in the UK."""
    data = EXAMPLE.read_bytes()
    if uk_only:
        data = data.replace(b"outside_uk: true", b"outside_uk: false")
    at.sidebar.file_uploader[0].upload(EXAMPLE.name, data).run()


def procedure_names(at):
    return [p["name"] for p in at.session_state.p["phases"]]


@pytest.mark.parametrize("uk_only", [False, True])
def test_all_pages_render_with_the_example(uk_only):
    at = new_app()
    load_example(at, uk_only)
    for step in range(N_STEPS):
        go(at, step)
        assert not at.exception, f"step {step + 1}: {at.exception}"


def test_back_and_next_buttons_move_between_steps():
    at = new_app()
    assert not [b for b in at.button if b.key == "btn_back"]          # nothing before step 1
    for step in range(1, N_STEPS):
        at.button(key="btn_next").click().run()
        assert not at.exception, at.exception
        assert at.sidebar.radio[0].value.startswith(f"{step + 1}.")   # sidebar follows the buttons
    assert not [b for b in at.button if b.key == "btn_next"]          # nothing after the last step
    at.button(key="btn_back").click().run()
    assert at.sidebar.radio[0].value.startswith(f"{N_STEPS - 1}.")
    go(at, 2)                                                          # sidebar still works too
    at.button(key="btn_next").click().run()
    assert at.sidebar.radio[0].value.startswith("4.")


def test_edit_flows_into_answers():
    at = new_app()
    load_example(at)
    go(at, 5)
    at.number_input(key="w_withdrawal_amount").set_value(6).run()
    go(at, 6)
    assert any("up to 6 weeks" in c.value for c in at.code)


def test_new_project_after_example_starts_empty():
    at = new_app()
    load_example(at)
    assert at.session_state.p["title"]
    at.button(key="btn_new").click().run()
    assert at.session_state.p["title"] == ""
    assert procedure_names(at) == ["Study procedure 1"]
    go(at, 0)
    assert at.text_input(key="w_title").value == ""  # widget shows the empty project, not the example


def test_add_duplicate_delete_procedures():
    at = new_app()
    load_example(at)
    go(at, 2)
    before = procedure_names(at)

    at.button(key="btn_add_proc").click().run()
    assert len(procedure_names(at)) == len(before) + 1

    at.button(key="dup_0").click().run()
    assert procedure_names(at)[1] == before[0] + " (copy)"

    at.button(key="del_1").click().run()   # delete the copy
    at.button(key="del_0").click().run()   # delete the first original
    names = procedure_names(at)
    assert names[0] == before[1]
    # widgets were re-bound to the shifted list, not left showing deleted values
    assert at.text_input(key="w_phases.0.name").value == before[1]
    assert not at.exception


def test_uploaded_tool_is_reusable_in_other_procedures():
    at = new_app()
    load_example(at)
    go(at, 2)
    pool = at.multiselect(key="w_phases.0.custom_tools").options
    assert "Interview_Topic_Guide.pdf" in pool  # uploaded in procedure 2, offered in procedure 1


def team(at):
    return at.session_state.p["team"]


def test_team_add_person_pi_is_exclusive_and_external_fields():
    at = new_app()
    at.button(key="btn_new").click().run()
    go(at, 1)
    assert team(at)[0]["is_pi"]                                  # new project starts with the PI card
    at.button(key="btn_add_person").click().run()
    assert len(team(at)) == 2 and not team(at)[1]["is_pi"]

    at.checkbox(key="w_team.1.is_pi").check().run()              # make person 2 the PI
    assert [m["is_pi"] for m in team(at)] == [False, True]
    assert at.checkbox(key="w_team.0.is_pi").value is False      # checkbox on card 1 unticked too

    at.checkbox(key="w_team.0.external").check().run()           # person 1 is external
    at.text_input(key="w_team.0.organisation").input("Example Partner Ltd").run()
    assert team(at)[0]["organisation"] == "Example Partner Ltd"

    at.button(key="del_person_0").click().run()
    assert len(team(at)) == 1 and team(at)[0]["is_pi"]
    assert at.checkbox(key="w_team.0.is_pi").value is True       # widgets re-bound after delete
    assert not at.exception


def test_safeguarding_role_and_dual_role_on_person_card():
    at = new_app()
    at.button(key="btn_new").click().run()
    go(at, 1)
    at.selectbox(key="w_team.0.safeguarding_role").select("Mental Health First Aider").run()
    at.checkbox(key="w_team.0.dual_role").check().run()
    at.text_input(key="w_team.0.dual_role_details").input("Event organiser; not involved in consent").run()
    person = at.session_state.p["team"][0]
    assert person["safeguarding_role"] == "Mental Health First Aider"
    assert person["dual_role_details"].startswith("Event organiser")
    assert not at.exception


def saved_yaml(title):
    from model import Project, dump_project
    return dump_project(Project(title=title)).encode()


@pytest.mark.parametrize("filename", ["project.yaml", "project.yml", "ethics_project.yaml.txt"])
def test_saved_project_loads_back(filename):
    at = new_app()
    load_example(at)                       # something else is open when loading
    at.sidebar.file_uploader[0].upload(filename, saved_yaml("Reloaded study")).run()
    assert not at.exception
    assert at.session_state.p["title"] == "Reloaded study"
    go(at, 0)
    assert at.text_input(key="w_title").value == "Reloaded study"


def test_project_can_be_loaded_twice_in_a_row():
    at = new_app()
    at.sidebar.file_uploader[0].upload("a.yaml", saved_yaml("First")).run()
    at.sidebar.file_uploader[0].upload("b.yaml", saved_yaml("Second")).run()
    assert at.session_state.p["title"] == "Second"


def test_invalid_project_file_shows_error_and_keeps_current_project():
    at = new_app()
    at.text_input(key="w_title").set_value("Keep me").run()
    at.sidebar.file_uploader[0].upload("broken.yaml", b"team: not-a-list\n").run()
    assert not at.exception
    assert any("Could not load broken.yaml" in e.value for e in at.error)
    assert at.session_state.p["title"] == "Keep me"


@pytest.fixture
def library_copy(tmp_path, monkeypatch):
    """Point the app at a copy of library/ so tests never change the real instruments.yaml."""
    import model
    for f in model.LIBRARY_DIR.glob("*.yaml"):
        (tmp_path / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(model, "LIBRARY_DIR", tmp_path)
    return tmp_path


def add_pis(at, to_library):
    """Fill the 'Add a questionnaire' form of procedure 1 (its widgets have no keys, so find them by text)."""
    [t for t in at.text_input if t.placeholder == "Full name (ABBREVIATION)"][0].set_value(
        "Player Identification Scale (PIS)")
    [t for t in at.text_input if t.placeholder == "Author et al., Year"][0].set_value("Downs et al., 2019")
    lib_box = [c for c in at.checkbox if c.label.startswith("Also add to the shared library")][0]
    lib_box.set_value(to_library)
    [b for b in at.button if b.label == "Add questionnaire"][0].click().run()


@pytest.mark.parametrize("to_library", [False, True])
def test_add_questionnaire_from_the_app(library_copy, to_library):
    at = new_app()
    load_example(at)                          # procedure 1 uses questionnaires
    go(at, 2)
    add_pis(at, to_library)
    assert not at.exception, at.exception
    p = at.session_state.p
    assert p["custom_instruments"]["pis"]["citation"] == "Downs et al., 2019"
    assert "pis" in p["phases"][0]["instruments"]
    assert "pis" in at.multiselect(key="w_phases.0.instruments").value
    in_library = "pis:" in (library_copy / "instruments.yaml").read_text(encoding="utf-8")
    assert in_library == to_library
    go(at, 6)
    assert any("Player Identification Scale (PIS)" in c.value for c in at.code)


def test_screening_and_risk_answers_open_the_matching_questions():
    at = new_app()
    at.get_by_key("w_data_sources").set_value(["new_data", "human_tissue"]).run()   # step 1 = screening
    assert not at.exception, at.exception
    assert at.multiselect(key="w_ans_B1.4")                     # B1.4 shown on the screening step
    at.multiselect(key="w_ans_B1.4").set_value(
        ["b) I will collect new samples of relevant material from participants"]).run()
    go(at, 2)
    assert at.text_area(key="w_ans_F1")                          # human tissue section on study procedures

    go(at, 4)
    at.checkbox(key="w_deception").check().run()
    assert at.text_area(key="w_ans_I6")
    at.get_by_key("w_ans_I6.1").set_value("No").run()           # follow-up appears on the same rerun
    assert not at.exception, at.exception
    assert at.text_area(key="w_ans_I6.3")
    at.text_area(key="w_ans_I6.3").set_value("Full debrief would bias the follow-up session").run()
    go(at, 6)
    assert not any("I6.3: not answered" in w.value for w in at.warning)
    assert any("Full debrief would bias" in c.value for c in at.code)
    assert at.session_state.p["answers"]["I6.1"] == "No"


def test_procedure_flag_outside_uk_opens_overseas_questions():
    at = new_app()
    load_example(at, uk_only=True)
    go(at, 2)
    assert not [t for t in at.text_area if t.key == "w_ans_D3.1"]
    at.checkbox(key="w_phases.0.outside_uk").check().run()
    assert not at.exception, at.exception
    assert at.text_area(key="w_ans_D3.1")
    assert any("collect data outside the UK: Online survey" in c.value for c in at.caption)


def test_suggestions_follow_the_project_until_edited():
    at = new_app()
    load_example(at, uk_only=True)                               # industry partner, all in the UK
    assert at.get_by_key("w_ans_C6").value == "Yes"              # suggested on page 1
    assert any("Suggested from your other answers" in c.value for c in at.caption)
    assert "C6" not in at.session_state.p["answers"]             # suggestions are not stored

    go(at, 2)
    at.checkbox(key="w_phases.0.outside_uk").check().run()
    assert at.get_by_key("w_ans_D3.2").value == "No"             # online only: nobody travels
    assert "Online survey" in at.text_area(key="w_ans_D3.1").value
    at.text_input(key="w_phases.0.name").set_value("Remote survey").run()
    assert "Remote survey" in at.text_area(key="w_ans_D3.1").value   # untouched suggestion follows

    at.text_area(key="w_ans_D3.1").set_value("Interviews with participants in Germany").run()
    at.text_input(key="w_phases.0.name").set_value("Survey (online)").run()
    assert at.text_area(key="w_ans_D3.1").value == "Interviews with participants in Germany"   # edit kept
    assert at.session_state.p["answers"]["D3.1"] == "Interviews with participants in Germany"
    assert not at.exception, at.exception


def test_pre_screening_survey_becomes_a_procedure():
    at = new_app()
    load_example(at)                                             # own screening technique
    go(at, 3)
    assert at.text_area(key="w_screening_details").value.startswith("Participants confirm eligibility")
    at.selectbox(key="w_screening_method").set_value("survey").run()
    at.multiselect(key="w_screening_survey").set_value(["phq8"]).run()
    uploader = [u for u in at.file_uploader if u.label == "Or upload a new screening survey"][0]
    uploader.upload("Screening questions.pdf", b"%PDF").run()
    assert not at.exception, at.exception
    p = at.session_state.p
    assert p["phases"][0]["screening"] and p["phases"][0]["custom_tools"] == ["Screening questions.pdf"]
    assert p["screening_survey"] == ["phq8", "Screening questions.pdf"]

    go(at, 2)                                                    # shown read-only on study procedures
    assert any("Pre-screening survey" in m.value for m in at.markdown)
    assert at.text_input(key="w_phases.1.name").value == "Online survey"   # real procedures keep their widgets

    go(at, 3)
    at.selectbox(key="w_screening_method").set_value("self_declaration").run()
    assert not any(ph["screening"] for ph in at.session_state.p["phases"])
    go(at, 2)
    assert at.text_input(key="w_phases.0.name").value == "Online survey"


def test_hosted_mode_hides_the_filler_and_library_writes(monkeypatch):
    monkeypatch.setenv("ETHICS_HOSTED", "1")
    at = new_app()
    assert any("Test version" in i.value for i in at.sidebar.info)
    load_example(at)
    go(at, 6)
    assert not [b for b in at.button if b.key == "btn_fill"]
    assert any("only available when the tool runs on your own computer" in c.value for c in at.caption)
    go(at, 2)
    assert not [c for c in at.checkbox if c.label.startswith("Also add to the shared library")]
