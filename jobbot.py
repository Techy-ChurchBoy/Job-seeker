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

MODEL = None  # set at startup by pick_model()
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
MIN_SCORE = 55          # only keep jobs scoring at least this
MAX_TO_SCORE = 80       # cap per run to control cost

PROFILE = open("profile.txt", encoding="utf-8").read()

# Words that must appear in title or description to be worth scoring
ROLE_WORDS = ["accountant", "accounting", "finance", "financial", "bookkeeper", "bookkeeping",
              "accounts", "audit", "reconciliation", "payroll", "treasury", "fp&a", "controller",
              "graduate", "trainee", "intern", "internship", "entry", "junior", "associate", "officer"]

# Company boards on Greenhouse / Lever. Add slugs of companies you want to watch.
GREENHOUSE = ["flutterwave", "andela", "moniepoint"]
LEVER = ["paystack"]


def strip_html(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def remotive():
    seen_ids = set()
    for q in ["accountant", "finance", "bookkeeper", "accounts"]:
        r = requests.get("https://remotive.com/api/remote-jobs", params={"search": q, "limit": 50}, timeout=30)
        for j in r.json().get("jobs", []):
            if j["id"] in seen_ids:
                continue
            seen_ids.add(j["id"])
            yield dict(source="Remotive", title=j["title"], company=j["company_name"],
                       location=j.get("candidate_required_location", ""), url=j["url"],
                       description=strip_html(j.get("description")))


def himalayas():
    for offset in range(0, 100, 20):
        r = requests.get("https://himalayas.app/jobs/api", params={"limit": 20, "offset": offset}, timeout=30)
        for j in r.json().get("jobs", []):
            yield dict(source="Himalayas", title=j.get("title", ""), company=j.get("companyName", ""),
                       location=", ".join(j.get("locationRestrictions") or []) or "Worldwide",
                       url=j.get("applicationLink") or j.get("guid", ""),
                       description=strip_html(j.get("description") or j.get("excerpt")))


def workingnomads():
    r = requests.get("https://www.workingnomads.com/api/exposed_jobs/", timeout=30)
    for j in r.json():
        yield dict(source="WorkingNomads", title=j.get("title", ""), company=j.get("company_name", ""),
                   location=j.get("location", ""), url=j.get("url", ""),
                   description=strip_html(j.get("description")))


def jobicy():
    r = requests.get("https://jobicy.com/api/v2/remote-jobs", params={"count": 50, "industry": "accounting-finance"}, timeout=30)
    for j in r.json().get("jobs", []):
        yield dict(source="Jobicy", title=j.get("jobTitle", ""), company=j.get("companyName", ""),
                   location=j.get("jobGeo", ""), url=j.get("url", ""),
                   description=strip_html(j.get("jobDescription")))


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
            data = r.json()
            if not isinstance(data, list):
                print(f"lever {slug}: unexpected response, check the company slug", file=sys.stderr)
                continue
            for j in data:
                yield dict(source=f"Lever:{slug}", title=j["text"], company=slug,
                           location=(j.get("categories") or {}).get("location", ""), url=j["hostedUrl"],
                           description=j.get("descriptionPlain", ""))
        except Exception as e:
            print(f"lever {slug} failed: {e}", file=sys.stderr)


JOOBLE_ERRORS = []


def jooble():
    """Optional: free API key from jooble.org/api/about. Covers Nigerian listings."""
    key = os.getenv("JOOBLE_KEY")
    if not key:
        return
    for loc in ["Lagos", "Abuja", "Nigeria"]:
        for kw in ["accountant", "finance officer", "management accountant", "graduate trainee accountant", "accounting internship", "finance graduate trainee", "junior accountant"]:
            try:
                r = requests.post(f"https://jooble.org/api/{key}", json={"keywords": kw, "location": loc}, timeout=30)
                for j in r.json().get("jobs", []):
                    yield dict(source="Jooble", title=j["title"], company=j.get("company", ""),
                               location=j.get("location", ""), url=j["link"],
                               description=strip_html(j.get("snippet")))
            except Exception as e:
                JOOBLE_ERRORS.append(str(e)[:200])


def prefilter(j):
    """Only checks the job title is finance/accounting or an entry-level role. No location restriction."""
    title = j["title"].lower()
    return any(w in title for w in ROLE_WORDS)


PROMPT = """You screen jobs for a candidate. Candidate profile:
{profile}

Targets: accounting and finance roles for a candidate based in Nigeria. Remote, hybrid and onsite (Nigeria or elsewhere) are all acceptable. Entry-level, graduate trainee, internship and junior roles are welcome. Mid-level roles are fine too. Senior roles (head, director, controller, CFO) score low.
Job:
Title: {title}
Company: {company}
Location: {location}
Description: {description}

Return ONLY JSON: {{"score": 0-100, "reason": "one sentence", "blockers": "hard requirements the candidate lacks, e.g. ACA/ACCA required, 5+ years experience, or empty"}}.
Score low if a hard professional qualification (ACA, ACCA, CPA, ICAN) or 5+ years experience is required and missing."""


def pick_model():
    """Use GEMINI_MODEL if set, else ask Gemini which Flash models this key can use and take the newest stable one."""
    if os.getenv("GEMINI_MODEL"):
        return os.getenv("GEMINI_MODEL")
    r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                     headers={"x-goog-api-key": GEMINI_KEY}, timeout=30)
    r.raise_for_status()
    names = [m["name"].split("/")[-1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    flash = [n for n in names if "flash" in n and not any(x in n for x in ("preview", "image", "tts", "live", "exp"))]
    if not flash:
        raise RuntimeError(f"no Flash model available to this key. Models: {names[:20]}")
    # Prefer Flash-Lite: much higher free daily limits, good enough for screening. Newest first.
    lite = [n for n in flash if "lite" in n]
    chosen = sorted(lite or flash, reverse=True)[0]
    print(f"Using model: {chosen}")
    return chosen


class QuotaError(Exception):
    pass


def score(j):
    prompt = PROMPT.format(profile=PROFILE, title=j["title"], company=j["company"],
                           location=j["location"], description=j["description"][:3000])
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2}}
    for attempt in range(3):
        r = requests.post(url, headers={"x-goog-api-key": GEMINI_KEY}, json=body, timeout=60)
        if r.status_code == 503:          # Google temporarily overloaded: retry
            time.sleep(10)
            continue
        if r.status_code == 429:          # rate or daily quota hit
            time.sleep(15)
            continue
        r.raise_for_status()
        break
    else:
        raise QuotaError("Gemini quota or rate limit hit (429). Daily free quota may be used up.")
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    time.sleep(6)                          # stay under free-tier requests per minute
    return json.loads(text.strip().replace("```json", "").replace("```", ""))


