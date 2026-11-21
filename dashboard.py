"""
Builds dashboard/index.html after each run. Shows everything: every scored job, the skills to build,
sends, drafts and run results. Never shows your CV or cover letter text.
"""
import csv, html, json, os
from collections import Counter, defaultdict
from datetime import datetime, timezone

OUT = "dashboard/index.html"
DAILY_LIMIT = 10
MIN_SCORE = 70


def rows(path):
    return list(csv.DictReader(open(path, encoding="utf-8"))) if os.path.exists(path) else []


def esc(x):
    return html.escape(str(x or ""))


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def gaps(r):
    return [g.strip() for g in (r.get("skill_gaps") or "").split(";") if g.strip()]


def link(url):
    u = str(url or "")
    return f'<a href="{esc(u)}" target="_blank" rel="noopener">Open posting</a>' if u.startswith("http") else ""


CSS = """
:root{--ink:#000;--paper:#FFFBF1;--soft:rgba(0,0,0,.55)}
*{box-sizing:border-box}
body{margin:0;padding:18px;background:var(--paper);color:var(--ink);font-family:system-ui,-apple-system,sans-serif;font-size:15px;line-height:1.45}
h1{font-size:24px;margin:0 0 4px;letter-spacing:-.3px} h2{font-size:17px;margin:0 0 12px}
.muted{color:var(--soft);font-size:13px}
section{margin-top:22px}
.neu{background:var(--paper);border-radius:22px;padding:16px;box-shadow:9px 9px 18px rgba(0,0,0,.10),-9px -9px 18px #ffffff}
.clay{background:var(--paper);border-radius:28px;padding:14px 16px;margin-bottom:12px;box-shadow:inset 0 -7px 0 rgba(0,0,0,.06),8px 10px 22px rgba(0,0,0,.12)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px}
.stat b{display:block;font-size:26px;margin-top:4px}
.pill{display:inline-block;padding:6px 14px;border-radius:999px;font-size:13px;font-weight:600;color:var(--paper);background:linear-gradient(#222,#000);box-shadow:inset 0 1px 0 rgba(255,255,255,.28),0 4px 8px rgba(0,0,0,.25)}
.pill.off{background:linear-gradient(#555,#222)}
.track{height:12px;border-radius:99px;background:var(--paper);box-shadow:inset 3px 3px 6px rgba(0,0,0,.14),inset -3px -3px 6px #fff;overflow:hidden;margin:8px 0}
.fill{height:100%;border-radius:99px;background:linear-gradient(90deg,#000,#3a3a3a);box-shadow:inset 0 1px 0 rgba(255,255,255,.25)}
.tag{display:inline-block;margin:3px 4px 0 0;padding:4px 10px;border-radius:999px;font-size:12px;background:var(--paper);box-shadow:inset 2px 2px 4px rgba(0,0,0,.12),inset -2px -2px 4px #fff}
.score{font-size:22px;font-weight:700}
pre{white-space:pre-wrap;word-break:break-word;font-size:13px;margin:0;padding:14px;border-radius:18px;background:var(--paper);box-shadow:inset 5px 5px 10px rgba(0,0,0,.10),inset -5px -5px 10px #fff}
a{color:var(--ink);font-weight:600}
.btn{display:inline-block;margin-top:8px;padding:9px 16px;border-radius:14px;color:var(--paper);text-decoration:none;font-size:14px;background:linear-gradient(#262626,#000);box-shadow:inset 0 1px 0 rgba(255,255,255,.25),0 5px 10px rgba(0,0,0,.25)}
.row{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap}
"""


def card(inner, cls="clay"):
    return f'<div class="{cls}">{inner}</div>'


