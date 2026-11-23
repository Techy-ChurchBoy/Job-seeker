"""Prints the Telegram summary for a job search run, using the same plain-English report as the dashboard."""
import csv, json, os
import dashboard

status = json.load(open("status.json", encoding="utf-8")) if os.path.exists("status.json") else {}
matches = list(csv.DictReader(open("matches.csv", encoding="utf-8"))) if os.path.exists("matches.csv") else []
lines = dashboard.plain_report(status, matches)
print("Job search finished\n" + "\n".join(lines[:12]))
