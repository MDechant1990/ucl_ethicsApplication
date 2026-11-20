"""Fill an ethics@ucl DRAFT from a project file. Never submits or signs.

Usage (Chrome started with `python -m filler.browser --launch` and logged in):
    python -m filler.fill examples/gaze.yaml --project 6677      # fill an existing draft
    python -m filler.fill my_project.yaml --new                  # create a new draft, then fill it

Safety:
- network guard (filler/browser.py) blocks submit/sign/lock/delete requests and the signature page;
- only the page "Save" button is clicked, never "Next" into the declarations;
- attestation boxes ("I confirm...", "I have read...") are never ticked;
- fields that already contain text are left alone unless --overwrite is given.
"""
import argparse
import re
import sys

from playwright.sync_api import Page, sync_playwright

from filler.answers import MANUAL, build_plan
from filler.browser import SIGNATURE_PAGE, connect, guard_network, safe_click
from model import load_library, load_project

BASE = "https://ethics.ucl.ac.uk"
SKIP_PAGES = {"1597"}                       # introduction (no questions)
ATTESTATION = re.compile(r"^\s*I (confirm|have read|accept|understand|agree|declare)", re.I)

# Every visible input between a question's number (e.g. "E1)") and the next question's number.
FIELDS_JS = r"""(q) => {
  const isQ = l => /^[A-L]\d+(\.\d+)*\)$/.test(l.textContent.trim());
  const labels = [...document.querySelectorAll('label.label')].filter(isQ);
  const i = labels.findIndex(l => l.textContent.trim() === q);
  if (i < 0) return null;
  const start = labels[i], end = labels[i + 1];
  const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
  if (!vis(start)) return null;
  return [...document.querySelectorAll('input:not([type=hidden]), textarea, select')]
    .filter(e => (start.compareDocumentPosition(e) & 4) && (!end || (end.compareDocumentPosition(e) & 2)))
    .filter(vis)
    .map(e => ({id: e.id, type: e.type,
                label: ((document.querySelector(`label[for="${e.id}"]`) || {}).textContent || '').trim()}));
}"""


def create_draft(page: Page, title: str) -> str:
    page.goto(f"{BASE}/ActivityForm/Index")
    page.wait_for_load_state("networkidle")
    safe_click(page.locator("#createProject"))
    page.locator("#inputProjectTitle").fill(title[:200])
    page.locator("#inputFormId").select_option(label="Research Ethics Application")
    page.wait_for_timeout(1500)
    page.locator("#selectedCentreId").select_option(label="UCL", force=True)
    page.locator("#selectedCentreId").dispatch_event("change")
    safe_click(page.locator("#inputCreateBtn"))
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2500)
    page.goto(f"{BASE}/ActivityForm/Index")
    link = page.locator("a[href^='/Project/Index/']", has_text=title[:60]).first
    return link.get_attribute("href").rsplit("/", 1)[-1]


def page_ids(page: Page, project: str) -> list[str]:
    page.goto(f"{BASE}/Project/Index/{project}")
    page.wait_for_load_state("networkidle")
    hrefs = [a.get_attribute("href") for a in page.locator(f"a[href^='/Project/Page/'][href$='/{project}']").all()]
    ids = [h.split("/")[3] for h in hrefs]
    return [i for i in dict.fromkeys(ids) if i not in SKIP_PAGES and f"/{i}/" != SIGNATURE_PAGE]


def fill_question(page: Page, q: str, kind: str, value, overwrite: bool) -> str:
    fields = page.evaluate(FIELDS_JS, q)
    if not fields:
        return "not on this page"

    def by_id(f):
        return page.locator(f"[id='{f['id']}']")

    if kind in ("radio", "check"):
        done = []
        for text in ([value] if kind == "radio" else value):
            if ATTESTATION.search(text):
                continue
            match = [f for f in fields if f["type"] in ("radio", "checkbox")
                     and f["label"].lower().startswith(text.lower())]
            if not match:
                return f"FAILED: no option starting with '{text}'"
            by_id(match[0]).check()
            done.append(text)
        page.wait_for_timeout(700)                 # follow-up questions appear
        return f"selected {done}"

    boxes = [f for f in fields if f["type"] in ("textarea", "text")]
    values = value if isinstance(value, list) else [value]
    if len(boxes) < len(values):
        return f"FAILED: expected {len(values)} text boxes, found {len(boxes)}"
    filled = 0
    for box, text in zip(boxes, values):
        loc = by_id(box)
        if loc.input_value().strip() and not overwrite:
            continue
        loc.fill(text)
        loc.press("Escape")                        # close date pickers
        loc.dispatch_event("change")
        filled += 1
    return f"filled {filled}/{len(values)} box(es)" if filled else "kept existing text"


def save(page: Page):
    button = page.locator("#save-tile")
    if not button.is_visible():                    # since late 2026, Save sits in the "More" menu
        safe_click(page.locator("#more-actions-btn"))
        button.wait_for(state="visible", timeout=5000)
    safe_click(button)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)


def fill_project(page: Page, project: str, plan, overwrite=False, log=print) -> dict:
    remaining = {q: (kind, v) for q, kind, v in plan}
    done_pages: set[str] = set()
    while True:                                    # later pages appear once A/B are saved
        todo = [pid for pid in page_ids(page, project) if pid not in done_pages]
        if not todo:
            break
        for pid in todo:
            page.goto(f"{BASE}/Project/Page/{pid}/{project}")
            page.wait_for_load_state("networkidle")
            log(f"\n== page {pid}")
            changed = progress = False
            first = True
            while first or progress:               # re-scan: answers can reveal follow-up questions
                first, progress = False, False
                for q in list(remaining):
                    kind, value = remaining[q]
                    try:
                        result = fill_question(page, q, kind, value, overwrite)
                    except Exception as e:         # keep going; report at the end
                        result = f"FAILED: {type(e).__name__}: {str(e).splitlines()[0][:100]}"
                    if result != "not on this page":
                        log(f"  {q:8} {result}")
                        remaining.pop(q)
                        changed = progress = True
            if changed:
                save(page)
            done_pages.add(pid)
    return remaining


def run(project_file, project=None, overwrite=False, log=print) -> str:
    """Fill (or create and fill) a draft. Returns the ethics@ucl project number."""
    lib = load_library()
    proj = load_project(project_file)
    plan = build_plan(proj, lib)
    with sync_playwright() as pw:
        _, _, page = connect(pw)
        blocked = guard_network(page, read_only=False)
        try:
            number = project or create_draft(page, proj.title)
            log(f"Filling draft {BASE}/Project/Index/{number} ({len(plan)} answers)")
            remaining = fill_project(page, number, plan, overwrite, log)
        finally:
            page.unroute("**/*")
        page.goto(f"{BASE}/Project/Index/{number}")
    log("\n== Not filled (question not shown in this draft): " + (", ".join(remaining) or "none"))
    log(f"== Blocked by the safety guard: {blocked or 'nothing'}")
    log("== Please complete yourself:")
    for m in MANUAL:
        log(f"  - {m}")
    log("\nThe draft has NOT been submitted or signed.")
    return number


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project_file")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--project", help="existing ethics@ucl project number (from the URL)")
    g.add_argument("--new", action="store_true", help="create a new draft with the project title")
    ap.add_argument("--overwrite", action="store_true", help="replace text already in the draft")
    args = ap.parse_args()
    run(args.project_file, args.project, args.overwrite)


if __name__ == "__main__":
    sys.exit(main())
