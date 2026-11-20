"""Data model: the single source of truth for one ethics application.

Every fact (withdrawal window, pay rate, storage...) is entered ONCE here
and reused by every generated answer and document.
"""
import re
import warnings
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, model_validator

LIBRARY_DIR = Path(__file__).parent / "library"

ORG_TYPES = ["UK higher education institution", "Overseas higher education institution",
             "Industry partner", "Charity / community organisation", "Other"]
DATA_ACCESS = {"pseudonymised": "Pseudonymised research data (joint analysis)",
               "aggregated": "Aggregated, anonymised findings only",
               "none": "No access to participant data"}
DEMOGRAPHICS = ["age", "gender", "education", "occupation", "ethnicity", "neurodivergence status"]
SAFEGUARDING_ROLES = ["", "Mental Health First Aider", "Clinician / clinical psychologist",
                      "Safeguarding lead", "Other (described under experience)"]
PAYMENT_METHODS = ["by bank transfer", "in Amazon vouchers", "in retailer vouchers", "via Prolific"]
# A1: key -> label in ethics@ucl
PROJECT_TYPES = {"staff": "UCL staff project (including staff-led projects which will involve student researchers)",
                 "research_degree": "UCL research degree project (MPhil/PhD, Professional Doctorate)",
                 "masters": "UCL Master's student project",
                 "undergraduate": "UCL undergraduate student project"}
# E2.2: how eligibility is checked
SCREENING_METHODS = {
    "survey": "Pre-screening survey before taking part",
    "self_declaration": "Participants confirm themselves that they meet each criterion before the study starts",
    "own": "Another technique (describe it), e.g. identifying participants from existing records or earlier studies",
}
SCREENING_PHASE = "Pre-screening survey"
# B1: key -> (label in the app, label in ethics@ucl)
DATA_SOURCES = {
    "new_data": ("New data collection with participants",
                 "My research involves new data collection and/or engagement with participants"),
    "secondary_data": ("Existing or secondary data about people",
                       "My research involves use of secondary/ existing data derived from or about people"),
    "human_tissue": ("Human tissue ('relevant material' under the Human Tissue Act)",
                     "My research involves use of 'relevant material' as defined by the Human Tissue Act"),
    "other_issues": ("None of these, but the research raises ethical issues",
                     "None of the above, but my research presents ethical issues requiring consideration"),
}


class Researcher(BaseModel):
    is_pi: bool = False                # principal investigator (applicant, A5)
    external: bool = False             # not a UCL member (C8.1)
    title: str = ""
    first_name: str = ""
    surname: str = ""
    email: str = ""
    faculty: str = "Faculty of Brain Sciences"
    department: str = ""
    organisation: str = "UCL"          # external collaborators only
    org_type: str = ORG_TYPES[0]       # external collaborators only
    country: str = "United Kingdom"
    data_access: str = "pseudonymised"  # external collaborators only (key of DATA_ACCESS)
    role: str = ""
    experience: str = ""               # skills/training, used for I3
    safeguarding_role: str = ""        # one of SAFEGUARDING_ROLES (empty = none)
    dual_role: bool = False            # e.g. community insider, event organiser, teacher/manager of participants
    dual_role_details: str = ""        # which role, and how it is kept separate from the research

    @property
    def full_name(self) -> str:
        return " ".join(x for x in [self.title, self.first_name, self.surname] if x)


# "construct" matches the library's YAML key; it shadows pydantic's deprecated BaseModel.construct(), which is fine.
warnings.filterwarnings("ignore", message='Field name "construct"')


class Instrument(BaseModel):
    """A standardised questionnaire (same fields as an entry in library/instruments.yaml)."""
    name: str                          # full name with abbreviation, e.g. "Player Identification Scale (PIS)"
    citation: str = ""                 # e.g. "Downs et al., 2019"
    url: str = ""                      # DOI or link
    construct: str = ""                # what it measures, e.g. "identification with the player character"
    health: bool = False               # special category "data concerning health" (J1.3)
    sensitive: bool = False            # B2 "Sensitivity" borderline flag + justification in I1.1
    warning: str = ""                  # shown to the applicant when selected


class Phase(BaseModel):
    name: str = "Study procedure 1"
    location: str = "online"           # key of library/locations.yaml
    lab_location: str = ""             # free text: which lab / venue / event
    duration_min: int = 30
    sample_size: int = 0
    sample_justification: str = ""
    methods: list[str] = []            # keys of library/methods.yaml
    instruments: list[str] = []        # keys of library/instruments.yaml or Project.custom_instruments
    custom_tools: list[str] = []       # uploaded file names (custom questionnaires, topic guides)
    outside_uk: bool = False           # data collected outside the UK in this procedure (opens D3)
    screening: bool = False            # the pre-screening survey procedure, maintained by sync_screening()


