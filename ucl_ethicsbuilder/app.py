"""Streamlit UI. Run with:  streamlit run app.py

The UI only collects input into one dict (st.session_state.p) shaped like
model.Project. All logic lives in rules.py / render.py / checks.py.
"""
import datetime as dt
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import streamlit as st
import yaml

from checks import check_placeholders, check_project, check_questions
from model import (DATA_ACCESS, DATA_SOURCES, DEMOGRAPHICS, ORG_TYPES, PAYMENT_METHODS, PROJECT_TYPES,
                   SAFEGUARDING_ROLES, SCREENING_METHODS, Instrument, Phase, Project, Researcher, add_to_library,
                   dump_project, instrument_key, load_library, sync_screening, with_project_instruments)
from questions import applicable
from render import answers_markdown, markdown_to_docx, render_answers, render_documents
from rules import derive

st.set_page_config(page_title="UCL Ethics Builder", page_icon="📝", layout="wide")
LIB = load_library()
# Hosted for colleagues (e.g. via a Dev Tunnel): no ethics@ucl filler (it drives Chrome on the host) and no
# writing to the shared library (everyone's additions would mix). Start with ETHICS_HOSTED=1.
HOSTED = os.environ.get("ETHICS_HOSTED") == "1"
STEPS = ["1. Screening & project", "2. Research team", "3. Study procedures", "4. Population",
         "5. Risk check", "6. Data protection & pay", "7. Generate"]
# Step keys used by library/questions.yaml and render.SOURCE_STEP -> index in STEPS.
STEP_OF = {"screening": 0, "project": 0, "team": 1, "procedures": 2, "population": 3, "risk": 4, "data": 5}


def go_to_step(index):
    """Button callback: runs before the sidebar radio is drawn on the next run, so it may set its value."""
    st.session_state.step = STEPS[index]

if "p" not in st.session_state:
    st.session_state.p = Project().model_dump()
p = st.session_state.p
for _field, _default in Project().model_dump().items():   # sessions started before a new field was added
    p.setdefault(_field, _default)
# Answers typed on this run are in widget state already; copy them first so follow-up questions appear at once.
# A value that is still the suggestion shown (sug_<number>) is not stored, so it keeps following the project.
for _key in [k for k in st.session_state if k.startswith("w_ans_")]:
    _number = _key.removeprefix("w_ans_")
    if st.session_state[_key] == st.session_state.get(f"sug_{_number}"):
        p["answers"].pop(_number, None)
    else:
        p["answers"][_number] = st.session_state[_key]


# ---------- helpers: bind a widget to a path in the project dict ----------
def _get(path):
    obj = p
    for part in path.split("."):
        obj = obj[int(part)] if isinstance(obj, list) else obj[part]
    return obj


def _set(path, value):
    *parents, last = path.split(".")
    obj = p
    for part in parents:
        obj = obj[int(part)] if isinstance(obj, list) else obj[part]
    obj[int(last) if isinstance(obj, list) else last] = value


def bind(widget, label, path, **kw):
    """Show `widget` pre-filled from the project and write the result back."""
    key = "w_" + path
    if key not in st.session_state:
        st.session_state[key] = _get(path)
    value = widget(label, key=key, **kw)
    _set(path, value)
    return value


def bind_list(label, path, help=None):
    """Edit a list of strings as one item per line."""
    key = "w_" + path
    if key not in st.session_state:
        st.session_state[key] = "\n".join(_get(path))
    text = st.text_area(label, key=key, help=help or "One item per line")
    _set(path, [line.strip() for line in text.splitlines() if line.strip()])


def bind_date(label, path):
    key = "w_" + path
    if key not in st.session_state:
        st.session_state[key] = dt.date.fromisoformat(_get(path)) if _get(path) else None
    value = st.date_input(label, key=key, format="DD/MM/YYYY")
    _set(path, value.isoformat() if value else "")


def labels(lib_name):
    return lambda k: LIB[lib_name].get(k, {}).get("label") or LIB[lib_name].get(k, {}).get("name", k)


def project() -> Project:
    return Project.model_validate(p)