def main():
    seen_path = "seen.json"
    seen = set(json.load(open(seen_path))) if os.path.exists(seen_path) else set()

    jobs, lines = [], []
    for src in (remotive, himalayas, workingnomads, jobicy, remoteok, greenhouse, lever, jooble):
        try:
            got = list(src())
        except Exception as e:
            got = []
            lines.append(f"- {src.__name__}: FAILED ({e})")
        else:
            lines.append(f"- {src.__name__}: {len(got)} fetched, {sum(prefilter(j) for j in got)} passed filter")
        jobs += got
    if JOOBLE_ERRORS:
        lines.append(f"- jooble errors ({len(JOOBLE_ERRORS)}). First: {JOOBLE_ERRORS[0]}")
    if not os.getenv("JOOBLE_KEY"):
        lines.append("- jooble: skipped (no JOOBLE_KEY, so no Nigerian listings)")

    jobs = [j for j in jobs if j["url"] not in seen and prefilter(j)][:MAX_TO_SCORE]
    lines.append(f"- {len(jobs)} new jobs sent to scoring")
    print("\n".join(lines))

    results, score_errors, scored = [], [], []
    for j in jobs:
        try:
            s = score(j)
        except QuotaError as e:
            print(f"stopping: {e}", file=sys.stderr)
            score_errors.append(str(e))
            break
        except Exception as e:
            print(f"score failed for {j['title']}: {e}", file=sys.stderr)
            score_errors.append(str(e))
            continue
        seen.add(j["url"])
        scored.append((s["score"], j["title"], j["company"], s.get("blockers", ""), j["url"]))
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
    if scored:
        lines.append("- Top scores (threshold is %d):" % MIN_SCORE)
        for sc, title, company, blockers, url in sorted(scored, reverse=True)[:5]:
            lines.append(f"  - {sc}: {title} at {company}. Blockers: {blockers or 'none'}")
    if score_errors:
        lines.append(f"- {len(score_errors)} jobs FAILED scoring. First error: {score_errors[0][:300]}")
    msg = f"- {len(results)} scored {MIN_SCORE}+ and written to matches.csv"
    print(msg)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write("## jobbot run\n" + "\n".join(lines + [msg]) + "\n")


def selftest():
    """Makes one real Gemini call and one fetch per source. Writes no files. Run with: python jobbot.py --selftest"""
    print("== Gemini check ==")
    sample = dict(title="Accountant", company="Test Co", location="Remote (worldwide)",
                  description="Prepare monthly bank reconciliations and journal entries. Remote, open to all countries.")
    try:
        print("OK:", score(sample))
    except Exception as e:
        print("FAILED:", repr(e))
    print("== Sources ==")
    for src in (remotive, himalayas, workingnomads, jobicy, remoteok, greenhouse, lever):
        try:
            got = list(src())
            print(f"{src.__name__}: {len(got)} jobs. Sample: {[g['title'] for g in got[:3]]}")
        except Exception as e:
            print(f"{src.__name__}: FAILED {e!r}")


if __name__ == "__main__":
    if not GEMINI_KEY:
        sys.exit("Set GEMINI_API_KEY")
    MODEL = pick_model()
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
