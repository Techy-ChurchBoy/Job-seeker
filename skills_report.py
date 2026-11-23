"""
Skills report: what the jobs you scored ask for that your CV doesn't show yet, in plain English.
Writes skills_report.txt (read by the /skills command on Telegram) and emails it to you once a week.

Needs env for the email: GMAIL_ADDRESS, GMAIL_APP_PASSWORD, CANDIDATE_NAME.
"""
import csv, json, os, smtplib
from urllib.parse import quote_plus
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

REPORT = "skills_report.txt"
SENT_PATH = "skills_report_sent.json"
EMAIL_EVERY_DAYS = 7

CATEGORIES = [
    ("Accounting and finance", ["ifrs", "gaap", "tax", "audit", "consolidat", "modell", "budget", "forecast",
                                "cost accounting", "inventory", "reconcil", "financial reporting", "account"]),
    ("Systems and tools", ["sap", "oracle", "netsuite", "intacct", "power bi", "tableau", "sql", "python",
                           "salesforce", "xero", "quickbooks", "dynamics", "erp", "vba", "pivot", "excel"]),
    ("Certifications", ["acca", "cpa", "icai", "ican", "aca", "cfa", "certif", "chartered"]),
    ("Business and communication", ["negotiat", "stakeholder", "communicat", "present", "customer", "sales",
                                    "marketing", "client", "relationship"]),
]
ADVICE = {
    "Accounting and finance": "Practise each one on a small real task, and keep the file as proof. For example, a short IFRS note or a simple budget model.",
    "Systems and tools": "Learn one tool at a time. Pick the one that appears most often in the jobs below, and use its free trial or training first.",
    "Certifications": "Check the blockers list before deciding. If a certification is a hard requirement, decide whether the time and cost are worth it.",
    "Business and communication": "Show these in your CV with a real example from your NCAT role or your fellowship work. Don't claim what you haven't done.",
    "Other": "Look at the example jobs to see what they actually need, then decide whether it's worth building.",
}


# Providers named by hand. The bot doesn't generate web addresses; each skill also gets a search link.
RESOURCES = {
    "power bi": ["Microsoft Learn (free Power BI modules)", "Coursera (Power BI courses)"],
    "sql": ["freeCodeCamp (free SQL course)", "Microsoft Learn (SQL fundamentals)"],
    "excel": ["Microsoft Learn (free Excel training)", "Coursera (Excel courses)"],
    "ifrs": ["IFRS Foundation (free educational material)", "ACCA (IFRS study resources)"],
    "sap": ["openSAP (free SAP courses)", "SAP Learning Hub (paid)"],
    "oracle": ["Oracle Learning Library (free tutorials)"],
    "netsuite": ["Oracle NetSuite SuiteAnswers (free help articles)"],
    "dynamics": ["Microsoft Learn (Dynamics 365 Business Central modules)"],
    "sage intacct": ["Sage official training videos"],
    "quickbooks": ["QuickBooks ProAdvisor training (free)"],
    "xero": ["Xero Central (free courses)"],
    "python": ["python.org tutorial (free)", "freeCodeCamp (Python course)"],
    "tableau": ["Tableau free training videos"],
    "salesforce": ["Salesforce Trailhead (free)"],
    "acca": ["ACCA official study route"],
    "cpa": ["AICPA official CPA exam information"],
    "financial modell": ["Corporate Finance Institute (free articles)", "Wall Street Prep (free resources)"],
    "forecast": ["Corporate Finance Institute (free articles)"],
    "budget": ["Corporate Finance Institute (free articles)"],
    "inventory": ["Coursera (supply chain and inventory courses)"],
}


# YouTube channels named by hand (check each is still active before relying on it).
YOUTUBE = {
    "power bi": ["Alex The Analyst", "Microsoft Power BI"],
    "sql": ["freeCodeCamp.org", "Alex The Analyst"],
    "excel": ["Leila Gharani", "Excel Campus"],
    "ifrs": ["ACCA Global", "Corporate Finance Institute"],
    "financial modell": ["Corporate Finance Institute", "Wall Street Prep"],
    "budget": ["Corporate Finance Institute"],
    "forecast": ["Corporate Finance Institute"],
    "python": ["Corey Schafer", "Programming with Mosh"],
    "tableau": ["Tableau"],
    "quickbooks": ["QuickBooks"],
    "xero": ["Xero"],
    "oracle": ["Oracle Developers"],
    "acca": ["ACCA Global"],
    "cpa": ["AICPA & CIMA"],
    "salesforce": ["Salesforce"],
}