# ---------- questions asked directly (library/questions.yaml), shown only when they apply ----------
def bind_answer(q):
    number, spec = q["number"], q["spec"]
    key, sug_key, suggestion = f"w_ans_{number}", f"sug_{number}", q["suggestion"]
    if key not in st.session_state:
        st.session_state[key] = q["value"] if q["value"] is not None else ([] if spec["kind"] == "multi" else None)
    elif number not in p["answers"] and suggestion is not None:
        st.session_state[key] = suggestion          # not edited yet: follow the current suggestion
    st.session_state[sug_key] = suggestion
    label = f"**{number})** {spec['question']}"
    hint = spec.get("hint")
    if spec.get("manual"):
        hint = (hint + " " if hint else "") + "You tick this yourself in ethics@ucl; the filler never does."
    if spec["kind"] == "yes_no":
        st.segmented_control(label, ["Yes", "No"], key=key, help=hint)
    elif spec["kind"] == "choice":
        st.radio(label, spec["options"], key=key, help=hint)
    elif spec["kind"] == "multi":
        st.multiselect(label, spec["options"], key=key, help=hint)
    elif spec["kind"] == "text":
        st.text_input(label, key=key, help=hint)
    else:
        st.text_area(label, key=key, placeholder=hint, help=hint, height="content")
    value = st.session_state[key]
    if suggestion is not None and value == suggestion:
        p["answers"].pop(number, None)
        st.caption(":material/auto_awesome: Suggested from your other answers. Edit it if needed"
                   + (", and replace the [bracketed] parts." if "[" in str(value) else "."))
    else:
        p["answers"][number] = value


def ask(step_key):
    """All questions of this step that apply, grouped by section."""
    qs = [q for q in applicable(project(), LIB) if q["step"] == step_key]
    for title in dict.fromkeys(q["title"] for q in qs):
        with st.container(border=True):
            st.subheader(title)
            if any(q["section"] == "overseas" and q["title"] == title for q in qs):
                st.caption("Shown because these procedures collect data outside the UK: "
                           + ", ".join(ph["name"] for ph in p["phases"] if ph.get("outside_uk")))
            for q in qs:
                if q["title"] == title:
                    bind_answer(q)


# ---------- sidebar: navigation + save/load ----------
def reset_widgets(prefix="w_"):
    """Forget widget state so widgets re-read the project dict (after load/delete)."""
    for k in [k for k in st.session_state if k.startswith(prefix)]:
        del st.session_state[k]
    st.session_state.gen = st.session_state.get("gen", 0) + 1  # fresh file uploaders


if sync_screening(p):          # e.g. a project file loaded with a screening survey
    reset_widgets("w_phases.")


def start_project(project_obj: Project):
    st.session_state.p = project_obj.model_dump()
    reset_widgets()
    st.rerun()


with st.sidebar:
    st.title("UCL Ethics Builder")
    if HOSTED:
        st.info("Test version. Please use made-up details. Nothing is kept on the server: use **Save project** "
                "to keep your work.", icon=":material/science:")
    step = st.radio("Step", STEPS, key="step", label_visibility="collapsed")
    st.divider()
    if st.button("➕ New project", key="btn_new", width="stretch"):
        start_project(Project())
    with st.popover("📂 Load project", width="stretch"):
        # .txt is accepted because Chrome on Windows may save the download as "ethics_project.yaml.txt".
        up = st.file_uploader("Project file (.yaml)", type=["yaml", "yml", "txt"],
                              key=f"load_{st.session_state.get('gen', 0)}",
                              help="A file saved with 'Save project', or one of the files in examples/.")
    if up is not None:
        try:
            loaded = Project.model_validate(yaml.safe_load(up.getvalue().decode("utf-8-sig")) or {})
        except Exception as e:  # bad YAML or fields that don't match the model
            st.error(f"Could not load {up.name}: {e}")
        else:
            start_project(loaded)
    # Filled at the very end of the script, so the saved file includes edits made on this run.
    save_slot = st.empty()

if st.session_state.get("shown_step") != step:      # step changed (sidebar or Back/Next): start at the top
    if "shown_step" in st.session_state:
        st.html(f"<script>/* {step} */ for (const el of [document.querySelector('[data-testid=\"stMain\"]'),"
                " document.querySelector('section.main'), document.scrollingElement]) "
                "{ if (el) el.scrollTo({top: 0}); }</script>", unsafe_allow_javascript=True)
    st.session_state.shown_step = step

