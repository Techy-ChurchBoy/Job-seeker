"""
Job matcher, steps 1-2: fetch jobs from allowed sources, score against your profile with Gemini,
write matches to matches.csv. Nothing is sent anywhere.

Setup:
    pip install requests
    export GEMINI_API_KEY=...
    python jobbot.py
"""
import csv, json, os, re, sys, time
import requests

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
MIN_SCORE = 65          # only keep jobs scoring at least this
MAX_TO_SCORE = 80       # cap per run to control cost

PROFILE = open("profile.txt", encoding="utf-8").read()

# Words that must appear in title or description to be worth scoring
ROLE_WORDS = ["accountant", "accounting", "finance", "financial", "bookkeeper", "bookkeeping",
              "accounts", "audit", "reconciliation", "payroll", "treasury", "fp&a", "controller"]
LOCATION_WORDS = ["remote", "worldwide", "anywhere", "africa", "nigeria", "lagos", "abuja", "emea"]

# Company boards on Greenhouse / Lever. Add slugs of companies you want to watch.
GREENHOUSE = ["flutterwave", "andela", "moniepoint"]
LEVER = ["paystack"]


def strip_html(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def remotive():
    r = requests.get("https://remotive.com/api/remote-jobs", params={"category": "finance-legal"}, timeout=30)
    for j in r.json().get("jobs", []):
        yield dict(source="Remotive", title=j["title"], company=j["company_name"],
                   location=j.get("candidate_required_location", ""), url=j["url"],
                   description=strip_html(j.get("description")))


def remoteok():
    r = requests.get("https://remoteok.com/api", headers={"User-Agent": "jobbot"}, timeout=30)
    for j in r.json()[1:]:
        yield dict(source="RemoteOK", title=j.get("position", ""), company=j.get("company", ""),
                   location=j.get("location") or "Remote", url=j.get("url", ""),
                   description=strip_html(j.get("description")))


def greenhouse():
    for slug in GREENHOUSE:
        try:
            r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true", timeout=30)
            for j in r.json().get("jobs", []):
                yield dict(source=f"Greenhouse:{slug}", title=j["title"], company=slug,
                           location=(j.get("location") or {}).get("name", ""), url=j["absolute_url"],
                           description=strip_html(j.get("content")))
        except Exception as e:
            print(f"greenhouse {slug} failed: {e}", file=sys.stderr)


def lever():
    for slug in LEVER:
        try:
            r = requests.get(f"https://api.lever.co/v0/postings/{slug}?mode=json", timeout=30)
            for j in r.json():
                yield dict(source=f"Lever:{slug}", title=j["text"], company=slug,
                           location=(j.get("categories") or {}).get("location", ""), url=j["hostedUrl"],
                           description=j.get("descriptionPlain", ""))
        except Exception as e:
            print(f"lever {slug} failed: {e}", file=sys.stderr)


def jooble():
    """Optional: free API key from jooble.org/api/about. Covers Nigerian listings."""
    key = os.getenv("JOOBLE_KEY")
    if not key:
        return
    for loc in ["Lagos", "Abuja", "Remote"]:
        for kw in ["accountant", "finance officer", "management accountant"]:
            try:
                r = requests.post(f"https://jooble.org/api/{key}", json={"keywords": kw, "location": loc}, timeout=30)
                for j in r.json().get("jobs", []):
                    yield dict(source="Jooble", title=j["title"], company=j.get("company", ""),
                               location=j.get("location", ""), url=j["link"],
                               description=strip_html(j.get("snippet")))
            except Exception as e:
                print(f"jooble failed: {e}", file=sys.stderr)


def prefilter(j):
    text = f"{j['title']} {j['description'][:1500]}".lower()
    title = j["title"].lower()
    loc = f"{j['location']} {text}".lower()
    return any(w in title for w in ROLE_WORDS) and any(w in loc for w in LOCATION_WORDS)


PROMPT = """You screen jobs for a candidate. Candidate profile:
{profile}

Targets: accounting/finance roles, entry to mid level, located Remote, Lagos or Abuja.
Job:
Title: {title}
Company: {company}
Location: {location}
Description: {description}

Return ONLY JSON: {{"score": 0-100, "reason": "one sentence", "blockers": "hard requirements the candidate lacks, e.g. ACA/ACCA, 5+ years, or empty"}}.
Score low if a hard qualification (ACA, ACCA, CPA, ICAN, 5+ years) is required and missing, or if the location is not open to someone in Nigeria."""


def score(j):
    prompt = PROMPT.format(profile=PROFILE, title=j["title"], company=j["company"],
                           location=j["location"], description=j["description"][:3000])
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2}}
    for attempt in range(4):
        r = requests.post(url, headers={"x-goog-api-key": GEMINI_KEY}, json=body, timeout=60)
        if r.status_code == 429:          # free tier rate limit: wait and retry
            time.sleep(20 * (attempt + 1))
            continue
        r.raise_for_status()
        break
    else:
        raise RuntimeError("rate limited")
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    time.sleep(6)                          # stay under free-tier requests per minute
    return json.loads(text.strip().replace("```json", "").replace("```", ""))


def main():
    if not GEMINI_KEY:
        sys.exit("Set GEMINI_API_KEY")
    seen_path = "seen.json"
    seen = set(json.load(open(seen_path))) if os.path.exists(seen_path) else set()

    jobs, lines = [], []
    for src in (remotive, remoteok, greenhouse, lever, jooble):
        try:
            got = list(src())
        except Exception as e:
            got = []
            lines.append(f"- {src.__name__}: FAILED ({e})")
        else:
            lines.append(f"- {src.__name__}: {len(got)} fetched, {sum(prefilter(j) for j in got)} passed filter")
        jobs += got
    if not os.getenv("JOOBLE_KEY"):
        lines.append("- jooble: skipped (no JOOBLE_KEY, so no Nigerian listings)")

    jobs = [j for j in jobs if j["url"] not in seen and prefilter(j)][:MAX_TO_SCORE]
    lines.append(f"- {len(jobs)} new jobs sent to scoring")
    print("\n".join(lines))

    results = []
    for j in jobs:
        try:
            s = score(j)
        except Exception as e:
            print(f"score failed for {j['title']}: {e}", file=sys.stderr)
            continue
        seen.add(j["url"])
        if s["score"] >= MIN_SCORE:
            results.append({**{k: j[k] for k in ("source", "title", "company", "location", "url")}, **s})

    results.sort(key=lambda r: r["score"], reverse=True)
    new_file = not os.path.exists("matches.csv")
    with open("matches.csv", "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["score", "title", "company", "location", "source", "url", "reason", "blockers"])
        if new_file:
            w.writeheader()
        for r in results:
            w.writerow({k: r.get(k, "") for k in w.fieldnames})
    json.dump(sorted(seen), open(seen_path, "w"))
    msg = f"- {len(results)} scored {MIN_SCORE}+ and written to matches.csv"
    print(msg)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write("## jobbot run\n" + "\n".join(lines + [msg]) + "\n")


if __name__ == "__main__":
    main()
