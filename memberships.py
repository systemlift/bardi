#!/usr/bin/env python3
"""
ServiceTitan -> Google Sheets: Membership Report
Runs weekly (Sundays). Pulls two reports into two tabs:
  1. Membership Summary  — all membership types with status counts
  2. Cancelled Members   — name, phone, membership type, cancel date

Usage:
    python memberships.py
"""

import os
import sys
import time
import socket
import requests
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

socket.setdefaulttimeout(20)
load_dotenv()

# ── Config ───────────────────────────────────────────────────────────────────
ST_AUTH_URL      = "https://auth.servicetitan.io/connect/token"
ST_BASE_URL      = "https://api.servicetitan.io"
ST_TENANT_ID     = os.environ["ST_TENANT_ID"]
ST_CLIENT_ID     = os.environ["ST_CLIENT_ID"]
ST_CLIENT_SECRET = os.environ["ST_CLIENT_SECRET"]
ST_APP_KEY       = os.environ["ST_APP_KEY"]

SHEET_ID         = os.environ["MEMBERSHIP_SHEET_ID"]    # separate sheet from job report
SA_JSON_PATH     = os.environ["GOOGLE_SA_JSON"]
SCOPES           = ["https://www.googleapis.com/auth/spreadsheets"]

SUMMARY_TAB      = "Membership Summary"
CANCELLED_TAB    = "Cancelled Members"

SUMMARY_HEADERS  = [
    "Membership Type",
    "Active",
    "Cancelled",
    "Suspended",
    "Expired",
    "Total",
]

CANCELLED_HEADERS = [
    "Customer Name",
    "Phone Number",
    "Membership Type",
    "Cancel Date",
    "Status",
]

SESSION = requests.Session()


# ── Auth ─────────────────────────────────────────────────────────────────────

def get_st_token() -> str:
    resp = SESSION.post(ST_AUTH_URL, data={
        "grant_type":    "client_credentials",
        "client_id":     ST_CLIENT_ID,
        "client_secret": ST_CLIENT_SECRET,
    }, timeout=30)
    if not resp.ok:
        raise SystemExit(f"Auth failed {resp.status_code}: {resp.text}")
    return resp.json()["access_token"]


def st_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "ST-App-Key":    ST_APP_KEY,
        "Content-Type":  "application/json",
    }


# ── Paginated GET ─────────────────────────────────────────────────────────────

def st_get_all(token: str, path: str, params: dict = None) -> list:
    url = f"{ST_BASE_URL}{path}"
    params = dict(params or {})
    params.setdefault("pageSize", 500)
    results = []
    page = 1
    while True:
        params["page"] = page
        for attempt in range(5):
            try:
                resp = SESSION.get(url, headers=st_headers(token), params=params, timeout=20)
                break
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                if attempt == 4:
                    print(f" [giving up on {path.split('/')[-1]}]", end="", flush=True)
                    return results
                wait = 2 ** attempt
                print(f" [retry {attempt+1} in {wait}s]", end="", flush=True)
                time.sleep(wait)
        if not resp.ok:
            print(f" [error {resp.status_code} on {path}]")
            return results
        data = resp.json()
        results.extend(data.get("data", []))
        if not data.get("hasMore", False):
            break
        page += 1
    return results


# ── Data fetchers ─────────────────────────────────────────────────────────────

def get_all_memberships(token: str) -> list:
    """Pull every customer membership regardless of status."""
    return st_get_all(token, f"/memberships/v2/tenant/{ST_TENANT_ID}/memberships")


def get_customer(token: str, customer_id: int) -> dict:
    """Fetch a single customer record to get phone number."""
    url = f"{ST_BASE_URL}/crm/v2/tenant/{ST_TENANT_ID}/customers/{customer_id}"
    try:
        resp = SESSION.get(url, headers=st_headers(token), timeout=15)
        if resp.ok:
            return resp.json()
    except Exception:
        pass
    return {}


def extract_phone(customer: dict) -> str:
    """Pull the first available phone number from contacts."""
    for contact in (customer.get("contacts") or []):
        value = contact.get("value") or contact.get("phoneNumber") or ""
        if value:
            return value
    # fallback: top-level phone field
    return customer.get("mobilePhone") or customer.get("phone") or ""