st.header(step)
st.caption(f"Step {STEPS.index(step) + 1} of {len(STEPS)}")

# ---------- 1. Screening (A1–A4, B1) and the project itself (C1–C5, D1, I1) ----------
if step == STEPS[0]:
    st.caption("These answers decide which parts of the ethics@ucl form apply to your project.")
    with st.container(border=True):
        st.subheader("Classification of the project (A1–A4)")
        bind(st.selectbox, "This application is for (A1)", "project_type",
             options=list(PROJECT_TYPES), format_func=PROJECT_TYPES.get)
        bind(st.checkbox, "UCL is the lead sponsor (A2)", "ucl_sponsor")
        bind(st.checkbox, "The research also needs NHS REC or MoDREC review (A3)", "nhs_review")
        bind(st.checkbox, "The project was approved by another UK university ethics committee in the last 3 years (A4)",
             "existing_approval")
    with st.container(border=True):
        st.subheader("Type of research (B1)")
        bind(st.pills, "The research involves (select all that apply)", "data_sources",
             options=list(DATA_SOURCES), format_func=lambda k: DATA_SOURCES[k][0], selection_mode="multi")
        if not p["data_sources"]:
            st.warning("Select at least one type of research.")
    ask("screening")

    with st.container(border=True):
        st.subheader("The project (C1, D1, I1)")
        bind(st.text_input, "Project title (C1)", "title")
        bind(st.text_area, "Aims and objectives in plain language (D1)", "aims", height=150)
        bind(st.text_area, "Specific benefits for participants/communities (I1, optional)", "benefits")
    with st.container(border=True):
        st.subheader("Project details (C2–C5)")
        c1, c2, c3 = st.columns(3)
        with c1:
            bind_date("Start date (C2)", "start_date")
        with c2:
            bind_date("Completion date (C3)", "end_date")
        with c3:
            bind(st.text_input, "Related UCL ethics ID (C4, optional)", "related_ethics_id")
        c1, c2 = st.columns([1, 3], vertical_alignment="bottom")
        bind(c1.checkbox, "Funded project (C5)", "funded")
        if p["funded"]:
            bind(c2.text_input, "Funder", "funder")
    ask("project")

# ---------- 2. Research team (A5, C7, C8) ----------
elif step == STEPS[1]:
    st.caption("Add everyone involved. Tick one person as principal investigator (the applicant) and "
               "mark people outside UCL as external.")
    team = p["team"]

    def make_only_pi(i):
        """Ticking one person as PI unticks everyone else."""
        if st.session_state[f"w_team.{i}.is_pi"]:
            for j, member in enumerate(team):
                if j != i:
                    member["is_pi"] = False
                    st.session_state[f"w_team.{j}.is_pi"] = False

    for i, person in enumerate(team):
        with st.container(border=True):
            c1, c2, c3, c4, c5 = st.columns([1, 2, 2, 3, 0.5], vertical_alignment="bottom")
            bind(c1.text_input, "Title", f"team.{i}.title")
            bind(c2.text_input, "First name", f"team.{i}.first_name")
            bind(c3.text_input, "Surname", f"team.{i}.surname")
            bind(c4.text_input, "Email", f"team.{i}.email")
            if c5.button("🗑", key=f"del_person_{i}", help="Remove this person"):
                team.pop(i)
                reset_widgets("w_team.")
                st.rerun()

            c1, c2 = st.columns(2)
            bind(c1.checkbox, "Principal investigator", f"team.{i}.is_pi", on_change=make_only_pi, args=(i,))
            bind(c2.checkbox, "External (not UCL)", f"team.{i}.external")
            if person["is_pi"] and person["external"]:
                st.warning("The principal investigator must be a UCL member.")

            if person["external"]:
                c1, c2, c3 = st.columns(3)
                bind(c1.text_input, "Organisation", f"team.{i}.organisation")
                bind(c2.selectbox, "Organisation type", f"team.{i}.org_type", options=ORG_TYPES)
                bind(c3.text_input, "Country", f"team.{i}.country")
                bind(st.selectbox, "Access to participant data (J1.5/J4)", f"team.{i}.data_access",
                     options=list(DATA_ACCESS), format_func=DATA_ACCESS.get)
            else:
                c1, c2 = st.columns(2)
                bind(c1.text_input, "Faculty", f"team.{i}.faculty")
                bind(c2.text_input, "Department / Institute", f"team.{i}.department")
            bind(st.text_input, "Role in the project", f"team.{i}.role")
            bind(st.text_input, "Relevant experience and training (I3)", f"team.{i}.experience")
            c1, c2 = st.columns(2)
            bind(c1.selectbox, "Safeguarding role (I1.1, I3)", f"team.{i}.safeguarding_role",
                 options=SAFEGUARDING_ROLES, format_func=lambda r: r or "None")
            bind(c2.checkbox, "Holds a dual role (community insider, event organiser, teacher or manager "
                              "of potential participants)", f"team.{i}.dual_role")
            if person["dual_role"]:
                bind(st.text_input, "Which role, and how is it kept separate from the research? (E3.1)",
                     f"team.{i}.dual_role_details")

    if st.button("➕ Add person", key="btn_add_person", width="stretch"):
        team.append(Researcher(is_pi=not any(m["is_pi"] for m in team)).model_dump())
        st.rerun()
    if not any(m["is_pi"] for m in team):
        st.warning("Nobody is marked as principal investigator yet.")
    if not any(m["safeguarding_role"] for m in team):
        st.info("Tip: if participants may discuss sensitive topics, give a team member a safeguarding role.")


