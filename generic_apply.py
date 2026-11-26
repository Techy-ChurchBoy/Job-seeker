"""
Fills plain application forms (name, email, phone, CV upload, cover letter) that the collector found
on company pages. Review only: the bot fills the form, takes a screenshot and sends it to you on Telegram.
It never presses submit. Postings that ask for documents you don't have are held.
"""
import csv, json, os, re
import requests
from playwright.sync_api import sync_playwright
import docs
from send_applications import read_cover_letter

NAME = os.getenv("CANDIDATE_NAME", "").strip()
PHONE = os.getenv("CANDIDATE_PHONE", "").strip()
SENDER = os.getenv("GMAIL_ADDRESS", "").strip()
TOKEN, CHAT = os.getenv("TELEGRAM_BOT_TOKEN", "").strip(), os.getenv("TELEGRAM_CHAT_ID", "").strip()
AUTO = os.getenv("AUTO_SUBMIT", "false").strip().lower() == "true"  # the dashboard switch
QUEUE, STATE_PATH, SCREEN_DIR = "direct_apply.json", "applied_forms.json", "applications/screens"
MAX_PER_RUN = 5


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
            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto", data={"chat_id": CHAT},
                          files={"photo": f}, timeout=60)


def first(page, selectors):
    for sel in selectors:
        loc = page.locator(sel)
        if loc.count():
            return loc.first
    return None


def fill_form(page, letter, sel):
    if page.locator('iframe[src*="recaptcha"], .g-recaptcha, iframe[src*="hcaptcha"]').count():
        return "captcha"
    first_name = first(page, ['input[name*="first" i]', 'input[id*="first" i]', 'input[placeholder*="first" i]'])
    last_name = first(page, ['input[name*="last" i]', 'input[id*="last" i]', 'input[placeholder*="last" i]'])
    full_name = first(page, ['input[name*="name" i]:not([name*="company" i])'])
    given, _, family = NAME.partition(" ")
    if first_name:
        first_name.fill(given)
        if last_name:
            last_name.fill(family or given)
    elif full_name:
        full_name.fill(NAME)
    email = first(page, ['input[type="email"]', 'input[name*="email" i]'])
    if email:
        email.fill(SENDER)
    phone = first(page, ['input[type="tel"]', 'input[name*="phone" i]'])
    if phone:
        phone.fill(PHONE)
    files = [os.path.join(os.getcwd(), docs.DOCS[k]) for k in sel["attach"]]
    upload = page.locator('input[type="file"]')
    if upload.count():
        try:
            upload.first.set_input_files(files if sel["single"] is False else files[:1])
        except Exception:
            upload.first.set_input_files(files[0])
    boxes = page.locator("textarea")
    if boxes.count():
        boxes.first.fill(letter)
    return "filled"


def submit(page):
    """Presses the form's submit button and checks for a confirmation. Never used when a captcha is shown."""
    button = page.locator('button[type="submit"], input[type="submit"]')
    if not button.count():
        return "no_submit_button"
    button.first.click()
    page.wait_for_timeout(6000)
    text = page.content().lower()
    if any(s in text for s in ("thank you for applying", "thanks for applying", "application submitted",
                               "application received", "we have received your application")):
        return "submitted"
    return "submit_unconfirmed"


def main():
    if not os.path.exists(QUEUE):
        print("No direct-apply queue yet.")
        return
    queue = json.load(open(QUEUE, encoding="utf-8"))
    state = json.load(open(STATE_PATH)) if os.path.exists(STATE_PATH) else {}
    rows = {r["url"]: r for r in csv.DictReader(open("matches.csv", encoding="utf-8"))} if os.path.exists("matches.csv") else {}
    todo, seen_forms = [], set()
    notified = json.load(open("notified_forms.json")) if os.path.exists("notified_forms.json") else []
    for posting, item in queue.items():
        if item.get("status") != "generic_form" or item.get("apply_url") in state or posting not in rows:
            continue
        if item["apply_url"] in seen_forms:  # the same form queued under two postings: fill it once
            continue
        seen_forms.add(item["apply_url"])
        letter = read_cover_letter(rows[posting])
        if letter:
            todo.append((posting, item, letter))
        elif item["apply_url"] not in notified:
            telegram(f"Waiting for a cover letter before filling: {item['title']} at {item['company']}. "
                     f"It will be filled on a later run. Apply here if you prefer: {item['apply_url']}")
            notified.append(item["apply_url"])
    json.dump(notified, open("notified_forms.json", "w"))
    todo = todo[:MAX_PER_RUN]
    print(f"{len(todo)} plain forms to fill (review only).")
    if not todo:
        return
    os.makedirs(SCREEN_DIR, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        for posting, item, letter in todo:
            url = item["apply_url"]
            shot = f"{SCREEN_DIR}/generic-{re.sub(r'[^a-z0-9]+', '-', item['company'].lower())[:30]}.png"
            sel = docs.select(rows[posting].get("description", ""), posting)
            if sel["missing"]:
                docs.hold(posting, item["title"], item["company"], sel, TOKEN, CHAT)
                state[url] = "held"
                continue
            try:
                page.goto(url, timeout=60000)
                result = fill_form(page, fill_placeholders(letter), sel)
                if result == "filled":
                    if AUTO:
                        result = submit(page)
                    page.screenshot(path=shot, full_page=True)
                    if result == "filled":
                        result = "ready_for_review"
            except Exception as e:
                result = f"error: {str(e)[:150]}"
            state[url] = result
            if result == "ready_for_review":
                telegram(f"Form filled, NOT submitted: {item['title']} at {item['company']}.\n"
                         f"Check the screenshot, then submit here: {url}", shot)
            elif result in ("submitted", "submit_unconfirmed"):
                telegram(f"Application {'submitted' if result == 'submitted' else 'sent, but no confirmation was shown'}: "
                         f"{item['title']} at {item['company']}.", shot)
            elif result == "captcha":
                telegram(f"This form has a captcha, so I stopped. Please apply here: {url}")
            else:
                telegram(f"Could not fill automatically ({result}). Apply here: {url}")
            print(f"{item['company']} | {item['title']}: {result}")
        browser.close()
    json.dump(state, open(STATE_PATH, "w"), indent=1)


if __name__ == "__main__":
    main()
