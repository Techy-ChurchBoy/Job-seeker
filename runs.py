"""Runs a job search on demand (from the Runs page on the dashboard).

Two modes:
- site: a saved site from feed/sites.json. OpenTrain is searched through its own search tool, paging through
  every open and recent job. Other sites of type "link" are read like a pasted page.
- link: any page you paste. The bot reads the job links on that page.

Filters: keyword applies to both. Category, domain, language, country and pay type only work on OpenTrain,
because a normal web page has no such filters. Blocked jobs are kept in the results and marked, never hidden.

Writes feed/runs/<run id>.json and updates feed/runs/index.json (newest first, last 50 kept).
Needs env: RUN_MODE, and SITE_ID or LINK_URL. Optional: SAVE_SITE, SITE_NAME, FILTER_* values, OPENTRAIN_API_KEY.
"""
import html.parser, json, os, re, uuid
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
import requests

SITES = "feed/sites.json"
RUNS_DIR = "feed/runs"
INDEX = f"{RUNS_DIR}/index.json"
KEEP_RUNS = 50
MAX_PAGES = 40
JOB_WORDS = re.compile(r"job|career|position|role|vacanc|opening|hiring|opportunit|apply|/jobs?/|/positions?/", re.I)
# Words that usually mean the person must already hold something or meet a rule. Shown as "Blocked", never hidden.
BLOCKER = re.compile(
    r"\b(ACCA|ACA|CPA|CFA|CIMA|chartered accountant|security clearance|work permit|"
    r"citizens? only|citizenship required|must hold (?:a |an )?(?:licen[cs]e|certificat)|"
    r"licen[cs]ed (?:professional|practitioner)|own (?:a )?(?:vehicle|car)|must be (?:a )?(?:US|UK) (?:citizen|resident))\b",
    re.I,
)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def job_row(title, url, pay="not stated", countries="not stated", text=""):
    m = BLOCKER.search(text or "")
    return {"title": title or "Untitled role", "url": url, "pay": pay, "countries": countries,
            "blocked": bool(m), "blocked_reason": m.group(0) if m else ""}


def keyword_ok(keyword, text):
    words = [w for w in re.split(r"\s+", (keyword or "").lower()) if w]
    return all(w in (text or "").lower() for w in words)


# ---------- OpenTrain (its own search tool, every page) ----------

def run_opentrain(f):
    import opentrain_scout as ot
    session = ot.open_session()
    base = {"limit": 25}
    for key, arg in [("keyword", "q"), ("category", "category"), ("domain", "domain"),
                     ("language", "language"), ("country", "country"), ("pay_type", "payType")]:
        if f.get(key):
            base[arg] = f[key]
    jobs, seen, cursor, pages = [], set(), None, 0
    while pages < MAX_PAGES:
        args = dict(base)
        if cursor:
            args["cursor"] = cursor
        body, _ = ot._call("tools/call", {"name": "opentrain_search_jobs", "arguments": args}, session)
        data = ot.tool_result(body)
        items = data.get("jobs", data) if isinstance(data, dict) else data
        items = items if isinstance(items, list) else []
        for j in items:
            if not isinstance(j, dict):
                continue
            url = j.get("url") or j.get("canonicalUrl") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            text = " ".join(str(j.get(k, "")) for k in ("title", "description", "summary", "skills"))
            jobs.append(job_row(j.get("title"), url, j.get("payText") or j.get("pay") or "not stated",
                                ", ".join(j["countries"]) if isinstance(j.get("countries"), list)
                                else (j.get("countries") or "not stated"), text))
        pages += 1
        cursor = data.get("nextCursor") if isinstance(data, dict) else None
        if not cursor or not items:
            break
    note = f"Read {pages} page(s) from OpenTrain."
    if cursor:
        note += f" Stopped at {MAX_PAGES} pages, so some jobs may be missing."
    return jobs, note


# ---------- any pasted page ----------

