# UCL Ethics Builder

Fill in the parts of a UCL ethics application that change; generate the generic parts
(answers for ethics@ucl, information sheet, consent form, debrief) from approved wording.

## Run locally (Windows / PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py        # opens http://localhost:8501
pytest                      # run the tests
```

Use **Save project** to download your inputs as `.yaml` and **Load project** to continue later.
To see a full application, use **Load project** with one of the files in `examples/`.

## How it is organised

| File | Job |
|---|---|
| `model.py` | `Project` – every fact entered once (single source of truth) |
| `library/methods.yaml` | Method descriptions, data types, exclusions, risks (D2, D2.1, J2, I1.1) |
| `library/instruments.yaml` | Standardised questionnaires with references and sensitivity flags |
| `library/locations.yaml` | Online / lab / community venue / event / workplace wording and permissions (D4, D4.1) |
| `library/populations.yaml` | Participant groups; `vulnerable` → high risk, `borderline` → justification in I1.1 |
| `library/channels.yaml` | Recruitment channels (E4) |
| `library/considerations.yaml` | "Other ethical issues" (I10) added automatically when their `when:` conditions match |
| `rules.py` | Derived facts: risk level, exclusions, data types, special category data, pay; `form_choices()` = every tick-box answer in ethics@ucl terms |
| `library/questions.yaml` | Questions the tool asks directly (129, by form number), grouped in sections, each with the form's exact options, a `when` condition and a writing hint |
| `questions.py` | Which of those questions apply to a project, and their answers (stored in `Project.answers`) |
| `suggest.py`, `templates/suggest/*.j2` | Suggested answers worked out from the project (e.g. D3.2 travel, C6, D3.1, I4–I7, J6); pre-filled in the app and kept up to date until the user edits them. `[brackets]` mark what only the researcher can write |
| `templates/form/*.j2` | One template per ethics@ucl question |
| `templates/docs/*.j2` | Information sheet, consent form, debrief |
| `templating.py` | Shared Jinja environment and filters |
| `render.py` | Templates → text and `.docx` |
| `checks.py` | Missing fields, unanswered questions that apply, and unfilled `[placeholders]` |
| `filler/inventory.py` | Read-only crawl of all form questions and rules → `filler/form_inventory.json`, `docs/form_inventory.md` |
| `app.py` | Streamlit UI (7 steps: screening & project first, then the research team); input only, no logic. Questions from `questions.yaml` appear at the end of their step when they apply |
| `examples/*.yaml` | The three approved applications (eye tracking, Grimdark, M.E.E.T.) as tool input |

**Add a new method or questionnaire:** add an entry to `library/methods.yaml` or
`library/instruments.yaml`. No code change needed.
Questionnaires can also be added in the app (**2. Study procedures → ➕ Add a questionnaire that isn't listed**).
They are always stored in the project file (`custom_instruments`), and by default also appended to
`library/instruments.yaml` so every future project can pick them. Review and commit that file to share them.
**Change the wording of an answer:** edit the matching file in `templates/form/`.
**Ask another form question:** add it to `library/questions.yaml` (copy text and options from `docs/form_inventory.md`); `tests/test_questions.py` checks it against the real form.

## Fill a draft in ethics@ucl (local only)

```powershell
python -m filler.browser --launch                      # opens Chrome; log in to ethics@ucl once
python -m filler.fill my_project.yaml --new            # create a draft and fill it
python -m filler.fill my_project.yaml --project 6677   # fill an existing draft
```

Or use **6. Generate → Fill a draft in ethics@ucl automatically** in the app.

**It never submits.** Two independent guards in `filler/browser.py` (covered by `tests/test_guard.py`):
- the click guard refuses buttons mentioning submit, sign, declaration, lock, delete, transfer...;
- the network guard blocks any write request whose URL or field names mention those words, and any
  request to the Declarations & Signatures page. The filler only ever clicks *Save*.

Attestation boxes ("I confirm...") are never ticked, and existing text is kept unless `--overwrite`.
Team members (C7.1/C8.1), uploads, overseas details (D3.x) and insurance (I11) stay manual.
