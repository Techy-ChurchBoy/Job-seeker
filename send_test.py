"""
Send one test application, started by hand from the Actions tab (send-test workflow).
Uses the same Gmail and candidate secrets as the real email step.
"""
import os, smtplib, sys
from email.message import EmailMessage

LETTER = """Dear Hiring Manager,

I am applying for the {role} position at {company}. I am an accounting graduate (B.Sc. Accounting, Obafemi Awolowo University, 2025) with 11 months of experience as a Junior Accountant in the Bursary Department of the Nigerian College of Aviation Technology. There I maintained and reconciled receipt and payment records, processed revenue transactions, supported month-end close, and investigated inter-departmental account variances. I work with QuickBooks, Microsoft Dynamics 365 Business Central, Zoho Books, Sage, and advanced Excel.

I would welcome the chance to discuss how I can support {company}'s accounting and reporting. My CV is attached.

Yours sincerely,
[FULL NAME]
[PHONE] | [EMAIL]"""


def letter_for(role, company):
    """Write a fresh letter with Gemini, the same way the real drafts are written.
    Falls back to the fixed template if Gemini is unavailable."""
    try:
        import prepare
        from jobbot import pick_model
        model = pick_model()
        out = prepare.generate(model, prepare.PROMPT.format(
            cv=prepare.CV_TEXT, title=role, company=company, location="Nigeria",
            description="(No posting text. Write from the CV, the role and the company name only.)"))
        letter = out.get("cover_letter", "").strip()
        if letter:
            print(f"Letter written by {model}.")
            return prepare.scrub(letter)
    except Exception as e:
        print(f"Gemini letter failed ({str(e)[:120]}). Using the fixed template.")
    return LETTER.format(role=role, company=company)


def main():
    name = os.getenv("CANDIDATE_NAME", "").strip()
    phone = os.getenv("CANDIDATE_PHONE", "").strip()
    sender = os.getenv("GMAIL_ADDRESS", "").strip()
    pw = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    to = os.getenv("TEST_TO", "").strip()
    role = os.getenv("TEST_ROLE", "").strip() or "Accountant"
    company = os.getenv("TEST_COMPANY", "").strip() or "Midnight"
    if not all([name, phone, sender, pw, to]):
        sys.exit("Missing a secret or the recipient. Nothing sent.")
    if not os.path.exists("cv/cv.pdf"):
        sys.exit("cv/cv.pdf is missing. Nothing sent.")

    body = (letter_for(role, company)
            .replace("[FULL NAME]", name).replace("[PHONE]", phone)
            .replace("[EMAIL]", sender).replace("[LOCATION]", "Nigeria"))
    msg = EmailMessage()
    msg["From"] = f"{name} <{sender}>"
    msg["To"] = to
    msg["Reply-To"] = sender
    msg["Subject"] = f"Application: {role} at {company}"
    msg.set_content(body)
    msg.add_attachment(open("cv/cv.pdf", "rb").read(), maintype="application", subtype="pdf",
                       filename=f"{name.replace(' ', '_')}_CV.pdf")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(sender, pw)
        s.send_message(msg)
    print(f"Test application sent to {to}: {msg['Subject']}")


if __name__ == "__main__":
    main()