# ---------- 2. Study procedures (methods + tools) ----------
elif step == STEPS[2]:
    st.caption("Add one study procedure per thing participants do (e.g. an online survey, an interview, a lab "
               "session). Tools you upload in one procedure can be reused in any other.")
    procs = p["phases"]
    gen = st.session_state.get("gen", 0)

    def add_questionnaire(i, instr):
        """Form to add a questionnaire that isn't in the list; it is selected in procedure i straight away."""
        with st.popover("➕ Add a questionnaire that isn't listed", width="stretch"):
            with st.form(f"add_instr_{i}", clear_on_submit=True, border=False):
                name = st.text_input("Full name with abbreviation",
                                     placeholder="Full name (ABBREVIATION)")
                c1, c2 = st.columns(2)
                citation = c1.text_input("Reference", placeholder="Author et al., Year")
                url = c2.text_input("DOI or link", placeholder="https://doi.org/...")
                construct = st.text_input("What it measures", placeholder="identification with the player character")
                health = st.checkbox("Asks about health or mental health (special category data, J1.3)")
                sensitive = st.checkbox("Asks about sensitive topics such as mood, anxiety or trauma (B2)")
                to_library = False if HOSTED else st.checkbox(
                    "Also add to the shared library (available in every project)", value=True)
                if st.form_submit_button("Add questionnaire", type="primary"):
                    if not name.strip():
                        st.error("Enter the questionnaire's name.")
                        return
                    new = Instrument(name=name.strip(), citation=citation.strip(), url=url.strip(),
                                     construct=construct.strip(), health=health, sensitive=sensitive)
                    key = instrument_key(new.name, instr)
                    p["custom_instruments"][key] = new.model_dump()
                    procs[i]["instruments"].append(key)
                    st.session_state.pop(f"w_phases.{i}.instruments", None)  # multiselect re-reads the project
                    if to_library:
                        add_to_library(key, new)
                    st.rerun()

    def tool_pool():
        """All uploaded materials in this project (uploaded anywhere, selectable everywhere)."""
        return list(dict.fromkeys(p["custom_tools"] + [t for ph in procs for t in ph["custom_tools"]]))

    number = 0
    for i, ph in enumerate(procs):
        if ph.get("screening"):
            with st.container(border=True):
                instr = with_project_instruments(project(), LIB)["instruments"]
                survey = ", ".join(instr.get(k, {}).get("name", k) for k in ph["instruments"] + ph["custom_tools"])
                st.markdown(f"**{ph['name']}** · online · about {ph['duration_min']} minutes · unpaid")
                st.caption(f"Survey: {survey or 'not chosen yet'}. Added automatically because eligibility is "
                           "checked with a pre-screening survey; change it on the Population step.")
            continue
        number += 1
        with st.container(border=True):
            # Header: the procedure's name as its title, actions top right.
            name = st.session_state.get(f"w_phases.{i}.name", ph["name"])   # shows a rename at once
            c1, c2 = st.columns([3, 2], vertical_alignment="center")
            c1.subheader(name or "Untitled procedure")
            with c2.container(horizontal=True, horizontal_alignment="right"):
                with st.popover("Rename", icon=":material/edit:"):
                    bind(st.text_input, "Name of this procedure", f"phases.{i}.name")
                duplicate = st.button("Duplicate", key=f"dup_{i}", icon=":material/content_copy:",
                                      help="Add a copy of this procedure below it")
                delete = st.button("Delete", key=f"del_{i}", icon=":material/delete:",
                                   help="Remove this procedure")
            if duplicate:
                copy = dict(ph, name=ph["name"] + " (copy)")
                procs.insert(i + 1, Phase.model_validate(copy).model_dump())
                reset_widgets("w_phases.")
                st.rerun()
            if delete:
                procs.pop(i)
                reset_widgets("w_phases.")
                st.rerun()

            # 1. Methods, 2. their details (questionnaires and materials)
            bind(st.multiselect, "Methods", f"phases.{i}.methods",
                 options=list(LIB["methods"]), format_func=labels("methods"))

            if ph["methods"]:
                st.markdown("**Details for these methods**")
                if any(LIB["methods"][m].get("questionnaires") for m in ph["methods"]) or ph["instruments"]:
                    instr = with_project_instruments(project(), LIB)["instruments"]
                    bind(st.multiselect, "Standardised questionnaires", f"phases.{i}.instruments",
                         options=list(instr), format_func=lambda k: instr.get(k, {}).get("name", k))
                    for key in ph["instruments"]:
                        if w := instr.get(key, {}).get("warning"):
                            st.warning(f"**{instr[key]['name']}**: {w}")
                    add_questionnaire(i, instr)
                files = st.file_uploader("Upload your own questionnaires, topic guides or tool descriptions",
                                         accept_multiple_files=True, key=f"up_{gen}_{i}")
                new = [f.name for f in files or [] if f.name not in ph["custom_tools"]]
                if new:
                    ph["custom_tools"] += new
                    p["custom_tools"] = list(dict.fromkeys(p["custom_tools"] + new))
                    st.session_state.pop(f"w_phases.{i}.custom_tools", None)
                bind(st.multiselect, "Your uploaded materials used here", f"phases.{i}.custom_tools",
                     options=tool_pool())

            # 3. Duration and location
            c1, c2 = st.columns([1, 3])
            bind(c1.number_input, "Duration (min)", f"phases.{i}.duration_min", min_value=1, max_value=600)
            bind(c2.selectbox, "Where", f"phases.{i}.location",
                 options=list(LIB["locations"]), format_func=labels("locations"))
            if ph["location"] != "online":
                bind(st.text_input, "Which lab / venue / event? (D4)", f"phases.{i}.lab_location")
            bind(st.checkbox, "Data is collected outside the UK in this procedure (incl. partner labs abroad or "
                              "participants taking part online from abroad) (D3)", f"phases.{i}.outside_uk")

            # 4. Sample size
            c1, c2 = st.columns([1, 3])
            bind(c1.number_input, "Sample size", f"phases.{i}.sample_size", min_value=0)
            bind(c2.text_input, "Sample size justification", f"phases.{i}.sample_justification")

    if st.button("Add study procedure", key="btn_add_proc", icon=":material/add:", width="stretch"):
        procs.append(Phase(name=f"Study procedure {number + 1}").model_dump())
        st.rerun()
    ask("procedures")