def main():
    matches = rows("matches.csv")
    applied = rows("applied.csv")
    prepared = set(json.load(open("prepared.json"))) if os.path.exists("prepared.json") else set()
    status = json.load(open("status.json")) if os.path.exists("status.json") else {"last_run": None, "summary": []}
    paused = os.path.exists("PAUSE")
    today = datetime.now(timezone.utc).date().isoformat()

    scored = sorted(matches, key=lambda r: num(r.get("score")), reverse=True)
    strong = sum(1 for r in scored if num(r.get("score")) >= MIN_SCORE)
    sent_today = sum(1 for r in applied if (r.get("sent_at") or "").startswith(today))

    # Skills to build: count each missing skill across all scored jobs
    gap_count = Counter()
    gap_examples = defaultdict(list)
    for r in scored:
        for g in gaps(r):
            key = g.lower()
            gap_count[key] += 1
            if len(gap_examples[key]) < 3:
                gap_examples[key].append(f"{r.get('title', '')} at {r.get('company', '')}")

    badge = ('<span class="pill off">Sending paused</span>' if paused
             else '<span class="pill">Sending on</span>')

    stats = [
        ("Jobs scored", len(scored)),
        (f"Strong ({MIN_SCORE}+)", strong),
        ("Drafts ready", len(prepared)),
        (f"Sent today (max {DAILY_LIMIT})", sent_today),
        ("Sent in total", len(applied)),
    ]
    stats_html = "".join(card(f'<div class="muted">{esc(l)}</div><b>{esc(v)}</b>', "neu stat") for l, v in stats)
    stats_html = f'<div class="grid">{stats_html}</div>'

    if gap_count:
        upskill_html = "".join(card(
            f'<div class="row"><b>{esc(skill.title())}</b><span class="muted">in {n} job{"s" if n != 1 else ""}</span></div>'
            f'<div class="muted">{esc("; ".join(gap_examples[skill]))}</div>')
            for skill, n in gap_count.most_common(15))
    else:
        upskill_html = card('<span class="muted">No skill gaps recorded yet. They appear after the next run.</span>')

    sent_html = "".join(card(
        f'<div class="row"><b>{esc(r.get("title"))}</b><span class="muted">{esc((r.get("sent_at") or "")[:16].replace("T", " "))} UTC</span></div>'
        f'<div class="muted">{esc(r.get("company"))} &middot; to {esc(r.get("email"))} &middot; score {esc(r.get("score"))}</div>'
        f'{link(r.get("url"))}')
        for r in reversed(applied)) or card('<span class="muted">Nothing sent yet.</span>')

    def job_card(r):
        s = num(r.get("score"))
        pct = max(0, min(100, int(s)))
        g = gaps(r)
        gap_tags = "".join(f'<span class="tag">{esc(x)}</span>' for x in g) or '<span class="muted">none</span>'
        draft = "draft ready" if r.get("url") in prepared else "no draft yet"
        blockers = r.get("blockers") or "none"
        return card(
            f'<div class="row"><span class="score">{int(s)}</span><span class="muted">{esc(r.get("source"))} &middot; {draft}</span></div>'
            f'<div class="track"><div class="fill" style="width:{pct}%"></div></div>'
            f'<b>{esc(r.get("title"))}</b><div class="muted">{esc(r.get("company"))} &middot; {esc(r.get("location"))}</div>'
            f'<div class="muted" style="margin-top:6px">{esc(r.get("reason"))}</div>'
            f'<div class="muted" style="margin-top:6px">Blockers: {esc(blockers)}</div>'
            f'<div style="margin-top:6px">{gap_tags}</div>'
            f'{"<br>" + link(r.get("url")) if link(r.get("url")) else ""}')

    jobs_html = "".join(job_card(r) for r in scored) or card('<span class="muted">No jobs scored yet.</span>')

    run_text = "\n".join(status.get("summary", [])) or "No run recorded yet."
    last_run = status.get("last_run") or "never"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Job search</title><style>{CSS}</style></head>
<body>
<h1>Job search</h1>
<div class="row">{badge}<span class="muted">Last run: {esc(last_run)} UTC</span></div>
<p><a class="btn" href="apply.html">Apply to a job</a></p>

<section><h2>Overview</h2>{stats_html}</section>

<section><h2>Skills to build</h2>
<p class="muted">Skills and tools that the jobs ask for and your CV doesn't show yet, most common first.</p>
{upskill_html}</section>

<section><h2>Last run</h2><pre>{esc(run_text)}</pre></section>

<section><h2>Sent applications</h2>{sent_html}</section>

<section><h2>All scored jobs</h2>
<p class="muted">{len(scored)} jobs, highest score first.</p>
{jobs_html}</section>

<p class="muted" style="margin-top:24px">Generated {esc(stamp)}</p>
</body></html>
"""
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(page)
    print(f"Dashboard written to {OUT}")


if __name__ == "__main__":
    main()
