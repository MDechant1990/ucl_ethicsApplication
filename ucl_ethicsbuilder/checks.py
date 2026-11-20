"""Checks: what a reviewer would send back. Each returns plain messages."""
import re

from model import Project, load_library
from questions import EMPTY, applicable

PLACEHOLDER = re.compile(r"\[[^\]]{2,}\]")


def check_project(p: Project) -> list[str]:
    issues = []
    if not p.title:
        issues.append("Project title is missing (C1).")
    pis = [r for r in p.team if r.is_pi]
    if len(pis) != 1:
        issues.append(f"Mark exactly one person as principal investigator (currently {len(pis)}).")
    elif pis[0].external:
        issues.append("The principal investigator must be a UCL member, not external (A5).")
    if not (p.pi.first_name and p.pi.surname and p.pi.email):
        issues.append("PI name or email is missing (A5).")
    if p.start_date and p.end_date and p.end_date <= p.start_date:
        issues.append("Completion date must be after the start date (C2/C3).")
    if not p.aims:
        issues.append("Research aims are missing (D1).")
    if not p.phases:
        issues.append("No study procedures yet (D2).")
    for ph in p.study_phases:
        if not ph.methods:
            issues.append(f"{ph.name}: no methods selected (D2).")
        if ph.sample_size <= 0:
            issues.append(f"{ph.name}: sample size is missing (E1).")
        if set(ph.methods) & {"interview", "expert_interview", "focus_group", "co_design", "creative_workshop"}:
            if not ph.custom_tools:
                issues.append(f"{ph.name}: upload an interview/focus group topic guide (D2.3).")
    if not p.screening_method:
        issues.append("Choose how eligibility is checked (E2.2, Population step).")
    elif p.screening_method == "survey" and not p.screening_survey:
        issues.append("Choose or upload the pre-screening survey (E2.2, D2.3).")
    elif p.screening_method == "own" and not p.screening_details.strip():
        issues.append("Describe your screening technique (E2.2).")
    for ins in p.custom_instruments.values():
        if not ins.citation:
            issues.append(f"{ins.name}: add the questionnaire's reference (D2.1).")
    if not p.dp_registration:
        issues.append("Data Protection registration number is missing (J1.1). Register before submitting.")
    if any(r.data_access == "pseudonymised" for r in p.external_team) and not p.data_sharing_agreement:
        issues.append("External partner receives pseudonymised data but no data sharing agreement is planned (J1.5.1).")
    if p.funded and not p.funder:
        issues.append("Funded project: name the funder (C5/E14).")
    for r in p.dual_role_team:
        if not r.dual_role_details:
            issues.append(f"{r.full_name or 'Team member'}: describe the dual role and how it is kept separate (E3.1).")
    days = p.withdrawal_amount * {"days": 1, "working days": 1.4, "weeks": 7}[p.withdrawal_unit]
    if days < 14:
        issues.append(f"Withdrawal window of {p.withdrawal} is short; reviewers usually expect at least 2 weeks (E12).")
    return issues


def check_questions(p: Project, lib=None) -> list[str]:
    """Questions that apply to this project (library/questions.yaml) but have no answer yet."""
    lib = lib or load_library()
    return [f"{q['number']}: not answered yet ({q['title']})." for q in applicable(p, lib) if q["value"] in EMPTY]


def check_placeholders(answers: list[dict], documents: dict[str, str]) -> list[str]:
    issues = []
    for a in answers:
        for m in PLACEHOLDER.findall(a["text"]):
            issues.append(f"{a['id']}: unfilled placeholder {m}")
    for name, text in documents.items():
        for m in PLACEHOLDER.findall(text):
            issues.append(f"{name}: unfilled placeholder {m}")
    return issues
