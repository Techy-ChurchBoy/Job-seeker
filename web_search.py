"""
Web search for job postings. Uses Gemini with Google Search grounding. The web addresses come from the
search results Google returns, never from the model's own text, so no address is made up.
Each address is opened (robots.txt checked first) to read the posting. Capped per run.
"""
import os, re, time
from urllib.parse import urlparse
import requests
import jobbot as jb

QUERIES = [
    "graduate trainee accounts officer job Nigeria 2026 apply",
    "entry level finance officer job Lagos 2026 apply",
    "internship accounting job Abuja 2026 apply",
    "junior accountant remote job Africa 2026 apply",
]
MAX_RESULTS = 10
MAX_PAGES = 12
UA = "jobbot-personal-job-search/1.0 (one request per run)"


def grounded_sources(query):
    """Returns (uri, title) pairs from the search results Gemini used."""
    model = jb.pick_model()
    body = {"contents": [{"parts": [{"text": f"Search the web for current job postings: {query}. "
                                              "List the postings you find."}]}],
            "tools": [{"google_search": {}}]}
    res = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                        headers={"x-goog-api-key": jb.GEMINI_KEY}, json=body, timeout=90)
    res.raise_for_status()
    meta = res.json()["candidates"][0].get("groundingMetadata", {})
    out = []
    for chunk in meta.get("groundingChunks", []):
        web = chunk.get("web", {})
        if web.get("uri"):
            out.append((web["uri"], web.get("title", "")))
    time.sleep(6)
    return out


def final_url(uri):
    """Follows Google's redirect to the real address of the posting."""
    try:
        r = requests.get(uri, headers={"User-Agent": UA}, timeout=20, allow_redirects=True)
        return r.url if r.ok else ""
    except requests.RequestException:
        return ""


def web_search_jobs():
    seen, pages = set(), 0
    for query in QUERIES:
        try:
            found = grounded_sources(query)
        except Exception as e:
            print(f"Web search failed for '{query}': {str(e)[:100]}")
            continue
        for uri, title in found:
            if len(seen) >= MAX_RESULTS or pages >= MAX_PAGES:
                return
            url = final_url(uri)
            if not url or url in seen or not url.startswith("http"):
                continue
            seen.add(url)
            if not jb.allowed_by_robots(url):
                continue
            pages += 1
            time.sleep(2)
            try:
                html = requests.get(url, headers={"User-Agent": UA}, timeout=20).text
            except requests.RequestException:
                continue
            raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
            text = jb.strip_html(raw)
            if len(text) < 300:
                continue
            found_title = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
            heading = jb.strip_html(found_title.group(1)) if found_title else title
            host = urlparse(url).netloc.replace("www.", "")
            yield dict(posted=None, source="Web search", title=heading or title or "Job posting",
                       company=host, location="", url=url, description=text[:6000])
