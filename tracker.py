"""
Application tracker. Each application has one stage: Applied, Replied, Interview, Offer, Rejected or Closed.
Run by the track workflow, which receives a company name and a stage from Telegram (/track) or the dashboard.
"""
import json, os
from datetime import datetime, timezone

STAGES = ["Applied", "Replied", "Interview", "Offer", "Rejected", "Closed"]
PATH = "tracker.json"


def load():
    return json.load(open(PATH, encoding="utf-8")) if os.path.exists(PATH) else {}


def update(company, stage):
    """Sets the stage for every application whose company name contains the text given."""
    if stage not in STAGES:
        return f"Unknown stage. Use one of: {', '.join(STAGES)}."
    data = load()
    hits = [k for k in data if company.lower() in k.lower()] or []
    if not hits:
        data[company] = {"stage": stage, "updated": datetime.now(timezone.utc).date().isoformat()}
        hits = [company]
    else:
        for k in hits:
            data[k]["stage"] = stage
            data[k]["updated"] = datetime.now(timezone.utc).date().isoformat()
    json.dump(data, open(PATH, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return f"{', '.join(hits)} set to {stage}."


if __name__ == "__main__":
    print(update(os.getenv("TRACK_COMPANY", "").strip(), os.getenv("TRACK_STAGE", "").strip()))
