"""
Writes dashboard/data/feed.json. The dashboard page (dashboard/index.html) is a static file that reads this feed,
so the page exists and works whether or not the job bot has run. Never includes your CV or cover letter text.
"""
import csv, glob, json, os
from collections import Counter, defaultdict
from datetime import datetime, timezone

FEED = "dashboard/data/feed.json"
MIN_SCORE = 40


def rows(path):
    return list(csv.DictReader(open(path, encoding="utf-8"))) if os.path.exists(path) else []


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def gaps(r):
    return [g.strip() for g in (r.get("skill_gaps") or "").split(";") if g.strip()]


FRIENDLY = {"remotive": "Remotive", "himalayas": "Himalayas", "workingnomads": "Working Nomads",
            "jobicy": "Jobicy", "remoteok": "RemoteOK", "greenhouse": "company boards (Greenhouse)",
            "lever": "company boards (Lever)", "ashby": "company boards (Ashby)", "smartyacad": "Dixcover Hub (jobs.smartyacad.com)", "jooble": "Jooble (Nigeria)"}


def no_blockers(r):
    return (r.get("blockers") or "").strip().lower() in ("", "none", "n/a", "no")


def plain_report(status, matches):
    """Sentences a non-technical reader can follow, built from what each step recorded."""
    if not status.get("last_run"):
        return ["No job search has run yet. It runs automatically twice a day once the schedule is working."]
    rep = status.get("report", {})
    src = rep.get("sources", [])
    lines = [f"Last run: {status['last_run']} UTC."]
    if src:
        ok = [x for x in src if x.get("ok")]
        bad = [FRIENDLY.get(x["name"], x["name"]) for x in src if not x.get("ok")]
        found = sum(x.get("fetched", 0) for x in src)
        matched = sum(x.get("passed", 0) for x in src)
        lines.append(f"The search checked {len(src)} job sources and {len(ok)} responded. "
                     f"It found {found} postings in total, and {matched} matched your skills.")
        if bad:
            lines.append("These sources could not be reached: " + ", ".join(bad) + ".")
    if rep.get("scored") is not None:
        lines.append(f"{rep.get('scored', 0)} postings were scored against your CV this run.")
    if rep.get("scoring_failed"):
        lines.append(f"{rep['scoring_failed']} postings could not be scored because the AI service was busy. "
                     "They will be tried again next run.")
    if rep.get("boards_failed"):
        names = ", ".join(b.split(":")[0] for b in rep["boards_failed"])
        lines.append(f"These company boards could not be read, so their names need checking: {names}.")
    drafts = status.get("drafts")
    if drafts:
        text = f"{drafts.get('written', 0)} cover letters were written."
        if drafts.get("waiting"):
            text += f" {drafts['waiting']} more are waiting for the next run."
        lines.append(text)
    emails = status.get("emails")
    if emails is not None:
        n = emails.get("sent", 0)
        if n:
            names = emails.get("names", [])
            more = " and more." if n > len(names) else "."
            lines.append(f"{n} application emails were sent: " + "; ".join(names[:5]) + more)
        else:
            lines.append("No application emails were sent this run.")
    ready = sum(1 for r in matches if num(r.get("score")) >= 40 and no_blockers(r))
    lines.append(f"Overall, {ready} postings currently qualify for an email (score 40 or more, no blockers).")
    return lines


def load_batches():
    out = []
    for path in sorted(glob.glob("outreach/*.json"), reverse=True):
        try:
            b = json.load(open(path, encoding="utf-8"))
        except ValueError:
            continue
        out.append({"file": os.path.basename(path), "location": b.get("location", ""),
                    "categories": b.get("categories", ""), "created": b.get("created", ""),
                    "items": [{"id": i.get("id"), "org": i.get("org"), "kind": i.get("kind"),
                               "email": i.get("email"), "website": i.get("website"),
                               "letter": i.get("letter"), "status": i.get("status")}
                              for i in b.get("items", [])]})
    return out


def build():
    matches = rows("matches.csv")
    applied = rows("applied.csv")
    prepared = set(json.load(open("prepared.json"))) if os.path.exists("prepared.json") else set()
    status = json.load(open("status.json")) if os.path.exists("status.json") else {}
    paused = os.path.exists("PAUSE")
    today = datetime.now(timezone.utc).date().isoformat()

    scored = sorted(matches, key=lambda r: num(r.get("score")), reverse=True)

    gap_count = Counter()
    gap_examples = defaultdict(list)
    for r in scored:
        for g in gaps(r):
            key = g.lower()
            gap_count[key] += 1
            if len(gap_examples[key]) < 3:
                gap_examples[key].append(f"{r.get('title', '')} at {r.get('company', '')}")

    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "report": plain_report(status, matches),
        "batches": load_batches(),
        "paused": paused,
        "last_run": status.get("last_run"),
        "summary": status.get("summary", []),
        "stats": {
            "jobs_scored": len(scored),
            "strong": sum(1 for r in scored if num(r.get("score")) >= MIN_SCORE),
            "drafts": len(prepared),
            "sent_today": sum(1 for r in applied if (r.get("sent_at") or "").startswith(today)),
            "sent_total": len(applied),
        },
        "skills": [{"skill": skill.title(), "count": n, "examples": gap_examples[skill]}
                   for skill, n in gap_count.most_common(15)],
        "sent": [{"sent_at": r.get("sent_at", ""), "title": r.get("title", ""), "company": r.get("company", ""),
                  "email": r.get("email", ""), "score": r.get("score", ""), "url": r.get("url", "")}
                 for r in reversed(applied)],
        "jobs": [{"score": int(num(r.get("score"))), "title": r.get("title", ""), "company": r.get("company", ""),
                  "location": r.get("location", ""), "source": r.get("source", ""), "reason": r.get("reason", ""),
                  "blockers": r.get("blockers", ""), "gaps": gaps(r), "url": r.get("url", ""),
                  "drafted": r.get("url") in prepared} for r in scored],
    }


def main():
    os.makedirs(os.path.dirname(FEED), exist_ok=True)
    feed = build()
    with open(FEED, "w", encoding="utf-8") as f:
        json.dump(feed, f, ensure_ascii=False, indent=1)
    print(f"Dashboard feed written: {len(feed['jobs'])} jobs, {len(feed['sent'])} sent")


if __name__ == "__main__":
    main()
