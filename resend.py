"""
Resends one application (the job link is given) with the documents that posting asks for.
Refuses when a required document is missing, and tells you on Telegram.

Needs env: JOB_URL, GMAIL_ADDRESS, GMAIL_APP_PASSWORD, CANDIDATE_NAME, CANDIDATE_PHONE,
and optionally TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
"""
import csv, json, os, smtplib, sys
from datetime import datetime, timezone
from email.message import EmailMessage
import docs
from send_applications import contact_email, read_cover_letter

JOB_URL = os.getenv("JOB_URL", "").strip()
NAME = os.getenv("CANDIDATE_NAME", "").strip()
PHONE = os.getenv("CANDIDATE_PHONE", "").strip()
SENDER = os.getenv("GMAIL_ADDRESS", "").strip()
PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").strip()


def fill(text):
    return (text.replace("[FULL NAME]", NAME).replace("[PHONE]", PHONE)
                .replace("[EMAIL]", SENDER).replace("[LOCATION]", "Nigeria"))


def find(path, url):
    if not os.path.exists(path):
        return None
    for r in csv.DictReader(open(path, encoding="utf-8")):
        if r.get("url") == url:
            return r
    return None


def main():
    if not (JOB_URL and SENDER and PASSWORD and NAME and PHONE):
        sys.exit("Missing the job link or a secret. Nothing sent.")
    job = find("matches.csv", JOB_URL) or find("applied.csv", JOB_URL)
    if not job:
        sys.exit("That job is not in the saved matches. Nothing sent.")
    description = job.get("description", "")
    to = (find("applied.csv", JOB_URL) or {}).get("email") or contact_email(description)
    if not to:
        sys.exit("No contact address for this job. Nothing sent.")
    letter = read_cover_letter(job)
    if not letter:
        sys.exit("No cover letter draft for this job. Nothing sent.")
    sel = docs.select(description, JOB_URL)
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if sel["missing"]:
        docs.hold(JOB_URL, job["title"], job["company"], sel, token, chat)
        sys.exit("Held: a required document is missing.")

    msg = EmailMessage()
    msg["From"] = f"{NAME} <{SENDER}>"
    msg["To"] = to
    msg["Reply-To"] = SENDER
    msg["Subject"] = f"Application: {job['title']}"
    msg.set_content(fill(letter))
    docs.attach(msg, sel, NAME)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(SENDER, PASSWORD)
        smtp.send_message(msg)

    import records
    records.upsert("sender", JOB_URL, sent=True)
    new = not os.path.exists("applied.csv")
    with open("applied.csv", "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["sent_at", "score", "title", "company", "email", "url"])
        w.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), job.get("score", ""),
                    job["title"], job["company"], to, JOB_URL])
    print(f"Resent to {to} with: {', '.join(sel['attach'])}. {' '.join(sel['notes'])}")


if __name__ == "__main__":
    main()
