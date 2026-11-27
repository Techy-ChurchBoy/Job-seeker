"""
Finds contact addresses in a full posting, including ones written as 'name [at] domain' or with HTML entities.
The addresses are stored at the top of the saved description, so they survive the length cut.
"""
import html, re

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
OBFUSCATED = re.compile(r"([A-Za-z0-9._%+-]+)\s*(?:\[at\]|\(at\)|\{at\}|\sat\s)\s*([A-Za-z0-9-]+(?:\s*(?:\[dot\]|\(dot\)|\sdot\s)\s*[A-Za-z0-9-]+)+)", re.I)
SKIP = ("noreply", "no-reply", "donotreply", "example.", "sentry", "wixpress")


def find(text):
    text = html.unescape(text or "")
    found = [m.group(0) for m in EMAIL.finditer(text)]
    for m in OBFUSCATED.finditer(text):
        domain = re.sub(r"\s*(?:\[dot\]|\(dot\)|\sdot\s)\s*", ".", m.group(2), flags=re.I)
        found.append(f"{m.group(1)}@{domain}")
    out = []
    for e in found:
        if not any(x in e.lower() for x in SKIP) and e.lower() not in [o.lower() for o in out]:
            out.append(e)
    return out


def with_contacts(full_text, description_cut):
    """The stored description: any contacts first, then the (cut) text."""
    emails = find(full_text)
    return (f"Contacts: {'; '.join(emails)}\n" if emails else "") + (description_cut or "")
