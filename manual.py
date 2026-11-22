"""
Apply to a job you submit by hand (the apply-job workflow in the Actions tab).

Fetches the posting (or uses the description you pasted), scores it, writes a tailored draft,
and emails it if a contact address is found. Manual jobs skip the score threshold, but blockers
are still written into the draft notes so you can decide. Counts toward the daily send limit.
"""
import csv, json, os, re, smtplib, sys
from datetime import datetime, timezone
from email.message import EmailMessage
from urllib.parse import urlparse
import requests
import jobbot as jb
import prepare as pr
import send_applications as sa

JOB_URL = os.getenv("JOB_URL", "").strip()
JOB_COMPANY = os.getenv("JOB_COMPANY", "").strip()
JOB_EMAIL = os.getenv("JOB_EMAIL", "").strip()
PASTED = os.getenv("JOB_DESCRIPTION", "").strip()
MATCH_FIELDS = ["score", "title", "company", "location", "source", "url", "reason", "blockers", "description", "skill_gaps"]


def write_result(status, reason):
    """Records what actually happened, so Telegram reports the truth: sent, drafted or failed."""
    json.dump({"status": status, "reason": reason, "url": JOB_URL},
              open("manual_result.json", "w", encoding="utf-8"), ensure_ascii=False)


def fetch_posting(url):
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (jobbot)"}, timeout=30)
    r.raise_for_status()
    raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", r.text, flags=re.S | re.I)
    m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
    return (jb.strip_html(m.group(1)) if m else ""), jb.strip_html(raw)


def save_row(row):
    new = not os.path.exists(sa.MATCHES_PATH)
    with open(sa.MATCHES_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MATCH_FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in MATCH_FIELDS})


def write_draft(job, score, notes, letter, cv):
    path = f"{sa.OUT_DIR}/{pr.slug(job)}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {job['title']} at {job['company']}\n\n")
        f.write(f"Score: {score}/100. Source: Manual. Job link: {job['url']}\n\n")
        f.write(f"## Notes for you\n\n{pr.scrub(notes)}\n\n")
        f.write(f"## Cover letter\n\n{pr.scrub(letter)}\n\n")
        f.write(f"## Tailored CV\n\n{pr.scrub(cv)}\n")
    return path


def send(job, body_letter, to):
    name = os.getenv("CANDIDATE_NAME", "").strip()
    phone = os.getenv("CANDIDATE_PHONE", "").strip()
    sender = os.getenv("GMAIL_ADDRESS", "").strip()
    pw = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    body = (body_letter.replace("[FULL NAME]", name).replace("[PHONE]", phone)
            .replace("[EMAIL]", sender).replace("[LOCATION]", "Nigeria"))
    msg = EmailMessage()
    msg["From"] = f"{name} <{sender}>"
    msg["To"] = to
    msg["Reply-To"] = sender
    msg["Subject"] = f"Application: {job['title']} at {job['company']}"
    msg.set_content(body)
    msg.add_attachment(open(sa.CV_PDF, "rb").read(), maintype="application", subtype="pdf",
                       filename=f"{name.replace(' ', '_')}_CV.pdf")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(sender, pw)
        s.send_message(msg)


def main():
    if not JOB_URL:
        sys.exit("Set job_url.")
    if not jb.GEMINI_KEY:
        sys.exit("Set GEMINI_API_KEY.")
    os.makedirs(sa.OUT_DIR, exist_ok=True)
    lines = []

    if PASTED:
        title, text = "", PASTED
    else:
        try:
            title, text = fetch_posting(JOB_URL)
        except Exception as e:
            print(f"Could not fetch the posting: {e}")
            print("Re-run with the job description pasted into the description field.")
            write_result("failed", f"Could not read the posting ({str(e)[:120]}). Paste the description instead.")
            return
        if len(text) < 300:
            print("The page returned very little text (it may need JavaScript). Re-run with the description pasted.")
            write_result("failed", "The page showed almost no text (it may need JavaScript). Paste the description instead.")
            return

    company = JOB_COMPANY or urlparse(JOB_URL).hostname.replace("www.", "")
    job = {"source": "Manual", "title": title or "Job posting", "company": company,
           "location": "", "url": JOB_URL or f"pasted-{company}", "description": text[:6000]}

    jb.MODEL = jb.pick_model()
    s = jb.score(job)
    save_row({**job, "score": s["score"], "reason": s.get("reason", ""), "blockers": s.get("blockers", ""),
              "skill_gaps": s.get("skill_gaps", ""), "description": job["description"][:2500]})
    lines.append(f"- Scored {s['score']}/100: {job['title']} at {job['company']}")
    lines.append(f"- Blockers: {s.get('blockers') or 'none'}")

    letter_out = pr.generate(jb.MODEL, pr.PROMPT.format(
        cv=pr.CV_TEXT, title=job["title"], company=company, location="Nigeria",
        description=job["description"][:2500]))
    path = write_draft(job, s["score"], letter_out.get("notes", ""),
                       letter_out.get("cover_letter", ""), letter_out.get("tailored_cv", ""))
    done = set(json.load(open(pr.PREPARED_PATH))) if os.path.exists(pr.PREPARED_PATH) else set()
    done.add(job["url"])
    json.dump(sorted(done), open(pr.PREPARED_PATH, "w"))
    lines.append(f"- Draft saved: {path}")

    to = JOB_EMAIL or sa.contact_email(job["description"])
    applied = sa.load_applied()
    if not to:
        lines.append("- No contact email found. Apply through the posting's link using the draft.")
        write_result("drafted", "Not sent: no contact email in the posting. A draft was saved; apply through the link.")
    elif os.path.exists("PAUSE"):
        lines.append("- PAUSE file found, so nothing was sent.")
        write_result("failed", "Not sent: the PAUSE file is on.")
    elif not all(os.getenv(k, "").strip() for k in ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "CANDIDATE_NAME", "CANDIDATE_PHONE")):
        lines.append("- Gmail or candidate secrets are missing, so nothing was sent.")
        write_result("failed", "Not sent: Gmail or candidate secrets are missing on GitHub.")
    elif job["url"] in {r["url"] for r in applied}:
        lines.append("- Already applied to this posting, so nothing was sent.")
        write_result("failed", "Not sent: this posting was already applied to.")
    else:
        send(job, letter_out.get("cover_letter", ""), to)
        applied.append({"sent_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "score": s["score"], "title": job["title"], "company": company,
                        "email": to, "url": job["url"]})
        sa.save_applied(applied)
        lines.append(f"- Emailed {to}")
        write_result("sent", f"Email sent to {to}.")

    print("\n".join(lines))
    if os.getenv("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write("## Manual application\n" + "\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
