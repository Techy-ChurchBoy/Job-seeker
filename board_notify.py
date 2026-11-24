"""Prints the Telegram summary for a board-finder run, from board_finder_log.json."""
import json, os

try:
    log = json.load(open("board_finder_log.json", encoding="utf-8"))
except (OSError, ValueError):
    log = {}
found = sum(1 for v in log.values() if v.get("status") == "found")
missing = sum(1 for v in log.values() if v.get("status") == "not found")
left = len(json.load(open("companies_to_find.json", encoding="utf-8"))) - len(log) if os.path.exists("companies_to_find.json") else 0
print(f"Board finder finished.\nBoards verified so far: {found}. No board found: {missing}. Not yet searched: {left}.\n"
      f"Details: https://github.com/{os.getenv('GITHUB_REPOSITORY', '')}/actions/runs/{os.getenv('GITHUB_RUN_ID', '')}")
