"""
Location outreach, step 1: find organisations in a town or area (OpenStreetMap, free), find a public
business contact address for each, and write an open-application letter. Writes a batch for approval.
Nothing is sent here.

Needs env: LOCATION, GEMINI_API_KEY, CANDIDATE_NAME, CANDIDATE_PHONE, GMAIL_ADDRESS.
Optional: CATEGORIES (shown in the batch for reference).
"""
import hashlib, json, os, re, time
from datetime import datetime, timezone
import requests
import jobbot as jb
import prepare as pr

UA = "jobbot-personal-job-search/1.0 (one request per run)"
LOCATION = os.getenv("LOCATION", "").strip()
CATEGORIES = os.getenv("CATEGORIES", "").strip() or "banks, fintechs, accounting and audit firms, insurers"
MAX_ORGS = 20
PERSONAL = ("gmail.", "yahoo.", "hotmail.", "outlook.", "icloud.", "proton")
PREFERRED = ("careers", "hr", "jobs", "recruit", "info", "admin", "contact")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")

OPEN_PROMPT = """You write an open application letter from a Nigerian graduate to an organisation. There is no advertised vacancy, so do not claim one.

CANDIDATE CV (the only source of facts you may use):
{cv}

ORGANISATION: {org}
TYPE: {kind}
LOCATION: {location}

Write "cover_letter": 150 to 200 words, plain text, British spelling, no markdown and no bullet points. Use the greeting "Dear Hiring Manager,". One paragraph says you are interested in opportunities at {org} in {location} in finance, accounting, reporting or operations. One paragraph gives two concrete examples from the CV. One line asks to be considered for future openings and says the CV is attached. Then "Yours sincerely," on its own line, "[FULL NAME]" on the next line, and "[PHONE] | [EMAIL]" after that. Do not invent anything about the organisation beyond its name, type and location.
Return ONLY JSON with the keys "cover_letter" and "notes"."""


def geocode():
    r = requests.get("https://nominatim.openstreetmap.org/search",
                     params={"q": f"{LOCATION}, Nigeria", "format": "json", "limit": 1},
                     headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    hits = r.json()
    if not hits:
        raise SystemExit(f"Could not find {LOCATION} on the map.")
    south, north, west, east = [float(x) for x in hits[0]["boundingbox"]]
    return south, west, north, east


def organisations(bbox):
    s, w, n, e = bbox
    query = (f'[out:json][timeout:60];('
             f'nwr["amenity"="bank"]({s},{w},{n},{e});'
             f'nwr["office"~"financial|accountant|insurance|consulting"]({s},{w},{n},{e});'
             f');out tags center 300;')
    r = requests.post("https://overpass-api.de/api/interpreter", data={"data": query},
                      headers={"User-Agent": UA}, timeout=90)
    r.raise_for_status()
    seen, found = set(), []
    for el in r.json().get("elements", []):
        tags = el.get("tags", {})
        name = (tags.get("name") or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        found.append({"org": name, "kind": tags.get("amenity") or tags.get("office") or "organisation",
                      "website": tags.get("website") or tags.get("contact:website") or "",
                      "email": (tags.get("email") or tags.get("contact:email") or "").strip()})
    return found


def usable(address):
    domain = address.split("@")[-1].lower()
    return not address.lower().endswith(IMAGE_EXT) and not domain.startswith(PERSONAL)


def find_email(org):
    if org["email"] and usable(org["email"]):
        return org["email"]
    if not org["website"]:
        return ""
    base = org["website"] if org["website"].startswith("http") else "https://" + org["website"]
    base = base.rstrip("/")
    for path in ("", "/contact", "/contact-us"):
        url = base + path
        if not jb.allowed_by_robots(url):
            continue
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=20)
        except requests.RequestException:
            continue
        if r.ok:
            found = [e for e in EMAIL_RE.findall(r.text) if usable(e)]
            if found:
                found.sort(key=lambda e: 0 if e.lower().startswith(PREFERRED) else 1)
                return found[0]
        time.sleep(1)
    return ""


def main():
    if not LOCATION:
        raise SystemExit("Set LOCATION.")
    if not pr.GEMINI_KEY:
        raise SystemExit("Set GEMINI_API_KEY.")
    orgs = organisations(geocode())
    print(f"{len(orgs)} named organisations found in {LOCATION}.")
    model = jb.pick_model()
    items = []
    for org in orgs:
        if len(items) >= MAX_ORGS:
            break
        email = find_email(org)
        if not email:
            continue
        try:
            letter = pr.generate(model, OPEN_PROMPT.format(cv=pr.CV_TEXT, org=org["org"],
                                                           kind=org["kind"], location=LOCATION))["cover_letter"]
        except Exception as e:
            print(f"No letter for {org['org']}: {str(e)[:100]}")
            continue
        items.append({"id": hashlib.sha1((email + org["org"]).encode()).hexdigest()[:8],
                      "org": org["org"], "kind": org["kind"], "website": org["website"],
                      "email": email, "letter": letter, "status": "pending"})
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    slug = re.sub(r"[^a-z0-9]+", "-", LOCATION.lower()).strip("-")
    batch_id = f"{slug}-{stamp}"
    with open(f"outreach/{batch_id}.json", "w", encoding="utf-8") as f:
        json.dump({"id": batch_id, "location": LOCATION, "categories": CATEGORIES,
                   "created": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                   "items": items}, f, ensure_ascii=False, indent=1)
    print(f"Batch {batch_id}: {len(items)} organisations with a public contact, ready for approval.")


if __name__ == "__main__":
    main()
