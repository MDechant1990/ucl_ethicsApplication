"""Collect every question of the ethics@ucl form (including hidden follow-ups) from a draft. READ-ONLY.

Usage (Chrome started with `python -m filler.browser --launch` and logged in):
    python -m filler.inventory 6687                 # any draft number you own
    python -m filler.inventory --docs               # only rebuild docs/form_inventory.md from the JSON

Each form page contains all of its questions in the HTML (follow-ups are only hidden) plus the
branching rules as JSON (`var dependencies = ...`). So nothing has to be answered: the script opens each
page with the network guard in read-only mode (every non-GET request is blocked) and reads the DOM.
The Declarations & Signatures page is never opened.

Writes filler/form_inventory.json (structured) and docs/form_inventory.md (readable, with app coverage).
"""
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from filler.browser import SIGNATURE_PAGE, connect, guard_network

BASE = "https://ethics.ucl.ac.uk"
PAGE_RANGE = range(1597, 1618)  # application pages; 1618+ belong to the amendment form, 1604 is the signature page
ROOT = Path(__file__).parent.parent
QNUM = re.compile(r"^([A-L]\d+(?:\.\d+)*[a-z]?)\)\s*(.*)$", re.S)

# Runs in the page: one entry per question row, visible or hidden.
ROWS_JS = r"""() => {
  const txt = e => (e ? e.textContent : '').replace(/\s+/g, ' ').trim();
  const shown = e => { for (; e && e !== document.body; e = e.parentElement)
                         if (getComputedStyle(e).display === 'none') return false; return true; };
  return [...document.querySelectorAll('div.panel div.row')].map(row => {
    const panel = row.closest('div.panel');
    const help = panel.querySelector(':scope > button[aria-label]');
    // Question texts and inputs in page order (option labels, i.e. label[for], belong to their input).
    const items = [...row.querySelectorAll(
        'label.label:not([for]), span.label, input:not([type=hidden]), textarea, select')].map(e =>
      e.matches('label, span') ? {text: txt(e)} : {
        type: e.tagName === 'INPUT' ? e.type : e.tagName.toLowerCase(),
        label: txt(document.querySelector(`label[for="${CSS.escape(e.id)}"]`)),
        bit: e.dataset.bitvalue || null,
        options: e.tagName === 'SELECT' ? [...e.options].filter(o => o.value && txt(o) !== 'Please Select...')
                                       .map(o => ({label: txt(o), value: o.value})) : null,
      }).filter(i => i.text !== '' && i.label !== 'Search');
    return {
      question_id: row.dataset.id, panel_id: panel.dataset.id, items,
      help: help ? help.getAttribute('aria-label').replace(/\s+/g, ' ').trim() : '',
      mandatory: panel.dataset.mandatory === 'True',
      repeatable: Number(panel.dataset.maxinstancecount || 1) > 1,
      visible_now: shown(row),
    };
  });
}"""


def _json_var(html: str, name: str) -> list:
    m = re.search(rf"var {name} = JSON\.parse\('(.*?)'\);", html, re.S)
    return json.loads(m.group(1).encode().decode("unicode_escape")) if m else []


def dependencies(html: str) -> list[dict]:
    """Branching rules of a page: `dependencies` (same page) plus `groups`, whose contracts also cover
    questions/pages that depend on answers given on OTHER pages (OnPage: false), e.g. section F on B1."""
    rules = _json_var(html, "dependencies")
    for g in _json_var(html, "groups"):
        for c in g.get("Contracts") or []:
            rules.append({"SourceQuestionId": c.get("SourceQuestionId"), "TargetQuestionId": c.get("DependentQuestionId"),
                          "TargetPanelId": c.get("DependentPanelId"), "ConditionTrueJson": c.get("RequiredValuesJson"),
                          "AndGroupId": c.get("AndId"), "DependencyActionId": c.get("Action"),
                          "DependencyOperatorId": c.get("Operator")})
    return rules


def page_name(page, pid) -> str:
    for sel in [f"a[href^='/Project/Page/{pid}/']", "h2", "h3"]:     # nav link (listed pages), else heading
        for loc in page.locator(sel).all():
            t = loc.inner_text().strip()
            if t and t.lower() != "help":
                return t.splitlines()[0][:80]
    return ""


