"""
Writes feed/feed.json. The dashboard page (dashboard/index.html) is a static file that reads this feed,
so the page exists and works whether or not the job bot has run. Never includes your CV or cover letter text.
"""
import csv, glob, json, os, re
from datetime import timedelta
from collections import Counter, defaultdict
from datetime import datetime, timezone

FEED = "feed/feed.json"
HISTORY = "feed/history.json"
KNOWN = "feed/known_jobs.json"
RECENT_DAYS = 7
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


def contact_address(description):
    import re
    found = re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", description or "")
    return [a for a in found if not any(x in a.lower() for x in ("noreply", "no-reply", "example."))]


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
    qualifying = [r for r in matches if num(r.get("score")) >= 40 and no_blockers(r)]
    with_email = sum(1 for r in qualifying if contact_address(r.get("description", "")))
    lines.append(f"Overall, {len(qualifying)} postings meet the score rules (40 or more, no blockers). "
                 f"{with_email} of them list a contact address the bot can email; the rest need the application link.")
    return lines


# Keep this False until the dashboard is behind a login. Replies come from private mail.
SHOW_REPLIES = False


def load_replies():
    if not os.path.exists("replies.json"):
        return []
    try:
        return json.load(open("replies.json", encoding="utf-8"))
    except ValueError:
        return []


def load_tracker():
    if not os.path.exists("tracker.json"):
        return []
    try:
        data = json.load(open("tracker.json", encoding="utf-8"))
    except ValueError:
        return []
    return [{"company": k, "stage": v.get("stage", ""), "updated": v.get("updated", "")} for k, v in data.items()]


def build_drafts():
    """Every draft-ready opportunity, read from the draft files written by the letter step."""
    import glob
    handled = set(json.load(open("handled.json", encoding="utf-8"))) if os.path.exists("handled.json") else set()
    out = []
    for path in glob.glob("applications/*.md"):
        text = open(path, encoding="utf-8").read()
        head = re.search(r"^# (.+?) at (.+)$", text, re.M)
        score = re.search(r"Score: ([\d.]+)/100", text)
        link = re.search(r"Job link: (\S+)", text)
        letter = re.search(r"## Cover letter\n\n(.*?)\n\n## Tailored CV", text, re.S)
        notes = re.search(r"## Notes for you\n\n(.*?)\n\n## Cover letter", text, re.S)
        if not head:
            continue
        out.append({"title": head.group(1), "company": head.group(2),
                    "score": int(float(score.group(1))) if score else 0,
                    "url": link.group(1) if link else "",
                    "letter": letter.group(1).strip() if letter else "",
                    "notes": notes.group(1).strip() if notes else "",
                    "handled": bool(link) and link.group(1) in handled})
    return sorted(out, key=lambda d: d["score"], reverse=True)


def build_checks():
    import records
    return records.check(
        [r for r in rows("applied.csv")],
        [r for r in rows("matches.csv")])


def build_usage():
    """Calls per process, with rate-limit (429) and overload (503) counts. Keeps the newest 5,000 lines."""
    if not os.path.exists("usage.jsonl"):
        return {"processes": [], "note": "No Gemini calls logged yet."}
    lines = open("usage.jsonl", encoding="utf-8").read().splitlines()[-5000:]
    open("usage.jsonl", "w", encoding="utf-8").write("\n".join(lines) + "\n")
    entries = [json.loads(x) for x in lines if x.strip()]
    cutoff_day = datetime.now(timezone.utc).date().isoformat()
    week_start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    summary = {}
    for e in entries:
        if e["at"] < week_start:
            continue
        p = summary.setdefault(e["process"], {"process": e["process"], "today": 0, "week": 0, "limited": 0,
                                              "overloaded": 0, "tokens_in": 0, "tokens_out": 0})
        p["week"] += 1
        if e["at"].startswith(cutoff_day):
            p["today"] += 1
        if e["status"] == 429:
            p["limited"] += 1
        if e["status"] == 503:
            p["overloaded"] += 1
        p["tokens_in"] += e.get("prompt_tokens", 0)
        p["tokens_out"] += e.get("output_tokens", 0)
    return {"processes": sorted(summary.values(), key=lambda x: -x["week"]),
            "note": "429 means the free quota was hit for that process. 503 means Google was overloaded."}


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


def recent(stamp):
    """True if an ISO timestamp is within the last RECENT_DAYS."""
    if not stamp:
        return False
    try:
        from datetime import datetime, timezone
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return when >= datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)
    except ValueError:
        return False


def build():
    matches = rows("matches.csv")
    applied = rows("applied.csv")
    prepared = set(json.load(open("prepared.json"))) if os.path.exists("prepared.json") else set()
    status = json.load(open("status.json")) if os.path.exists("status.json") else {}
    paused = os.path.exists("PAUSE")
    today = datetime.now(timezone.utc).date().isoformat()

    scored = sorted(matches, key=lambda r: num(r.get("score")), reverse=True)
    known_urls = set(json.load(open(KNOWN))) if os.path.exists(KNOWN) else set()

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
        "tracker": load_tracker(),
        "usage": build_usage(),
        "checks": build_checks(),
        "drafts": build_drafts(),
        "replies": [dict(r, recent=recent(r.get("received"))) for r in (load_replies() if SHOW_REPLIES else [])],
        "replies_hidden": (not SHOW_REPLIES) and os.path.exists("replies.json"),
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
                  "email": r.get("email", ""), "score": r.get("score", ""), "url": r.get("url", ""),
                  "recent": recent(r.get("sent_at")),
                  "repeat": sum(1 for x in applied if x.get("url") == r.get("url")) > 1}
                 for r in reversed(applied)],
        "jobs": [{"score": int(num(r.get("score"))), "title": r.get("title", ""), "company": r.get("company", ""),
                  "location": r.get("location", ""), "source": r.get("source", ""), "reason": r.get("reason", ""),
                  "blockers": r.get("blockers", ""), "gaps": gaps(r), "url": r.get("url", ""),
                  "drafted": r.get("url") in prepared, "recent": r.get("url") not in known_urls} for r in scored],
    }


def main():
    os.makedirs(os.path.dirname(FEED), exist_ok=True)
    feed = build()
    # history: one entry per job run, newest first
    history = json.load(open(HISTORY)) if os.path.exists(HISTORY) else []
    status = json.load(open("status.json")) if os.path.exists("status.json") else {}
    if status.get("last_run") and (not history or history[-1].get("last_run") != status["last_run"]):
        history.append({"last_run": status["last_run"], "report": feed["report"], "summary": status.get("summary", [])})
        history = history[-60:]
        json.dump(history, open(HISTORY, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    feed["history"] = list(reversed(history))
    # remember every job shown, so the next run can mark what is new
    json.dump([j["url"] for j in feed["jobs"]], open(KNOWN, "w", encoding="utf-8"))
    with open(FEED, "w", encoding="utf-8") as f:
        json.dump(feed, f, ensure_ascii=False, indent=1)
    print(f"Dashboard feed written: {len(feed['jobs'])} jobs, {len(feed['sent'])} sent")
    import outstanding
    outstanding.main()


if __name__ == "__main__":
    main()
