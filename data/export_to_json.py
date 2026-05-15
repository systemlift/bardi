#!/usr/bin/env python3"""
Exports Google Sheets data to JSON files for the Bardi dashboard.
Reads: Job Summary Sheet + Membership Sheet
Writes: data/jobs.json, data/memberships.json, data/config.json

Run manually or via GitHub Actions after daily/weekly data pulls.
"""

import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

load_dotenv()

SHEET_ID            = os.environ["GOOGLE_SHEET_ID"]
MEMBERSHIP_SHEET_ID = os.environ["MEMBERSHIP_SHEET_ID"]
SA_JSON_PATH        = os.environ["GOOGLE_SA_JSON"]
SHEET_TAB           = os.environ.get("GOOGLE_SHEET_TAB", "Sheet1")
SCOPES              = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

SUMMARY_TAB   = "Membership Summary"
CANCELLED_TAB = "Canceled & Expired Members"
CONFIG_TAB    = "Config"
DAYS_TO_KEEP  = 90   # export last 90 days so dashboard can show custom ranges


def sheets_client():
    creds = Credentials.from_service_account_file(SA_JSON_PATH, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)


def read_tab(svc, sheet_id, tab_name):
    try:
        result = svc.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range=f"'{tab_name}'"
        ).execute()
        return result.get("values", [])
    except Exception as e:
        print(f"  Could not read tab '{tab_name}': {e}")
        return []


def rows_to_dicts(rows):
    if not rows or len(rows) < 2:
        return []
    headers = rows[0]
    result = []
    for row in rows[1:]:
        if not any(row):
            continue
        padded = row + [''] * (len(headers) - len(row))
        result.append(dict(zip(headers, padded)))
    return result


def export_jobs(svc):
    print(f"Reading job data from '{SHEET_TAB}'...")
    rows = read_tab(svc, SHEET_ID, SHEET_TAB)
    all_jobs = rows_to_dicts(rows)
    print(f"  {len(all_jobs)} total rows in sheet.")

    cutoff = (datetime.now() - timedelta(days=DAYS_TO_KEEP)).strftime("%Y-%m-%d")
    filtered = [r for r in all_jobs if r.get("Invoice Date", "") >= cutoff]
    print(f"  {len(filtered)} rows in last {DAYS_TO_KEEP} days.")

    os.makedirs("data", exist_ok=True)
    with open("data/jobs.json", "w") as f:
        json.dump({
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "rows": filtered
        }, f, separators=(",", ":"))
    print("  Wrote data/jobs.json")


def export_memberships(svc):
    print("Reading membership data...")
    summary_rows  = read_tab(svc, MEMBERSHIP_SHEET_ID, SUMMARY_TAB)
    cancelled_rows = read_tab(svc, MEMBERSHIP_SHEET_ID, CANCELLED_TAB)

    os.makedirs("data", exist_ok=True)
    with open("data/memberships.json", "w") as f:
        json.dump({
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "summary":   rows_to_dicts(summary_rows),
            "cancelled": rows_to_dicts(cancelled_rows)
        }, f, separators=(",", ":"))
    print("  Wrote data/memberships.json")


def export_config(svc):
    print("Reading config...")
    config = {}
    rows = read_tab(svc, SHEET_ID, CONFIG_TAB)
    for row in rows[1:]:          # skip header row
        if len(row) >= 2 and row[0]:
            config[row[0]] = row[1]
    if not config:
        print("  No Config tab found — writing empty config.")

    os.makedirs("data", exist_ok=True)
    with open("data/config.json", "w") as f:
        json.dump(config, f, separators=(",", ":"))
    print("  Wrote data/config.json")


def main():
    print("Connecting to Google Sheets...")
    svc = sheets_client()
    export_jobs(svc)
    export_memberships(svc)
    export_config(svc)
    print("Export complete.")


if __name__ == "__main__":
    main()
