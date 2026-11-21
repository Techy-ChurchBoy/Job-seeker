"""
Builds dashboard/index.html from the repo's files. Run after each job run.
Shows job matches, drafts, sends and run status. Never shows your CV or cover letter text.
"""
import csv, html, json, os
from datetime import datetime, timezone

OUT_DIR = "dashboard"
DAILY_LIMIT = 10


def rows(path):
    return list(csv.DictReader(open(path, encoding="utf-8"))) if os.path.exists(path) else []


def esc(x):
    return html.escape(str(x or ""))


def link(url):
    u = str(url or "")
    return f'<a href="{esc(u)}" target="_blank" rel="noopener">open</a>' if u.startswith("http") else ""


def score(r):
    try:
        return int(r["score"])
    except (KeyError, ValueError):
        return 0


CSS = """
body{font-family:system-ui,sans-serif;margin:0;padding:16px;background:#0f1115;color:#e6e6e6;font-size:15px}
h1{font-size:22px;margin:0 0 4px} h2{font-size:17px;margin:24px 0 8px}
.muted{color:#8a8f98;font-size:13px}
.badge{display:inline-block;padding:3px 10px;border-radius:12px;font-size:13px;font-weight:600}
.on{background:#14532d;color:#bbf7d0} .off{background:#7f1d1d;color:#fecaca}
.cards{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-top:14px}
.card{background:#1a1d24;border-radius:10px;padding:12px}
.card b{display:block;font-size:24px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:6px 4px;border-bottom:1px solid #262a33;vertical-align:top}
th{color:#8a8f98;font-weight:500}
a{color:#7dd3fc}
pre{background:#1a1d24;padding:10px;border-radius:8px;white-space:pre-wrap;font-size:12px}
"""


def main():
    matches = rows("matches.csv")
    applied = rows("applied.csv")
    prepared = set(json.load(open("prepared.json"))) if os.path.exists("prepared.json") else set()
    status = json.load(open("status.json")) if os.path.exists("status.json") else {"last_run": None, "summary": []}
    paused = os.path.exists("PAUSE")
    today = datetime.now(timezone.utc).date().isoformat()

    strong = [r for r in matches if score(r) >= 70]
    sent_today = sum(1 for r in applied if r["sent_at"].startswith(today))
    top = sorted(matches, key=score, reverse=True)[:40]
    recent = list(reversed(applied))[:50]

    badge = ('<span class="badge off">Sending paused</span>' if paused
             else '<span class="badge on">Sending on</span>')

    cards = [
        ("Matches (55+)", len(matches)),
        ("Strong (70+)", len(strong)),
        ("Drafts ready", len(prepared)),
        (f"Sent today (max {DAILY_LIMIT})", f"{sent_today}"),
        ("Sent in total", len(applied)),
    ]
    cards_html = "".join(f'<div class="card">{esc(label)}<b>{esc(value)}</b></div>' for label, value in cards)

    sent_rows = "".join(
        f"<tr><td>{esc(r['sent_at'][:16].replace('T', ' '))}</td><td>{esc(r['company'])}</td>"
        f"<td>{esc(r['title'])}</td><td>{esc(r['email'])}</td><td>{link(r['url'])}</td></tr>"
        for r in recent) or '<tr><td colspan="5" class="muted">Nothing sent yet.</td></tr>'

    match_rows = "".join(
        f"<tr><td>{score(r)}</td><td>{esc(r['title'])}</td><td>{esc(r['company'])}</td>"
        f"<td>{esc(r['source'])}</td><td>{'yes' if (r['url'] in prepared) else ''}</td>"
        f"<td>{esc(r.get('blockers', ''))}</td><td>{link(r['url'])}</td></tr>"
        for r in top) or '<tr><td colspan="7" class="muted">No matches yet.</td></tr>'

    run_text = "\n".join(status.get("summary", [])) or "No run recorded yet."
    last_run = status.get("last_run") or "never"

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Job search dashboard</title><style>{CSS}</style></head>
<body>
<h1>Job search dashboard</h1>
<p><a href="apply.html">Apply to a job</a></p>
<div>{badge} <span class="muted">Last run: {esc(last_run)} UTC</span></div>
<div class="cards">{cards_html}</div>

<h2>Last run</h2>
<pre>{esc(run_text)}</pre>

<h2>Sent applications</h2>
<table><tr><th>When (UTC)</th><th>Company</th><th>Role</th><th>To</th><th></th></tr>{sent_rows}</table>

<h2>Top matches</h2>
<table><tr><th>Score</th><th>Role</th><th>Company</th><th>Source</th><th>Draft</th><th>Blockers</th><th></th></tr>{match_rows}</table>
</body></html>
"""
    os.makedirs(OUT_DIR, exist_ok=True)
    open(f"{OUT_DIR}/index.html", "w", encoding="utf-8").write(page)
    print(f"Dashboard written to {OUT_DIR}/index.html")


if __name__ == "__main__":
    main()
