"""Connect to the user's own Chrome (already logged in) and enforce the NO-SUBMIT rules.

Start Chrome once with:  python -m filler.browser --launch
Then log in to https://ethics.ucl.ac.uk/ in that window.

Two independent safety guards:
1. safe_click() refuses any element whose text/label mentions submitting, signing, declarations etc.
2. guard_network() blocks requests; in read-only mode EVERY non-GET request is blocked, and in
   draft mode requests whose URL or body mention forbidden words are blocked.
"""
import re
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = Path(__file__).parent.parent / ".chrome-profile"   # separate profile: Chrome requires it for remote control
PORT = 9222
ETHICS = "https://ethics.ucl.ac.uk/"

FORBIDDEN = re.compile(r"\b(submit\w*|sign|signs|signed|signing|signature\w*|declaration\w*|declare|lock\w*|"
                       r"unlock|approve\w*|delete\w*|withdraw\w*|transfer\w*|reassign\w*)\b", re.I)
SIGNATURE_PAGE = "/1604/"   # "Declarations & Signatures" page: never opened by the filler


def _words(text: str) -> str:
    """Split camelCase / paths so 'SubmitProject' and '/Signatures/Sign' are checked word by word."""
    return re.sub(r"([a-z])([A-Z])", r"\1 \2", re.sub(r"[/_\-?=&.]", " ", text))


def _field_names(body: str) -> str:
    """Only the parameter NAMES of a form post (never the user's text, which may say 'co-design')."""
    return " ".join(part.split("=", 1)[0] for part in body.split("&"))


class Blocked(Exception):
    """Raised when an action would risk submitting or signing."""


def launch_chrome():
    PROFILE.mkdir(exist_ok=True)
    subprocess.Popen([CHROME, f"--remote-debugging-port={PORT}", f"--user-data-dir={PROFILE}", ETHICS])
    print(f"Chrome started. Log in to {ETHICS} in the new window.")


def connect(pw):
    browser = pw.chromium.connect_over_cdp(f"http://localhost:{PORT}")
    context = browser.contexts[0]
    pages = [pg for pg in context.pages if "ethics.ucl.ac.uk" in pg.url]
    return browser, context, (pages[0] if pages else context.new_page())


def guard_network(page: Page, read_only: bool = True):
    blocked = []

    def handle(route):
        req = route.request
        if "ethics.ucl.ac.uk" not in req.url:            # analytics etc.: never needed
            return route.abort() if req.method != "GET" else route.continue_()
        if SIGNATURE_PAGE in req.url:                     # never even open the signature page
            blocked.append(f"{req.method} {req.url}")
            return route.abort()
        if req.method == "GET":                           # reading is always safe
            return route.continue_()
        risky = (FORBIDDEN.search(_words(req.url))
                 or FORBIDDEN.search(_words(_field_names(req.post_data or ""))))
        if risky or read_only:
            blocked.append(f"{req.method} {req.url}")
            return route.abort()
        return route.continue_()

    page.route("**/*", handle)
    return blocked


def safe_click(locator):
    text = " ".join(filter(None, [locator.inner_text(timeout=3000) if locator.count() else "",
                                  locator.get_attribute("value") or "", locator.get_attribute("title") or "",
                                  locator.get_attribute("aria-label") or "", locator.get_attribute("id") or ""]))
    if FORBIDDEN.search(_words(text)):
        raise Blocked(f"Refusing to click '{text.strip()[:80]}'")
    locator.click()


if __name__ == "__main__":
    if "--launch" in sys.argv:
        launch_chrome()
    else:
        with sync_playwright() as pw:
            _, _, page = connect(pw)
            print("Connected:", page.title(), page.url)
