"""Render: project + derived facts -> form answers (text) and documents (.docx)."""
import io

from docx import Document

from model import Project, with_project_instruments
from questions import EMPTY, applicable, as_text
from rules import derive
from templating import environment as _env

# (question id, heading, template file) in the order ethics@ucl asks them.
QUESTIONS = [
    ("A5", "Applicant details", "A5.j2"),
    ("B1.2/B2", "Risk checklist", "B2.j2"),
    ("C1–C6", "Project details", "C1.j2"),
    ("C7.1", "UCL research team", "C7_1.j2"),
    ("C8.1", "External research team", "C8_1.j2"),
    ("D1", "Research aims and objectives", "D1.j2"),
    ("D2", "Methods (tick boxes)", "D2.j2"),
    ("D2.1", "Overview of research design", "D2_1.j2"),
    ("D4", "Research location", "D4.j2"),
    ("D4.1", "Location permissions", "D4_1.j2"),
    ("E1", "Sample size and age limits", "E1.j2"),
    ("E2", "Eligibility criteria", "E2.j2"),
    ("E2.2", "How eligibility is checked", "E2_2.j2"),
    ("E3.1", "Relationships, conflicts of interest, power dynamics", "E3_1.j2"),
    ("E4", "How participants are approached", "E4.j2"),
    ("E5", "Time to decide", "E5.j2"),
    ("E6.1", "Compensation", "E6_1.j2"),
    ("E8.2", "How consent is taken and recorded", "E8_2.j2"),
    ("E8.3", "Ongoing consent", "E8_3.j2"),
    ("E10", "Withdrawal process", "E10.j2"),
    ("E11", "Limits on withdrawal", "E11.j2"),
    ("E12", "Withdrawal deadline", "E12.j2"),
    ("E13", "Sharing findings with participants", "E13.j2"),
    ("E14", "Wider dissemination", "E14.j2"),
    ("I1", "Benefits", "I1.j2"),
    ("I1.1", "Risks and why this is low risk", "I1_1.j2"),
    ("I3", "Team skills and training", "I3.j2"),
    ("I10", "Other ethical issues", "I10.j2"),
    ("J1.1", "Data protection registration", "J1_1.j2"),
    ("J1.2", "Personal data processed", "J1_2.j2"),
    ("J1.2.1", "Pseudonymisation / anonymisation", "J1_2_1.j2"),
    ("J1.3/J1.4", "Special category data", "J1_3.j2"),
    ("J1.5.1", "Transfers outside UCL", "J1_5_1.j2"),
    ("J1.6", "Deletion schedule", "J1_6.j2"),
    ("J2", "Types of data", "J2.j2"),
    ("J3", "Storage and security", "J3.j2"),
    ("J4", "Access to data", "J4.j2"),
    ("J7", "End of project", "J7.j2"),
]

# Where in the app the facts behind each generated answer are entered (step keys as in library/questions.yaml,
# plus "team"). Lets the Generate page link every answer back to the step that changes it.
SOURCE_STEP = {
    "A5": "team", "B1.2/B2": "risk", "C1–C6": "project", "C7.1": "team", "C8.1": "team", "D1": "project",
    "D2": "procedures", "D2.1": "procedures", "D4": "procedures", "D4.1": "procedures",
    "E1": "population", "E2": "population", "E2.2": "population", "E3.1": "population", "E4": "population",
    "E5": "population", "E6.1": "data", "E8.2": "data", "E8.3": "population", "E10": "data", "E11": "data",
    "E12": "data", "E13": "data", "E14": "data", "I1": "project", "I1.1": "risk", "I3": "team", "I10": "risk",
    "J1.1": "data", "J1.2": "data", "J1.2.1": "data", "J1.3/J1.4": "data", "J1.5.1": "data", "J1.6": "data",
    "J2": "data", "J3": "data", "J4": "data", "J7": "data",
}

DOCUMENTS = {
    "Information sheet": "information_sheet.md.j2",
    "Consent form": "consent_form.md.j2",
    "Debrief": "debrief.md.j2",
}


def render_answers(p: Project, lib) -> list[dict]:
    lib = with_project_instruments(p, lib)
    env, d = _env(lib), derive(p, lib)
    generated = [
        {"id": qid, "title": title, "text": env.get_template(f"form/{tpl}").render(p=p, d=d).strip(),
         "step": SOURCE_STEP[qid]}
        for qid, title, tpl in QUESTIONS
    ]
    asked = [{"id": q["number"], "title": q["title"], "text": as_text(q["value"]), "step": q["step"]}
             for q in applicable(p, lib) if q["value"] not in EMPTY]
    return generated + asked


def render_documents(p: Project, lib) -> dict[str, str]:
    lib = with_project_instruments(p, lib)
    env, d = _env(lib), derive(p, lib)
    return {name: env.get_template(f"docs/{tpl}").render(p=p, d=d).strip() for name, tpl in DOCUMENTS.items()}


def answers_markdown(answers: list[dict]) -> str:
    return "\n\n".join(f"## {a['id']} – {a['title']}\n\n{a['text']}" for a in answers)


def markdown_to_docx(md: str) -> bytes:
    """Very small Markdown -> .docx converter (headings, bullets, checkboxes, bold lines)."""
    doc = Document()
    for line in md.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("# "):
            doc.add_heading(s[2:], level=1)
        elif s.startswith("## "):
            doc.add_heading(s[3:], level=2)
        elif s.startswith("- [ ] "):
            doc.add_paragraph("☐ " + s[6:])
        elif s.startswith("- "):
            _add_runs(doc.add_paragraph(style="List Bullet"), s[2:])
        else:
            _add_runs(doc.add_paragraph(), s)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _add_runs(par, text: str):
    """Support **bold** segments."""
    for i, part in enumerate(text.split("**")):
        par.add_run(part).bold = i % 2 == 1