# ---------- 3. Population ----------
elif step == STEPS[3]:
    bind(st.multiselect, "Who will take part?", "populations",
         options=list(LIB["populations"]), format_func=labels("populations"))
    c1, c2 = st.columns(2)
    bind(c1.number_input, "Minimum age", "min_age", min_value=0, max_value=120)
    bind(c2.number_input, "Maximum age", "max_age", min_value=0, max_value=120)
    bind(st.text_input, "Age limit justification", "age_justification")
    bind_list("Inclusion criteria", "inclusion")
    bind_list("Exclusion criteria (method-specific ones are added automatically)", "exclusion")
    auto = derive(project(), LIB)["exclusions"]
    st.caption("Exclusions that will appear in the application: " + "; ".join(auto))

    with st.container(border=True):
        st.subheader("How eligibility is checked (E2.2)")
        st.caption("Your answer to E2.2 is written from this choice and the criteria above.")
        if "w_screening_method" not in st.session_state:
            st.session_state["w_screening_method"] = p["screening_method"] or None
        method = st.selectbox("Screening technique", list(SCREENING_METHODS), format_func=SCREENING_METHODS.get,
                              key="w_screening_method", placeholder="Choose a screening technique")
        p["screening_method"] = method or ""
        if method == "survey":
            instr = with_project_instruments(project(), LIB)["instruments"]
            uploaded = list(dict.fromkeys(p["custom_tools"] + [t for ph in p["phases"] for t in ph["custom_tools"]]))
            bind(st.multiselect, "Screening survey", "screening_survey",
                 options=uploaded + [k for k in instr if k not in uploaded],
                 format_func=lambda k: f"{k} (uploaded)" if k in uploaded else instr.get(k, {}).get("name", k),
                 help="Your uploaded materials and the questionnaires in the library.")
            files = st.file_uploader("Or upload a new screening survey", accept_multiple_files=True,
                                     key=f"scr_up_{st.session_state.get('gen', 0)}")
            new = [f.name for f in files or [] if f.name not in p["custom_tools"]]
            if new:
                p["custom_tools"] = list(dict.fromkeys(p["custom_tools"] + new))
                p["screening_survey"] = list(dict.fromkeys(p["screening_survey"] + new))
                st.session_state.pop("w_screening_survey", None)
                st.rerun()
            st.caption("Added to the study procedures as 'Pre-screening survey' (online, about 5 minutes, unpaid).")
        elif method == "own":
            bind(st.text_area, "Describe your screening technique", "screening_details", height=120,
                 placeholder="E.g. participants are identified from an earlier study's consenting participants who "
                             "agreed to be contacted; their records are checked against the criteria above. "
                             "Say what people who are not eligible are told.")
        if sync_screening(p):
            reset_widgets("w_phases.")
    bind(st.multiselect, "Demographic data collected (J1.2/J1.3)", "demographics", options=DEMOGRAPHICS)
    bind(st.multiselect, "Recruitment channels", "channels",
         options=list(LIB["channels"]), format_func=labels("channels"))
    bind(st.selectbox, "Time to decide after receiving the information sheet (E5)", "decision_time",
         options=["at least 24 hours", "at least 48 hours", "at least 5 working days", "at least one week"])
    ask("population")


