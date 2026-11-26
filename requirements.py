"""
Reads a posting with the AI and lists what it asks for: documents, the degree class, age limits and
eligibility. Each posting is read once and cached in requirements.json. If the reading fails, the caller
falls back to the keyword rules in docs.py.
"""
import json, os
import jobbot as jb

CACHE = "requirements.json"
DOC_KEYS = ["cv", "nin", "wassce", "nysc", "leaving", "oau_result", "transcript", "other"]
PROMPT = """Read this job posting and list exactly what the applicant must provide and must meet.
Return ONLY JSON with these keys:
- "documents": list chosen from ["cv", "nin" (any national ID, NIN or NRC), "wassce" (secondary school certificate),
  "nysc" (NYSC certificate), "leaving" (primary school leaving certificate), "oau_result" (university result or degree
  certificate), "transcript" (official transcript), "other" (any other document, e.g. references, portfolio, licence)].
  Include only documents the posting clearly asks for. Do not guess.
- "academic_certificates": true if the posting asks for academic certificates in general.
- "single_document": true if the posting asks for everything as one document.
- "minimum_degree_class": the class asked for (e.g. "Merit", "Second Class Upper") or null.
- "age_limit": the maximum age asked for as a number, or null.
- "eligibility": short phrases for other hard requirements (current employees only, residency, years of experience).
- "questions": short phrases for questions the application form asks (for example salary, notice period).
Use only the posting. If something is not stated, leave it out or use null.

POSTING:
"""

def _load():
    return json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}

def extract(url, description):
    cache = _load()
    if url in cache:
        return cache[url]
    model = jb.pick_model()
    body = {"contents": [{"parts": [{"text": PROMPT + (description or "")[:6000]}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0}}
    res = jb.gemini_post("requirements", model, body, 60)
    res.raise_for_status()
    data = json.loads(res.json()["candidates"][0]["content"]["parts"][0]["text"])
    data["documents"] = [d for d in data.get("documents", []) if d in DOC_KEYS]
    cache[url] = data
    json.dump(cache, open(CACHE, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return data
