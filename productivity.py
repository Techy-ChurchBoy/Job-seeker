"""
Daily plan, follow-ups, deadline warnings, interview prep and the weekly summary.

- Once a day: a plan on Telegram (jobs to apply to by hand, follow-ups due, deadlines, interviews, skill task).
- Follow-ups: applications with no reply after 7 days get a short Gmail draft. You send it or delete it.
- Interview prep: when a reply mentions an interview, a one-page prep file is written from your CV and the posting.
- Sundays: a weekly summary of runs, scored jobs, and GitHub Actions minutes used.

Needs env: GMAIL_ADDRESS, GMAIL_APP_PASSWORD, CANDIDATE_NAME, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GITHUB_TOKEN (optional).
"""
import csv, imaplib, json, os, re, time
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
import requests
import tracker

STATE = "productivity_state.json"
FOLLOWED = "followups_done.json"
PREP_DIR = "applications/prep"
FOLLOW_UP_AFTER = 7
DEADLINE_WARNING = 3
DATE_RE = re.compile(r"(?:deadline|closing date|closes|apply by|applications close)[^.\n]{0,40}?(\d{1,2}\s+[A-Za-z]+\s+\d{4}|[A-Za-z]+\s+\d{1,2},?\s+\d{4})", re.I)
FORMATS = ["%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y"]
NAME = os.getenv("CANDIDATE_NAME", "").strip()
SENDER = os.getenv("GMAIL_ADDRESS", "").strip()
PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").strip()
TOKEN, CHAT = os.getenv("TELEGRAM_BOT_TOKEN", "").strip(), os.getenv("TELEGRAM_CHAT_ID", "").strip()


def telegram(text):
    if TOKEN and CHAT:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      data={"chat_id": CHAT, "text": text[:4000], "disable_web_page_preview": True}, timeout=60)


def rows(path):
    return list(csv.DictReader(open(path, encoding="utf-8"))) if os.path.exists(path) else []


def parse_deadline(text):
    m = DATE_RE.search(text or "")
    if not m:
        return None
    for fmt in FORMATS:
        try:
            return datetime.strptime(m.group(1).replace(",", "").strip(), fmt).date()
        except ValueError:
            continue
    return None


def top_skill():
    if not os.path.exists("skills_report.txt"):
        return None
    for line in open("skills_report.txt", encoding="utf-8"):
        m = re.match(r"- (.+?): in \d+ job", line)
        if m:
            return m.group(1)
    return None