# ---------- 4. Risk check ----------
elif step == STEPS[4]:
    st.write("Confirm the items that cannot be derived from your answers (B2 checklist):")
    for field, label in [("deception", "Deception or covert research"),
                         ("disclosures", "Participants may disclose illegal/harmful activities or safeguarding concerns"),
                         ("security_sensitive", "Security-sensitive material (extremism, terrorism)"),
                         ("researcher_risk", "Risk to researcher safety or wellbeing"),
                         ("medicinal", "Medicines or other substances administered"),
                         ("invasive", "Physically invasive procedures")]:
        bind(st.checkbox, label, field)
    d = derive(project(), LIB)
    st.divider()
    if d["risk_level"] == "high":
        st.error("**High-risk review** is likely required.")
    else:
        st.success("**Low-risk review** route.")
    for f in d["flags"]:
        {"high": st.error, "borderline": st.warning, "info": st.info}[f.level](f"**{f.code}**: {f.message}")
    ask("risk")


# ---------- 5. Data protection & pay ----------
elif step == STEPS[5]:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Reimbursement")
        bind(st.number_input, "Rate per hour (£)", "rate_per_hour", min_value=0.0, step=0.5)
        bind(st.selectbox, "Paid", "payment_method", options=PAYMENT_METHODS)
        bind(st.checkbox, "Course credit (SONA) as alternative", "course_credit")
        bind(st.radio, "If a participant stops early, pay", "pay_on_withdrawal",
             options=["full", "pro rata"], horizontal=True)
        bind(st.checkbox, "Reimburse travel expenses", "travel_expenses")
        bind(st.text_input, "In-kind incentive (optional), e.g. 'a miniature of their choice'", "in_kind")
        bind(st.text_input, "Prize (optional), e.g. 'a prize of up to £100 for the winner'", "prize")
        st.table(derive(project(), LIB)["compensation"])
    with c2:
        st.subheader("Data protection")
        bind(st.text_input, "Data Protection registration number (J1.1)", "dp_registration")
        c3, c4 = st.columns(2)
        bind(c3.number_input, "Withdrawal window", "withdrawal_amount", min_value=0, max_value=365)
        bind(c4.selectbox, "Unit", "withdrawal_unit", options=["days", "working days", "weeks"])
        bind(st.number_input, "Retention after project end (years)", "retention_years", min_value=1, max_value=30)
        bind(st.selectbox, "Storage", "storage", options=[
            "UCL OneDrive for Business", "UCL Research Data Storage (RDS)", "UCL Data Safe Haven"])
        bind(st.checkbox, "Data sharing agreement with external partners", "data_sharing_agreement")
        bind(st.checkbox, "Paper consent forms at in-person sessions", "paper_consent")
        bind(st.checkbox, "Share anonymised data in the UCL Research Data Repository", "open_data")
        st.subheader("Dissemination (E13/E14)")
        bind(st.checkbox, "Share a plain-language summary via community channels", "community_summary")
        bind(st.text_input, "Target conferences / journals", "dissemination_venues")
    st.subheader("Special category data (J1.3) – derived")
    for s in derive(project(), LIB)["special_category"] or ["None"]:
        st.write("- " + s)
    ask("data")


