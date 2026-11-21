"""
Adds each cover-letter draft to your Gmail Drafts folder, with your CV attached.
Nothing is sent. You open each draft in Gmail, check it, then send it or delete it.
Each job is added once (gmail_drafts.json remembers which).

Needs env: GMAIL_ADDRESS, GMAIL_APP_PASSWORD, CANDIDATE_NAME, CANDIDATE_PHONE.
IMAP must be turned on in Gmail (Settings, See all settings, Forwarding and POP/IMAP).
"""
import csv, imaplib, json, os, re, time
from email.message import EmailMessage
from send_applications import contact_email, read_cover_letter

MIN_SCORE = 40
DONE_PATH = "gmail_drafts.json"
NAME = os.getenv("CANDIDATE_NAME", "").strip()
PHONE = os.getenv("CANDIDATE_PHONE", "").strip()
SENDER = os.getenv("GMAIL_ADDRESS", "").strip()
PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").strip()


def fill(text):
    return (text.replace("[FULL NAME]", NAME).replace("[PHONE]", PHONE)
                .replace("[EMAIL]", SENDER).replace("[LOCATION]", "Nigeria"))


def build_message(r, letter, failed_send=False):
    to = contact_email(r.get("description", "")) or ""
    msg = EmailMessage()
    msg["From"] = f"{NAME} <{SENDER}>"
    if to:
        msg["To"] = to
    msg["Subject"] = f"Application: {r['title']} at {r['company']}"
    msg["Reply-To"] = SENDER
    body = fill(letter)
    body += f"\n\n--- Notes for you (delete before sending) ---\nJob link: {r['url']}\n"
    if failed_send:
        body += f"The automatic send failed. Contact address: {to}. Please send this one yourself."
    else:
        body += "No email address was found in the posting, so please apply through the link."
    msg.set_content(body)
    if os.path.exists("cv/cv.pdf"):
        with open("cv/cv.pdf", "rb") as f:
            msg.add_attachment(f.read(), maintype="application", subtype="pdf",
                               filename=f"{NAME.replace(' ', '_')}_CV.pdf")
    return msg


def main():
    if not (SENDER and PASSWORD):
        print("Gmail secrets missing, so no drafts were added.")
        return
    if not os.path.exists("matches.csv"):
        print("No matches.csv yet.")
        return
    done = set(json.load(open(DONE_PATH))) if os.path.exists(DONE_PATH) else set()
    sent_urls = set()
    if os.path.exists("applied.csv"):
        sent_urls = {x["url"] for x in csv.DictReader(open("applied.csv", encoding="utf-8"))}
    if os.path.exists("applied_forms.json"):
        forms = json.load(open("applied_forms.json"))
        sent_urls |= {u for u, status in forms.items() if status == "submitted"}
    failed = set(json.load(open("failed_sends.json"))) if os.path.exists("failed_sends.json") else set()

    rows = list(csv.DictReader(open("matches.csv", encoding="utf-8")))
    todo = []
    for r in rows:
        url = r.get("url")
        if url in done or url in sent_urls:
            continue
        try:
            if float(r.get("score") or 0) < MIN_SCORE:
                continue
        except ValueError:
            continue
        has_email = bool(contact_email(r.get("description", ""))) and "himalayas.app" not in url
        if has_email and url not in failed:
            continue  # the bot emails these itself
        letter = read_cover_letter(r)
        if letter:
            todo.append((r, letter, url in failed))
    if not todo:
        print("No new drafts to add to Gmail.")
        return

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(SENDER, PASSWORD)
    added = 0
    for r, letter, failed_send in todo:
        mail.append('"[Gmail]/Drafts"', None, imaplib.Time2Internaldate(time.time()),
                    build_message(r, letter, failed_send).as_bytes())
        done.add(r["url"])
        added += 1
    mail.logout()
    json.dump(sorted(done), open(DONE_PATH, "w"))
    print(f"{added} drafts added to Gmail Drafts.")


if __name__ == "__main__":
    main()
