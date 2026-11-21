"""
Reply tracking: looks in your Gmail inbox for replies from organisations the bot has applied to,
and records them in replies.json for the dashboard.

Read-only. It reads only the sender, subject and date headers, never the message body, and it never
marks mail as read or replies to anything.
Needs env: GMAIL_ADDRESS, GMAIL_APP_PASSWORD.
"""
import csv, email, imaplib, json, os
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime

REPLIES_PATH = "replies.json"
SENT_FILES = ["applied.csv", "outreach_sent.csv"]
GENERIC = ("gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "proton.me")
AUTOMATED = ("noreply", "no-reply", "donotreply", "mailer-daemon", "notifications")
LOOKBACK_DAYS = 30


def sent_index():
    by_addr, by_domain = {}, {}
    for path in SENT_FILES:
        if not os.path.exists(path):
            continue
        for r in csv.DictReader(open(path, encoding="utf-8")):
            addr = (r.get("email") or "").strip().lower()
            if "@" not in addr:
                continue
            match = ((r.get("company") or r.get("org") or "").strip(),
                     (r.get("title") or "open application").strip())
            by_addr[addr] = match
            domain = addr.split("@")[-1]
            if domain not in GENERIC:
                by_domain[domain] = match
    return by_addr, by_domain


def text(value):
    if not value:
        return ""
    return "".join(p.decode(enc or "utf-8", "ignore") if isinstance(p, bytes) else p
                   for p, enc in decode_header(value))


def fetch_headers(mail, msg_id):
    _, data = mail.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])")
    raw = next((part[1] for part in data if isinstance(part, tuple)), b"")
    return email.message_from_bytes(raw)


def main():
    sender = os.getenv("GMAIL_ADDRESS", "").strip()
    password = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    if not (sender and password):
        print("Gmail secrets missing. Replies not checked.")
        return
    by_addr, by_domain = sent_index()
    if not by_addr:
        print("Nothing sent yet, so there are no replies to look for.")
        return
    replies = json.load(open(REPLIES_PATH, encoding="utf-8")) if os.path.exists(REPLIES_PATH) else []
    seen = {r["message_id"] for r in replies}
    since = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime("%d-%b-%Y")

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(sender, password)
    mail.select("INBOX", readonly=True)
    _, data = mail.search(None, f'(SINCE "{since}")')
    new = []
    for msg_id in data[0].split()[-300:]:
        msg = fetch_headers(mail, msg_id)
        message_id = (msg.get("Message-ID") or "").strip()
        addr = parseaddr(msg.get("From", ""))[1].lower()
        if not message_id or message_id in seen or not addr or any(x in addr for x in AUTOMATED):
            continue
        match = by_addr.get(addr) or by_domain.get(addr.split("@")[-1])
        if not match:
            continue
        try:
            when = parsedate_to_datetime(msg.get("Date")).astimezone(timezone.utc).isoformat(timespec="minutes")
        except (TypeError, ValueError):
            when = ""
        new.append({"message_id": message_id, "received": when, "from": addr,
                    "subject": text(msg.get("Subject")), "company": match[0], "application": match[1]})
    mail.logout()

    replies = sorted(new + replies, key=lambda r: r.get("received") or "", reverse=True)[:200]
    json.dump(replies, open(REPLIES_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(new)} new replies recorded.")


if __name__ == "__main__":
    main()
