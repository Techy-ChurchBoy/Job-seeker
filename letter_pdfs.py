"""Makes a ready-to-send PDF of each cover letter that has not been sent yet, with every placeholder filled in.

Reads applications/<slug>.md, fills [FULL NAME], [PHONE], [EMAIL] and [LOCATION], and writes applications/pdf/<slug>.pdf.
Your details come from the CANDIDATE_NAME, CANDIDATE_PHONE and GMAIL_ADDRESS settings when they exist,
and otherwise from the header of cv/cv.txt. A letter that still has an unfilled [PLACEHOLDER] is skipped and reported.
A PDF is rebuilt only when its letter changes. When a job has been sent, its PDF is removed."""
import csv, glob, hashlib, json, os, re
from fpdf import FPDF

OUT_DIR = "applications"
PDF_DIR = f"{OUT_DIR}/pdf"
HASHES = f"{PDF_DIR}/.hashes.json"
LEFTOVER = re.compile(r"\[[A-Z][A-Z0-9 _/-]{1,30}\]")
SMART = {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-", "\u2026": "...",
         "\u00a0": " ", "\u20a6": "NGN ", "\u2022": "-", "\u2192": "->"}


def my_details():
    """Name, phone, email, location. Settings first, then the CV header."""
    name = os.getenv("CANDIDATE_NAME", "").strip()
    phone = os.getenv("CANDIDATE_PHONE", "").strip()
    email = os.getenv("GMAIL_ADDRESS", "").strip()
    location = "Nigeria"
    if os.path.exists("cv/cv.txt"):
        head = "\n".join(open("cv/cv.txt", encoding="utf-8").read().splitlines()[:6])
        if not name:
            first = next((l.strip() for l in head.splitlines() if l.strip()), "")
            name = first.title() if first.isupper() else first
        if not phone:
            m = re.search(r"\+?\d[\d ()-]{8,}\d", head)
            phone = m.group(0).strip() if m else ""
        if not email:
            m = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", head)
            email = m.group(0) if m else ""
    return name, phone, email, location


def fill(text, name, phone, email, location):
    return (text.replace("[FULL NAME]", name).replace("[PHONE]", phone)
                .replace("[EMAIL]", email).replace("[LOCATION]", location))


def latin(text):
    for a, b in SMART.items():
        text = text.replace(a, b)
    return text.encode("latin-1", "replace").decode("latin-1")


def build_pdf(letter, path, author):
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=22)
    pdf.set_margins(24, 24, 24)
    pdf.set_title("Cover letter")
    pdf.set_author(latin(author))
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    for para in re.split(r"\n\s*\n", letter.strip()):
        pdf.multi_cell(0, 5.8, latin(para.strip()), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)
    pdf.output(path)


def main():
    name, phone, email, location = my_details()
    missing = [k for k, v in (("name", name), ("phone", phone), ("email", email)) if not v]
    if missing:
        raise SystemExit(f"Cannot fill the letters: no {', '.join(missing)} found in the settings or the CV header.")
    os.makedirs(PDF_DIR, exist_ok=True)
    hashes = json.load(open(HASHES)) if os.path.exists(HASHES) else {}
    sent = set()
    if os.path.exists("applied.csv"):
        sent = {r.get("url") for r in csv.DictReader(open("applied.csv", encoding="utf-8")) if r.get("url")}
    made = kept = removed = skipped = 0
    for md in sorted(glob.glob(f"{OUT_DIR}/*.md")):
        stem = os.path.splitext(os.path.basename(md))[0]
        pdf_path = f"{PDF_DIR}/{stem}.pdf"
        text = open(md, encoding="utf-8").read()
        link = re.search(r"^Job link:\s*(\S+)", text, re.M)
        letter = re.search(r"## Cover letter\n\n(.*?)\n\n## Tailored CV", text, re.S)
        if not letter:
            continue
        if link and link.group(1) in sent:  # already sent: not an untreated job any more
            if os.path.exists(pdf_path):
                os.remove(pdf_path); hashes.pop(stem, None); removed += 1
            continue
        filled = fill(letter.group(1).strip(), name, phone, email, location)
        left = LEFTOVER.findall(filled)
        if left:
            print(f"SKIPPED {stem}: unfilled {sorted(set(left))}")
            skipped += 1
            continue
        digest = hashlib.sha1(filled.encode("utf-8")).hexdigest()
        if hashes.get(stem) == digest and os.path.exists(pdf_path):
            kept += 1
            continue
        build_pdf(filled, pdf_path, name)
        hashes[stem] = digest
        made += 1
    json.dump(hashes, open(HASHES, "w"), indent=0)
    print(f"Cover letter PDFs: {made} made, {kept} already up to date, {removed} removed (sent), {skipped} skipped.")


if __name__ == "__main__":
    main()
