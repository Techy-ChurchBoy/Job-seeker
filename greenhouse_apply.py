"""
Fills Greenhouse application forms for strong matches that have no contact email.

Review mode (default, AUTO_SUBMIT is not "true"): fills the form, takes a screenshot, and sends it to you on
Telegram. Nothing is submitted.
Auto mode (AUTO_SUBMIT=true): also clicks Submit, unless a captcha is shown, then confirms the submission.

Every attempt is recorded in applied_forms.json, so a job is never tried twice.
Needs: playwright (installed by the workflow), GMAIL_ADDRESS, CANDIDATE_NAME, CANDIDATE_PHONE, TELEGRAM_* secrets.
"""
import csv, json, os, re, sys
import requests
from playwright.sync_api import sync_playwright
from send_applications import contact_email, read_cover_letter

MIN_SCORE = 40
MAX_PER_RUN = 5
AUTO = os.getenv("AUTO_SUBMIT", "false").strip().lower() == "true"
NAME = os.getenv("CANDIDATE_NAME", "").strip()
PHONE = os.getenv("CANDIDATE_PHONE", "").strip()
SENDER = os.getenv("GMAIL_ADDRESS", "").strip()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT = os.getenv("TELEGRAM_CHAT_ID", "").strip()
STATE_PATH = "applied_forms.json"
SCREEN_DIR = "applications/screens"
GREENHOUSE = re.compile(r"^https?://(job-)?boards\.greenhouse\.io/")


def fill_placeholders(text):
    return (text.replace("[FULL NAME]", NAME).replace("[PHONE]", PHONE)
                .replace("[EMAIL]", SENDER).replace("[LOCATION]", "Nigeria"))


def telegram(text, photo=None):
    if not (TOKEN and CHAT):
        return
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                  data={"chat_id": CHAT, "text": text[:4000], "disable_web_page_preview": True}, timeout=60)
    if photo and os.path.exists(photo):
        with open(photo, "rb") as f:
            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                          data={"chat_id": CHAT}, files={"photo": f}, timeout=60)


def eligible(r):
    try:
        score = float(r.get("score") or 0)
    except ValueError:
        return False
    no_blockers = (r.get("blockers") or "").strip().lower() in ("", "none", "n/a", "no")
    return (score >= MIN_SCORE and no_blockers and GREENHOUSE.match(r.get("url") or "")
            and not contact_email(r.get("description", "")))


def fill_form(page, letter):
    page.goto(r_url(page), timeout=60000)
    if page.locator('input[name="first_name"]').count() == 0:
        apply_link = page.get_by_role("link", name=re.compile(r"apply", re.I)).first
        if apply_link.count():
            apply_link.click()
            page.wait_for_load_state("domcontentloaded", timeout=30000)
    if page.locator('input[name="first_name"]').count() == 0:
        return "form_not_found"
    if page.locator('iframe[src*="recaptcha"], .g-recaptcha').count():
        return "captcha"
    first, _, last = NAME.partition(" ")
    page.fill('input[name="first_name"]', first)
    page.fill('input[name="last_name"]', last or first)
    page.fill('input[name="email"]', SENDER)
    if page.locator('input[name="phone"]').count():
        page.fill('input[name="phone"]', PHONE)
    page.set_input_files('input[type="file"]', "cv/cv.pdf")
    box = page.locator('textarea[name="cover_letter"]')
    if box.count():
        box.fill(letter)
    return "filled"


def r_url(page):
    return page.url if page.url.startswith("http") and "greenhouse" in page.url else CURRENT["url"]


def submit(page):
    page.locator('button[type="submit"], input[type="submit"]').first.click()
    page.wait_for_timeout(6000)
    text = page.content().lower()
    if any(s in text for s in ("thank you for applying", "thanks for applying", "application submitted")):
        return "submitted"
    return "submit_unconfirmed"


CURRENT = {"url": ""}


def main():
    if not os.path.exists("matches.csv"):
        print("No matches.csv yet.")
        return
    state = json.load(open(STATE_PATH)) if os.path.exists(STATE_PATH) else {}
    rows = list(csv.DictReader(open("matches.csv", encoding="utf-8")))
    todo = []
    for r in rows:
        if r.get("url") in state or not eligible(r):
            continue
        letter = read_cover_letter(r)
        if letter:
            todo.append((float(r["score"]), r, letter))
    queue = json.load(open("direct_apply.json", encoding="utf-8")) if os.path.exists("direct_apply.json") else {}
    by_url = {r["url"]: r for r in rows}
    for posting, item in queue.items():
        if item.get("status") != "greenhouse" or item.get("apply_url") in state or posting not in by_url:
            continue
        orig = by_url[posting]
        letter = read_cover_letter(orig)
        if letter:
            todo.append((float(orig["score"]), dict(orig, url=item["apply_url"]), letter))
    todo.sort(key=lambda x: x[0], reverse=True)
    todo = todo[:MAX_PER_RUN]
    print(f"{len(todo)} Greenhouse forms to fill. Mode: {'AUTO SUBMIT' if AUTO else 'review only'}.")
    if not todo:
        return

    os.makedirs(SCREEN_DIR, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        for score, r, letter in todo:
            CURRENT["url"] = r["url"]
            shot = f"{SCREEN_DIR}/{re.sub(r'[^a-z0-9]+', '-', r['company'].lower())[:30]}-{abs(hash(r['url'])) % 10**6}.png"
            try:
                result = fill_form(page, fill_placeholders(letter))
                if result == "filled":
                    page.screenshot(path=shot, full_page=True)
                    if AUTO:
                        result = submit(page)
                        page.screenshot(path=shot, full_page=True)
                    else:
                        result = "ready_for_review"
            except Exception as e:
                result = f"error: {str(e)[:150]}"
            state[r["url"]] = result
            if result == "ready_for_review":
                telegram(f"Form filled, not submitted: {r['title']} at {r['company']} ({int(score)}/100).\n"
                         f"Check the screenshot, then submit here: {r['url']}", shot)
            elif result == "submitted":
                telegram(f"Application submitted: {r['title']} at {r['company']} ({int(score)}/100).", shot)
            else:
                telegram(f"Could not fill automatically ({result}). Apply here: {r['url']}")
            print(f"{r['company']} | {r['title']}: {result}")
        browser.close()
    json.dump(state, open(STATE_PATH, "w"), indent=1)


if __name__ == "__main__":
    main()
