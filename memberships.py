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
import argparse
import requests
from datetime import datetime, timedelta
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
CANCELLED_TAB    = "Canceled & Expired Members"

SUMMARY_HEADERS  = [
    "Membership Type",
    "Active",
    "Canceled",
    "Suspended",
    "Expired",
    "Total",
]

CANCELLED_HEADERS = [
    "Customer Name",
    "Phone Number",
    "Membership Type",
    "Date",
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

def get_all_memberships(token: str, from_date: str = None, to_date: str = None) -> list:
    """Pull memberships modified within the given date range."""
    params = {}
    if from_date:
        params["modifiedOnOrAfter"] = f"{from_date}T00:00:00Z"
    if to_date:
        params["modifiedOnOrBefore"] = f"{to_date}T23:59:59Z"
    return st_get_all(token, f"/memberships/v2/tenant/{ST_TENANT_ID}/memberships", params)


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


def get_membership_types(token: str) -> dict:
    """Returns {membership_type_id: name}. Fetches active + inactive types,
    then looks up any still-missing IDs individually (legacy types)."""
    # Active types
    types = st_get_all(token, f"/memberships/v2/tenant/{ST_TENANT_ID}/membership-types")
    known = {t["id"]: t.get("name", "") for t in types}
    # Inactive/legacy types
    try:
        inactive = st_get_all(token, f"/memberships/v2/tenant/{ST_TENANT_ID}/membership-types",
                              {"active": "false"})
        for t in inactive:
            if t["id"] not in known:
                known[t["id"]] = t.get("name", "")
    except Exception:
        pass
    return known


def lookup_type_by_id(token: str, type_id: int, type_map: dict) -> str:
    """Get type name, fetching individually if not in map (legacy IDs)."""
    if type_id in type_map:
        return type_map[type_id]
    try:
        url = f"{ST_BASE_URL}/memberships/v2/tenant/{ST_TENANT_ID}/membership-types/{type_id}"
        resp = SESSION.get(url, headers=st_headers(token), timeout=10)
        if resp.ok:
            name = resp.json().get("name", f"ID:{type_id}")
            type_map[type_id] = name   # cache it
            return name
    except Exception:
        pass
    return f"ID:{type_id}"


def get_customer_contacts(token: str, customer_id: int) -> str:
    """Fetch phone number from the contacts endpoint."""
    url = f"{ST_BASE_URL}/crm/v2/tenant/{ST_TENANT_ID}/customers/{customer_id}/contacts"
    try:
        resp = SESSION.get(url, headers=st_headers(token), timeout=15)
        if resp.ok:
            for contact in (resp.json().get("data") or []):
                phone = contact.get("value") or ""
                ctype = (contact.get("type") or "").lower()
                if phone and ("phone" in ctype or "mobile" in ctype or "cell" in ctype or ctype == ""):
                    return phone
    except Exception:
        pass
    return ""


def extract_phone(customer: dict) -> str:
    """Pull the first available phone number from contacts."""
    for contact in (customer.get("contacts") or []):
        value = contact.get("value") or contact.get("phoneNumber") or ""
        if value:
            return value
    # fallback: top-level phone field
    return customer.get("mobilePhone") or customer.get("phone") or ""


# ── Build report data ─────────────────────────────────────────────────────────

def build_summary(token: str, memberships: list, type_map: dict) -> list[list]:
    """Aggregate counts by membership type and status."""
    from collections import defaultdict
    counts = defaultdict(lambda: defaultdict(int))

    for m in memberships:
        type_id   = m.get("membershipTypeId")
        type_name = lookup_type_by_id(token, type_id, type_map) if type_id else "Unknown"
        status    = (m.get("status") or "Unknown").capitalize()
        counts[type_name][status] += 1

    rows = [SUMMARY_HEADERS]
    for type_name in sorted(counts.keys()):
        c = counts[type_name]
        total = sum(c.values())
        rows.append([
            type_name,
            c.get("Active", 0),
            c.get("Canceled", 0),
            c.get("Suspended", 0),
            c.get("Expired", 0),
            total,
        ])
    return rows


def build_cancelled(token: str, memberships: list, type_map: dict) -> list[list]:
    """Build canceled and expired member rows with customer name, phone, type, date."""
    cancelled = [m for m in memberships
                 if (m.get("status") or "").lower() in ("canceled", "cancelled", "expired")]

    print(f"  {len(cancelled)} canceled/expired membership(s) found.")

    rows = [CANCELLED_HEADERS]
    for i, m in enumerate(cancelled, 1):
        customer_id    = m.get("customerId")
        type_id        = m.get("membershipTypeId")
        type_name      = type_map.get(type_id, f"ID:{type_id}")
        cancel_date    = (m.get("cancellationDate") or m.get("to") or m.get("modifiedOn") or "")[:10]
        status         = (m.get("status") or "").capitalize()

        print(f"  [{i}/{len(cancelled)}] Fetching customer {customer_id}...", end="", flush=True)

        customer      = get_customer(token, customer_id) if customer_id else {}
        customer_name = customer.get("name", "")
        phone         = get_customer_contacts(token, customer_id) if customer_id else ""

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
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    today    = datetime.now().strftime("%Y-%m-%d")

    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="from_date", default=week_ago, metavar="YYYY-MM-DD")
    parser.add_argument("--to",   dest="to_date",   default=today,    metavar="YYYY-MM-DD")
    args = parser.parse_args()

    print(f"Date range: {args.from_date} to {args.to_date}")
    print("Authenticating to ServiceTitan...")
    token = get_st_token()

    print("Fetching memberships...")
    memberships = get_all_memberships(token, from_date=args.from_date, to_date=args.to_date)
    print(f"  {len(memberships)} membership record(s) found in range.")

    if not memberships:
        print("No membership data returned. Check API permissions.")
        sys.exit(0)

    print("Fetching membership types...")
    type_map = get_membership_types(token)
    print(f"  {len(type_map)} membership type(s) loaded.")

    print("Building membership summary...")
    summary_rows = build_summary(token, memberships, type_map)

    print("Building canceled/expired members list...")
    cancelled_rows = build_cancelled(token, memberships, type_map)

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
