"""
Chooses which of your documents a posting asks for, so only those are attached.

Your CV is always attached. A document is attached only when the posting asks for it.
If the posting asks for something you don't have, the application is held and you are told.
"""
import json, os, re
import requests
from io import BytesIO
from email.message import EmailMessage
from pypdf import PdfReader, PdfWriter

DOCS = {
    "cv": "documents/01_CV_Bolaji_Alexander_Ifeoluwa.pdf",
    "nin": "documents/02_NIN_Slip_NIMC.pdf",
    "wassce": "documents/03_WASSCE_Result_2018.pdf",
    "leaving": "documents/04_Leaving_Certificate_Foundation_Junior_School_2009.pdf",
    "nysc": "documents/05_NYSC_Certificate_2026.pdf",
    "oau_result": "documents/06_OAU_Result_Notification_2025.pdf",
}
PACK_NAME = "Bolaji_Alexander_Ifeoluwa_Application_Pack.pdf"
HOLD_PATH = "needs_attention.json"

NIN_WORDS = (r"\bnin\b", "national identification", "national identity number", r"\bnrc\b", "national registration")
ACADEMIC_WORDS = ("academic certificate", "academic qualification", "certificates")
WASSCE_WORDS = (r"\bwassce\b", r"\bwaec\b", "o-level", "o level", "secondary school certificate", "senior school certificate")
TRANSCRIPT_WORDS = ("transcript", "statement of result")
NYSC_WORDS = (r"\bnysc\b", "national youth service", "discharge certificate")
LEAVING_WORDS = ("leaving certificate", "primary school certificate")
SINGLE_WORDS = ("single document", "one document", "single pdf", "as a single")


def _has(text, words):
    return any(re.search(w, text) for w in words)


def select(description, url=""):
    """What to attach, what is missing, and notes. The posting is read by the AI when a link is given,
    and the keyword rules are the fallback."""
    if url:
        try:
            import requirements
            req = requirements.extract(url, description)
            return _from_requirements(req, description)
        except Exception as e:
            print(f"Requirement reading failed, using keyword rules: {str(e)[:100]}")
    return _keyword_select(description)


def _from_requirements(req, description):
    wanted = set(req.get("documents", []))
    attach, missing, notes = ["cv"], [], []
    if "nin" in wanted:
        attach.append("nin")
        if "NRC" in (description or "") or "National Registration" in (description or ""):
            notes.append("The posting asks for an NRC. Your NIN slip has been sent instead.")
    if req.get("academic_certificates") or "wassce" in wanted or "oau_result" in wanted:
        attach += ["wassce", "oau_result"]
    if "nysc" in wanted:
        attach.append("nysc")
    if "leaving" in wanted:
        attach.append("leaving")
    if "transcript" in wanted:
        attach.append("oau_result")
        missing.append("official transcript (you have a notification of results, not a transcript)")
    if "other" in wanted:
        missing.append("a document the posting asks for that is not on file")
    return {"attach": [k for k in DOCS if k in attach], "missing": missing, "notes": notes,
            "single": bool(req.get("single_document")), "requirements": req}


def _keyword_select(description):
    text = (description or "").lower()
    attach, missing, notes = ["cv"], [], []
    if _has(text, NIN_WORDS):
        attach.append("nin")
        if _has(text, [r"\bnrc\b", "national registration"]):
            notes.append("The posting asks for an NRC. Your NIN slip has been sent instead.")
    if _has(text, ACADEMIC_WORDS) or _has(text, WASSCE_WORDS):
        attach += ["wassce", "oau_result"]
    if _has(text, TRANSCRIPT_WORDS):
        attach.append("oau_result")
        missing.append("official transcript (you have a notification of results, not a transcript)")
    if _has(text, NYSC_WORDS):
        attach.append("nysc")
    if _has(text, LEAVING_WORDS):
        attach.append("leaving")
    ordered = [k for k in DOCS if k in attach]
    return {"attach": ordered, "missing": missing, "notes": notes, "single": _has(text, SINGLE_WORDS)}


def attach(msg, sel, name):
    """Adds the chosen documents to an email: one combined PDF if asked for, otherwise separate files."""
    if sel["single"]:
        writer = PdfWriter()
        for key in sel["attach"]:
            for page in PdfReader(DOCS[key]).pages:
                writer.add_page(page)
        buf = BytesIO()
        writer.write(buf)
        msg.add_attachment(buf.getvalue(), maintype="application", subtype="pdf", filename=PACK_NAME)
        return
    for key in sel["attach"]:
        with open(DOCS[key], "rb") as f:
            msg.add_attachment(f.read(), maintype="application", subtype="pdf", filename=os.path.basename(DOCS[key]))


def hold(job_url, title, company, sel, telegram_token="", chat_id=""):
    """Records an application that is held because a document is missing, and tells you on Telegram."""
    held = json.load(open(HOLD_PATH)) if os.path.exists(HOLD_PATH) else {}
    held[job_url] = {"title": title, "company": company, "missing": sel["missing"]}
    json.dump(held, open(HOLD_PATH, "w"), indent=1)
    print(f"HELD {title} at {company}: missing {', '.join(sel['missing'])}")
    if telegram_token and chat_id:
        requests.post(f"https://api.telegram.org/bot{telegram_token}/sendMessage",
                      data={"chat_id": chat_id, "disable_web_page_preview": True, "text":
                            f"Application held: {title} at {company}.\nThe posting asks for: "
                            f"{'; '.join(sel['missing'])}.\nIt was not sent. Apply here: {job_url}"}, timeout=60)
