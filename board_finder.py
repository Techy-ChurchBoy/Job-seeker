"""
Board finder. For each company in companies_to_find.json, searches the web (Gemini with Google Search grounding)
for its public job board on Greenhouse, Lever, Ashby, SmartRecruiters or Workable. The web addresses come from
the search results, and each board is confirmed through its public API before it is added to companies.json.
Companies with no verified board are logged as not found. Runs a small batch per run to keep quota use low.
"""
import json, os, re
import requests
import jobbot as jb
import web_search as ws

TO_FIND = "companies_to_find.json"
LOG = "board_finder_log.json"
COMPANIES = "companies.json"
PER_RUN = 10
UA = "jobbot-personal-job-search/1.0 (one request per run)"
PATTERNS = [
    ("greenhouse", re.compile(r"boards\.greenhouse\.io/([A-Za-z0-9_-]+)")),
    ("lever", re.compile(r"jobs\.lever\.co/([A-Za-z0-9_-]+)")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)")),
    ("smartrecruiters", re.compile(r"jobs\.smartrecruiters\.com/([A-Za-z0-9_-]+)")),
    ("workable", re.compile(r"apply\.workable\.com/([A-Za-z0-9_-]+)")),
]
CHECKS = {
    "greenhouse": lambda s: f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs",
    "lever": lambda s: f"https://api.lever.co/v0/postings/{s}?mode=json",
    "ashby": lambda s: f"https://api.ashbyhq.com/posting-api/job-board/{s}",
    "smartrecruiters": lambda s: f"https://api.smartrecruiters.com/v1/companies/{s}/postings",
    "workable": lambda s: f"https://apply.workable.com/api/v1/widget/accounts/{s}",
}


def verified(system, slug):
    """True only if the board's public API answers with job data."""
    try:
        r = requests.get(CHECKS[system](slug), timeout=30, headers={"User-Agent": UA})
        if not r.ok:
            return False
        data = r.json()
    except (requests.RequestException, ValueError):
        return False
    if isinstance(data, list):
        return True
    return isinstance(data, dict) and any(k in data for k in ("jobs", "content", "postings"))


def search_for(name, country):
    """Gemini with Google Search. Returns the web addresses it found, not any text it wrote."""
    model = jb.pick_model()
    body = {"contents": [{"parts": [{"text": f"Find the official public job board of {name} ({country}). "
                                              "Give the careers page or job board link."}]}],
            "tools": [{"google_search": {}}]}
    res = jb.gemini_post("board_finder", model, body, 90)
    if not res.ok:
        return []
    meta = res.json()["candidates"][0].get("groundingMetadata", {})
    return [c.get("web", {}).get("uri", "") for c in meta.get("groundingChunks", []) if c.get("web", {}).get("uri")]


def find_board(name, country):
    for uri in search_for(name, country):
        final = ws.final_url(uri) or uri
        for system, pattern in PATTERNS:
            m = pattern.search(final)
            if m and verified(system, m.group(1)):
                return system, m.group(1)
    return None, None


def main():
    companies = json.load(open(TO_FIND, encoding="utf-8"))
    log = json.load(open(LOG, encoding="utf-8")) if os.path.exists(LOG) else {}
    board_file = json.load(open(COMPANIES, encoding="utf-8")) if os.path.exists(COMPANIES) else {}
    todo = [c for c in companies if c["name"] not in log][:PER_RUN]
    print(f"{len(todo)} companies to look up this run.")
    for c in todo:
        system, slug = find_board(c["name"], c["country"])
        if system:
            entries = board_file.setdefault(system, [])
            if not any(e.get("board") == slug for e in entries):
                entries.append({"name": c["name"], "board": slug})
            log[c["name"]] = {"status": "found", "system": system, "board": slug}
            print(f"{c['name']}: {system} board '{slug}' verified")
        else:
            log[c["name"]] = {"status": "not found"}
            print(f"{c['name']}: no verified board")
    json.dump(board_file, open(COMPANIES, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    json.dump(log, open(LOG, "w", encoding="utf-8"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
