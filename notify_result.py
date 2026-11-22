"""Prints the Telegram message for an apply-job run, from what the run actually did."""
import json, os

try:
    result = json.load(open("manual_result.json", encoding="utf-8"))
    status, reason = result.get("status", "unknown").upper(), result.get("reason", "")
except (OSError, ValueError):
    status, reason = "FAILED", "The run did not finish. Check the run details below."

print(f"Application result: {status}\n{reason}\nJob: {os.getenv('JOB_URL', '')}\n"
      f"Details: https://github.com/{os.getenv('GITHUB_REPOSITORY', '')}/actions/runs/{os.getenv('GITHUB_RUN_ID', '')}")
