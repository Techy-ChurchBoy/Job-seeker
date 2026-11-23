"""
Direct-apply collector. Takes eligible postings that have no contact email, looks for the company's own
application link (Greenhouse, Lever, Ashby or Workable), and queues the result in direct_apply.json.
Review first: nothing is submitted here. Greenhouse links then go to the form filler in review mode.
Postings on skip_companies.json and companies already applied to are left out.
"""
import csv, json, os, re, time
from datetime import datetime, timezone
import requests
import jobbot as jb
from urllib.parse import urljoin
from send_applications import contact_email

QUEUE = "direct_apply.json"
ATS = re.compile(r"https?://(?:job-)?boards\.greenhouse\.io/[^\s\"'<>]+|https?://jobs\.lever\.co/[^\s\"'<>]+|"
                 r"https?://jobs\.ashbyhq\.com/[^\s\"'<>]+|https?://apply\.workable\.com/[^\s\"'<>]+", re.I)
GREENHOUSE = re.compile(r"^https?://(job-)?boards\.greenhouse\.io/")
UA = "jobbot-personal-job-search/1.0 (one request per run)"
MAX_PER_RUN = 10


def skipped_companies():
    return [n.lower() for n in json.load(open("skip_companies.json"))] if os.path.exists("skip_companies.json") else []


def applied_urls():
    if not os.path.exists("applied.csv"):
        return set()
    return {r["url"] for r in csv.DictReader(open("applied.csv", encoding="utf-8")) if r.get("url")}


def eligible(r, skip):
    try:
        score = float(r.get("score") or 0)
    except ValueError:
        return False
    no_blockers = (r.get("blockers") or "").strip().lower() in ("", "none", "n/a", "no")
    text = f"{r.get('company', '')} {r.get('title', '')} {r.get('url', '')}".lower()
    if any(s in text for s in skip):
        return False
    return score >= 40 and no_blockers and not contact_email(r.get("description", ""))


APPLY_LINK = re.compile(r"apply|careers|vacanc|opening|join (us|our)", re.I)
FORM_EMAIL = re.compile(r"<input[^>]+type=[\"']email", re.I)
FORM_FILE = re.compile(r"<input[^>]+type=[\"']file", re.I)
MAX_REQUESTS = 6  # per posting: pages opened while looking for a form


def page(url):
    if not jb.allowed_by_robots(url):
        return ""
    time.sleep(2)
    try:
        return requests.get(url, headers={"User-Agent": UA}, timeout=20).text
    except requests.RequestException:
        return ""


def apply_links(html, base):
    """Links on a page whose wording suggests applying or careers."""
    found = []
    for href, text in re.findall(r"<a\s[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html or "", re.I | re.S):
        if APPLY_LINK.search(re.sub(r"<[^>]+>", " ", text)):
            link = urljoin(base, href)
            if link.startswith("http") and link not in found:
                found.append(link)
    return found


def classify(html, url):
    """('greenhouse' | 'supported_other', link) for a known system, ('generic_form', url) for a plain form."""
    ats = ATS.search(html or "")
    if ats:
        link = ats.group(0)
        return ("greenhouse" if GREENHOUSE.match(link) else "supported_other", link)
    if FORM_EMAIL.search(html or "") and FORM_FILE.search(html or ""):
        return ("generic_form", url)
    return None


def find_apply_link(posting_url):
    """Looks at the posting, then up to two links deeper, for a supported system or a plain application form."""
    budget = [MAX_REQUESTS]

    def visit(url):
        budget[0] -= 1
        return page(url)

    html = visit(posting_url)
    hit = classify(html, posting_url)
    if hit:
        return hit
    queue_pages = [(link, 1) for link in apply_links(html, posting_url)[:3]]
    while queue_pages and budget[0] > 0:
        url, depth = queue_pages.pop(0)
        html = visit(url)
        hit = classify(html, url)
        if hit:
            return hit
        if depth < 2:
            queue_pages += [(link, depth + 1) for link in apply_links(html, url)[:2]]
    return ("none", "")


def telegram(text):
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if token and chat:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat, "disable_web_page_preview": True, "text": text}, timeout=60)


def main():
    queue = json.load(open(QUEUE, encoding="utf-8")) if os.path.exists(QUEUE) else {}
    if not os.path.exists("matches.csv"):
        print("No matches.csv yet.")
        return
    skip = skipped_companies()
    rows = list(csv.DictReader(open("matches.csv", encoding="utf-8")))
    done = applied_urls()
    todo = [r for r in rows if r.get("url") not in queue and r.get("url") not in done and eligible(r, skip)][:MAX_PER_RUN]
    print(f"{len(todo)} postings to check for a direct application link.")
    for r in todo:
        status, link = find_apply_link(r["url"])
        if status == "none":
            status = "no_direct_form"
        queue[r["url"]] = {"company": r["company"], "title": r["title"], "posting": r["url"],
                           "apply_url": link, "status": status,
                           "checked": datetime.now(timezone.utc).isoformat(timespec="minutes")}
        if status == "no_direct_form":
            telegram(f"No direct application link found: {r['title']} at {r['company']}.\n"
                     f"Apply here: {r['url']}")
        print(f"{r['company']} | {r['title']}: {status}")
    json.dump(queue, open(QUEUE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
