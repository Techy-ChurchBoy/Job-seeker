"""
OpenTrain scout. Two read-only jobs over OpenTrain's MCP server:
1. Job listings: searches public listings and sends a Telegram message for each new one. No scoring.
2. Messages: if the OpenTrain key is set, looks for a read-only messages tool and sends you a Telegram message
   for each new message. It never replies, sends, or changes anything.

Applying always happens on OpenTrain itself, from your own account.
Needs env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID. Optional: OPENTRAIN_API_KEY (read-only), OPENTRAIN_MCP_URL.
"""
import json, os, re
import requests

MCP_URL = os.getenv("OPENTRAIN_MCP_URL", "https://app.opentrain.ai/mcp").strip()
SEEN_JOBS = "opentrain_seen.json"
SEEN_MESSAGES = "opentrain_messages_seen.json"
QUERIES = ["finance", "accounting", "legal and finance evaluation"]
PER_QUERY = 10
MAX_ALERTS = 10
MAX_MESSAGES = 10
WRITE_WORDS = re.compile(r"send|reply|create|update|delete|post|close|invite|archive|mark|pay|withdraw", re.I)
HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


def _auth_headers(session=None):
    headers = dict(HEADERS)
    key = os.getenv("OPENTRAIN_API_KEY", "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if session:
        headers["Mcp-Session-Id"] = session
    return headers


def _parse(res):
    text = res.text.strip()
    if res.headers.get("Content-Type", "").startswith("text/event-stream") or text.startswith("event:") or "\ndata:" in text:
        for line in text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        return {}
    return json.loads(text) if text else {}


def _call(method, params, session=None, msg_id=2):
    res = requests.post(MCP_URL, headers=_auth_headers(session),
                        json={"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params}, timeout=60)
    res.raise_for_status()
    return _parse(res), res.headers.get("Mcp-Session-Id") or session


def open_session():
    _, session = _call("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                      "clientInfo": {"name": "jobbot-scout", "version": "1.0"}}, msg_id=1)
    try:
        requests.post(MCP_URL, headers=_auth_headers(session),
                      json={"jsonrpc": "2.0", "method": "notifications/initialized"}, timeout=30)
    except requests.RequestException:
        pass
    return session


def tool_result(body):
    """The text inside an MCP tool result, parsed as JSON where possible."""
    text = "".join(part.get("text", "") for part in body.get("result", {}).get("content", [])
                   if isinstance(part, dict))
    try:
        return json.loads(text) if text else {}
    except ValueError:
        return {}


def listings(session):
    found, seen = [], set()
    for q in QUERIES:
        body, _ = _call("tools/call", {"name": "opentrain_search_jobs",
                                       "arguments": {"q": q, "limit": PER_QUERY}}, session)
        data = tool_result(body)
        jobs = data.get("jobs", data) if isinstance(data, dict) else data
        for j in jobs if isinstance(jobs, list) else []:
            if not isinstance(j, dict):
                continue
            key = str(j.get("id") or j.get("url") or j.get("canonicalUrl") or j.get("title"))
            url = j.get("url") or j.get("canonicalUrl") or ""
            if key in seen or not url:
                continue
            seen.add(key)
            found.append({"id": key, "title": j.get("title", "Untitled role"), "url": url,
                          "pay": j.get("payText") or j.get("pay") or "not stated",
                          "countries": ", ".join(j["countries"]) if isinstance(j.get("countries"), list)
                          else (j.get("countries") or "not stated")})
    return found


def messages_tool(session):
    """Finds a read-only messages tool in the server's own list. Returns None if there isn't one."""
    body, _ = _call("tools/list", {}, session)
    for tool in body.get("result", {}).get("tools", []):
        name = tool.get("name", "")
        if "message" in name.lower() and not WRITE_WORDS.search(name):
            return name
    return None


def messages(session, tool):
    body, _ = _call("tools/call", {"name": tool, "arguments": {"limit": 20}}, session)
    data = tool_result(body)
    items = data.get("messages", data) if isinstance(data, dict) else data
    out = []
    for m in items if isinstance(items, list) else []:
        if not isinstance(m, dict):
            continue
        mid = str(m.get("id") or m.get("createdAt") or m.get("subject") or "")
        preview = str(m.get("body") or m.get("text") or m.get("preview") or "")[:300]
        out.append({"id": mid, "from": m.get("from") or m.get("sender") or "someone",
                    "subject": m.get("subject") or "(no subject)", "preview": preview,
                    "when": m.get("createdAt") or m.get("sentAt") or ""})
    return out


def telegram(text):
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if token and chat:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat, "disable_web_page_preview": True, "text": text[:4000]}, timeout=60)


def load(path):
    return set(json.load(open(path))) if os.path.exists(path) else set()


def main():
    session = open_session()
    seen = load(SEEN_JOBS)
    try:
        found = listings(session)
    except (requests.RequestException, ValueError) as e:
        print(f"OpenTrain listings could not be read: {str(e)[:150]}")
        found = []
    new = [j for j in found if j["id"] not in seen][:MAX_ALERTS]
    print(f"{len(found)} listings found, {len(new)} new.")
    for j in new:
        telegram(f"OpenTrain listing: {j['title']}\nPay: {j['pay']}\nOpen to: {j['countries']}\n"
                 f"Apply on OpenTrain yourself: {j['url']}")
        seen.add(j["id"])
    json.dump(sorted(seen), open(SEEN_JOBS, "w"))

    if not os.getenv("OPENTRAIN_API_KEY", "").strip():
        return
    try:
        tool = messages_tool(session)
        if not tool:
            print("No read-only messages tool was found on the OpenTrain server.")
            return
        seen_msgs = load(SEEN_MESSAGES)
        fresh = [m for m in messages(session, tool) if m["id"] not in seen_msgs][:MAX_MESSAGES]
        print(f"{len(fresh)} new OpenTrain messages.")
        for m in fresh:
            telegram(f"OpenTrain message from {m['from']}: {m['subject']}\n{m['when']}\n{m['preview']}\n"
                     "Read and reply on OpenTrain.")
            seen_msgs.add(m["id"])
        json.dump(sorted(seen_msgs), open(SEEN_MESSAGES, "w"))
    except (requests.RequestException, ValueError) as e:
        print(f"OpenTrain messages could not be read: {str(e)[:150]}")


if __name__ == "__main__":
    main()
