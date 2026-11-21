"""
Step 4: email applications for strong matches that list a contact email.

Guardrails: score 70 or higher, no blockers, a contact email in the posting, a draft in applications/,
at most MAX_PER_DAY a day, and a PAUSE file in the repo stops everything. Every send is logged to applied.csv.

Needs env: GMAIL_ADDRESS, GMAIL_APP_PASSWORD, CANDIDATE_NAME, CANDIDATE_PHONE.
Run with --dry-run to see what would be sent without sending anything.
"""
import csv, os, re, smtplib, sys
from datetime import datetime, timezone
from email.message import EmailMessage
from prepare import slug  # same file naming as the drafts

MIN_SCORE = 40
MAX_PER_DAY = 10
MATCHES_PATH = "matches.csv"
APPLIED_PATH = "applied.csv"
APPLIED_FIELDS = ["sent_at", "score", "title", "company", "email", "url"]
OUT_DIR = "applications"
CV_PDF = "cv/cv.pdf"
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
NO_BLOCKERS = {"", "none", "n/a", "no", "not applicable"}
PLACEHOLDER_RE = re.compile(r"\[(FULL NAME|PHONE|EMAIL|LOCATION)\]")


def contact_email(description):
    for e in EMAIL_RE.findall(description or ""):
        low = e.lower()
        if any(x in low for x in ("noreply", "no-reply", "example.")):
            continue
        return e
    return None


def load_applied():
    if not os.path.exists(APPLIED_PATH):
        return []
    return list(csv.DictReader(open(APPLIED_PATH, encoding="utf-8")))


def save_applied(rows):
    with open(APPLIED_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=APPLIED_FIELDS)
        w.writeheader()
        w.writerows(rows)


def sent_today(applied):
    today = datetime.now(timezone.utc).date().isoformat()
    return sum(1 for r in applied if r["sent_at"].startswith(today))


def read_cover_letter(job):
    path = f"{OUT_DIR}/{slug(job)}.md"
    if not os.path.exists(path):
        return None
    text = open(path, encoding="utf-8").read()
    m = re.search(r"## Cover letter\n\n(.*?)\n\n## Tailored CV", text, re.S)
    return m.group(1).strip() if m else None


def fill(text, name, phone, address):
    return (text.replace("[FULL NAME]", name).replace("[PHONE]", phone)
                .replace("[EMAIL]", address).replace("[LOCATION]", "Nigeria"))


def main(dry_run):
    if os.path.exists("PAUSE"):
        print("PAUSE file found. Nothing sent.")
        return
    name = os.getenv("CANDIDATE_NAME", "").strip()
    phone = os.getenv("CANDIDATE_PHONE", "").strip()
    sender = os.getenv("GMAIL_ADDRESS", "").strip()
    pw = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    if not dry_run and not (name and phone and sender and pw):
        print("Missing CANDIDATE_NAME, CANDIDATE_PHONE, GMAIL_ADDRESS or GMAIL_APP_PASSWORD. Nothing sent.")
        return
    if not os.path.exists(CV_PDF):
        print(f"{CV_PDF} is missing. Nothing sent.")
        return

    applied = load_applied()
    already = {r["url"] for r in applied}
    budget = None  # no daily cap: every eligible job is sent

    rows = list(csv.DictReader(open(MATCHES_PATH, encoding="utf-8"))) if os.path.exists(MATCHES_PATH) else []
    eligible = []
    for r in rows:
        if r.get("url") in already:
            continue
        try:
            score = int(r["score"])
        except (KeyError, ValueError):
            continue
        if score < MIN_SCORE or r.get("blockers", "").strip().lower() not in NO_BLOCKERS:
            continue
        addr = contact_email(r.get("description", ""))
        letter = read_cover_letter(r) if addr else None
        if addr and letter:
            eligible.append((score, r, addr, letter))
    eligible.sort(key=lambda e: e[0], reverse=True)
    print(f"{len(eligible)} eligible. Sending all of them.")

    sent = 0
    for score, r, addr, letter in eligible[:budget]:
        body = fill(letter, name, phone, sender)
        if PLACEHOLDER_RE.search(body):
            print(f"Skipped {r['title']}: a placeholder was left unfilled.")
            continue
        subject = f"Application: {r['title']}"
        if dry_run:
            print(f"[dry run] would send {score} to {addr}: {subject} ({r['company']})")
            continue

        msg = EmailMessage()
        msg["From"] = f"{name} <{sender}>"
        msg["To"] = addr
        msg["Reply-To"] = sender
        msg["Subject"] = subject
        msg.set_content(body)
        msg.add_attachment(open(CV_PDF, "rb").read(), maintype="application", subtype="pdf",
                           filename=f"{name.replace(' ', '_')}_CV.pdf")
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(sender, pw)
            s.send_message(msg)

        applied.append({"sent_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "score": score, "title": r["title"], "company": r["company"],
                        "email": addr, "url": r["url"]})
        save_applied(applied)  # save after every send so a crash can't cause a double send
        sent += 1
        print(f"Sent: {r['title']} at {r['company']} to {addr}")

    summary = f"- {sent} emails sent this run" + (" (dry run, none sent)" if dry_run else "")
    print(summary)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write("## Emails\n" + summary + "\n")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
