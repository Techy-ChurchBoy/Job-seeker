"""
Telegram alert for strong matches that have no contact email. Sends the job link, the cover letter
(with your details filled in) and your CV as a PDF, so you can apply through the company's form.
Each job is alerted once; alerted.json remembers which ones.

Needs env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, CANDIDATE_NAME, CANDIDATE_PHONE, GMAIL_ADDRESS.
"""
import csv, json, os, re
import requests
from send_applications import contact_email, read_cover_letter

MIN_SCORE = 40
ALERTED_PATH = "alerted.json"
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT = os.getenv("TELEGRAM_CHAT_ID", "").strip()
NAME = os.getenv("CANDIDATE_NAME", "").strip()
PHONE = os.getenv("CANDIDATE_PHONE", "").strip()
SENDER = os.getenv("GMAIL_ADDRESS", "").strip()


def api(method, **kwargs):
    return requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}", timeout=60, **kwargs)


def fill(text):
    text = text.replace("[FULL NAME]", NAME).replace("[PHONE]", PHONE).replace("[EMAIL]", SENDER)
    return text.replace("[LOCATION]", "Nigeria")


def strong_without_email(r):
    try:
        score = float(r.get("score") or 0)
    except ValueError:
        return False
    no_blockers = (r.get("blockers") or "").strip().lower() in ("", "none", "n/a", "no")
    if "himalayas.app" in (r.get("url") or ""):
        return score >= MIN_SCORE and no_blockers  # Himalayas jobs are applied to through their own link
    return score >= MIN_SCORE and no_blockers and not contact_email(r.get("description", ""))


def main():
    if not (TOKEN and CHAT):
        print("Telegram secrets missing, so no alerts were sent.")
        return
    if not os.path.exists("matches.csv"):
        print("No matches.csv yet.")
        return
    alerted = set(json.load(open(ALERTED_PATH))) if os.path.exists(ALERTED_PATH) else set()
    rows = list(csv.DictReader(open("matches.csv", encoding="utf-8")))
    todo = []
    for r in rows:
        if r.get("url") in alerted or not strong_without_email(r):
            continue
        letter = read_cover_letter(r)
        if letter:  # if no draft exists yet, the job is tried again on the next run
            todo.append((float(r["score"]), r, letter))
    todo.sort(key=lambda x: x[0], reverse=True)

    sent = 0
    for score, r, letter in todo:
        text = (f"New match ({int(score)}/100): {r['title']} at {r['company']}\n"
                f"Apply here: {r['url']}\n\n"
                f"Cover letter (copy and paste into the form):\n\n{fill(letter)}")
        res = api("sendMessage", data={"chat_id": CHAT, "text": text[:4000], "disable_web_page_preview": True})
        if not res.ok:
            print(f"Telegram refused the message (status {res.status_code}). Stopping alerts.")
            break
        if os.path.exists("cv/cv.pdf"):
            with open("cv/cv.pdf", "rb") as f:
                api("sendDocument", data={"chat_id": CHAT, "caption": "Your CV for the job above"},
                    files={"document": (f"{NAME.replace(' ', '_')}_CV.pdf", f, "application/pdf")})
        alerted.add(r["url"])
        sent += 1
    json.dump(sorted(alerted), open(ALERTED_PATH, "w"))
    print(f"{sent} Telegram alerts sent (job, cover letter and CV).")


if __name__ == "__main__":
    main()