def learn_line(skill):
    low = skill.lower()
    named = []
    for key, providers in RESOURCES.items():
        if key in low:
            named += providers
    channels = []
    for key, names in YOUTUBE.items():
        if key in low:
            channels += names
    yt_search = quote_plus(f"{skill} tutorial")
    parts = []
    parts.append(f"YouTube: {'; '.join(dict.fromkeys(channels)) or 'search below'}. "
                 f"Search: https://www.youtube.com/results?search_query={yt_search}")
    if named:
        parts.append("Also: " + "; ".join(named[:2]))
    google = quote_plus(f"free course {skill}")
    parts.append(f"Search: https://www.google.com/search?q={google}")
    return " | ".join(parts)


def category(skill):
    low = skill.lower()
    for name, words in CATEGORIES:
        if any(w in low for w in words):
            return name
    return "Other"


def build():
    if not os.path.exists("matches.csv"):
        return "No scored jobs yet, so there is no skills report. It is created after the next job run."
    rows = list(csv.DictReader(open("matches.csv", encoding="utf-8")))
    counts, examples = Counter(), defaultdict(list)
    blockers = Counter()
    for r in rows:
        for g in [x.strip() for x in (r.get("skill_gaps") or "").split(";") if x.strip()]:
            key = g.lower()
            counts[key] += 1
            if len(examples[key]) < 2:
                examples[key].append(f"{r['title']} at {r['company']}")
        b = (r.get("blockers") or "").strip()
        if b and b.lower() not in ("none", "n/a", "no"):
            blockers[b] += 1
    if not counts:
        return "No skill gaps recorded yet."

    out = [f"YOUR SKILLS REPORT  ({datetime.now(timezone.utc).strftime('%d %B %Y')})", "",
           f"Based on {len(rows)} jobs scored against your CV.", "",
           "THE 5 SKILLS THAT COME UP MOST", ""]
    for skill, n in counts.most_common(5):
        out.append(f"- {skill.title()}: in {n} job{'s' if n != 1 else ''}")
    out += ["", "BY AREA", ""]
    grouped = defaultdict(list)
    for skill, n in counts.most_common():
        grouped[category(skill)].append((skill, n))
    for name, _ in CATEGORIES + [("Other", [])]:
        items = grouped.get(name)
        if not items:
            continue
        out += [name.upper(), ADVICE[name]]
        for skill, n in items[:8]:
            out.append(f"- {skill.title()} ({n} job{'s' if n != 1 else ''}): e.g. {examples[skill][0]}")
            out.append(f"  Learn: {learn_line(skill)}")
        out.append("")
    quick = [s for s, n in counts.items() if n >= 2]
    out += ["QUICK WINS", "These show up in two or more jobs, so they are worth building first."]
    out += [f"- {s.title()}" for s in sorted(quick)[:8]] if quick else ["- None yet."]
    out += ["", "REQUIREMENTS YOU CAN'T MEET YET", "These are hard requirements from the jobs you scored."]
    out += [f"- {b} ({n} job{'s' if n != 1 else ''})" for b, n in blockers.most_common(6)] or ["- None recorded."]
    out += ["", "A NOTE ON YOUR CV",
            "Only add a skill once you've actually used it. Recruiters check, and an honest gap is better than an overstated skill."]
    return "\n".join(out)


def email_if_due(text):
    sender = os.getenv("GMAIL_ADDRESS", "").strip()
    password = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    if not (sender and password):
        return
    sent = json.load(open(SENT_PATH)) if os.path.exists(SENT_PATH) else {}
    last = sent.get("last")
    if last and datetime.fromisoformat(last) > datetime.now(timezone.utc) - timedelta(days=EMAIL_EVERY_DAYS):
        return
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = sender
    msg["Subject"] = "Your skills report"
    msg.set_content(text)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender, password)
        smtp.send_message(msg)
    json.dump({"last": datetime.now(timezone.utc).isoformat(timespec="minutes")}, open(SENT_PATH, "w"))
    print("Skills report emailed to you.")


if __name__ == "__main__":
    text = build()
    open(REPORT, "w", encoding="utf-8").write(text + "\n")
    print(f"Skills report written ({len(text.splitlines())} lines).")
    if "No scored jobs" not in text and "No skill gaps" not in text:
        email_if_due(text)