def questions(row: dict) -> list[dict]:
    """Split a row into questions: every 'A2.2)' label starts a new one (some rows hold several)."""
    parts = [{"number": "", "text": [], "inputs": []}]
    for it in row["items"]:
        if "text" in it:
            m = QNUM.match(it["text"])
            if m:
                if parts[-1]["number"] or parts[-1]["inputs"]:
                    parts.append({"number": "", "text": [], "inputs": []})
                parts[-1]["number"] = m.group(1)
                if m.group(2):
                    parts[-1]["text"].append(m.group(2))
            else:
                parts[-1]["text"].append(it["text"])
        else:
            parts[-1]["inputs"].append(it)
    out = []
    for n, part in enumerate(parts):
        text = " ".join(dict.fromkeys(part["text"]))
        inputs = part["inputs"]
        help_ = row["help"] if n == 0 else ""
        if help_ and (help_[:60] in text or text[:60] in help_):   # info button that only repeats the question
            help_ = ""
        out.append({
            "number": part["number"], "text": text, "kinds": sorted({i["type"] for i in inputs}),
            "options": [{"label": i["label"], "bit": i["bit"]} for i in inputs
                        if i["type"] in ("radio", "checkbox") and i["label"]]
                       + [{"label": o["label"], "bit": o["value"]} for i in inputs if i["options"] for o in i["options"]],
            "n_text_boxes": sum(i["type"] in ("text", "textarea", "date", "number", "email") for i in inputs),
            "help": help_, **{k: row[k] for k in ("question_id", "panel_id", "mandatory", "repeatable", "visible_now")}})
    return out


def collect(draft: str, log=print) -> dict:
    pages, deps = {}, []
    with sync_playwright() as pw:
        _, _, page = connect(pw)
        blocked = guard_network(page, read_only=True)
        try:
            for pid in PAGE_RANGE:
                if f"/{pid}/" == SIGNATURE_PAGE:
                    continue
                page.goto(f"{BASE}/Project/Page/{pid}/{draft}")
                page.wait_for_load_state("networkidle")
                rows = page.evaluate(ROWS_JS)
                if not rows:
                    continue
                qs = [q for r in rows for q in questions(r)]
                pages[str(pid)] = {"name": page_name(page, pid), "questions": qs}
                deps += [dict(d, page=str(pid)) for d in dependencies(page.content())]
                log(f"page {pid}: {len(qs)} rows, {sum(1 for q in qs if q['number'])} numbered, "
                    f"{sum(1 for q in qs if not q['visible_now'])} hidden")
        finally:
            page.unroute("**/*")
    if blocked:
        log(f"Blocked requests (expected none): {blocked}")
    return {"draft": draft, "pages": pages, "dependencies": resolve(pages, deps)}


def resolve(pages: dict, deps: list[dict]) -> list[dict]:
    """Turn id-based rules into 'B2 shown when A1 = option X' with question numbers and option labels."""
    by_q: dict[str, list] = {}                     # row id -> its questions (first one carries the options)
    for p in pages.values():
        for q in p["questions"]:
            by_q.setdefault(q["question_id"], []).append(q)
    by_panel: dict[str, list] = {}
    for p in pages.values():
        for q in p["questions"]:
            by_panel.setdefault(q["panel_id"], []).append(q)
    out, seen = [], set()
    for d in deps:
        src = next((q for q in by_q.get(d.get("SourceQuestionId"), []) if q["options"]), None)
        targets = (by_q[d["TargetQuestionId"]] if d.get("TargetQuestionId") in by_q
                   else by_panel.get(d.get("TargetPanelId"), []))
        bits = [str(b) for b in json.loads(d.get("ConditionTrueJson") or "[]")]
        when = [o["label"] for o in (src or {}).get("options", []) if o["bit"] in bits] or bits
        for t in targets:
            rule = (t["question_id"], t["number"], src["question_id"] if src else d.get("SourceQuestionId"),
                    tuple(when), d.get("AndGroupId"))
            if rule in seen:
                continue
            seen.add(rule)
            out.append({"target": t["number"] or t["text"][:60], "target_id": t["question_id"],
                        "target_number": t["number"],
                        "source": (src["number"] or src["text"][:60]) if src else "?", "when": when,
                        "and_group": d.get("AndGroupId"), "action": d.get("DependencyActionId"),
                        "operator": d.get("DependencyOperatorId")})
    return out


def coverage() -> tuple[set, set, set]:
    """Question numbers the app generates text for, the filler fills, and the filler leaves manual."""
    from filler.answers import MANUAL, build_plan
    from model import load_library, load_project
    from render import QUESTIONS
    rendered = set()
    for qid, _, _ in QUESTIONS:
        if m := re.fullmatch(r"([A-L])(\d+)–[A-L](\d+)", qid):       # "C1–C6" -> C1 … C6
            rendered |= {f"{m[1]}{n}" for n in range(int(m[2]), int(m[3]) + 1)}
        else:
            rendered |= set(qid.split("/"))
    filled = {q.rstrip(")") for q, _, _ in build_plan(load_project(ROOT / "examples" / "meet.yaml"), load_library())}
    manual = {x for m in MANUAL for x in re.findall(r"[A-L]\d+(?:\.\d+)*(?:\.x)?", m)}
    return rendered, filled, manual


