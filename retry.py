"""
Retry one application. Refetches the posting in full from its own link, re-reads it for contact addresses,
saves any it finds, and sends if the normal checks pass (letter present, required documents, not already
sent to that address). If no contact address is in the full posting, it says so and sends nothing.

Needs env: JOB_URL, GMAIL_ADDRESS, GMAIL_APP_PASSWORD, CANDIDATE_NAME, CANDIDATE_PHONE, TELEGRAM_BOT_TOKEN,
TELEGRAM_CHAT_ID (optional).
"""
import csv, json, os, re, smtplib, sys, time
from datetime import datetime, timezone
from email.message import EmailMessage
import requests
import contacts
import docs
import jobbot as jb
import records
from send_applications import read_cover_letter

URL = os.getenv("JOB_URL", "").strip()
NAME = os.getenv("CANDIDATE_NAME", "").strip()
PHONE = os.getenv("CANDIDATE_PHONE", "").strip()
SENDER = os.getenv("GMAIL_ADDRESS", "").strip()
PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").strip()
TOKEN, CHAT = os.getenv("TELEGRAM_BOT_TOKEN", "").strip(), os.getenv("TELEGRAM_CHAT_ID", "").strip()
UA = "jobbot-personal-job-search/1.0 (one request per run)"


def say(text):
    if TOKEN and CHAT:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      data={"chat_id": CHAT, "text": text[:4000], "disable_web_page_preview": True}, timeout=60)
    print(text)


def fetch_full(url):
    """The whole posting, read again from its own link. Falls back to the saved text if the page can't be read."""
    if not jb.allowed_by_robots(url):
        return ""
    time.sleep(2)
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
        if not r.ok:
            return ""
        raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", r.text, flags=re.S | re.I)
        return jb.strip_html(raw)
    except requests.RequestException:
        return ""


def find_row(path, url):
    if not os.path.exists(path):
        return None
    for r in csv.DictReader(open(path, encoding="utf-8")):
        if r.get("url") == url:
            return r
    return None


def fill(text):
    return (text.replace("[FULL NAME]", NAME).replace("[PHONE]", PHONE)
                .replace("[EMAIL]", SENDER).replace("[LOCATION]", "Nigeria"))


def main():
    if not URL:
        sys.exit("Need the job link.")
    row = find_row("matches.csv", URL) or find_row("applied.csv", URL)
    if not row:
        say(f"Retry: that posting is not in the saved matches. Nothing sent. {URL}")
        return
    skip = [s.lower() for s in json.load(open("skip_companies.json"))] if os.path.exists("skip_companies.json") else []
    if any(s in f"{row.get('company','')} {row.get('title','')} {URL}".lower() for s in skip):
        say(f"Retry: you ruled this posting out. Nothing sent. {row.get('title')} at {row.get('company')}")
        return

    full = fetch_full(URL) or row.get("description", "")
    found = contacts.find(full)
    if not found:
        say(f"Retry: the full posting has no contact address. Nothing sent. Apply through the link: {URL}")
        return

    saved = row.get("description", "")
    if any(e.lower() in saved.lower() for e in found) is False:
        records.upsert("scoring", URL, title=row.get("title", ""))  # keeps the record present
    # the contacts are saved on the posting so later runs see them too
    matches = list(csv.DictReader(open("matches.csv", encoding="utf-8"))) if os.path.exists("matches.csv") else []
    if matches:
        fields = list(matches[0].keys())
        for m in matches:
            if m["url"] == URL and not contacts.find(m.get("description", "")):
                m["description"] = f"Contacts: {'; '.join(found)}\n" + (m.get("description") or "")
        with open("matches.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(matches)

    letter = read_cover_letter(row)
    if not letter:
        say(f"Retry: contact found ({', '.join(found)}) but there is no cover letter yet. Nothing sent.")
        return
    sel = docs.select(full, URL)
    if sel["missing"]:
        say(f"Retry: a required document is missing, so nothing was sent: {'; '.join(sel['missing'])}")
        return

    applied = list(csv.DictReader(open("applied.csv", encoding="utf-8"))) if os.path.exists("applied.csv") else []
    sent_pairs = {(a.get("url"), (a.get("email") or "").lower()) for a in applied}
    to = next((e for e in found if (URL, e.lower()) not in sent_pairs), None)
    if not to:
        say(f"Retry: already sent to {', '.join(found)} for this posting. Nothing sent.")
        return

    msg = EmailMessage()
    msg["From"] = f"{NAME} <{SENDER}>"
    msg["To"] = to
    msg["Reply-To"] = SENDER
    msg["Subject"] = f"Application: {row.get('title', 'Job application')}"
    msg.set_content(fill(letter))
    docs.attach(msg, sel, NAME)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(SENDER, PASSWORD)
        smtp.send_message(msg)
    new = not os.path.exists("applied.csv")
    with open("applied.csv", "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["sent_at", "score", "title", "company", "email", "url"])
        w.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), row.get("score", ""),
                    row.get("title", ""), row.get("company", ""), to, URL])
    records.upsert("sender", URL, sent=True)
    say(f"Retry: sent to {to} for {row.get('title')} at {row.get('company')}, with: {', '.join(sel['attach'])}.")


if __name__ == "__main__":
    main()
