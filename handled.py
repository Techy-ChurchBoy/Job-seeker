"""Marks a draft as handled, or reopens it. Run by the handled workflow. Keeps handled.json, a list of links."""
import json, os

PATH = "handled.json"
url = os.getenv("HANDLED_URL", "").strip()
state = os.getenv("HANDLED_STATE", "").strip()
items = set(json.load(open(PATH, encoding="utf-8"))) if os.path.exists(PATH) else set()
if not url or state not in ("handled", "open"):
    raise SystemExit("Need a draft link and a state of handled or open.")
if state == "handled":
    items.add(url)
else:
    items.discard(url)
json.dump(sorted(items), open(PATH, "w", encoding="utf-8"), indent=1)
print(f"{state}: {url}")
