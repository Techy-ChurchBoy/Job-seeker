"""
Writes dashboard/data/feed.json. The dashboard page (dashboard/index.html) is a static file that reads this feed,
so the page exists and works whether or not the job bot has run. Never includes your CV or cover letter text.
"""
import csv, json, os
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
