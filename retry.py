"""Retries one outstanding item chosen on the dashboard.
RETRY_KIND=draft: writes the cover letter for that one job (uses prepare.py).
RETRY_KIND=send: runs the send step again. It only sends applications that are still eligible and not yet sent."""
import csv, json, os, tempfile
import prepare
import send_applications


def retry_draft(url):
    rows = list(csv.DictReader(open(prepare.MATCHES_PATH, encoding="utf-8")))
    row = next((r for r in rows if r.get("url") == url), None)
    if not row:
        raise SystemExit("That job is no longer in matches.csv.")
    done = set(json.load(open(prepare.PREPARED_PATH))) if os.path.exists(prepare.PREPARED_PATH) else set()
    done.discard(url)  # a retry must write the letter again
    json.dump(sorted(done), open(prepare.PREPARED_PATH, "w"))
    attempts = json.load(open(prepare.ATTEMPTS_PATH)) if os.path.exists(prepare.ATTEMPTS_PATH) else {}
    attempts.pop(url, None)
    json.dump(attempts, open(prepare.ATTEMPTS_PATH, "w"))
    # run prepare.main() on just this one row
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8", newline="") as tmp:
        writer = csv.DictWriter(tmp, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerow(row)
        path = tmp.name
    prepare.MATCHES_PATH, prepare.MAX_PER_RUN, prepare.DRAFT_MIN_SCORE = path, 1, 0
    prepare.main()


if __name__ == "__main__":
    kind, url = os.environ.get("RETRY_KIND", ""), os.environ.get("RETRY_URL", "").strip()
    if not url.startswith(("http://", "https://")):
        raise SystemExit("No job link given.")
    if kind == "draft":
        retry_draft(url)
    elif kind == "send":
        send_applications.main(False)
    else:
        raise SystemExit(f"Unknown retry kind {kind!r}.")
