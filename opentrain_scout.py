"""
OpenTrain scout. Searches OpenTrain's public listings through its MCP server (read-only, no account needed)
and sends you a Telegram message for each new listing. It does not score listings and it never applies:
applying happens on OpenTrain's job page, from your own account.

Needs env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID. Optional: OPENTRAIN_MCP_URL.
"""
import json, os, re
import requests

MCP_URL = os.getenv("OPENTRAIN_MCP_URL", "https://app.opentrain.ai/mcp").strip()
SEEN_PATH = "opentrain_seen.json"
QUERIES = ["finance", "accounting", "legal and finance evaluation"]
PER_QUERY = 10
MAX_ALERTS = 10
HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


def _parse(res):
    """MCP over HTTP answers with JSON, or with a server-sent event stream. Handle both."""
    text = res.text.strip()
    if res.headers.get("Content-Type", "").startswith("text/event-stream") or text.startswith("event:") or "\ndata:" in text:
        for line in text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        return {}
    return json.loads(text) if text else {}


def _post(payload, session=None):
    headers = dict(HEADERS)
    if session:
        headers["Mcp-Session-Id"] = session
    res = requests.post(MCP_URL, headers=headers, json=payload, timeout=60)
    res.raise_for_status()
    return _parse(res), res.headers.get("Mcp-Session-Id") or session


def search(query, session):
    body, session = _post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                           "params": {"name": "opentrain_search_jobs",
                                      "arguments": {"q": query, "limit": PER_QUERY}}}, session)
    result = body.get("result", {})
    text = "".join(part.get("text", "") for part in result.get("content", []) if isinstance(part, dict))
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        return []
    jobs = data.get("jobs", data) if isinstance(data, dict) else data
    return [j for j in jobs if isinstance(j, dict)]


def listings():
    """Returns listings from every query. Each is a dict with id, title, url, pay, countries."""
    _, session = _post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                   "clientInfo": {"name": "jobbot-scout", "version": "1.0"}}})
    try:
        requests.post(MCP_URL, headers=HEADERS, json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                      timeout=30)
    except requests.RequestException:
        pass
    found, seen = [], set()
    for q in QUERIES:
        for j in search(q, session):
            key = str(j.get("id") or j.get("url") or j.get("canonicalUrl") or j.get("title"))
            if key in seen:
                continue
            seen.add(key)
            url = j.get("url") or j.get("canonicalUrl") or ""
            if not url:
                continue
            found.append({"id": key, "title": j.get("title", "Untitled role"), "url": url,
                          "pay": j.get("payText") or j.get("pay") or "not stated",
                          "countries": ", ".join(j.get("countries", [])) if isinstance(j.get("countries"), list)
                          else (j.get("countries") or "not stated")})
    return found


def telegram(text):
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if token and chat:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat, "disable_web_page_preview": True, "text": text[:4000]}, timeout=60)


def main():
    seen = set(json.load(open(SEEN_PATH))) if os.path.exists(SEEN_PATH) else set()
    try:
        found = listings()
    except (requests.RequestException, ValueError) as e:
        print(f"OpenTrain scout could not reach its server: {str(e)[:150]}")
        return
    new = [j for j in found if j["id"] not in seen][:MAX_ALERTS]
    print(f"{len(found)} listings found, {len(new)} new.")
    for j in new:
        telegram(f"OpenTrain listing: {j['title']}\nPay: {j['pay']}\nOpen to: {j['countries']}\n"
                 f"Apply on OpenTrain yourself: {j['url']}")
        seen.add(j["id"])
    json.dump(sorted(seen), open(SEEN_PATH, "w"))


if __name__ == "__main__":
    main()