def markdown(inv: dict) -> str:
    rendered, filled, manual = coverage()
    rules: dict[str, list] = {}
    for d in inv["dependencies"]:
        rules.setdefault((d["target_id"], d["target_number"]), []).append(d)

    # Server-side section switches measured by filler/explore.py (optional).
    tpath = Path(__file__).parent / "form_triggers.json"
    triggers = json.loads(tpath.read_text(encoding="utf-8")) if tpath.exists() else None
    always = ({q for qs in triggers["baseline"]["questions"].values() for q in qs} if triggers else set())
    unlocked_by: dict[str, list] = {}
    for name, s in (triggers or {}).get("scenarios", {}).items():
        for n in s["unlocks"]:
            unlocked_by.setdefault(n, []).append(name)

    def shown_when(q):
        rs = rules.get((q["question_id"], q["number"]), [])
        groups: dict = {}
        for r in rs:
            groups.setdefault(r["and_group"], []).append(f"{r['source']} = {' / '.join(r['when'])}")
        parts = [" **or** ".join(" and ".join(g) for g in groups.values())] if groups else []
        n = q["number"]
        if triggers and n and not groups:
            if n in always:
                parts.append("always")
            elif n in unlocked_by:
                parts.append("*section:* " + "; ".join(unlocked_by[n]))
            elif not q["visible_now"]:
                parts.append("*not reached by the explored A/B answers*")
        return " · ".join(parts)

    def status(num):
        if not num:
            return ""
        if num in filled:
            return "auto-filled"
        if num in rendered:
            return "text generated"
        if num in manual or any(m.endswith(".x") and num.startswith(m[:-2]) for m in manual):
            return "manual (listed)"
        return "**not covered**"

    lines = [f"# ethics@ucl form inventory", "",
             f"Collected read-only from draft {inv['draft']} with `python -m filler.inventory {inv['draft']}`.",
             "Hidden questions are shown only when the condition in *Shown when* is met.", ""]
    total = [q for p in inv["pages"].values() for q in p["questions"] if q["number"]]
    nc = [q["number"] for q in total if status(q["number"]) == "**not covered**"]
    lines += [f"**{len(total)} numbered questions** on {len(inv['pages'])} pages; "
              f"{sum(status(q['number']) == 'auto-filled' for q in total)} auto-filled, "
              f"{sum(status(q['number']) == 'text generated' for q in total)} with generated text only, "
              f"{len(nc)} not covered by the app.", ""]
    if triggers:
        names = {pid: p["name"] for pid, p in inv["pages"].items()}
        lines += ["## Sections switched on by answers on pages A/B", "",
                  f"Measured with `python -m filler.explore {triggers['draft']}`: baseline = "
                  "staff project, UCL sponsor, no NHS/existing approval, new data collection only, no one under 16, "
                  "B2 'None of the above'. Each row changes one answer.", "",
                  "| Answer | New pages | Questions that appear | Questions that disappear |", "|---|---|---|---|"]
        for name, s in triggers["scenarios"].items():
            pages_ = ", ".join(f"{names.get(x, x)} ({x})" for x in s["new_pages"])
            if s.get("error"):
                pages_ = f"*not measured – {s['error'][:120]}*"
            lines.append(f"| {name} | {pages_} | {', '.join(s['unlocks'])} | {', '.join(s['hides'])} |")
        lines.append("")
    for pid, p in inv["pages"].items():
        lines += [f"## Page {pid}{' – ' + p['name'] if p['name'] else ''}", "",
                  "| # | Question | Answer type | Options | Shown when | App |", "|---|---|---|---|---|---|"]
        for q in p["questions"]:
            if not (q["number"] or q["text"] or q["options"] or q["n_text_boxes"]):
                continue
            kinds = ", ".join(q["kinds"]) + (f" ×{q['n_text_boxes']}" if q["n_text_boxes"] > 1 else "")
            if q["repeatable"]:
                kinds += " (repeatable)"
            opts = "; ".join(o["label"] for o in q["options"])[:400]
            text = q["text"].replace("|", "/")[:500]
            if q["help"] and q["help"] != q["text"]:
                text += f"<br>*Help:* {q['help'].replace('|', '/')[:400]}"
            lines.append(f"| {q['number']} | {text} | {kinds} | {opts.replace('|', '/')} | {shown_when(q)} | "
                         f"{status(q['number'])} |")
        lines.append("")
    return "\n".join(lines)


def main():
    json_path = Path(__file__).parent / "form_inventory.json"
    if sys.argv[1:] == ["--docs"]:                 # rebuild the Markdown from the saved JSON, no browser
        inv = json.loads(json_path.read_text(encoding="utf-8"))
    elif len(sys.argv) == 2 and sys.argv[1].isdigit():
        inv = collect(sys.argv[1])
        json_path.write_text(json.dumps(inv, indent=1, ensure_ascii=False), encoding="utf-8")
    else:
        sys.exit(__doc__)
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "form_inventory.md").write_text(markdown(inv), encoding="utf-8")
    print("Wrote docs/form_inventory.md" + ("" if sys.argv[1] == "--docs" else " and filler/form_inventory.json"))


if __name__ == "__main__":
    main()
