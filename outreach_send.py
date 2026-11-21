"""
Location outreach, step 2: sends the approved organisations in one batch, at most DAILY_CAP a day.
Every send is logged to outreach_sent.csv.

Needs env: BATCH (batch file name), IDS (comma-separated ids), GMAIL_ADDRESS, GMAIL_APP_PASSWORD,
CANDIDATE_NAME, CANDIDATE_PHONE.
"""
import csv, json, os, smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

DAILY_CAP = 20
LOG = "outreach_sent.csv"
NAME = os.getenv("CANDIDATE_NAME", "").strip()
PHONE = os.getenv("CANDIDATE_PHONE", "").strip()
SENDER = os.getenv("GMAIL_ADDRESS", "").strip()
PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").strip()


def fill(text):
    return (text.replace("[FULL NAME]", NAME).replace("[PHONE]", PHONE)
                .replace("[EMAIL]", SENDER).replace("[LOCATION]", "Nigeria"))


def sent_today():
    if not os.path.exists(LOG):
        return 0
    today = datetime.now(timezone.utc).date().isoformat()
    return sum(1 for r in csv.DictReader(open(LOG, encoding="utf-8"))
               if r["sent_at"].startswith(today) and r["status"] == "sent")


def build(item):
    msg = EmailMessage()
    msg["From"] = f"{NAME} <{SENDER}>"
    msg["To"] = item["email"]
    msg["Reply-To"] = SENDER
    msg["Subject"] = f"Open application: {item['org']}"
    msg.set_content(fill(item["letter"]))
    if os.path.exists("cv/cv.pdf"):
        with open("cv/cv.pdf", "rb") as f:
            msg.add_attachment(f.read(), maintype="application", subtype="pdf",
                               filename=f"{NAME.replace(' ', '_')}_CV.pdf")
    return msg


def main():
    path = os.path.join("outreach", os.getenv("BATCH", "").strip())
    if not os.path.isfile(path):
        print("Batch not found. Nothing sent.")
        return
    if os.path.exists("PAUSE"):
        print("PAUSE file found. Nothing sent.")
        return
    if not (SENDER and PASSWORD and NAME and PHONE):
        print("Gmail or candidate secrets missing. Nothing sent.")
        return
    ids = {x.strip() for x in os.getenv("IDS", "").split(",") if x.strip()}
    batch = json.load(open(path, encoding="utf-8"))
    room = DAILY_CAP - sent_today()
    if room <= 0:
        print(f"Daily cap of {DAILY_CAP} reached. Nothing sent.")
        return

    new_log = not os.path.exists(LOG)
    with open(LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_log:
            w.writerow(["sent_at", "batch", "org", "email", "status"])
        sent = 0
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(SENDER, PASSWORD)
            for item in batch["items"]:
                if sent >= room:
                    break
                if item["id"] not in ids or item["status"] != "pending":
                    continue
                try:
                    smtp.send_message(build(item))
                    item["status"] = "sent"
                    sent += 1
                except Exception as e:
                    item["status"] = "failed"
                    print(f"Failed for {item['org']}: {str(e)[:100]}")
                w.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"),
                            batch["id"], item["org"], item["email"], item["status"]])
                f.flush()
    json.dump(batch, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{sent} organisation emails sent from batch {batch['id']}. Daily cap {DAILY_CAP}.")


if __name__ == "__main__":
    main()