def plan_text(today):
    matches = rows("matches.csv")
    applied = rows("applied.csv")
    applied_urls = {r["url"] for r in applied}
    by_hand = [r for r in matches if float(r.get("score") or 0) >= 40 and r["url"] not in applied_urls
               and not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", r.get("description") or "")][:3]
    replied = {r.get("company") for r in (json.load(open("replies.json")) if os.path.exists("replies.json") else [])}
    due = [a for a in applied if (today - datetime.fromisoformat(a["sent_at"]).date()).days >= FOLLOW_UP_AFTER
           and a["company"] not in replied
           and tracker.load().get(a["company"], {}).get("stage", "Applied") == "Applied"]
    deadlines = []
    for r in matches:
        d = parse_deadline(r.get("description"))
        if d and 0 <= (d - today).days <= DEADLINE_WARNING:
            deadlines.append(f"{r['title']} at {r['company']}: closes {d:%d %b}")
    interviews = [k for k, v in tracker.load().items() if v.get("stage") == "Interview"]
    lines = [f"Today's plan ({today:%A %d %B})", ""]
    lines.append("Apply by hand (top 3):")
    lines += [f"- {r['title']} at {r['company']} ({int(float(r['score']))}/100): {r['url']}" for r in by_hand] or ["- Nothing waiting."]
    lines += ["", f"Follow-ups due: {len(due)}"] + [f"- {a['company']}: sent {a['sent_at'][:10]}" for a in due[:5]]
    if deadlines:
        lines += ["", "Closing soon:"] + [f"- {d}" for d in deadlines[:5]]
    if interviews:
        lines += ["", "Interviews to prepare for:"] + [f"- {i}" for i in interviews]
    skill = top_skill()
    lines += ["", f"30-minute task: {'learn ' + skill if skill else 'add your newest skill to the CV'}."]
    return "\n".join(lines)


def follow_ups(today):
    if not (SENDER and PASSWORD):
        return 0
    done = set(json.load(open(FOLLOWED))) if os.path.exists(FOLLOWED) else set()
    replies = json.load(open("replies.json")) if os.path.exists("replies.json") else []
    replied = {r.get("company") for r in replies}
    stages = tracker.load()
    due = [a for a in rows("applied.csv") if a["url"] not in done and a["company"] not in replied
           and (today - datetime.fromisoformat(a["sent_at"]).date()).days >= FOLLOW_UP_AFTER
           and stages.get(a["company"], {}).get("stage", "Applied") == "Applied"]
    if not due:
        return 0
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(SENDER, PASSWORD)
    for a in due:
        msg = EmailMessage()
        msg["From"] = f"{NAME} <{SENDER}>"
        msg["Subject"] = f"Following up: {a['title']}"
        msg.set_content(f"Dear Hiring Manager,\n\nI applied for {a['title']} at {a['company']} on "
                        f"{datetime.fromisoformat(a['sent_at']):%d %B %Y} and wanted to follow up. "
                        "I remain interested and would be glad to share any further information.\n\n"
                        f"Thank you for your time.\n\nYours sincerely,\n{NAME}\n\n"
                        f"--- Notes for you (delete before sending) ---\nApplied via: {a['url']}")
        mail.append('"[Gmail]/Drafts"', None, imaplib.Time2Internaldate(time.time()), msg.as_bytes())
        done.add(a["url"])
    mail.logout()
    json.dump(sorted(done), open(FOLLOWED, "w"))
    return len(due)


def interview_prep():
    replies = json.load(open("replies.json")) if os.path.exists("replies.json") else []
    os.makedirs(PREP_DIR, exist_ok=True)
    made = 0
    for r in replies:
        if "interview" not in (r.get("subject") or "").lower():
            continue
        name = re.sub(r"[^a-z0-9]+", "-", (r.get("company") or "company").lower()).strip("-")[:40]
        path = f"{PREP_DIR}/{name}.md"
        if os.path.exists(path):
            continue
        cv = open("cv/cv.txt", encoding="utf-8").read()[:1500] if os.path.exists("cv/cv.txt") else ""
        job = next((m for m in rows("matches.csv") if r.get("company") and r["company"] in m.get("company", "")), {})
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# Interview prep: {r.get('company')}\n\nReply: {r.get('subject')} ({r.get('received')})\n\n")
            f.write(f"## The role\n{job.get('title', 'See the posting')}\n\n")
            f.write(f"## What the posting asks for\n{(job.get('description') or '')[:800]}\n\n")
            f.write("## Your background (from your CV)\n" + cv + "\n\n")
            f.write("## Questions to prepare\n- Tell me about yourself.\n- Why this company?\n"
                    "- Describe a time you reconciled or investigated a difference in records.\n"
                    "- What tools would you use for this role, and how have you used them?\n"
                    "- Where do you see yourself in two years?\n")
        made += 1
    return made


def weekly_summary(today):
    runs = json.load(open("status.json")).get("report", {}) if os.path.exists("status.json") else {}
    token = os.getenv("GITHUB_TOKEN", "").strip()
    minutes = None
    if token:
        since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        res = requests.get("https://api.github.com/repos/Techy-ChurchBoy/Job-seeker/actions/runs",
                           params={"created": f">={since}", "per_page": 100},
                           headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}, timeout=30)
        if res.ok:
            minutes = sum(((r.get("run_duration_ms") or 0) for r in res.json().get("workflow_runs", []))) / 60000
    lines = ["Weekly summary", f"Scored this run: {runs.get('scored', 0)} jobs",
             f"Forms and letters: about {runs.get('scored', 0) + runs.get('new_to_score', 0)} AI calls this run (estimate)"]
    lines.append(f"GitHub Actions minutes this week: {minutes:.0f} of 2,000 free" if minutes is not None
                 else "GitHub Actions minutes: not checked (add the GITHUB_TOKEN secret).")
    return "\n".join(lines)


def main():
    today = date.today()
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    if state.get("plan_date") != today.isoformat():
        followed = follow_ups(today)
        prepared = interview_prep()
        text = plan_text(today)
        if today.weekday() == 6:
            text += "\n\n" + weekly_summary(today)
        if followed:
            text += f"\n\nFollow-up drafts added to Gmail: {followed}."
        if prepared:
            text += f"\nInterview prep files written: {prepared}."
        telegram(text)
        json.dump({"plan_date": today.isoformat()}, open(STATE, "w"))
        print("Daily plan sent.")
    else:
        print("Daily plan already sent today.")


if __name__ == "__main__":
    main()