class Project(BaseModel):
    # Step 1 – screening (ethics@ucl A1–A4, B1); they decide which sections of the form appear
    project_type: str = "staff"        # key of PROJECT_TYPES (A1)
    ucl_sponsor: bool = True           # A2
    nhs_review: bool = False           # A3: also needs NHS REC / MoDREC review
    existing_approval: bool = False    # A4: approved by another UK university committee in the last 3 years
    data_sources: list[str] = ["new_data"]  # keys of DATA_SOURCES (B1)

    # Step 1 – team & project
    title: str = ""
    start_date: str = ""
    end_date: str = ""
    related_ethics_id: str = ""
    funded: bool = False
    funder: str = ""
    team: list[Researcher] = [Researcher(is_pi=True)]
    aims: str = ""
    benefits: str = ""

    # Step 2 – study procedures (stored as `phases`), methods & tools
    phases: list[Phase] = [Phase()]
    custom_tools: list[str] = []       # pool of uploaded materials, selectable in any procedure
    custom_instruments: dict[str, Instrument] = {}  # questionnaires added by the user (key -> instrument)

    # Step 4 – population & recruitment
    populations: list[str] = ["healthy_adults"]
    min_age: int = 18
    max_age: int = 65
    age_justification: str = ""
    inclusion: list[str] = ["Able to read and understand English", "Able to give informed consent"]
    exclusion: list[str] = []
    demographics: list[str] = ["age", "gender"]
    channels: list[str] = ["mailing_lists", "social_media"]
    screening_method: str = ""         # key of SCREENING_METHODS ("" = not chosen yet) (E2.2)
    screening_survey: list[str] = []   # questionnaire keys and/or uploaded file names used for pre-screening
    screening_details: str = ""        # the applicant's own screening technique
    decision_time: str = "at least 24 hours"

    # Step 5 – risk checklist items that cannot be derived
    deception: bool = False
    disclosures: bool = False
    security_sensitive: bool = False
    researcher_risk: bool = False
    medicinal: bool = False
    invasive: bool = False

    # Step 6 – reimbursement
    rate_per_hour: float = 12.0
    payment_method: str = PAYMENT_METHODS[0]
    course_credit: bool = False
    pay_on_withdrawal: str = "full"    # full | pro rata
    travel_expenses: bool = False
    in_kind: str = ""                  # e.g. "a miniature of their choice"
    prize: str = ""                    # e.g. "a prize of up to £100 for the winner of the gaming event"

    # Step 6 – data protection
    withdrawal_amount: int = 4
    withdrawal_unit: str = "weeks"     # days | working days | weeks
    retention_years: int = 10
    storage: str = "UCL OneDrive for Business"
    dp_registration: str = ""
    paper_consent: bool = False        # in-person paper forms (scanned, originals locked away)
    data_sharing_agreement: bool = True
    open_data: bool = False

    # Dissemination
    community_summary: bool = False    # plain-language summary via community channels
    dissemination_venues: str = "ACM CHI and CHI PLAY"

    # Answers to library/questions.yaml (questions the templates cannot derive), keyed by form number, e.g. "F4.1"
    answers: dict[str, Any] = {}

    @model_validator(mode="before")
    @classmethod
    def _old_team_format(cls, data):
        """Accept older files with separate pi / ucl_team / external_team entries."""
        if isinstance(data, dict) and "team" not in data and {"pi", "ucl_team", "external_team"} & data.keys():
            data = dict(data)
            pi = data.pop("pi", None)
            team = [{**pi, "is_pi": True}] if pi else []
            team += [dict(r) for r in data.pop("ucl_team", None) or []]
            team += [{**r, "external": True} for r in data.pop("external_team", None) or []]
            data["team"] = team
        # project-level safeguarding / dual-role flags moved onto the people (attach to the PI)
        if isinstance(data, dict) and {"safeguarding", "dual_role"} & data.keys():
            data = dict(data)
            safeguarding, dual, details = (data.pop("safeguarding", False), data.pop("dual_role", False),
                                           data.pop("dual_role_details", ""))
            team = [dict(r) for r in data.get("team", [])]
            pi = next((r for r in team if r.get("is_pi")), None)
            if pi is not None:
                if safeguarding and not any(r.get("safeguarding_role") for r in team):
                    pi["safeguarding_role"] = SAFEGUARDING_ROLES[-1]
                if dual and not any(r.get("dual_role") for r in team):
                    pi.update(dual_role=True, dual_role_details=details)
            data["team"] = team
        # the pre-screening procedure always matches the screening choice
        if isinstance(data, dict):
            data = dict(data)
            data["phases"] = [ph.model_dump() if isinstance(ph, BaseModel) else dict(ph)
                              for ph in data.get("phases", [Phase().model_dump()])]
            sync_screening(data)
        # project-wide "collected outside the UK" moved onto the procedures (online ones, else all of them)
        if isinstance(data, dict) and "collect_abroad" in data:
            data = dict(data)
            if data.pop("collect_abroad") and not any(ph.get("outside_uk") for ph in data.get("phases", [])):
                phases = [dict(ph) for ph in data.get("phases", [])]
                online = [ph for ph in phases if ph.get("location", "online") == "online"]
                for ph in online or phases:
                    ph["outside_uk"] = True
                data["phases"] = phases
        return data

    # Derived views of the one team list (used by rules, templates and the filler).
    @property
    def pi(self) -> Researcher:
        return next((r for r in self.team if r.is_pi), Researcher())

    @property
    def ucl_team(self) -> list[Researcher]:
        return [r for r in self.team if not r.is_pi and not r.external]

    @property
    def external_team(self) -> list[Researcher]:
        return [r for r in self.team if r.external and not r.is_pi]

    @property
    def safeguarding_team(self) -> list[Researcher]:
        return [r for r in self.team if r.safeguarding_role]

    @property
    def safeguarding(self) -> bool:
        return bool(self.safeguarding_team)

    @property
    def dual_role_team(self) -> list[Researcher]:
        return [r for r in self.team if r.dual_role]

    @property
    def dual_role(self) -> bool:
        return bool(self.dual_role_team)

    @property
    def study_phases(self) -> list[Phase]:
        """The procedures participants are recruited for (without the automatic pre-screening survey)."""
        return [ph for ph in self.phases if not ph.screening]

    @property
    def collect_abroad(self) -> bool:
        """Any data collected outside the UK (D3): set per study procedure."""
        return any(ph.outside_uk for ph in self.phases)

    @property
    def withdrawal(self) -> str:
        """E.g. '4 weeks', '5 working days', '1 week'."""
        unit = self.withdrawal_unit
        if self.withdrawal_amount == 1:
            unit = unit.removesuffix("s")
        return f"{self.withdrawal_amount} {unit}"