class Links(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self._href, self._text = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href, self._text = dict(attrs).get("href"), []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join(" ".join(self._text).split())))
            self._href = None


def run_link(url, f):
    res = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (jobbot runs)"}, timeout=30)
    res.raise_for_status()
    parser = Links()
    parser.feed(res.text)
    base = res.url
    jobs, seen = [], set()
    for href, text in parser.links:
        if not href or href.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue
        target = urljoin(base, href)
        if target in seen or target.rstrip("/") == base.rstrip("/") or len(text) < 6:
            continue
        if not (JOB_WORDS.search(urlparse(target).path) or JOB_WORDS.search(text)):
            continue
        if f.get("keyword") and not keyword_ok(f["keyword"], text):
            continue
        seen.add(target)
        jobs.append(job_row(text, target, text=text))
    note = f"Read {len(parser.links)} links on the page and kept {len(jobs)} that look like jobs."
    if not parser.links:
        note += " The page had no links. It may load its jobs with JavaScript, which this run cannot read."
    if any(f.get(k) for k in ("category", "domain", "language", "country", "pay_type")):
        note += " Category, domain, language, country and pay type only apply to OpenTrain, so they were not used here."
    return jobs, note


# ---------- saved sites ----------

def load_sites():
    return json.load(open(SITES, encoding="utf-8")) if os.path.exists(SITES) else []


def save_sites(sites):
    json.dump(sites, open(SITES, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def update_index(summary):
    index = json.load(open(INDEX, encoding="utf-8")) if os.path.exists(INDEX) else []
    index = [summary] + [s for s in index if s["id"] != summary["id"]]
    index = index[:KEEP_RUNS]
    json.dump(index, open(INDEX, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def main():
    os.makedirs(RUNS_DIR, exist_ok=True)
    env = os.environ
    mode = env.get("RUN_MODE", "site")
    filters = {k: (env.get(f"FILTER_{k.upper()}") or "").strip()
               for k in ("keyword", "category", "domain", "language", "country", "pay_type")}
    if filters["country"] and not re.fullmatch(r"[A-Za-z]{2}", filters["country"]):
        raise SystemExit("Country must be two letters, such as US.")
    sites = load_sites()
    site_name, source_url, source_type = "", "", ""

    if mode == "site":
        site = next((s for s in sites if s["id"] == env.get("SITE_ID")), None)
        if not site:
            raise SystemExit(f"No saved site called {env.get('SITE_ID')!r}.")
        site_name, source_url, source_type = site["name"], site.get("url", ""), site["type"]
        jobs, note = run_opentrain(filters) if site["type"] == "opentrain" else run_link(site["url"], filters)
    else:
        link = (env.get("LINK_URL") or "").strip()
        if not re.match(r"^https?://\S+$", link):
            raise SystemExit("Add a page link starting with http or https.")
        source_url, source_type = link, "link"
        site_name = (env.get("SITE_NAME") or "").strip() or link
        jobs, note = run_link(link, filters)
        if (env.get("SAVE_SITE") or "").lower() == "true" and not any(s.get("url") == link for s in sites):
            sites.append({"id": uuid.uuid4().hex[:8], "name": site_name, "type": "link", "url": link})
            save_sites(sites)
            note += " Saved as a site."

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    result = {"id": run_id, "created": now(), "mode": mode, "site": site_name, "source_type": source_type,
              "source_url": source_url, "filters": {k: v for k, v in filters.items() if v},
              "count": len(jobs), "blocked": sum(1 for j in jobs if j["blocked"]), "note": note, "jobs": jobs}
    json.dump(result, open(f"{RUNS_DIR}/{run_id}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    update_index({k: result[k] for k in ("id", "created", "site", "source_type", "source_url", "count", "blocked", "note")})
    print(f"Run {run_id}: {len(jobs)} jobs ({result['blocked']} blocked). {note}")


if __name__ == "__main__":
    main()
