# UCL Ethics Builder – project memory

Everything needed to pick this project up again: what it is, how it is built, what was decided and why,
what we know about the ethics@ucl form, and what is still open. Last updated: 20 November 2026.

---

## 1. What the tool does

A Streamlit app that helps UCL researchers write a research ethics application for **ethics@ucl**:

- Researchers enter the facts of their study **once** (team, procedures, population, risks, data, pay).
- The tool **derives** everything that follows from those facts (risk level, B2 ticks, exclusions,
  special category data, pay per procedure, …).
- It **generates** the form answers from approved wording, plus an information sheet, consent form and
  debrief (`.docx`).
- It **asks directly** only the form questions it cannot derive (129 questions, shown only when they apply),
  and **pre-fills** suggestions where it can.
- Optionally it **fills a draft in ethics@ucl** through the user's own Chrome. It **never submits or signs**.

Status: working prototype, **326 tests passing** (`pytest`). Not yet in its own git repository (see §10).

---

## 2. Running it

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py          # http://localhost:8501
pytest                        # all tests (~30 s)
```

Known-good versions (Python 3.14.3): streamlit 1.67.0, pydantic 2.14.4, Jinja2 3.1.6, PyYAML 6.0.3,
python-docx 1.2.0, pytest 9.2.0, playwright 1.65.2. `requirements.txt` is not pinned yet; pin these when
creating the repository.

Other entry points:

| Command | What it does |
|---|---|
| `python -m filler.browser --launch` | Opens a separate Chrome (profile in `.chrome-profile/`, debug port 9222) for ethics@ucl; log in once |
| `python -m filler.fill project.yaml --new` / `--project 6677` | Fills a new / existing ethics@ucl draft, saves each page, never submits |
| `python -m filler.inventory 6687` | Read-only crawl of all form questions and rules from a draft → `filler/form_inventory.json`, `docs/form_inventory.md` |
| `python -m filler.inventory --docs` | Rebuilds `docs/form_inventory.md` from the JSON (no browser) |
| `ETHICS_HOSTED=1` (env var) | Hosted mode for colleagues: no filler, no writing to the shared library, "test version" notice |
| `host_devtunnel.ps1` | Starts the app in hosted mode on localhost and hosts the Dev Tunnel (see §9) |

**Restart Streamlit after editing Python modules other than `app.py`.** Once a changed `suggest.py` was not
reloaded and the running app crashed with `TemplateNotFound` although the code on disk was correct.

---

## 3. Architecture

Data flow:

```
app.py (UI, input only)  ──or──  project .yaml / examples/*.yaml
        │
        ▼
model.py  Project            ← every fact entered once (single source of truth)
        │
        ├─► rules.py  derive(p, lib) = "d"; form_choices() = every tick-box answer in ethics@ucl terms
        │       ▲
        │       └─ library/*.yaml          ← approved wording, flags, options (no code)
        ├─► questions.py  applicable()     ← library/questions.yaml + suggest.py (pre-fills)
        ▼
render.py + templating.py  →  templates/form/*.j2 (answers), templates/docs/*.j2 (documents)
        │
        ├─► checks.py        missing fields, unanswered questions, [placeholders]
        └─► filler/          answers.build_plan() → fill.py (Playwright) → ethics@ucl draft
```

### Files

| File | Job |
|---|---|
| `model.py` | `Project`, `Phase` (study procedure), `Researcher`, `Instrument`; constants (`PROJECT_TYPES`, `DATA_SOURCES`, `SCREENING_METHODS`, …); `sync_screening()`; migration of old project files; `load_library()`, `add_to_library()` |
| `rules.py` | `derive()` (all derived facts), `risk_flags()`, `compensation()`, `special_category()`, `b2_ticks()`, `form_choices()` |
| `questions.py` | Which questions from `library/questions.yaml` apply (conditions in the form's own terms), and their answer (user → suggestion → YAML default) |
| `suggest.py` | Suggested answers worked out from the project (tick boxes in code, text in `templates/suggest/*.j2`) |
| `templating.py` | Shared Jinja environment and filters |
| `render.py` | `QUESTIONS` (generated answers in form order), `DOCUMENTS`, Markdown → `.docx` |
| `checks.py` | `check_project()`, `check_questions()`, `check_placeholders()` |
| `app.py` | Streamlit UI (7 steps). `bind()` ties widgets to paths in the project dict; `ask(step)` renders the applicable questions of a step |
| `library/methods.yaml` | Methods: D2 tick, description, data types, exclusions, risks |
| `library/instruments.yaml` | Standardised questionnaires (`health`, `sensitive`, `warning`) |
| `library/locations.yaml` | Where procedures happen (`in_person`, `permission`, risks, D4 wording) |
| `library/populations.yaml` | Participant groups (`vulnerable`, `borderline`, notes, mitigations) |
| `library/channels.yaml` | Recruitment channels (E4) |
| `library/considerations.yaml` | "Other ethical issues" (I10) added when `when:` matches `rules.facts()` |
| `library/questions.yaml` | 129 questions asked directly, in 19 sections, with exact form options, `when` rules and hints |
| `templates/form/*.j2` | One template per generated answer (38 files, e.g. `E2_2.j2` = E2.2) |
| `templates/suggest/*.j2` | Pre-fill wording for D3.1, D3.3, I2.1, I4, I4.2, I5, I5.1, I7.1, J6 |
| `templates/docs/*.md.j2` | Information sheet, consent form, debrief |
| `filler/browser.py` | Chrome connection + **two independent no-submit guards** (click guard, network guard) |
| `filler/fill.py` | Draft creation, page walking, filling, saving (Save is in the "More" menu since late 2026) |
| `filler/answers.py` | `build_plan()`: ordered (question, kind, value) actions; `MANUAL` list |
| `filler/inventory.py` | Read-only form crawler (see §6) |
| `examples/*.yaml` | Three approved applications as tool input: `gaze`, `grimdark`, `meet` |
| `tests/` | `test_generate.py` (rules/templates), `test_app.py` (UI via `AppTest`), `test_questions.py` (YAML vs. real form, conditions, suggestions), `test_inventory.py` (crawler parser), `test_guard.py` (no-submit guards) |

### How to change things (no code needed for most)

- **New method / questionnaire / location / population:** add an entry to the matching `library/*.yaml`.
  Questionnaires can also be added in the app (step 3, "Add a questionnaire that isn't listed"); they are
  stored in the project (`custom_instruments`) and optionally appended to `library/instruments.yaml`.
- **Wording of a generated answer:** `templates/form/<ID>.j2`. **Wording of a suggestion:** `templates/suggest/<ID>.j2`.
- **Ask another form question:** add it to `library/questions.yaml` (copy text/options from
  `docs/form_inventory.md`). `tests/test_questions.py` checks every entry and condition against the real form.
- **Order of fields in a procedure card:** `app.py`, block "3. Study procedures" (commented parts 1–4).
  **Order of the extra question sections:** order of `sections:` / `questions:` in `library/questions.yaml`
  (follow-ups must stay after the question they depend on).

---

## 4. The app (7 steps)

1. **Screening & project**: classification A1–A4 (project type, UCL sponsor, NHS/MoD review, existing approval);
   type of research B1 (pills: new data, existing data, human tissue, other issues) + follow-ups;
   the project (title C1, aims D1, benefits I1); project details (dates, related ethics ID, funding) + C4–C6.
2. **Research team**: person cards (PI exclusive, external collaborators, safeguarding role, dual role).
3. **Study procedures**: one card per procedure. Header = procedure name as title, Rename / Duplicate /
   Delete top right. Then methods → method details (questionnaires, add questionnaire, uploads) →
   duration + location (+ venue, "outside the UK" tick) → sample size. Below: D2/D3/D4/G/F sections.
   The automatic "Pre-screening survey" procedure is shown read-only.
4. **Population**: groups, ages, inclusion/exclusion, **How eligibility is checked (E2.2)** dropdown
   (pre-screening survey / participants confirm themselves / another technique), demographics, channels,
   decision time, consent (E8) and under-16 (E9) sections.
5. **Risk check**: B2 items that cannot be derived, derived risk level and flags, I-sections and H.
6. **Data protection & pay**: pay per procedure, data protection, dissemination, J6.
7. **Generate**: issues to fix, downloads (answers `.md`, documents `.docx`), filler panel (local only),
   all answers and documents.

Sidebar: New project, Load project (popover with uploader; accepts `.yaml`, `.yml`, `.txt` because Chrome on
Windows may save downloads as `.yaml.txt`), Save project (filled at the end of each run so it contains the
latest edit; file named after the title).

---

## 5. Key design decisions (and why)

- **Single source of truth.** Every fact is entered once in `Project`; all answers and documents read it.
- **Wording lives in YAML/Jinja, logic in plain Python.** Researchers can maintain wording without code.
- **Conditions use the form's own terms.** `library/questions.yaml` says e.g. `F4.1 when F4 = Yes`; the
  derived answers come from `rules.form_choices()`, so the tool follows ethics@ucl's own branching.
- **Suggestions are never stored.** They are recomputed and follow project changes until the user edits them
  (then the user's text is stored in `Project.answers`). `[brackets]` mark what only the researcher can write;
  the Generate step lists remaining placeholders.
- **Safety of the filler.** It only clicks Save; a click guard refuses buttons mentioning submit/sign/
  declaration/lock/delete/transfer…; a network guard blocks such requests and never opens the Declarations &
  Signatures page (`/1604/`). Attestation boxes ("I confirm…", "I have read…") are never ticked; the commitment
  questions I9.3, I9.8, I9.11 are asked (they open follow-ups) but marked `manual`.
- **Screening (E2.2) is structured.** A dropdown chooses the technique; "pre-screening survey" automatically
  creates an unpaid "Pre-screening survey" procedure (no sample size, excluded from pay/E1/"several activities"
  wording) via `sync_screening()`; E2.2 is generated from this choice (no separate text field).
- **"Outside the UK" is set per procedure**; `Project.collect_abroad` is derived. D3 questions appear only then.
  Old files with project-wide `collect_abroad` are migrated (online procedures, else all).
- **Tool choices that differ from the real form** (documented in `questions.yaml`): D2.6 only after D2.4 = Yes;
  A3.2 / B1.4 / F-subsections keyed on the answer that leads there instead of attestation boxes.
- **Hosted mode** hides the filler and library writes, because both act on the host machine.

---

## 6. What we know about the ethics@ucl form

Collected with `filler/inventory.py` from the test draft **6687** ("TEST - question inventory (do not submit)",
owned by the user; contains test answers on pages A/B; not submitted; can be deleted).

- **208 numbered questions on 20 pages** (page IDs 1597–1617; 1604 = Declarations & Signatures, never opened;
  1618+ belong to the amendment form). All follow-up questions are in each page's HTML (only hidden).
- **160 branching rules** are embedded per page (`var dependencies` / `var groups` JSON); option values are the
  inputs' `data-bitvalue`.
- **Whole sections are switched on by the server** from answers on pages A/B (not in the HTML). Mapping used by
  the tool (plausible, **not verified** on the live form): B1 human tissue → F; B1 existing data → G;
  B1.2 under 16 → E9; B2 boxes → I4–I9 and H.
- **UI changes seen:** Save moved into the "More" menu (`#more-actions-btn`); changing an answer that removes
  follow-ups opens a "Dependencies Warning" dialog (`#proceedDependencies`).
- Coverage analysis (see `docs/form_inventory.md`): ~half of the form can be derived or generated; ~73 questions
  need the researcher's own writing (guided by hints/suggestions); ~30 stay manual (15 uploads, attestations,
  insurance, DP registration number, people pickers, travel advice).

---

## 7. Change log (this build session)

1. Explained the structure; found the project is not tracked in git.
2. **Load project fixed**: accept `.txt` downloads, save contains the latest edit, file named after title,
   readable error for broken files.
3. Removed "Load example"; Load/Save/New are matching sidebar controls (examples are loaded as files).
4. **User-added questionnaires** (project + optional shared library), included in all rules and checks.
5. **Form inventory crawler** (read-only) and `docs/form_inventory.md`; fixed filler Save for the "More" menu.
6. Analysis: which questions can be automated vs. hand-written.
7. **129 direct questions** (`library/questions.yaml`, `questions.py`), screening fields A1–A4/B1,
   `Project.answers`, checks for unanswered questions, filler plan for all of them.
8. Page 1 = screening & project (title, aims, benefits, dates, funding); page 2 = team only.
9. D2.6 only after D2.4; per-procedure "outside the UK" flag; D3 from it.
10. **Suggestions** (`suggest.py`, `templates/suggest/`): D3.2, C6, I6.1, E9 tick boxes; D3.1, D3.3, I2.1,
    I4, I4.2, I5, I5.1, I7.1, J6 text; J1.3.1 reuses the J1.1 number.
11. **Structured screening (E2.2)**: dropdown, pre-screening survey → automatic procedure, own technique;
    examples carry their approved E2.2 wording (from the PDFs) as "another technique".
12. Procedure card redesign (title header, actions top right, new field order).
13. **Hosted mode** + Dev Tunnel attempt (see §9).

---

## 8. Open issues and next steps

**Content (from the four clinical psychology / BDD applications added to `Example_Ethics/`):**
They all went to high-risk review (LMS REC) and argued via **I5 sensitivity**, not I4 vulnerability; I5.1 uses
recurring blocks (forewarning, skip/exit, named support services incl. BDD Foundation and SHOUT, researcher
contact, wellbeing call, graded risk protocol serious-vs-imminent + separate Risk and Distress Management
Protocol, no therapeutic misconception, reflexivity, "benefits outweigh risks" sentence). Proposed (not done):
1. Rewrite `templates/suggest/I5*.j2` and `I7_1.j2` with these approved patterns.
2. Population-specific support services (`library/support.yaml`) used by debrief and I5.1.
3. Clinical populations: add approved mitigations; **decide** whether they tick B2 Vulnerability (I4) or argue
   via Sensitivity (I5) like the approved applications.
4. Pre-screening option: confirmation call + supportive message with signposting for ineligible people.
5. Clinical questionnaires: BDD-5, BDD-YBOCS, PHQ-2, GAD-2, Mini-SPIN, BIQ, AAI.
6. "How approved applications answered this" panel per question (corpus from the 7 PDFs; names of colleagues →
   keep local or anonymise).
7. A fourth example project (iCBT feasibility trial).

**Other gaps:**
- Student projects: supervisor page (1600), course and student number are not asked.
- Section H covers one product (the form repeats it per product).
- Wording written by Claude (not from approved applications) needs review: `templates/suggest/*.j2`, in
  particular I2.1 ("UCL Employee Assistance Programme"), I7.1 ("UCL's safeguarding policy"), J6 ("CC BY 4.0").
- Section-level conditions (§6) are unverified on the live form.
- `requirements.txt` is unpinned; `examples/ethics_project.yaml` is an empty saved project (probably a test
  save) – delete or keep deliberately.

---

## 9. Hosting for colleagues (status)

- **Hosted mode** works (`ETHICS_HOSTED=1`, tested).
- **Dev Tunnel** `ucl-ethics-builder` (region eun1) was created by the user: port 8501/http, access = Entra
  tenant only (no anonymous), URL `https://k97fs1hj-8501.eun1.devtunnels.ms/`, **expires after 7 days**
  (recreate with the commands in `host_devtunnel.ps1`).
- **Problem: HTTP 431 after the Microsoft sign-in**, also in private windows. Diagnosis: the tunnel works end to
  end with a connect token (HTTP 200 from the app) and the local app accepts headers up to ~48 KB, so the error
  comes from the Dev Tunnels relay after sign-in – most likely the UCL sign-in cookie is too large (many group
  claims). Not fixed.
- Options: **A** share on the UCL network/VPN (`--server.address 0.0.0.0` + firewall rule; quick, no login);
  **B** tunnel with GitHub organisation access (`devtunnel access create … --org <org>`); **C** anonymous tunnel +
  Streamlit `st.login` with UCL Entra (needs an ISD app registration); **D** Streamlit Community Cloud (private
  repo, email invites; US hosting → test data only). Not recommended: anonymous tunnel without login.
- Long-term: container in UCL Azure (UK South) or a UCL VM with Entra sign-in (ask ISD / UCL ARC). Check UCL IT
  policy and Information Security before exposing the app.
- Streamlit binds all interfaces by default; use `--server.address localhost` unless sharing deliberately.

---

## 10. Moving into its own repository

Currently `C:\GIT` is the git root (a large mixed repository) and **none of this project's files are tracked**.

1. Copy `C:\GIT\ucl_ethicsbuilder` to the new location (or `git init` inside it).
2. Check `.gitignore` – it excludes: `.venv/`, `__pycache__/`, `.pytest_cache/`, `.chrome-profile/`
   (~950 MB browser profile with ethics@ucl session cookies), `filler/form_map_raw.json`, `Example_Ethics/`
   (colleagues' real applications with names), `.idea/`, Office lock files `~$*`.
3. **Do not commit** the real applications (`Example_Ethics/`), browser profiles, or saved projects with real
   personal data. `examples/*.yaml` contain the names and UCL emails of the original applicants
   (e.g. the PI of the Gaze study) – anonymise them before making a repository public.
4. `filler/form_inventory.json` and `docs/form_inventory.md` contain only form text – fine to commit; they
   drive `tests/test_questions.py`.
5. Pin `requirements.txt` (versions in §2), recreate the venv, run `pytest` (expect 326 passed).
6. Optional: add a `CLAUDE.md` with the "how to change things" rules from §3 for future AI-assisted work.
