"""Writes feed/outstanding.json: everything still waiting, with what the dashboard needs for a Retry button.
- letters: matches with a good score that have no cover letter yet (with how many tries failed so far)
- sends: applications whose email send failed"""
import csv, json, os
from datetime import datetime, timezone

MIN_SCORE = 40  # same as prepare.py DRAFT_MIN_SCORE
OUT = "feed/outstanding.json"


def load(path, default):
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else default


def main():
    prepared = set(load("prepared.json", []))
    attempts = load("draft_attempts.json", {})
    rows = list(csv.DictReader(open("matches.csv", encoding="utf-8"))) if os.path.exists("matches.csv") else []
    by_url = {r.get("url"): r for r in rows if r.get("url")}

    letters = []
    for r in rows:
        url = r.get("url")
        if not url or url in prepared:
            continue
        try:
            score = float(r.get("score") or 0)
        except ValueError:
            continue
        if score < MIN_SCORE:
            continue
        letters.append({"url": url, "title": r.get("title", ""), "company": r.get("company", ""),
                        "score": score, "tries_failed": attempts.get(url, 0), "kind": "draft"})
    letters.sort(key=lambda x: (x["tries_failed"], -x["score"]))

    sends = []
    for item in load("failed_sends.json", []):
        url = item if isinstance(item, str) else (item or {}).get("url", "")
        if not url:
            continue
        r = by_url.get(url, {})
        sends.append({"url": url, "title": r.get("title", "Application"), "company": r.get("company", ""),
                      "kind": "send"})

    data = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "letters": letters[:200], "letters_total": len(letters), "sends": sends}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"Outstanding: {len(letters)} letters waiting, {len(sends)} sends failed.")


if __name__ == "__main__":
    main()