# ── Build report data ─────────────────────────────────────────────────────────

def build_summary(memberships: list) -> list[list]:
    """Aggregate counts by membership type and status."""
    from collections import defaultdict
    # {type_name: {status: count}}
    counts = defaultdict(lambda: defaultdict(int))

    for m in memberships:
        type_name = (m.get("membershipType") or {}).get("name") or m.get("type") or "Unknown"
        status    = (m.get("status") or "Unknown").capitalize()
        counts[type_name][status] += 1

    rows = [SUMMARY_HEADERS]
    for type_name in sorted(counts.keys()):
        c = counts[type_name]
        total = sum(c.values())
        rows.append([
            type_name,
            c.get("Active", 0),
            c.get("Cancelled", 0),
            c.get("Suspended", 0),
            c.get("Expired", 0),
            total,
        ])
    return rows


def build_cancelled(token: str, memberships: list) -> list[list]:
    """Build cancelled member rows with customer name, phone, type, date."""
    cancelled = [m for m in memberships
                 if (m.get("status") or "").lower() == "cancelled"]

    print(f"  {len(cancelled)} cancelled membership(s) found.")

    rows = [CANCELLED_HEADERS]
    for i, m in enumerate(cancelled, 1):
        customer_id = (m.get("customer") or {}).get("id") or m.get("customerId")
        type_name   = (m.get("membershipType") or {}).get("name") or m.get("type") or ""
        cancel_date = (m.get("cancelledOn") or m.get("modifiedOn") or "")[:10]
        status      = (m.get("status") or "").capitalize()

        print(f"  [{i}/{len(cancelled)}] Fetching customer {customer_id}...", end="", flush=True)

        customer     = get_customer(token, customer_id) if customer_id else {}
        customer_name = (customer.get("name")
                         or (m.get("customer") or {}).get("name")
                         or "")
        phone        = extract_phone(customer)

        rows.append([customer_name, phone, type_name, cancel_date, status])
        print(" done")
        time.sleep(0.1)

    return rows


# ── Google Sheets ─────────────────────────────────────────────────────────────

def sheets_client():
    creds = Credentials.from_service_account_file(SA_JSON_PATH, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)


def ensure_tab(svc, tab_name: str):
    """Create the tab if it doesn't already exist."""
    meta = svc.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
    existing = [s["properties"]["title"] for s in meta["sheets"]]
    if tab_name not in existing:
        svc.spreadsheets().batchUpdate(
            spreadsheetId=SHEET_ID,
            body={"requests": [{"addSheet": {"properties": {"title": tab_name}}}]}
        ).execute()
        print(f"  Created tab: {tab_name}")


def write_tab(svc, tab_name: str, rows: list[list]):
    """Clear the tab and write fresh data."""
    svc.spreadsheets().values().clear(
        spreadsheetId=SHEET_ID,
        range=f"'{tab_name}'",
    ).execute()

    svc.spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"'{tab_name}'!A1",
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()
    print(f"  {len(rows) - 1} data row(s) written to '{tab_name}'.")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("Authenticating to ServiceTitan...")
    token = get_st_token()

    print("Fetching all memberships...")
    memberships = get_all_memberships(token)
    print(f"  {len(memberships)} total membership record(s) found.")

    if not memberships:
        print("No membership data returned. Check API permissions.")
        sys.exit(0)

    print("Building membership summary...")
    summary_rows = build_summary(memberships)

    print("Building cancelled members list...")
    cancelled_rows = build_cancelled(token, memberships)

    print("Connecting to Google Sheets...")
    svc = sheets_client()

    print("Writing Membership Summary tab...")
    ensure_tab(svc, SUMMARY_TAB)
    write_tab(svc, SUMMARY_TAB, summary_rows)

    print("Writing Cancelled Members tab...")
    ensure_tab(svc, CANCELLED_TAB)
    write_tab(svc, CANCELLED_TAB, cancelled_rows)

    print("Done.")


if __name__ == "__main__":
    main()