# ---------- 7. Generate ----------
elif step == STEPS[6]:
    proj = project()
    answers, docs = render_answers(proj, LIB), render_documents(proj, LIB)
    issues = check_project(proj) + check_questions(proj, LIB) + check_placeholders(answers, docs)
    if issues:
        st.warning(f"**{len(issues)} item(s) to fix before submitting.** Open the list, fix them in the steps "
                   "named, and come back here.", icon=":material/warning:")
        with st.expander("Show the items to fix"):
            st.markdown("\n".join(f"- {i}" for i in issues))
    else:
        st.success("No issues found.", icon=":material/check_circle:")

    # Placeholder for the direct connection to ethics@ucl (not built yet). Made large with CSS on its key class.
    st.html("<style>.st-key-btn_upload button {min-height: 4.5rem; font-size: 1.25rem; font-weight: 600;}"
            ".st-key-btn_upload button p {font-size: 1.25rem;}</style>")
    st.button("Upload to Ethics@UCL", key="btn_upload", icon=":material/cloud_upload:", type="primary",
              width="stretch", disabled=True,
              help="Coming soon: send these answers straight into a draft application in ethics@ucl.")
    st.caption("Coming soon: creates a draft in ethics@ucl with these answers. It will never submit or sign "
               "for you. Until then, download the documents and copy the answers below.")

    # ----- participant documents: first and most visible -----
    st.subheader(":material/description: Participant documents")
    st.caption("Generated from your answers. Download them as Word files, check them, and upload them to "
               "ethics@ucl with your application.")
    DOC_INFO = {
        "Information sheet": ("info", "What the study involves, risks, data use and contacts."),
        "Consent form": ("assignment_turned_in", "The statements participants agree to."),
        "Debrief": ("volunteer_activism", "What participants receive at the end, with support contacts."),
    }
    for col, (name, md) in zip(st.columns(len(docs)), docs.items()):
        icon, blurb = DOC_INFO.get(name, ("description", ""))
        with col.container(border=True, height="stretch"):
            st.markdown(f"**:material/{icon}: {name}**")
            st.download_button("Download (.docx)", markdown_to_docx(md), f"{name.replace(' ', '_')}.docx",
                               key=f"dl_{name}", icon=":material/download:", width="stretch")
            st.caption(blurb)
    with st.expander("Preview the documents"):
        for tab, md in zip(st.tabs(list(docs)), docs.values()):
            tab.markdown(md)

    # ----- form answers: second, each linked to the step it comes from -----
    st.subheader(":material/list_alt: Form answers")
    head, dl = st.columns([3, 1], vertical_alignment="center")
    head.caption("In the order ethics@ucl asks them. Copy each answer into the form, or use **Edit** to go to "
                 "the step where it comes from.")
    dl.download_button("All answers (.md)", answers_markdown(answers), "ethics_answers.md", key="dl_answers",
                       icon=":material/download:", width="stretch")
    for n, a in enumerate(answers):
        source = STEP_OF.get(a.get("step"))
        with st.expander(f"**{a['id']}** – {a['title']}"):
            if source is not None:
                st.button(f"Edit in {STEPS[source]}", key=f"edit_{n}", icon=":material/edit:", type="tertiary",
                          on_click=go_to_step, args=(source,))
            st.code(a["text"], language=None, wrap_lines=True)

    # ----- the local filler (only when running on your own computer) -----
    if not HOSTED:
        with st.expander("🤖 Fill a draft in ethics@ucl from this computer (local version only)"):
            st.markdown(
                "1. Click **Open Chrome for ethics@ucl** and log in in the new window (first time only).\n"
                "2. Create a new draft, or enter the number of an existing draft (from its URL, "
                "`/Project/Index/<number>`).\n"
                "3. The filler fills and **saves** each page. It **never submits, signs or opens the "
                "declarations page**; uploads, team members and confirmations stay for you.")
            c1, c2, c3 = st.columns([1, 1, 1])
            if c1.button("Open Chrome for ethics@ucl", key="btn_chrome"):
                from filler.browser import launch_chrome
                launch_chrome()
            target = c2.radio("Draft", ["Create new draft", "Existing draft"], key="fill_target",
                              label_visibility="collapsed")
            number = c3.text_input("Draft number", key="fill_number", disabled=target == "Create new draft")
            overwrite = st.checkbox("Overwrite text already in the draft", key="fill_overwrite")
            if st.button("Fill draft now", key="btn_fill",
                         disabled=target == "Existing draft" and not number.strip().isdigit()):
                tmp = Path(tempfile.gettempdir()) / "ethics_builder_fill.yaml"
                tmp.write_text(dump_project(proj), encoding="utf-8")
                cmd = [sys.executable, "-m", "filler.fill", str(tmp)]
                cmd += ["--new"] if target == "Create new draft" else ["--project", number.strip()]
                cmd += ["--overwrite"] if overwrite else []
                out, lines = st.empty(), []
                with subprocess.Popen(cmd, cwd=Path(__file__).parent, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                      env={**os.environ, "PYTHONIOENCODING": "utf-8"}) as proc:
                    for line in proc.stdout:
                        lines.append(line.rstrip())
                        out.code("\n".join(lines[-40:]), language=None)
                if proc.returncode == 0:
                    st.success("Draft filled and saved. It has not been submitted. Review it in ethics@ucl.")
                else:
                    st.error("The filler stopped with an error. Is Chrome open and are you logged in?")
                out.code("\n".join(lines), language=None)


# ---------- Back / Next (bottom of every step; the sidebar list stays in sync) ----------
_i = STEPS.index(step)
st.divider()
_back, _gap, _next = st.columns([2, 1, 2])
if _i > 0:
    _back.button(f"Back: {STEPS[_i - 1]}", key="btn_back", icon=":material/arrow_back:", width="stretch",
                 on_click=go_to_step, args=(_i - 1,))
if _i < len(STEPS) - 1:
    _next.button(f"Next: {STEPS[_i + 1]}", key="btn_next", icon=":material/arrow_forward:", width="stretch",
                 icon_position="right", type="primary", on_click=go_to_step, args=(_i + 1,))

# ---------- sidebar save button (last, so it contains every edit from this run) ----------
_saved = project()
_name = "".join(c if c.isalnum() else "_" for c in _saved.title)[:40].strip("_") or "ethics_project"
save_slot.download_button("💾 Save project (.yaml)", dump_project(_saved), file_name=f"{_name}.yaml",
                          mime="application/x-yaml", key="btn_save", width="stretch")
