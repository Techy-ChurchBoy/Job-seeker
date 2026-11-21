"""
Step 3: for each job in matches.csv not yet prepared, write a tailored CV and cover letter to applications/.

Contact details are never written to the repo: drafts use placeholders ([FULL NAME], [EMAIL], [PHONE], [LOCATION]).
Needs env: GEMINI_API_KEY. Reads your CV from cv/cv.txt (the repo is private).
"""
import csv, hashlib, json, os, re, sys, time
import requests
from jobbot import pick_model, QuotaError, GEMINI_KEY

CV_PATH = "cv/cv.txt"
CV_TEXT = open(CV_PATH, encoding="utf-8").read() if os.path.exists(CV_PATH) else ""
OUT_DIR = "applications"
PREPARED_PATH = "prepared.json"
MATCHES_PATH = "matches.csv"
MAX_PER_RUN = 15

PROMPT = """You are an experienced career writer helping a Nigerian graduate apply for a job. Write the way a careful, senior recruiter expects: clear, warm, confident, specific, never boastful, never generic.

CANDIDATE CV (the only source of facts you may use):
{cv}

JOB:
Title: {title}
Company: {company}
Location: {location}
Description: {description}

Produce three parts, returned as JSON.

1. "cover_letter": a professional cover letter of 230 to 290 words. Plain text only: no markdown, no bullet points, no bold, no headings. Use this structure, with one blank line between each part:
- Greeting: "Dear Hiring Manager," unless the description names a person to address.
- Opening paragraph (2 to 3 sentences): name the role and the company, and give one specific reason this role suits the candidate, drawn from the job description. Do not open with "I am applying" or "I am writing".
- Middle paragraph (3 to 4 sentences): two or three concrete examples from the CV that match what the job asks for, such as the NCAT reconciliation work, month-end support, the software used, or the degree. Connect each example to a need in the job description. Rephrase the CV, do not copy its bullet points.
- Third paragraph (2 to 3 sentences): if the candidate lacks a requirement, address it honestly and positively, for example by naming a learning step they are taking or their transferable skill. If the gap is minor, leave it out. Never claim a qualification or experience the CV does not show.
- Closing paragraph (1 to 2 sentences): express interest in discussing the role, and say the CV is attached.
- Sign-off: "Yours sincerely," on its own line, then "[FULL NAME]" on the next line, then "[PHONE] | [EMAIL]" on the line after.

Writing rules: use British spelling (organise, programme, analyse). Keep sentences under 25 words. Avoid clichés such as "passionate", "dynamic", "team player", "hit the ground running", "fast-paced", "I believe I would be a great fit". Do not invent facts about the company. If the description says little about the company, focus on the role. Use the job title as written in the posting.

2. "tailored_cv": the CV rewritten in Markdown for this job. Put the most relevant skills and experience first. Keep every fact true to the original CV: reorder and reword only, never add. Use these headings in this order: Profile, Experience, Skills, Education, Additional. Use the placeholders [FULL NAME], [PHONE], [EMAIL], [LOCATION] instead of contact details.

3. "notes": plain text for the candidate, short lines. The first line says the fit (strong, moderate or weak) and why, in one sentence. Then one line for each requirement the candidate does not meet, starting with "Gap:". If a professional qualification is required, such as ACCA, ACA or CPA, add a line starting with "Blocker:".

Never write a real name, phone number, email address or street address in any part. Use the placeholders exactly: [FULL NAME], [PHONE], [EMAIL], [LOCATION].

Return ONLY JSON with the keys "cover_letter", "tailored_cv" and "notes". Every value is a single string."""