def load_library() -> dict:
    """Load all YAML files in library/ into {filename_stem: content}."""
    return {f.stem: yaml.safe_load(f.read_text(encoding="utf-8")) for f in LIBRARY_DIR.glob("*.yaml")}


def sync_screening(data: dict) -> bool:
    """Add, update or remove the automatic 'Pre-screening survey' procedure in a project dict (in place).

    Chosen items that are uploaded files become the procedure's materials, the rest are questionnaire keys.
    Returns True if a procedure was added or removed (procedure widgets then need re-binding in the app).
    """
    phases = data.setdefault("phases", [])
    existing = next((ph for ph in phases if ph.get("screening")), None)
    if data.get("screening_method") != "survey":
        if existing is not None:
            phases.remove(existing)
        return existing is not None
    uploaded = set(data.get("custom_tools", [])) | {t for ph in phases for t in ph.get("custom_tools", [])}
    chosen = data.get("screening_survey", [])
    added = existing is None
    if added:
        existing = Phase(name=SCREENING_PHASE, location="online", duration_min=5, methods=["survey"],
                         screening=True).model_dump()
        phases.insert(0, existing)
    existing["instruments"] = [c for c in chosen if c not in uploaded]
    existing["custom_tools"] = [c for c in chosen if c in uploaded]
    return added


def with_project_instruments(p: Project, lib: dict) -> dict:
    """The library plus the project's own questionnaires (the project's version wins on a clash)."""
    if not p.custom_instruments:
        return lib
    own = {k: i.model_dump(exclude_defaults=True) | {"name": i.name} for k, i in p.custom_instruments.items()}
    return {**lib, "instruments": {**lib["instruments"], **own}}


def instrument_key(name: str, taken) -> str:
    """Short unique key from a name: 'Player Identification Scale (PIS)' -> 'pis'."""
    short = name.rsplit("(", 1)[-1].rstrip(") ") if "(" in name else name
    base = re.sub(r"[^a-z0-9]+", "_", short.lower()).strip("_")[:30] or "questionnaire"
    key, n = base, 2
    while key in taken:
        key, n = f"{base}_{n}", n + 1
    return key


def add_to_library(key: str, instrument: Instrument):
    """Append a questionnaire to library/instruments.yaml (appending keeps the file's comments)."""
    path = LIBRARY_DIR / "instruments.yaml"
    entry = yaml.safe_dump({key: instrument.model_dump(exclude_defaults=True) | {"name": instrument.name}},
                           sort_keys=False, allow_unicode=True)
    text = path.read_text(encoding="utf-8")
    path.write_text(text.rstrip("\n") + "\n" + entry, encoding="utf-8")


def load_project(path) -> Project:
    return Project.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def dump_project(p: Project) -> str:
    return yaml.safe_dump(p.model_dump(), sort_keys=False, allow_unicode=True)
