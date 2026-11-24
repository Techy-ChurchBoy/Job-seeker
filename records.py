"""
One record per posting (postings.json), keyed by a normalised link. Each process may write only its own
fields, so one process can't overwrite another's result. check() compares the records with the logs and
returns any mismatch, so problems show up on the dashboard instead of going unnoticed.
"""
import csv, json, os, re
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PATH = "postings.json"
OWNERS = {
    "scoring": ["score", "reason", "blockers", "skill_gaps", "title", "company", "source"],
    "deadlines": ["deadline"],
    "letters": ["drafted"],
    "sender": ["sent", "sent_at"],
}
FIELD_OWNER = {field: owner for owner, fields in OWNERS.items() for field in fields}
TRACKING = re.compile(r"^(utm_|fbclid|gclid|ref$|source$)", re.I)


def normalise(url):
    """Lower-case host, no www, no tracking codes, no trailing slash, no fragment."""
    parts = urlsplit((url or "").strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not TRACKING.match(k)]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(((parts.scheme or "https").lower(), parts.netloc.lower().replace("www.", ""),
                       path, urlencode(query), ""))


def load():
    return json.load(open(PATH, encoding="utf-8")) if os.path.exists(PATH) else {}


def upsert(process, url, **fields):
    """Writes only the fields this process owns. Anything else is ignored."""
    data = load()
    key = normalise(url)
    rec = data.setdefault(key, {"url": url, "owners": {}})
    for name, value in fields.items():
        if FIELD_OWNER.get(name) != process:
            continue
        rec[name] = value
        rec["owners"][name] = process
    rec["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    json.dump(data, open(PATH, "w", encoding="utf-8"), indent=1, ensure_ascii=False)


def check(applied_rows, matches_rows):
    """Lists mismatches between the records and the logs. An empty list means everything agrees."""
    data = load()
    issues = []
    sent_keys = {normalise(r.get("url", "")) for r in applied_rows if r.get("url")}
    for key, rec in data.items():
        if rec.get("sent") and key not in sent_keys:
            issues.append(f"Marked sent but not in the applied log: {rec.get('title', '')} at {rec.get('company', '')}")
    for key in sent_keys:
        if not (data.get(key) or {}).get("sent"):
            issues.append(f"In the applied log but not marked sent: {key}")
    raw_by_key = defaultdict(set)
    for r in matches_rows:
        url = r.get("url", "")
        if not url:
            continue
        key = normalise(url)
        raw_by_key[key].add(url)
        rec = data.get(key)
        if rec and "score" in rec and str(rec["score"]) != str(r.get("score", "")):
            issues.append(f"Score differs for {r.get('title', '')}: {r.get('score')} in matches, {rec['score']} in records")
    for key, urls in raw_by_key.items():
        if len(urls) > 1:
            issues.append(f"Same posting under {len(urls)} links: {key}")
    return issues