def generate(model, prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    last = None
    for attempt in range(3):
        p = prompt if attempt == 0 else prompt + (
            "\n\nReturn ONLY one JSON object with the keys tailored_cv, cover_letter and notes. No other text.")
        body = {"contents": [{"parts": [{"text": p}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.3,
                                     "maxOutputTokens": 4096}}
        r = requests.post(url, headers={"x-goog-api-key": GEMINI_KEY}, json=body, timeout=90)
        if r.status_code == 429:
            raise QuotaError("Gemini quota or rate limit hit (429).")
        if r.status_code == 503:
            time.sleep(10)
            last = "503 from Gemini"
            continue
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        time.sleep(6)
        try:
            parsed = json.loads(text.strip().replace("```json", "").replace("```", ""))
            if isinstance(parsed, list):
                parsed = next((x for x in parsed if isinstance(x, dict)), {})
            if not isinstance(parsed, dict) or not parsed.get("cover_letter"):
                raise ValueError(f"unexpected reply: {str(parsed)[:120]}")
            for key in ("tailored_cv", "cover_letter", "notes"):
                parsed[key] = as_text(parsed.get(key, ""))
            return parsed
        except ValueError as e:
            last = e
            time.sleep(2)
    raise RuntimeError(f"no usable draft after 3 tries: {last}")


def as_text(value):
    """Gemini sometimes returns a list where we expect text. Turn it into plain text."""
    if isinstance(value, (list, tuple)):
        return "\n".join(str(x) for x in value)
    return str(value or "")


def scrub(text):
    """Belt and braces: replace your name, emails and phone numbers if the model wrote them anyway."""
    text = as_text(text)
    first = next((l.strip() for l in CV_TEXT.splitlines() if l.strip()), "")
    if first:
        text = re.sub(re.escape(first), "[FULL NAME]", text, flags=re.I)
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[EMAIL]", text)
    text = re.sub(r"(\+\d{1,3}[ -]?)?0?\d{3}[ -]?\d{3}[ -]?\d{4}", "[PHONE]", text)
    return text


def slug(job):
    base = re.sub(r"[^a-z0-9]+", "-", f"{job['company']}-{job['title']}".lower()).strip("-")[:40]
    return f"{base}-{hashlib.sha1(job['url'].encode()).hexdigest()[:8]}"


def main():
    if not GEMINI_KEY:
        sys.exit("Set GEMINI_API_KEY")
    if not CV_TEXT.strip():
        print("cv/cv.txt is missing or empty, so no drafts were made.")
        return
    os.makedirs(OUT_DIR, exist_ok=True)
    if not os.path.exists(PREPARED_PATH):
        json.dump([], open(PREPARED_PATH, "w"))
    if not os.path.exists(MATCHES_PATH):
        print("No matches.csv yet.")
        return

    done = set(json.load(open(PREPARED_PATH)))
    rows = [r for r in csv.DictReader(open(MATCHES_PATH, encoding="utf-8")) if r.get("url") and r["url"] not in done]
    todo = rows[:MAX_PER_RUN]
    lines = [f"- {len(rows)} matches not yet prepared, doing {len(todo)} this run"]
    if not todo:
        print("\n".join(lines))
        return

    model = pick_model()
    lines.append(f"- Model: {model}")
    made, errors = 0, []
    for r in todo:
        try:
            out = generate(model, PROMPT.format(cv=CV_TEXT, title=r["title"], company=r["company"],
                                                location=r.get("location", ""),
                                                description=r.get("description", "")[:2500]))
        except QuotaError as e:
            errors.append(str(e))
            break
        except Exception as e:
            errors.append(f"{r['title']}: {str(e)[:200]}")
            continue

        path = f"{OUT_DIR}/{slug(r)}.md"
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# {r['title']} at {r['company']}\n\n")
            f.write(f"Score: {r['score']}/100. Location: {r.get('location', '')}. Source: {r['source']}\n\n")
            f.write(f"Job link: {r['url']}\n\n")
            f.write(f"## Notes for you\n\n{scrub(out.get('notes', ''))}\n\n")
            f.write(f"## Cover letter\n\n{scrub(out.get('cover_letter', ''))}\n\n")
            f.write(f"## Tailored CV\n\n{scrub(out.get('tailored_cv', ''))}\n")
        done.add(r["url"])
        made += 1
        json.dump(sorted(done), open(PREPARED_PATH, "w"))

    lines.append(f"- {made} drafts written to {OUT_DIR}/")
    for e in errors[:3]:
        lines.append(f"- FAILED: {e}")
    print("\n".join(lines))
    if os.getenv("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write("## Drafts\n" + "\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
