"""One-off helper: asks OpenTrain's MCP server for its list of tools and saves it to opentrain_tools.json.
Read-only. It only calls tools/list, which lists what tools exist. It does not search, send, or change anything."""
import json
import opentrain_scout as ot

session = ot.open_session()
body, _ = ot._call("tools/list", {}, session)
tools = body.get("result", {}).get("tools", [])
with open("opentrain_tools.json", "w", encoding="utf-8") as f:
    json.dump(tools, f, indent=2, ensure_ascii=False)
print(f"Saved {len(tools)} tools to opentrain_tools.json")
for t in tools:
    print("-", t.get("name"))
